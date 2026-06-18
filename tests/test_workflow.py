import pytest
from app.schemas import WorkflowRun, WorkflowState


def test_workflow_enforces_required_stage_order():
    run = WorkflowRun(domain="example.com")

    run.advance(WorkflowState.SCRAPING)
    run.advance(WorkflowState.CLASSIFYING)
    run.advance(WorkflowState.EXTRACTING)
    run.advance(WorkflowState.VALIDATING)
    run.advance(WorkflowState.COMPLETE)

    assert run.state == WorkflowState.COMPLETE
    assert run.finished_at is not None
    assert [item.to_state for item in run.transitions] == [
        WorkflowState.SCRAPING,
        WorkflowState.CLASSIFYING,
        WorkflowState.EXTRACTING,
        WorkflowState.VALIDATING,
        WorkflowState.COMPLETE,
    ]


def test_workflow_rejects_skipped_stage():
    run = WorkflowRun(domain="example.com")

    with pytest.raises(ValueError, match="invalid workflow transition"):
        run.advance(WorkflowState.EXTRACTING)
