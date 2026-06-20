from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Protocol

from app.config import settings
from app.schemas import CompetitorJob, JobStatus, ReportFeedback, ValidationReport, WorkflowRun


class JobRepository(Protocol):
    def create(
        self, domain: str, *, owner_id: str = "", ai_requested: bool = False
    ) -> CompetitorJob: ...
    def get(self, job_id: str) -> CompetitorJob | None: ...
    def list_for_owner(self, owner_id: str) -> list[CompetitorJob]: ...
    def list_all(self) -> list[CompetitorJob]: ...
    def save(self, job: CompetitorJob) -> None: ...
    def delete(self, job_id: str, owner_id: str) -> bool: ...
    def cleanup_expired(self, now: datetime | None = None) -> int: ...
    def save_feedback(self, feedback: ReportFeedback) -> None: ...
    def get_feedback(self, job_id: str, owner_id: str) -> ReportFeedback | None: ...
    def mark_failed(self, job_id: str, error: str) -> CompetitorJob | None: ...


class FileJobStore:
    def __init__(self, root: str | Path, *, retention_days: int = 30):
        self.root = Path(root)
        self.retention_days = retention_days
        self._lock = Lock()

    def create(
        self, domain: str, *, owner_id: str = "", ai_requested: bool = False
    ) -> CompetitorJob:
        job = CompetitorJob(
            domain=domain,
            owner_id=owner_id or settings.local_owner_id,
            ai_requested=ai_requested,
            expires_at=datetime.now(UTC) + timedelta(days=self.retention_days),
        )
        self.save(job)
        return job

    def get(self, job_id: str) -> CompetitorJob | None:
        path = self._path(job_id)
        if not path.exists():
            return None
        return CompetitorJob.model_validate_json(path.read_text(encoding="utf-8"))

    def list_for_owner(self, owner_id: str) -> list[CompetitorJob]:
        if not self.root.exists():
            return []
        jobs = []
        for path in self.root.glob("*.json"):
            try:
                job = CompetitorJob.model_validate_json(path.read_text(encoding="utf-8"))
            except ValueError:
                continue
            if job.owner_id == owner_id:
                jobs.append(job)
        return sorted(jobs, key=lambda item: item.created_at, reverse=True)

    def list_all(self) -> list[CompetitorJob]:
        return sorted(self._all_jobs(), key=lambda item: item.created_at, reverse=True)

    def update_workflow(self, job_id: str, workflow: WorkflowRun) -> CompetitorJob | None:
        job = self.get(job_id)
        if job is None:
            return None
        job.apply_workflow(workflow)
        self.save(job)
        return job

    def finish(
        self,
        job_id: str,
        workflow: WorkflowRun,
        validation: ValidationReport | None,
        *,
        result_count: int,
        fact_count: int,
        apify_estimated_cost_usd: float = 0.0,
        error: str = "",
    ) -> CompetitorJob | None:
        job = self.get(job_id)
        if job is None:
            return None
        job.apply_workflow(workflow)
        job.validation = validation
        job.result_count = result_count
        job.fact_count = fact_count
        job.apify_estimated_cost_usd = apify_estimated_cost_usd
        job.error = error
        job.updated_at = datetime.now(UTC)
        self.save(job)
        return job

    def save_artifacts(
        self,
        job_id: str,
        *,
        snapshot_json: str,
        pdf: bytes,
        evidence_pdf: bytes,
    ) -> CompetitorJob | None:
        job = self.get(job_id)
        if job is None:
            return None
        artifact_dir = self.root / "artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        self._artifact_path(job_id, "snapshot.json").write_text(snapshot_json, encoding="utf-8")
        self._artifact_path(job_id, "report.pdf").write_bytes(pdf)
        self._artifact_path(job_id, "evidence.pdf").write_bytes(evidence_pdf)
        job.has_snapshot = True
        job.has_pdf = True
        job.has_evidence = True
        self.save(job)
        return job

    def read_snapshot(self, job_id: str) -> str | None:
        path = self._artifact_path(job_id, "snapshot.json")
        return path.read_text(encoding="utf-8") if path.exists() else None

    def read_pdf(self, job_id: str) -> bytes | None:
        return self._read_artifact(job_id, "report.pdf")

    def read_evidence_pdf(self, job_id: str) -> bytes | None:
        return self._read_artifact(job_id, "evidence.pdf")

    def save_feedback(self, feedback: ReportFeedback) -> None:
        directory = self.root / "feedback"
        directory.mkdir(parents=True, exist_ok=True)
        self._feedback_path(feedback.job_id, feedback.owner_id).write_text(
            feedback.model_dump_json(indent=2),
            encoding="utf-8",
        )

    def mark_failed(self, job_id: str, error: str) -> CompetitorJob | None:
        job = self.get(job_id)
        if job is None:
            return None
        job.status = JobStatus.FAILED
        job.error = error
        job.updated_at = datetime.now(UTC)
        self.save(job)
        return job

    def get_feedback(self, job_id: str, owner_id: str) -> ReportFeedback | None:
        path = self._feedback_path(job_id, owner_id)
        return (
            ReportFeedback.model_validate_json(path.read_text(encoding="utf-8"))
            if path.exists()
            else None
        )

    def delete(self, job_id: str, owner_id: str) -> bool:
        job = self.get(job_id)
        if job is None or job.owner_id != owner_id:
            return False
        paths = [
            self._path(job_id),
            self._artifact_path(job_id, "snapshot.json"),
            self._artifact_path(job_id, "report.pdf"),
            self._artifact_path(job_id, "evidence.pdf"),
            self._feedback_path(job_id, owner_id),
        ]
        for path in paths:
            if path.exists():
                path.unlink()
        return True

    def cleanup_expired(self, now: datetime | None = None) -> int:
        current = now or datetime.now(UTC)
        removed = 0
        for job in self._all_jobs():
            if job.expires_at <= current and self.delete(job.job_id, job.owner_id):
                removed += 1
        return removed

    def save(self, job: CompetitorJob) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path(job.job_id)
        temporary = path.with_suffix(".tmp")
        with self._lock:
            temporary.write_text(job.model_dump_json(indent=2), encoding="utf-8")
            temporary.replace(path)

    def _all_jobs(self) -> list[CompetitorJob]:
        if not self.root.exists():
            return []
        jobs = []
        for path in self.root.glob("*.json"):
            try:
                jobs.append(CompetitorJob.model_validate_json(path.read_text(encoding="utf-8")))
            except ValueError:
                continue
        return jobs

    def _read_artifact(self, job_id: str, suffix: str) -> bytes | None:
        path = self._artifact_path(job_id, suffix)
        return path.read_bytes() if path.exists() else None

    def _path(self, job_id: str) -> Path:
        return self.root / f"{self._safe_id(job_id)}.json"

    def _artifact_path(self, job_id: str, suffix: str) -> Path:
        return self.root / "artifacts" / f"{self._safe_id(job_id)}.{suffix}"

    def _feedback_path(self, job_id: str, owner_id: str) -> Path:
        return self.root / "feedback" / f"{self._safe_id(owner_id)}.{self._safe_id(job_id)}.json"

    @staticmethod
    def _safe_id(value: str) -> str:
        return "".join(character for character in value if character.isalnum())


