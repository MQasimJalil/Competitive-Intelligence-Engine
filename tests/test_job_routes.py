import asyncio
import re
from dataclasses import replace

from app.auth.store import FileUserStore
from app.credits.store import FileCreditStore
from app.jobs.store import FileJobStore
from app.main import app
from app.schemas import (
    ExtractionResult,
    ExtractionStatus,
    JobStatus,
    NodeFailurePolicy,
    NodeRun,
    NodeStatus,
    NormalizedBusinessProfile,
    WorkflowRun,
    WorkflowState,
)
from app.tools.competitor_brief import router as router_module
from app.tools.competitor_brief.service import CompetitorSnapshot
from app.tools.competitor_brief.validation import validate_business_profile
from app.web import auth as web_auth
from app.web import csrf as csrf_module
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
    page = client.get("/auth/login")
    match = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    csrf_token = match.group(1) if match else ""
    client.post(
        "/auth/login",
        data={
            "email": "tester@example.com",
            "password": "tester-password",
            "csrf_token": csrf_token,
        },
        follow_redirects=False,
    )
    return client, user


def test_tool_page_offers_free_and_ai_report_choices(tmp_path, monkeypatch):
    client, _user = _create_logged_in_client(monkeypatch, tmp_path)

    response = client.get("/tools/competitor-brief")

    assert response.status_code == 200
    assert "Free brief" in response.text
    assert "Strategic analysis" in response.text
    assert "1 credit" in response.text
    assert "scanProgress.hidden = true" in response.text
    assert 'loadingMessage.classList.add("error")' in response.text
    assert "scanForm.reportValidity()" in response.text
    assert 'domainInput.addEventListener("invalid"' in response.text
    assert "We will show the new brief when it is ready" in response.text
    assert "focus({ preventScroll: true })" in response.text
    assert "current.progress_message" in response.text
    assert "Elapsed:" in response.text


def test_tool_page_polling_resets_ui_when_late_poll_fails(tmp_path, monkeypatch):
    client, _user = _create_logged_in_client(monkeypatch, tmp_path)

    response = client.get("/tools/competitor-brief")

    assert response.status_code == 200
    assert "const failResearchJob = (message)" in response.text
    assert "window.setTimeout(() => void poll(), 700)" in response.text
    assert 'if (current.status === "failed") {' in response.text
    assert 'failResearchJob(current.error || "Research job failed.")' in response.text


def test_job_status_returns_honest_progress_details(tmp_path, monkeypatch):
    store = FileJobStore(tmp_path)
    monkeypatch.setattr(router_module, "job_store", store)
    client, user = _create_logged_in_client(monkeypatch, tmp_path)
    job = store.create("example.com", owner_id=user.user_id)
    workflow = WorkflowRun(domain="example.com")
    workflow.advance(WorkflowState.SCRAPING, "Started robots and homepage collection.")
    workflow.advance(WorkflowState.CLASSIFYING, "Homepage collected. Classifying public pages.")
    workflow.advance(WorkflowState.EXTRACTING, "12 product facts found. Extracting selected pages.")
    workflow.node_runs.append(
        NodeRun(
            name="apify_public_enrichment",
            version="v1",
            failure_policy=NodeFailurePolicy.OPTIONAL,
            status=NodeStatus.RUNNING,
        )
    )
    store.update_workflow(job.job_id, workflow)

    response = client.get(f"/tools/competitor-brief/jobs/{job.job_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["progress_message"] == "Apify enrichment running."
    assert payload["progress_detail"] == "12 product facts found. Extracting selected pages."
    assert payload["elapsed_seconds"] >= 0
    assert payload["stage_facts"]["products_found"] == 12


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


def test_sync_post_is_disabled_by_default(tmp_path, monkeypatch):
    client, _user = _create_logged_in_client(monkeypatch, tmp_path)

    response = client.post("/tools/competitor-brief", data={"domain": "example.com"})

    assert response.status_code == 410
    assert "Synchronous report generation is disabled" in response.json()["detail"]


def test_job_creation_requires_csrf_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setattr(
        csrf_module,
        "settings",
        replace(csrf_module.settings, csrf_protection_enabled=True),
    )
    client, _user = _create_logged_in_client(monkeypatch, tmp_path)

    response = client.post("/tools/competitor-brief/jobs", data={"domain": "example.com"})

    assert response.status_code == 403
    assert "Security token" in response.json()["detail"]


def test_job_creation_accepts_csrf_token_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setattr(
        csrf_module,
        "settings",
        replace(csrf_module.settings, csrf_protection_enabled=True),
    )
    store = FileJobStore(tmp_path)
    requests = []

    async def capture(job_id, domain, enable_ai):
        requests.append((job_id, domain, enable_ai))

    monkeypatch.setattr(router_module, "job_store", store)
    monkeypatch.setattr(router_module, "_run_persisted_job", capture)
    client, _user = _create_logged_in_client(monkeypatch, tmp_path)
    page = client.get("/tools/competitor-brief")
    csrf_token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)

    response = client.post(
        "/tools/competitor-brief/jobs",
        data={"domain": "example.com", "csrf_token": csrf_token},
    )

    assert response.status_code == 200
    assert requests


