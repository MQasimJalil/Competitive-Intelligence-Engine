from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse

from app.schemas import (
    AIAnalysis,
    AIAnalysisRun,
    CompetitorProfile,
    ExtractionResult,
    ExtractionStatus,
    NodeRun,
    NormalizedBusinessProfile,
    StructuredIntelligenceProfile,
    ValidationReport,
    WorkflowRun,
)
from app.tools.competitor_brief.executive_view import ExecutiveReport, build_executive_report

DIAGNOSTIC_EXTRACTORS = {
    "robots_policy",
    "business_page_map",
    "public_link_discovery",
    "sitemap_discovery",
    "ranked_crawl_plan",
    "tech_signals",
    "page_title",
}

STATUS_LABELS = {
    ExtractionStatus.OK: "Found",
    ExtractionStatus.NO_DATA: "No public data",
    ExtractionStatus.ROBOTS_DISALLOWED: "Blocked by robots",
    ExtractionStatus.TOS_BLOCKED: "Access blocked",
    ExtractionStatus.RATE_LIMITED: "Rate limited",
    ExtractionStatus.PARSE_FAILED: "Could not parse",
    ExtractionStatus.NETWORK_FAILED: "Network failed",
}

STATUS_TONES = {
    ExtractionStatus.OK: "success",
    ExtractionStatus.NO_DATA: "muted",
    ExtractionStatus.ROBOTS_DISALLOWED: "blocked",
    ExtractionStatus.TOS_BLOCKED: "blocked",
    ExtractionStatus.RATE_LIMITED: "warning",
    ExtractionStatus.PARSE_FAILED: "warning",
    ExtractionStatus.NETWORK_FAILED: "warning",
}


@dataclass(frozen=True)
class ClaimView:
    label: str
    value: str
    evidence: str
    source_label: str
    source_url: str
    retrieved_label: str


@dataclass(frozen=True)
class SectionView:
    title: str
    question: str
    claims: list[ClaimView]


@dataclass(frozen=True)
class DiagnosticView:
    label: str
    status_label: str
    status_tone: str
    details: str
    source_url: str


@dataclass(frozen=True)
class WorkflowStageView:
    label: str
    detail: str
    duration_label: str


@dataclass(frozen=True)
class NodeRunView:
    label: str
    status: str
    failure_policy: str
    duration_label: str
    message: str


@dataclass(frozen=True)
class ValidationIssueView:
    code: str
    severity: str
    message: str


@dataclass(frozen=True)
class ReportView:
    domain: str
    generated_label: str
    coverage_sentence: str
    source_count: int
    sections: list[SectionView]
    unanswered_questions: list[str]
    diagnostics: list[DiagnosticView]
    executive: ExecutiveReport
    business_profile: NormalizedBusinessProfile | None
    ai_analysis: AIAnalysis | None
    ai_analysis_status: str
    ai_run: AIAnalysisRun | None
    workflow_state: str
    workflow_stages: list[WorkflowStageView]
    node_runs: list[NodeRunView]
    validation_ready: bool
    validation_issues: list[ValidationIssueView]
    intelligence: StructuredIntelligenceProfile | None
    extraction_result_count: int
    validated_fact_count: int
    job_id: str


