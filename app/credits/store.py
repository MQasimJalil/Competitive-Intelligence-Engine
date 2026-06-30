from pathlib import Path
from threading import Lock, RLock
from typing import Protocol

from app.config import settings
from app.schemas.credits import CreditLedgerEntry


class CreditRepository(Protocol):
    def grant(self, *, user_id: str, amount: int, reason: str) -> CreditLedgerEntry: ...
    def balance_for_user(self, user_id: str) -> int: ...
    def list_for_user(self, user_id: str) -> list[CreditLedgerEntry]: ...
    def list_for_job(self, job_id: str) -> list[CreditLedgerEntry]: ...
    def spend_successful_ai_report(
        self, *, user_id: str, job_id: str
    ) -> CreditLedgerEntry | None: ...


class FileCreditStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self._lock = RLock()

    def grant(self, *, user_id: str, amount: int, reason: str) -> CreditLedgerEntry:
        if amount <= 0:
            raise ValueError("Credit grants must be positive")
        entry = CreditLedgerEntry(user_id=user_id, amount=amount, reason=reason)
        self._save(entry)
        return entry

    def balance_for_user(self, user_id: str) -> int:
        return sum(entry.amount for entry in self.list_for_user(user_id))

    def list_for_user(self, user_id: str) -> list[CreditLedgerEntry]:
        return [
            entry
            for entry in sorted(self._all_entries(), key=lambda item: item.created_at)
            if entry.user_id == user_id
        ]

    def list_for_job(self, job_id: str) -> list[CreditLedgerEntry]:
        return [
            entry
            for entry in sorted(self._all_entries(), key=lambda item: item.created_at)
            if entry.job_id == job_id
        ]

    def spend_successful_ai_report(
        self, *, user_id: str, job_id: str
    ) -> CreditLedgerEntry | None:
        with self._lock:
            if self._successful_ai_entry(job_id) is not None:
                return None
            if self.balance_for_user(user_id) < 1:
                return None
            entry = CreditLedgerEntry(
                user_id=user_id,
                job_id=job_id,
                amount=-1,
                reason="successful_ai_report",
            )
            self._save(entry)
            return entry

    def _successful_ai_entry(self, job_id: str) -> CreditLedgerEntry | None:
        for entry in self.list_for_job(job_id):
            if entry.reason == "successful_ai_report":
                return entry
        return None

    def _save(self, entry: CreditLedgerEntry) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"{_safe_id(entry.entry_id)}.json"
        temporary = path.with_suffix(".tmp")
        with self._lock:
            temporary.write_text(entry.model_dump_json(indent=2), encoding="utf-8")
            temporary.replace(path)

    def _all_entries(self) -> list[CreditLedgerEntry]:
        if not self.root.exists():
            return []
        entries = []
        for path in self.root.glob("*.json"):
            try:
                entries.append(CreditLedgerEntry.model_validate_json(path.read_text("utf-8")))
            except ValueError:
                continue
        return entries


class PostgresCreditStore:
    def __init__(self, database_url: str):
        if not database_url:
            raise ValueError("DATABASE_URL is required for the Postgres credit repository")
        self.database_url = database_url
        self.initialize()

    def _connect(self):
        import psycopg

        return psycopg.connect(self.database_url)

    def initialize(self) -> None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS credit_ledger (
                    entry_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    job_id TEXT NOT NULL DEFAULT '',
                    amount INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    payload JSONB NOT NULL
                );
                CREATE INDEX IF NOT EXISTS credit_ledger_user_created_idx
                    ON credit_ledger (user_id, created_at);
                CREATE UNIQUE INDEX IF NOT EXISTS credit_ledger_successful_ai_job_idx
                    ON credit_ledger (job_id, reason)
                    WHERE job_id <> '' AND reason = 'successful_ai_report';
                """
            )

    def grant(self, *, user_id: str, amount: int, reason: str) -> CreditLedgerEntry:
        if amount <= 0:
            raise ValueError("Credit grants must be positive")
        entry = CreditLedgerEntry(user_id=user_id, amount=amount, reason=reason)
        self._insert(entry)
        return entry

    def balance_for_user(self, user_id: str) -> int:
        row = self._fetchone(
            "SELECT COALESCE(SUM(amount), 0) FROM credit_ledger WHERE user_id = %s",
            (user_id,),
        )
        return int(row[0]) if row else 0

    def list_for_user(self, user_id: str) -> list[CreditLedgerEntry]:
        rows = self._fetchall(
            "SELECT payload FROM credit_ledger WHERE user_id = %s ORDER BY created_at",
            (user_id,),
        )
        return [CreditLedgerEntry.model_validate(row[0]) for row in rows]

    def list_for_job(self, job_id: str) -> list[CreditLedgerEntry]:
        rows = self._fetchall(
            "SELECT payload FROM credit_ledger WHERE job_id = %s ORDER BY created_at",
            (job_id,),
        )
        return [CreditLedgerEntry.model_validate(row[0]) for row in rows]

    def spend_successful_ai_report(
        self, *, user_id: str, job_id: str
    ) -> CreditLedgerEntry | None:
        entry = CreditLedgerEntry(
            user_id=user_id,
            job_id=job_id,
            amount=-1,
            reason="successful_ai_report",
        )
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"credit:{user_id}",))
            cursor.execute(
                """
                SELECT 1 FROM credit_ledger
                WHERE job_id = %s AND reason = 'successful_ai_report'
                """,
                (job_id,),
            )
            if cursor.fetchone():
                return None
            cursor.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM credit_ledger WHERE user_id = %s",
                (user_id,),
            )
            if int(cursor.fetchone()[0]) < 1:
                return None
            cursor.execute(
                """
                INSERT INTO credit_ledger
                    (entry_id, user_id, job_id, amount, reason, created_at, payload)
                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    entry.entry_id,
                    entry.user_id,
                    entry.job_id,
                    entry.amount,
                    entry.reason,
                    entry.created_at,
                    entry.model_dump_json(),
                ),
            )
        return entry

    def _insert(self, entry: CreditLedgerEntry) -> None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO credit_ledger
                    (entry_id, user_id, job_id, amount, reason, created_at, payload)
                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    entry.entry_id,
                    entry.user_id,
                    entry.job_id,
                    entry.amount,
                    entry.reason,
                    entry.created_at,
                    entry.model_dump_json(),
                ),
            )

    def _fetchone(self, query: str, values: tuple):
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(query, values)
            return cursor.fetchone()

    def _fetchall(self, query: str, values: tuple):
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(query, values)
            return cursor.fetchall()


def build_credit_store(repository: str, *, root: str | Path, database_url: str):
    if repository.casefold() == "postgres":
        return PostgresCreditStore(database_url)
    return FileCreditStore(root)


class LazyCreditStore:
    def __init__(self):
        self._store = None
        self._lock = Lock()

    def _get_store(self):
        if self._store is None:
            with self._lock:
                if self._store is None:
                    self._store = build_credit_store(
                        settings.credit_repository,
                        root=settings.credit_store_dir,
                        database_url=settings.supabase_db_url or settings.database_url,
                    )
        return self._store

    def __getattr__(self, name: str):
        return getattr(self._get_store(), name)


def _safe_id(value: str) -> str:
    return "".join(character for character in value if character.isalnum())


credit_store = LazyCreditStore()