def test_create_job_passes_ai_choice_to_workflow(tmp_path, monkeypatch):
    store = FileJobStore(tmp_path)
    credits = FileCreditStore(tmp_path / "credits")
    requests = []

    async def capture(job_id, domain, enable_ai):
        requests.append((job_id, domain, enable_ai))

    monkeypatch.setattr(router_module, "job_store", store)
    monkeypatch.setattr(router_module, "credit_store", credits)
    monkeypatch.setattr(router_module, "_run_persisted_job", capture)
    client, user = _create_logged_in_client(monkeypatch, tmp_path)
    credits.grant(user_id=user.user_id, amount=1, reason="beta_grant")

    response = client.post(
        "/tools/competitor-brief/jobs",
        data={"domain": "example.com", "enable_ai": "true"},
    )

    job = store.get(response.json()["job_id"])
    assert response.status_code == 200
    assert job.owner_id == user.user_id
    assert job.ai_requested is True
    assert requests == [(job.job_id, "example.com", True)]


def test_create_ai_job_requires_available_credit(tmp_path, monkeypatch):
    store = FileJobStore(tmp_path / "jobs")
    credit_store = FileCreditStore(tmp_path / "credits")
    monkeypatch.setattr(router_module, "job_store", store)
    monkeypatch.setattr(router_module, "credit_store", credit_store)
    client, _user = _create_logged_in_client(monkeypatch, tmp_path)

    response = client.post(
        "/tools/competitor-brief/jobs",
        data={"domain": "example.com", "enable_ai": "true"},
    )

    assert response.status_code == 402
    assert "credit" in response.json()["detail"].lower()
    assert store.list_all() == []


def test_create_free_job_does_not_require_credit(tmp_path, monkeypatch):
    store = FileJobStore(tmp_path / "jobs")
    credit_store = FileCreditStore(tmp_path / "credits")
    monkeypatch.setattr(router_module, "job_store", store)
    monkeypatch.setattr(router_module, "credit_store", credit_store)
    client, user = _create_logged_in_client(monkeypatch, tmp_path)

    response = client.post("/tools/competitor-brief/jobs", data={"domain": "example.com"})

    assert response.status_code == 200
    assert store.get(response.json()["job_id"]).owner_id == user.user_id


def test_create_job_returns_clear_error_for_invalid_domain(tmp_path, monkeypatch):
    client, _user = _create_logged_in_client(monkeypatch, tmp_path)

    response = client.post("/tools/competitor-brief/jobs", data={"domain": "not a domain"})

    assert response.status_code == 400
    assert (
        response.json()["detail"]
        == "Enter a public website, such as example.com or https://example.com."
    )


def test_create_job_enforces_user_concurrency_limit(tmp_path, monkeypatch):
    store = FileJobStore(tmp_path)
    monkeypatch.setattr(router_module, "job_store", store)
    monkeypatch.setattr(router_module.job_start_limiter, "allow", lambda user_id: True)
    monkeypatch.setattr(
        router_module,
        "settings",
        replace(
            router_module.settings,
            job_user_concurrency_limit=1,
            job_global_concurrency_limit=10,
        ),
    )
    client, user = _create_logged_in_client(monkeypatch, tmp_path)
    existing = store.create("already-running.example", owner_id=user.user_id)
    existing.status = JobStatus.RUNNING
    store.save(existing)

    response = client.post("/tools/competitor-brief/jobs", data={"domain": "example.com"})

    assert response.status_code == 429
    assert "already has a report running" in response.json()["detail"]


def test_create_job_enforces_rate_limit(tmp_path, monkeypatch):
    store = FileJobStore(tmp_path)
    monkeypatch.setattr(router_module, "job_store", store)

    def block_start(owner_id):
        raise router_module.HTTPException(
            status_code=429,
            detail="Too many reports started recently. Wait a minute and try again.",
        )

    monkeypatch.setattr(router_module, "_enforce_job_start_limits", block_start)
    client, _user = _create_logged_in_client(monkeypatch, tmp_path)

    response = client.post("/tools/competitor-brief/jobs", data={"domain": "example.com"})

    assert response.status_code == 429
    assert "Too many reports started" in response.json()["detail"]


def test_file_job_creation_enforces_global_concurrency_limit(tmp_path, monkeypatch):
    store = FileJobStore(tmp_path)
    monkeypatch.setattr(router_module, "job_store", store)
    monkeypatch.setattr(router_module.job_start_limiter, "allow", lambda user_id: True)
    monkeypatch.setattr(
        router_module,
        "settings",
        replace(
            router_module.settings,
            job_user_concurrency_limit=10,
            job_global_concurrency_limit=1,
        ),
    )
    client, _user = _create_logged_in_client(monkeypatch, tmp_path)
    existing = store.create("already-running.example", owner_id="another-user")
    existing.status = JobStatus.RUNNING
    store.save(existing)

    response = client.post("/tools/competitor-brief/jobs", data={"domain": "example.com"})

    assert response.status_code == 429
    assert "queue is full" in response.json()["detail"]


