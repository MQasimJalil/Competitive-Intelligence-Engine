from app.schemas import (
    BusinessCategory,
    CompetitorProfile,
    ExtractionResult,
    ExtractionStatus,
    ProfileClaim,
    ProfileSection,
    ValidationReport,
    WorkflowRun,
    WorkflowState,
)
from app.tools.competitor_brief.view_model import build_report_view


def test_report_view_leads_with_business_coverage_and_claim_evidence():
    claim = ProfileClaim(
        category=BusinessCategory.PRICING_PACKAGING,
        label="Visible price",
        value="$20/month",
        evidence_excerpt="Pro costs $20/month for each user.",
        source_url="https://example.com/pricing",
        retrieved_at="2026-06-09T00:00:00Z",
    )
    profile = CompetitorProfile(
        domain="example.com",
        sections=[
            ProfileSection(
                title="Offer and commercial motion",
                question="What do they sell, and how do buyers start or buy?",
                claims=[claim],
            )
        ],
        unanswered_questions=[],
        source_count=1,
        answered_dimensions=1,
        total_dimensions=5,
    )

    report = build_report_view("example.com", [], profile)

    assert report.coverage_sentence == "1 of 5 areas answered; 1 source cited."
    assert report.sections[0].claims[0].evidence == "Pro costs $20/month for each user."
    assert report.sections[0].claims[0].source_label == "example.com/pricing"


def test_report_view_moves_collection_status_to_diagnostics():
    results = [
        ExtractionResult.unavailable(
            extractor_name="robots_policy",
            status=ExtractionStatus.ROBOTS_DISALLOWED,
            source_url="https://example.com/robots.txt",
            notes="disallowed",
        )
    ]

    report = build_report_view("example.com", results)

    assert len(report.diagnostics) == 1
    assert report.diagnostics[0].status_label == "Blocked by robots"


def test_report_view_exposes_workflow_and_validation_diagnostics():
    workflow = WorkflowRun(domain="example.com")
    workflow.advance(WorkflowState.SCRAPING, "Collecting")
    workflow.advance(WorkflowState.FAILED, "Stopped")
    validation = ValidationReport(ready_for_report=False, checked_fact_count=0)

    report = build_report_view(
        "example.com",
        [],
        workflow=workflow,
        validation=validation,
    )

    assert report.workflow_state == "failed"
    assert report.workflow_stages[0].label == "Scraping"
    assert not report.validation_ready
