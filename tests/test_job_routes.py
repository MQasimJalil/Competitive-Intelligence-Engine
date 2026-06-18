import asyncio

from app.auth.store import FileUserStore
from app.jobs.store import FileJobStore
from app.main import app
from app.schemas import (
    ExtractionResult,
    ExtractionStatus,
    NormalizedBusinessProfile,
    WorkflowRun,
    WorkflowState,
)
from app.tools.competitor_brief import router as router_module
from app.tools.competitor_brief.service import CompetitorSnapshot
from app.tools.competitor_brief.validation import validate_business_profile
from app.web import auth as web_auth
from fastapi.testclient import TestClient


def _configure_auth(monkeypatch, tmp_path):
    user_store = FileUserStore(tmp_path / "users")
    monkeypatch.setattr(web_auth, "user_store", user_store)
    monkeypatch.setattr(router_module, "user_store", user_store)
    return user_store


def _create_logged_in_client(monkeypatch, tmp_path, *, role="tester"):
    user_store = _configure_auth(monkeypatch, tmp_path)
    user = user_store.create_user(
        name="Route Tester",
        email="tester@example.com",
        password="tester-password",
        role=role,
    )
    client = TestClient(app)
    client.post(
        "/auth/login",
        data={"email": "tester@example.com", "password": "tester-password"},
        follow_redirects=False,
    )
    return client, user


def test_tool_page_offers_free_and_ai_report_choices(tmp_path, monkeypatch):
    client, _user = _create_logged_in_client(monkeypatch, tmp_path)

    response = client.get("/tools/competitor-brief")

    assert response.status_code == 200
    assert "Free report" in response.text
    assert "AI analysis" in response.text
    assert "1 credit" in response.text
    assert "scanProgress.hidden = true" in response.text
    assert 'loadingMessage.classList.add("error")' in response.text


def test_tool_page_polling_resets_ui_when_late_poll_fails(tmp_path, monkeypatch):
    client, _user = _create_logged_in_client(monkeypatch, tmp_path)

    response = client.get("/tools/competitor-brief")

    assert response.status_code == 200
    assert "const failResearchJob = (message)" in response.text
    assert "window.setTimeout(() => void poll(), 700)" in response.text
    assert 'if (current.status === "failed") {' in response.text
    assert 'failResearchJob(current.error || "Research job failed.")' in response.text


def test_create_job_defaults_to_free_report(tmp_path, monkeypatch):
    store = FileJobStore(tmp_path)
    requests = []

    async def capture(job_id, domain, enable_ai):
        requests.append((job_id, domain, enable_ai))

    monkeypatch.setattr(router_module, "job_store", store)
    monkeypatch.setattr(router_module, "_run_persisted_job", capture)
    client, user = _create_logged_in_client(monkeypatch, tmp_path)

    response = client.post("/tools/competitor-brief/jobs", data={"domain": "example.com"})

    job = store.get(response.json()["job_id"])
    assert response.status_code == 200
    assert job.owner_id == user.user_id
    assert job.ai_requested is False
    assert requests == [(job.job_id, "example.com", False)]


def test_create_job_passes_ai_choice_to_workflow(tmp_path, monkeypatch):
    store = FileJobStore(tmp_path)
    requests = []

    async def capture(job_id, domain, enable_ai):
        requests.append((job_id, domain, enable_ai))

    monkeypatch.setattr(router_module, "job_store", store)
    monkeypatch.setattr(router_module, "_run_persisted_job", capture)
    client, user = _create_logged_in_client(monkeypatch, tmp_path)

    response = client.post(
        "/tools/competitor-brief/jobs",
        data={"domain": "example.com", "enable_ai": "true"},
    )

    job = store.get(response.json()["job_id"])
    assert response.status_code == 200
    assert job.owner_id == user.user_id
    assert job.ai_requested is True
    assert requests == [(job.job_id, "example.com", True)]


def test_create_job_returns_clear_error_for_invalid_domain(tmp_path, monkeypatch):
    client, _user = _create_logged_in_client(monkeypatch, tmp_path)

    response = client.post("/tools/competitor-brief/jobs", data={"domain": "not a domain"})

    assert response.status_code == 400
    assert response.json()["detail"] == "Enter a valid public domain or URL"


def test_failed_research_job_persists_user_facing_reason(tmp_path, monkeypatch):
    store = FileJobStore(tmp_path)
    job = store.create("missing.example")
    result = ExtractionResult.unavailable(
        extractor_name="homepage_fetch",
        source_url="https://missing.example/",
        status=ExtractionStatus.NETWORK_FAILED,
        notes="Domain could not be resolved",
    )
    workflow = WorkflowRun(domain="missing.example")
    workflow.advance(WorkflowState.FAILED, "Homepage collection failed.")
    profile = NormalizedBusinessProfile(domain="missing.example")
    snapshot = CompetitorSnapshot(
        domain="missing.example",
        homepage="https://missing.example/",
        results=[result],
        business_profile=profile,
        validation=validate_business_profile([result], profile),
        workflow=workflow,
        failure_reason=(
            "The domain could not be resolved. Check that it exists and is spelled correctly."
        ),
    )

    async def failed_snapshot(*args, **kwargs):
        return snapshot

    monkeypatch.setattr(router_module, "job_store", store)
    monkeypatch.setattr(router_module, "build_preview_snapshot", failed_snapshot)
    monkeypatch.setattr(router_module, "render_full_dossier_bytes", lambda report: b"%PDF")
    monkeypatch.setattr(router_module, "render_evidence_appendix_bytes", lambda profile: b"%PDF")

    asyncio.run(router_module._run_persisted_job(job.job_id, job.domain, False))

    saved = store.get(job.job_id)
    assert saved.status.value == "failed"
    assert saved.error == snapshot.failure_reason
    assert saved.has_snapshot