def test_file_job_creation_enforces_start_rate_limiter(tmp_path, monkeypatch):
    store = FileJobStore(tmp_path)
    monkeypatch.setattr(router_module, "job_store", store)
    monkeypatch.setattr(router_module.job_start_limiter, "allow", lambda user_id: False)
    monkeypatch.setattr(
        router_module,
        "settings",
        replace(
            router_module.settings,
            job_user_concurrency_limit=10,
            job_global_concurrency_limit=10,
        ),
    )
    client, _user = _create_logged_in_client(monkeypatch, tmp_path)

    response = client.post("/tools/competitor-brief/jobs", data={"domain": "example.com"})

    assert response.status_code == 429
    assert "Too many reports started" in response.json()["detail"]


def test_pdf_download_requires_completed_job_id_without_recrawling(tmp_path, monkeypatch):
    store = FileJobStore(tmp_path)
    monkeypatch.setattr(router_module, "job_store", store)

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("download endpoint must not rebuild crawl snapshots")

    monkeypatch.setattr(router_module, "build_preview_snapshot", fail_if_called)
    client, _user = _create_logged_in_client(monkeypatch, tmp_path)

    response = client.post("/tools/competitor-brief/pdf", data={"domain": "example.com"})

    assert response.status_code == 400
    assert "completed brief" in response.json()["detail"]


def test_evidence_download_requires_completed_job_id_without_recrawling(tmp_path, monkeypatch):
    store = FileJobStore(tmp_path)
    monkeypatch.setattr(router_module, "job_store", store)

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("download endpoint must not rebuild crawl snapshots")

    monkeypatch.setattr(router_module, "build_preview_snapshot", fail_if_called)
    client, _user = _create_logged_in_client(monkeypatch, tmp_path)

    response = client.post("/tools/competitor-brief/evidence", data={"domain": "example.com"})

    assert response.status_code == 400
    assert "completed brief" in response.json()["detail"]


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
            "We couldn't find that domain. Check the spelling or try the company's main website."
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


def test_successful_ai_job_deducts_one_credit_after_artifacts_are_saved(tmp_path, monkeypatch):
    store = FileJobStore(tmp_path / "jobs")
    user_store = FileUserStore(tmp_path / "users")
    credit_store = FileCreditStore(tmp_path / "credits")
    credit_store.grant(user_id="owner-1", amount=1, reason="beta_grant")
    user = user_store.create_user(
        name="Owner One",
        email="owner@example.com",
        password="owner-password",
        credit_balance=1,
    )
    user.user_id = "owner-1"
    user_store.save(user)
    job = store.create("example.com", owner_id="owner-1", ai_requested=True)
    workflow = WorkflowRun(domain="example.com")
    workflow.advance(WorkflowState.SCRAPING)
    workflow.advance(WorkflowState.CLASSIFYING)
    workflow.advance(WorkflowState.EXTRACTING)
    workflow.advance(WorkflowState.VALIDATING)
    workflow.advance(WorkflowState.COMPLETE)
    snapshot = CompetitorSnapshot(
        domain="example.com",
        homepage="https://example.com/",
        results=[],
        ai_analysis_status="ok",
        ai_run={
            "status": "ok",
            "failure_code": "",
            "strategy": "structured_output",
            "attempt_count": 1,
            "provider": "openrouter",
            "model": "qwen/test",
            "prompt_version": "v1",
            "schema_version": "analysis-v1",
            "usage": {"total_tokens": 420, "estimated_cost_usd": 0.02},
            "message": "",
        },
        workflow=workflow,
    )

    async def successful_snapshot(*args, **kwargs):
        return snapshot

    monkeypatch.setattr(router_module, "job_store", store)
    monkeypatch.setattr(router_module, "user_store", user_store)
    monkeypatch.setattr(router_module, "credit_store", credit_store)
    monkeypatch.setattr(router_module, "build_preview_snapshot", successful_snapshot)
    monkeypatch.setattr(router_module, "render_full_dossier_bytes", lambda report: b"%PDF")
    monkeypatch.setattr(router_module, "render_evidence_appendix_bytes", lambda profile: b"%PDF")

    asyncio.run(router_module._run_persisted_job(job.job_id, job.domain, True))

    assert credit_store.balance_for_user("owner-1") == 0
    assert user_store.get("owner-1").credit_balance == 0
    assert len(credit_store.list_for_job(job.job_id)) == 1


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
    assert "Admin dashboard" in response.text
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
    assert "Download brief PDF" in response.text
    assert "Download evidence appendix" in response.text
    assert "Print report" in response.text


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
