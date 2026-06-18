from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field

from app.schemas.workflow import ValidationReport, WorkflowRun, WorkflowState


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"


class CompetitorJob(BaseModel):
    job_id: str = Field(default_factory=lambda: uuid4().hex)
    domain: str
    owner_id: str = "local-development-user"
    status: JobStatus = JobStatus.PENDING
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime = Field(default_factory=lambda: datetime.now(UTC) + timedelta(days=30))
    workflow: WorkflowRun | None = None
    validation: ValidationReport | None = None
    result_count: int = Field(default=0, ge=0)
    fact_count: int = Field(default=0, ge=0)
    ai_requested: bool | None = None
    apify_estimated_cost_usd: float = Field(default=0.0, ge=0.0)
    has_snapshot: bool = False
    has_pdf: bool = False
    has_evidence: bool = False
    error: str = ""

    def apply_workflow(self, workflow: WorkflowRun) -> None:
        self.workflow = workflow.model_copy(deep=True)
        self.updated_at = datetime.now(UTC)
        self.status = {
            WorkflowState.PENDING: JobStatus.PENDING,
            WorkflowState.PARTIAL: JobStatus.PARTIAL,
            WorkflowState.COMPLETE: JobStatus.COMPLETE,
            WorkflowState.FAILED: JobStatus.FAILED,
        }.get(workflow.state, JobStatus.RUNNING)


class ReportFeedback(BaseModel):
    job_id: str
    owner_id: str
    usefulness_rating: int = Field(ge=1, le=5)
    missing_information: str = Field(default="", max_length=2_000)
    factual_error: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
