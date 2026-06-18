from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class WorkflowState(StrEnum):
    PENDING = "pending"
    SCRAPING = "scraping"
    CLASSIFYING = "classifying"
    EXTRACTING = "extracting"
    VALIDATING = "validating"
    PARTIAL = "partial"
    COMPLETE = "complete"
    FAILED = "failed"


VALID_TRANSITIONS = {
    WorkflowState.PENDING: {WorkflowState.SCRAPING, WorkflowState.FAILED},
    WorkflowState.SCRAPING: {WorkflowState.CLASSIFYING, WorkflowState.FAILED},
    WorkflowState.CLASSIFYING: {WorkflowState.EXTRACTING, WorkflowState.FAILED},
    WorkflowState.EXTRACTING: {WorkflowState.VALIDATING, WorkflowState.FAILED},
    WorkflowState.VALIDATING: {
        WorkflowState.PARTIAL,
        WorkflowState.COMPLETE,
        WorkflowState.FAILED,
    },
    WorkflowState.PARTIAL: set(),
    WorkflowState.COMPLETE: set(),
    WorkflowState.FAILED: set(),
}


class WorkflowTransition(BaseModel):
    from_state: WorkflowState
    to_state: WorkflowState
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    detail: str = ""


class NodeStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    SKIPPED = "skipped"


class NodeFailurePolicy(StrEnum):
    FATAL = "fatal"
    PARTIAL = "partial"
    OPTIONAL = "optional"


class NodeRun(BaseModel):
    name: str
    version: str
    failure_policy: NodeFailurePolicy
    status: NodeStatus = NodeStatus.PENDING
    started_at: datetime | None = None
    finished_at: datetime | None = None
    message: str = ""


class WorkflowRun(BaseModel):
    domain: str
    state: WorkflowState = WorkflowState.PENDING
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    transitions: list[WorkflowTransition] = Field(default_factory=list)
    node_runs: list[NodeRun] = Field(default_factory=list)

    def advance(self, next_state: WorkflowState, detail: str = "") -> None:
        if next_state not in VALID_TRANSITIONS[self.state]:
            raise ValueError(f"invalid workflow transition: {self.state} -> {next_state}")
        self.transitions.append(
            WorkflowTransition(from_state=self.state, to_state=next_state, detail=detail)
        )
        self.state = next_state
        if next_state in {
            WorkflowState.PARTIAL,
            WorkflowState.COMPLETE,
            WorkflowState.FAILED,
        }:
            self.finished_at = datetime.now(UTC)


class ValidationSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ValidationIssue(BaseModel):
    code: str
    severity: ValidationSeverity
    message: str
    citation_ids: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)


class ValidationReport(BaseModel):
    ready_for_report: bool
    checked_fact_count: int = Field(ge=0)
    issues: list[ValidationIssue] = Field(default_factory=list)
    excluded_citation_ids: list[str] = Field(default_factory=list)
    category_fact_counts: dict[str, int] = Field(default_factory=dict)