def test_history_lists_local_owner_jobs_only(tmp_path, monkeypatch):
    store = FileJobStore(tmp_path)
    client, user = _create_logged_in_client(monkeypatch, tmp_path)
    store.create("visible.example", owner_id=user.user_id)
    store.create("hidden.example", owner_id="another-user")
    monkeypatch.setattr(router_module, "job_store", store)

    response = client.get("/tools/competitor-brief/history")

    assert response.status_code == 200
    assert "visible.example" in response.text
    assert "hidden.example" not in response.text


def test_admin_dashboard_shows_user_cost_rollups_without_report_subjects(tmp_path, monkeypatch):
    store = FileJobStore(tmp_path)
    client, user = _create_logged_in_client(monkeypatch, tmp_path, role="admin")
    job = store.create("secret-target.example", owner_id=user.user_id, ai_requested=True)
    snapshot = CompetitorSnapshot(
        domain="secret-target.example",
        homepage="https://secret-target.example/",
        results=[],
        ai_analysis_status="failed",
        apify_estimated_cost_usd=0.012,
        ai_run={
            "status": "failed",
            "failure_code": "response_schema_invalid",
            "strategy": "json_fallback",
            "attempt_count": 2,
            "provider": "openrouter",
            "model": "qwen/test",
            "prompt_version": "v1",
            "schema_version": "analysis-v1",
            "usage": {"total_tokens": 420, "estimated_cost_usd": 0.02},
            "message": "AI response did not match the required schema.",
        },
    )
    store.save_artifacts(
        job.job_id,
        snapshot_json=snapshot.model_dump_json(),
        pdf=b"%PDF",
        evidence_pdf=b"%PDF",
    )
    monkeypatch.setattr(router_module, "job_store", store)

    response = client.get("/tools/competitor-brief/admin")

    assert response.status_code == 200
    assert "Operations dashboard" in response.text
    assert "Route Tester" in response.text
    assert "secret-target.example" not in response.text
    assert f"/jobs/{job.job_id}/report" not in response.text
    assert "$0.0200" in response.text
    assert "$0.0120" in response.text


def test_customer_report_hides_operational_ai_metadata(tmp_path, monkeypatch):
    store = FileJobStore(tmp_path)
    client, user = _create_logged_in_client(monkeypatch, tmp_path)
    job = store.create("example.com", owner_id=user.user_id, ai_requested=True)
    snapshot = CompetitorSnapshot(
        domain="example.com",
        homepage="https://example.com/",
        results=[],
        ai_analysis_status="failed",
        ai_run={
            "status": "failed",
            "failure_code": "response_schema_invalid",
            "strategy": "json_fallback",
            "attempt_count": 2,
            "provider": "openrouter",
            "model": "qwen/test",
            "prompt_version": "v1",
            "schema_version": "analysis-v1",
            "usage": {"total_tokens": 420, "estimated_cost_usd": 0.02},
            "message": "AI response did not match the required schema.",
        },
    )
    store.save_artifacts(
        job.job_id,
        snapshot_json=snapshot.model_dump_json(),
        pdf=b"%PDF",
        evidence_pdf=b"%PDF",
    )
    monkeypatch.setattr(router_module, "job_store", store)

    response = client.get(f"/tools/competitor-brief/jobs/{job.job_id}/report")

    assert response.status_code == 200
    assert "qwen/test" not in response.text
    assert "420 tokens" not in response.text
    assert "Prompt v1" not in response.text
    assert "Verified report ready without AI analysis" in response.text


def test_feedback_route_persists_feedback_for_owned_job(tmp_path, monkeypatch):
    store = FileJobStore(tmp_path)
    client, user = _create_logged_in_client(monkeypatch, tmp_path)
    job = store.create("example.com", owner_id=user.user_id)
    monkeypatch.setattr(router_module, "job_store", store)

    response = client.post(
        f"/tools/competitor-brief/jobs/{job.job_id}/feedback",
        data={
            "usefulness_rating": "4",
            "missing_information": "More customer proof",
            "factual_error": "true",
        },
        follow_redirects=False,
    )

    feedback = store.get_feedback(job.job_id, user.user_id)
    assert response.status_code == 303
    assert feedback is not None
    assert feedback.usefulness_rating == 4
    assert feedback.factual_error


def test_delete_route_rejects_unowned_job(tmp_path, monkeypatch):
    store = FileJobStore(tmp_path)
    client, _user = _create_logged_in_client(monkeypatch, tmp_path)
    job = store.create("example.com", owner_id="another-user")
    monkeypatch.setattr(router_module, "job_store", store)

    response = client.post(
        f"/tools/competitor-brief/jobs/{job.job_id}/delete",
        follow_redirects=False,
    )

    assert response.status_code == 404
    assert store.get(job.job_id) is not None
