from datetime import UTC, datetime, timedelta

from app.jobs.store import FileJobStore, build_job_store
from app.schemas import CompetitorJob, ReportFeedback, WorkflowRun, WorkflowState


def test_legacy_job_without_ai_choice_remains_unknown():
    job = CompetitorJob.model_validate({"domain": "legacy.example"})

    assert job.ai_requested is None


def test_file_job_store_persists_workflow_progress(tmp_path):
    store = FileJobStore(tmp_path)
    job = store.create("example.com")
    workflow = WorkflowRun(domain="example.com")
    workflow.advance(WorkflowState.SCRAPING)

    store.update_workflow(job.job_id, workflow)
    saved = store.get(job.job_id)

    assert saved is not None
    assert saved.status.value == "running"
    assert saved.workflow.state == WorkflowState.SCRAPING


def test_file_job_store_persists_ai_request_choice(tmp_path):
    store = FileJobStore(tmp_path)

    free_job = store.create("free.example", ai_requested=False)
    ai_job = store.create("ai.example", ai_requested=True)

    assert store.get(free_job.job_id).ai_requested is False
    assert store.get(ai_job.job_id).ai_requested is True


def test_file_job_store_persists_completed_artifacts(tmp_path):
    store = FileJobStore(tmp_path)
    job = store.create("example.com")

    store.save_artifacts(
        job.job_id,
        snapshot_json='{"domain":"example.com"}',
        pdf=b"%PDF-report",
        evidence_pdf=b"%PDF-evidence",
    )

    saved = store.get(job.job_id)
    assert saved.has_snapshot and saved.has_pdf and saved.has_evidence
    assert store.read_pdf(job.job_id) == b"%PDF-report"


def test_file_job_store_lists_owner_jobs_and_keeps_tenants_separate(tmp_path):
    store = FileJobStore(tmp_path)
    newest = store.create("new.example", owner_id="owner-a")
    older = store.create("old.example", owner_id="owner-a")
    other = store.create("other.example", owner_id="owner-b")
    older.created_at = newest.created_at - timedelta(days=1)
    store.save(older)

    jobs = store.list_for_owner("owner-a")

    assert [job.job_id for job in jobs] == [newest.job_id, older.job_id]
    assert other.job_id not in {job.job_id for job in jobs}


def test_file_job_store_lists_all_jobs_for_privacy_safe_admin(tmp_path):
    store = FileJobStore(tmp_path)
    newest = store.create("new.example", owner_id="owner-a")
    older = store.create("old.example", owner_id="owner-b")
    older.created_at = newest.created_at - timedelta(days=1)
    store.save(older)

    jobs = store.list_all()

    assert [job.job_id for job in jobs] == [newest.job_id, older.job_id]


def test_file_job_store_persists_feedback_and_deletes_job_artifacts(tmp_path):
    store = FileJobStore(tmp_path)
    job = store.create("example.com", owner_id="owner-a")
    store.save_artifacts(
        job.job_id,
        snapshot_json='{"domain":"example.com"}',
        pdf=b"%PDF-report",
        evidence_pdf=b"%PDF-evidence",
    )
    feedback = ReportFeedback(
        job_id=job.job_id,
        owner_id="owner-a",
        usefulness_rating=4,
        missing_information="Current hiring signals",
        factual_error=True,
    )

    store.save_feedback(feedback)
    assert store.get_feedback(job.job_id, "owner-a") == feedback

    assert store.delete(job.job_id, "owner-a")
    assert store.get(job.job_id) is None
    assert store.read_pdf(job.job_id) is None


def test_file_job_store_cleans_up_expired_jobs(tmp_path):
    store = FileJobStore(tmp_path)
    expired = store.create("expired.example", owner_id="owner-a")
    active = store.create("active.example", owner_id="owner-a")
    expired.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    active.expires_at = datetime.now(UTC) + timedelta(days=1)
    store.save(expired)
    store.save(active)

    removed = store.cleanup_expired()

    assert removed == 1
    assert store.get(expired.job_id) is None
    assert store.get(active.job_id) is not None


def test_job_store_factory_requires_database_url_for_postgres(tmp_path):
    try:
        build_job_store("postgres", root=tmp_path, database_url="")
    except ValueError as exc:
        assert "DATABASE_URL" in str(exc)
    else:
        raise AssertionError("Postgres repository must require DATABASE_URL")


def test_file_job_store_marks_artifact_failure_as_failed(tmp_path):
    store = FileJobStore(tmp_path)
    job = store.create("example.com")

    store.mark_failed(job.job_id, "PDF exceeded page limit")

    saved = store.get(job.job_id)
    assert saved is not None
    assert saved.status.value == "failed"
    assert saved.error == "PDF exceeded page limit"
