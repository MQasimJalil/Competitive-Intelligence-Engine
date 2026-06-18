from dataclasses import dataclass

from app.schemas import CompetitorJob
from app.schemas.auth import UserSummary
from app.tools.competitor_brief.service import CompetitorSnapshot


@dataclass(frozen=True)
class AdminSummary:
    total_users: int
    total_reports: int
    complete_reports: int
    failed_reports: int
    ai_requested: int
    ai_successes: int
    total_ai_cost_usd: float
    total_apify_cost_usd: float
    total_estimated_cost_usd: float


@dataclass(frozen=True)
class AdminUserRollup:
    owner_id: str
    name: str
    email: str
    role: str
    total_reports: int
    complete_reports: int
    partial_reports: int
    failed_reports: int
    ai_requested: int
    ai_successes: int
    total_ai_cost_usd: float
    total_apify_cost_usd: float

    @property
    def total_estimated_cost_usd(self) -> float:
        return self.total_ai_cost_usd + self.total_apify_cost_usd


def build_admin_view(job_store, user_store=None) -> tuple[AdminSummary, list[AdminUserRollup]]:
    jobs = job_store.list_all()
    user_summaries = _user_summaries(user_store)
    snapshots = {
        job.job_id: _read_snapshot(job_store, job.job_id)
        for job in jobs
        if job.has_snapshot
    }
    by_owner: dict[str, list[CompetitorJob]] = {}
    for job in jobs:
        by_owner.setdefault(job.owner_id, []).append(job)

    users = [
        _rollup(owner_id, owner_jobs, snapshots, user_summaries.get(owner_id))
        for owner_id, owner_jobs in sorted(by_owner.items())
    ]
    users.extend(
        _empty_rollup(summary)
        for user_id, summary in sorted(user_summaries.items())
        if user_id not in by_owner
    )
    return (
        AdminSummary(
            total_users=len(users),
            total_reports=len(jobs),
            complete_reports=sum(user.complete_reports for user in users),
            failed_reports=sum(user.failed_reports for user in users),
            ai_requested=sum(user.ai_requested for user in users),
            ai_successes=sum(user.ai_successes for user in users),
            total_ai_cost_usd=sum(user.total_ai_cost_usd for user in users),
            total_apify_cost_usd=sum(user.total_apify_cost_usd for user in users),
            total_estimated_cost_usd=sum(user.total_estimated_cost_usd for user in users),
        ),
        users,
    )


def _rollup(
    owner_id: str,
    jobs: list[CompetitorJob],
    snapshots: dict[str, CompetitorSnapshot | None],
    user: UserSummary | None,
) -> AdminUserRollup:
    return AdminUserRollup(
        owner_id=owner_id,
        name=user.name if user else owner_id,
        email=user.email if user else "",
        role=user.role if user else "tester",
        total_reports=len(jobs),
        complete_reports=sum(job.status.value == "complete" for job in jobs),
        partial_reports=sum(job.status.value == "partial" for job in jobs),
        failed_reports=sum(job.status.value == "failed" for job in jobs),
        ai_requested=sum(job.ai_requested is True for job in jobs),
        ai_successes=sum(
            _ai_status(snapshots.get(job.job_id)) in {"ok", "cache_hit"} for job in jobs
        ),
        total_ai_cost_usd=sum(_ai_cost(snapshots.get(job.job_id)) for job in jobs),
        total_apify_cost_usd=sum(
            _apify_cost(job, snapshots.get(job.job_id)) for job in jobs
        ),
    )


def _empty_rollup(user: UserSummary) -> AdminUserRollup:
    return AdminUserRollup(
        owner_id=user.user_id,
        name=user.name,
        email=user.email,
        role=user.role,
        total_reports=0,
        complete_reports=0,
        partial_reports=0,
        failed_reports=0,
        ai_requested=0,
        ai_successes=0,
        total_ai_cost_usd=0.0,
        total_apify_cost_usd=0.0,
    )


def _user_summaries(user_store) -> dict[str, UserSummary]:
    if user_store is None:
        return {}
    return {user.user_id: user for user in user_store.list_users()}


def _ai_status(snapshot: CompetitorSnapshot | None) -> str:
    return snapshot.ai_analysis_status if snapshot else ""


def _ai_cost(snapshot: CompetitorSnapshot | None) -> float:
    if not snapshot or not snapshot.ai_run:
        return 0.0
    return snapshot.ai_run.usage.estimated_cost_usd


def _apify_cost(job: CompetitorJob, snapshot: CompetitorSnapshot | None) -> float:
    if job.apify_estimated_cost_usd > 0:
        return job.apify_estimated_cost_usd
    return snapshot.apify_estimated_cost_usd if snapshot else 0.0


def _read_snapshot(job_store, job_id: str) -> CompetitorSnapshot | None:
    raw = job_store.read_snapshot(job_id)
    if not raw:
        return None
    try:
        return CompetitorSnapshot.model_validate_json(raw)
    except ValueError:
        return None