def build_report_view(
    domain: str,
    results: list[ExtractionResult],
    profile: CompetitorProfile | None = None,
    business_profile: NormalizedBusinessProfile | None = None,
    ai_analysis: AIAnalysis | None = None,
    ai_analysis_status: str = "not_configured",
    ai_run: AIAnalysisRun | None = None,
    workflow: WorkflowRun | None = None,
    validation: ValidationReport | None = None,
    intelligence: StructuredIntelligenceProfile | None = None,
    job_id: str = "",
) -> ReportView:
    normalized = profile or CompetitorProfile(
        domain=domain,
        sections=[],
        unanswered_questions=[],
        source_count=0,
        answered_dimensions=0,
        total_dimensions=5,
    )
    report_business_profile = (
        intelligence.to_business_profile() if intelligence else business_profile
    )
    executive = build_executive_report(
        domain,
        results,
        normalized,
        report_business_profile,
        ai_analysis,
    )
    cited_source_count = len(executive.sources) or normalized.source_count
    source_label = "source" if cited_source_count == 1 else "sources"
    coverage_sentence = (
        f"{normalized.answered_dimensions} of {normalized.total_dimensions} areas answered; "
        f"{cited_source_count} {source_label} cited."
    )
    return ReportView(
        domain=domain,
        generated_label=normalized.generated_at.strftime("%Y-%m-%d %H:%M UTC"),
        coverage_sentence=coverage_sentence,
        source_count=normalized.source_count,
        sections=[
            SectionView(
                title=section.title,
                question=section.question,
                claims=[
                    ClaimView(
                        label=claim.label,
                        value=claim.value,
                        evidence=claim.evidence_excerpt,
                        source_label=_source_label(str(claim.source_url)),
                        source_url=str(claim.source_url),
                        retrieved_label=claim.retrieved_at.strftime("%Y-%m-%d"),
                    )
                    for claim in section.claims
                ],
            )
            for section in normalized.sections
        ],
        unanswered_questions=normalized.unanswered_questions,
        diagnostics=[_diagnostic_view(result) for result in results if _is_diagnostic(result)],
        executive=executive,
        business_profile=report_business_profile,
        ai_analysis=ai_analysis,
        ai_analysis_status=ai_analysis_status,
        ai_run=ai_run,
        workflow_state=workflow.state.value if workflow else "unknown",
        workflow_stages=_workflow_stage_views(workflow),
        node_runs=[_node_run_view(node) for node in (workflow.node_runs if workflow else [])],
        validation_ready=validation.ready_for_report if validation else False,
        validation_issues=[
            ValidationIssueView(
                code=issue.code,
                severity=issue.severity.value,
                message=issue.message,
            )
            for issue in (validation.issues if validation else [])
        ],
        intelligence=intelligence,
        extraction_result_count=len(results),
        validated_fact_count=len(report_business_profile.facts) if report_business_profile else 0,
        job_id=job_id,
    )


def _is_diagnostic(result: ExtractionResult) -> bool:
    return result.extractor_name in DIAGNOSTIC_EXTRACTORS or result.status != ExtractionStatus.OK


def _diagnostic_view(result: ExtractionResult) -> DiagnosticView:
    label = result.extractor_name.replace("_", " ").title()
    details = result.notes or "No additional details."
    if result.http_status:
        details = f"{details} HTTP {result.http_status}."
    return DiagnosticView(
        label=label,
        status_label=STATUS_LABELS[result.status],
        status_tone=STATUS_TONES[result.status],
        details=details,
        source_url=str(result.source_url) if result.source_url else "",
    )


def _source_label(source_url: str) -> str:
    parsed = urlparse(source_url)
    path = parsed.path.rstrip("/") or "/"
    return f"{parsed.netloc}{path}"


def _workflow_stage_views(workflow: WorkflowRun | None) -> list[WorkflowStageView]:
    if workflow is None:
        return []
    views = []
    for index, transition in enumerate(workflow.transitions):
        end = (
            workflow.transitions[index + 1].occurred_at
            if index + 1 < len(workflow.transitions)
            else workflow.finished_at
        )
        views.append(
            WorkflowStageView(
                label=transition.to_state.value.replace("_", " ").title(),
                detail=transition.detail,
                duration_label=_duration_label(transition.occurred_at, end),
            )
        )
    return views


def _node_run_view(node: NodeRun) -> NodeRunView:
    return NodeRunView(
        label=node.name.replace("_", " ").title(),
        status=node.status.value.replace("_", " ").title(),
        failure_policy=node.failure_policy.value.title(),
        duration_label=_duration_label(node.started_at, node.finished_at),
        message=node.message,
    )


def _duration_label(start: datetime | None, end: datetime | None) -> str:
    if start is None or end is None:
        return "In progress"
    seconds = max(0.0, (end - start).total_seconds())
    return f"{seconds:.2f}s"