class PostgresJobStore:
    def __init__(self, database_url: str, *, retention_days: int = 30):
        if not database_url:
            raise ValueError("DATABASE_URL is required for the Postgres job repository")
        self.database_url = database_url
        self.retention_days = retention_days
        self._pool = self._build_pool()
        self.initialize()

    def _connect(self):
        if self._pool is not None:
            return self._pool.connection()
        import psycopg

        return psycopg.connect(self.database_url)

    def _build_pool(self):
        try:
            from psycopg_pool import ConnectionPool
        except ImportError:
            return None
        return ConnectionPool(
            self.database_url,
            min_size=1,
            max_size=settings.postgres_pool_max_size,
            open=True,
        )

    def initialize(self) -> None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS competitor_jobs (
                    job_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL,
                    expires_at TIMESTAMPTZ NOT NULL,
                    payload JSONB NOT NULL,
                    snapshot_json TEXT,
                    report_pdf BYTEA,
                    evidence_pdf BYTEA
                );
                CREATE INDEX IF NOT EXISTS competitor_jobs_owner_created_idx
                    ON competitor_jobs (owner_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS competitor_jobs_expires_idx
                    ON competitor_jobs (expires_at);
                CREATE TABLE IF NOT EXISTS competitor_feedback (
                    job_id TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    PRIMARY KEY (job_id, owner_id),
                    FOREIGN KEY (job_id) REFERENCES competitor_jobs(job_id) ON DELETE CASCADE
                );
                """
            )

    def create(
        self, domain: str, *, owner_id: str = "", ai_requested: bool = False
    ) -> CompetitorJob:
        job = CompetitorJob(
            domain=domain,
            owner_id=owner_id or settings.local_owner_id,
            ai_requested=ai_requested,
            expires_at=datetime.now(UTC) + timedelta(days=self.retention_days),
        )
        self.save(job)
        return job

    def get(self, job_id: str) -> CompetitorJob | None:
        row = self._fetchone("SELECT payload FROM competitor_jobs WHERE job_id = %s", (job_id,))
        return CompetitorJob.model_validate(row[0]) if row else None

    def list_for_owner(self, owner_id: str) -> list[CompetitorJob]:
        rows = self._fetchall(
            "SELECT payload FROM competitor_jobs WHERE owner_id = %s ORDER BY created_at DESC",
            (owner_id,),
        )
        return [CompetitorJob.model_validate(row[0]) for row in rows]

    def list_all(self) -> list[CompetitorJob]:
        rows = self._fetchall(
            "SELECT payload FROM competitor_jobs ORDER BY created_at DESC",
            (),
        )
        return [CompetitorJob.model_validate(row[0]) for row in rows]

    def update_workflow(self, job_id: str, workflow: WorkflowRun) -> CompetitorJob | None:
        job = self.get(job_id)
        if job is None:
            return None
        job.apply_workflow(workflow)
        self.save(job)
        return job

    def finish(
        self,
        job_id: str,
        workflow: WorkflowRun,
        validation: ValidationReport | None,
        *,
        result_count: int,
        fact_count: int,
        apify_estimated_cost_usd: float = 0.0,
        error: str = "",
    ) -> CompetitorJob | None:
        job = self.get(job_id)
        if job is None:
            return None
        job.apply_workflow(workflow)
        job.validation = validation
        job.result_count = result_count
        job.fact_count = fact_count
        job.apify_estimated_cost_usd = apify_estimated_cost_usd
        job.error = error
        job.updated_at = datetime.now(UTC)
        self.save(job)
        return job

    def save(self, job: CompetitorJob) -> None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO competitor_jobs
                    (job_id, owner_id, domain, status, created_at, updated_at, expires_at, payload)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (job_id) DO UPDATE SET
                    owner_id = EXCLUDED.owner_id,
                    domain = EXCLUDED.domain,
                    status = EXCLUDED.status,
                    updated_at = EXCLUDED.updated_at,
                    expires_at = EXCLUDED.expires_at,
                    payload = EXCLUDED.payload
                """,
                (
                    job.job_id,
                    job.owner_id,
                    job.domain,
                    job.status.value,
                    job.created_at,
                    job.updated_at,
                    job.expires_at,
                    job.model_dump_json(),
                ),
            )

    def save_artifacts(
        self,
        job_id: str,
        *,
        snapshot_json: str,
        pdf: bytes,
        evidence_pdf: bytes,
    ) -> CompetitorJob | None:
        job = self.get(job_id)
        if job is None:
            return None
        job.has_snapshot = True
        job.has_pdf = True
        job.has_evidence = True
        self.save(job)
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE competitor_jobs
                SET snapshot_json = %s, report_pdf = %s, evidence_pdf = %s
                WHERE job_id = %s
                """,
                (snapshot_json, pdf, evidence_pdf, job_id),
            )
        return job

    def read_snapshot(self, job_id: str) -> str | None:
        row = self._fetchone(
            "SELECT snapshot_json FROM competitor_jobs WHERE job_id = %s",
            (job_id,),
        )
        return row[0] if row else None

    def read_pdf(self, job_id: str) -> bytes | None:
        return self._artifact(job_id, "report_pdf")

    def read_evidence_pdf(self, job_id: str) -> bytes | None:
        return self._artifact(job_id, "evidence_pdf")

    def save_feedback(self, feedback: ReportFeedback) -> None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO competitor_feedback (job_id, owner_id, payload)
                VALUES (%s, %s, %s::jsonb)
                ON CONFLICT (job_id, owner_id) DO UPDATE SET payload = EXCLUDED.payload
                """,
                (feedback.job_id, feedback.owner_id, feedback.model_dump_json()),
            )

    def mark_failed(self, job_id: str, error: str) -> CompetitorJob | None:
        job = self.get(job_id)
        if job is None:
            return None
        job.status = JobStatus.FAILED
        job.error = error
        job.updated_at = datetime.now(UTC)
        self.save(job)
        return job

    def get_feedback(self, job_id: str, owner_id: str) -> ReportFeedback | None:
        row = self._fetchone(
            "SELECT payload FROM competitor_feedback WHERE job_id = %s AND owner_id = %s",
            (job_id, owner_id),
        )
        return ReportFeedback.model_validate(row[0]) if row else None

    def delete(self, job_id: str, owner_id: str) -> bool:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM competitor_feedback WHERE job_id = %s AND owner_id = %s",
                (job_id, owner_id),
            )
            cursor.execute(
                "DELETE FROM competitor_jobs WHERE job_id = %s AND owner_id = %s",
                (job_id, owner_id),
            )
            return cursor.rowcount > 0

    def cleanup_expired(self, now: datetime | None = None) -> int:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM competitor_jobs WHERE expires_at <= %s",
                (now or datetime.now(UTC),),
            )
            return cursor.rowcount

    def _artifact(self, job_id: str, column: str) -> bytes | None:
        row = self._fetchone(f"SELECT {column} FROM competitor_jobs WHERE job_id = %s", (job_id,))
        return bytes(row[0]) if row and row[0] is not None else None

    def _fetchone(self, query: str, values: tuple):
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(query, values)
            return cursor.fetchone()

    def _fetchall(self, query: str, values: tuple):
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(query, values)
            return cursor.fetchall()


def build_job_store(
    repository: str,
    *,
    root: str | Path,
    database_url: str,
    retention_days: int = 30,
) -> FileJobStore | PostgresJobStore:
    if repository.casefold() == "postgres":
        return PostgresJobStore(database_url, retention_days=retention_days)
    return FileJobStore(root, retention_days=retention_days)


job_store = build_job_store(
    settings.job_repository,
    root=settings.job_store_dir,
    database_url=settings.database_url,
    retention_days=settings.report_retention_days,
)
