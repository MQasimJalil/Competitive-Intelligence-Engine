from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth import user_store
from app.config import settings
from app.jobs import JobStartLimiter, job_store
from app.reporting.dossier_pdf import render_full_dossier_bytes
from app.reporting.evidence_pdf import render_evidence_appendix_bytes
from app.schemas import JobStatus, NormalizedBusinessProfile, ReportFeedback, WorkflowState
from app.schemas.auth import UserRole
from app.scrapers.domain import normalize_domain
from app.tools.competitor_brief.admin_view import build_admin_view
from app.tools.competitor_brief.service import build_preview_snapshot
from app.tools.competitor_brief.view_model import build_report_view
from app.web import auth as web_auth

router = APIRouter(prefix="/tools/competitor-brief", tags=["competitor-brief"])
templates = Jinja2Templates(directory="templates")
ROLE_FORM = Form("tester")
ACTIVE_JOB_STATUSES = {JobStatus.PENDING, JobStatus.RUNNING}
job_start_limiter = JobStartLimiter(
    window_seconds=settings.job_rate_limit_window_seconds,
    max_per_window=settings.job_rate_limit_max_per_window,
)


@router.get("")
def competitor_brief_page(request: Request):
    user = web_auth.current_user(request)
    if user is None:
        return web_auth.login_redirect(request)
    return templates.TemplateResponse(
        request,
        "tools/competitor_brief.html",
        _template_context(request, domain="", report=None, error=""),
    )


@router.get("/history")
def competitor_brief_history(request: Request):
    user = web_auth.current_user(request)
    if user is None:
        return web_auth.login_redirect(request)
    job_store.cleanup_expired()
    return templates.TemplateResponse(
        request,
        "tools/competitor_brief_history.html",
        _template_context(request, jobs=job_store.list_for_owner(user.user_id)),
    )


@router.get("/admin")
def competitor_brief_admin(request: Request, tab: str = "dashboard"):
    web_auth.require_admin(request)
    active_tab = tab if tab in {"dashboard", "users", "usage"} else "dashboard"
    summary, users = build_admin_view(job_store, user_store)
    return templates.TemplateResponse(
        request,
        "tools/competitor_brief_admin.html",
        _template_context(
            request,
            summary=summary,
            users=users,
            user_error="",
            active_tab=active_tab,
        ),
    )


@router.post("/admin/users")
def create_admin_user(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    role: UserRole = ROLE_FORM,
):
    web_auth.require_admin(request)
    try:
        user_store.create_user(name=name, email=email, password=password, role=role)
    except ValueError as exc:
        summary, users = build_admin_view(job_store, user_store)
        return templates.TemplateResponse(
            request,
            "tools/competitor_brief_admin.html",
            _template_context(
                request,
                summary=summary,
                users=users,
                user_error=str(exc),
                active_tab="users",
            ),
            status_code=400,
        )
    return RedirectResponse(url="/tools/competitor-brief/admin?tab=users", status_code=303)


@router.post("/pdf")
async def competitor_brief_pdf(
    request: Request,
    domain: str = Form(...),
    job_id: str = Form(""),
) -> Response:
    user = web_auth.require_user(request)
    if not job_id:
        raise HTTPException(
            status_code=400,
            detail="Open a completed brief before downloading the PDF.",
        )
    job = _owned_job(job_id, user.user_id)
    saved = job_store.read_pdf(job_id)
    if saved is not None:
        return _pdf_response(saved, job.domain, "competitor-dossier")
    snapshot = _saved_snapshot(job_id)
    return _pdf_response(
        render_full_dossier_bytes(_report_from_snapshot(snapshot, job_id=job_id)),
        snapshot.domain,
        "competitor-dossier",
    )


@router.post("/evidence")
async def competitor_brief_evidence(
    request: Request,
    domain: str = Form(...),
    job_id: str = Form(""),
) -> Response:
    user = web_auth.require_user(request)
    if not job_id:
        raise HTTPException(
            status_code=400,
            detail="Open a completed brief before downloading the evidence appendix.",
        )
    job = _owned_job(job_id, user.user_id)
    saved = job_store.read_evidence_pdf(job_id)
    if saved is not None:
        return _pdf_response(saved, job.domain, "evidence-appendix")
    snapshot = _saved_snapshot(job_id)
    pdf = render_evidence_appendix_bytes(
        snapshot.business_profile or NormalizedBusinessProfile(domain=snapshot.domain)
    )
    return _pdf_response(pdf, snapshot.domain, "evidence-appendix")


@router.post("")
async def competitor_brief_submit(
    request: Request,
    domain: str = Form(...),
    enable_ai: bool = Form(False),
):
    user = web_auth.current_user(request)
    if user is None:
        return web_auth.login_redirect(request)
    try:
        snapshot = await build_preview_snapshot(domain, enable_ai=enable_ai)
    except ValueError as exc:
        return templates.TemplateResponse(
            request,
            "tools/competitor_brief.html",
            {
                "domain": domain,
                "report": None,
                "error": str(exc),
                "current_user": user,
            },
            status_code=400,
        )
    return templates.TemplateResponse(
        request,
        "tools/competitor_brief.html",
        _template_context(
            request,
            domain=snapshot.domain,
            report=build_report_view(
                snapshot.domain,
                snapshot.results,
                snapshot.profile,
                snapshot.business_profile,
                snapshot.ai_analysis,
                snapshot.ai_analysis_status,
                snapshot.ai_run,
                snapshot.workflow,
                snapshot.validation,
                snapshot.intelligence,
            ),
            error="",
        ),
    )


async def _run_persisted_job(job_id: str, domain: str, enable_ai: bool) -> None:
    try:
        snapshot = await build_preview_snapshot(
            domain,
            enable_ai=enable_ai,
            progress_callback=lambda workflow: job_store.update_workflow(job_id, workflow),
        )
        job_store.finish(
            job_id,
            snapshot.workflow,
            snapshot.validation,
            result_count=len(snapshot.results),
            fact_count=len(snapshot.business_profile.facts) if snapshot.business_profile else 0,
            apify_estimated_cost_usd=snapshot.apify_estimated_cost_usd,
            error=snapshot.failure_reason,
        )
        report = _report_from_snapshot(snapshot, job_id=job_id)
        job_store.save_artifacts(
            job_id,
            snapshot_json=snapshot.model_dump_json(),
            pdf=render_full_dossier_bytes(report),
            evidence_pdf=render_evidence_appendix_bytes(
                snapshot.business_profile or NormalizedBusinessProfile(domain=snapshot.domain)
            ),
        )
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        job = job_store.get(job_id)
        if job and job.workflow:
            if job.workflow.state not in {
                WorkflowState.COMPLETE,
                WorkflowState.PARTIAL,
                WorkflowState.FAILED,
            }:
                job.workflow.advance(
                    WorkflowState.FAILED,
                    "Unexpected persisted-job failure.",
                )
            job_store.finish(
                job_id,
                job.workflow,
                job.validation,
                result_count=job.result_count,
                fact_count=job.fact_count,
                apify_estimated_cost_usd=job.apify_estimated_cost_usd,
                error=error,
            )
        job_store.mark_failed(job_id, error)


@router.post("/jobs")
async def create_competitor_job(
    request: Request,
    background_tasks: BackgroundTasks,
    domain: str = Form(...),
    enable_ai: bool = Form(False),
):
    user = web_auth.require_user(request)
    try:
        normalized = normalize_domain(domain)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Enter a public website, such as example.com or https://example.com.",
        ) from exc
    _enforce_job_start_limits(user.user_id)
    job = job_store.create(
        normalized,
        owner_id=user.user_id,
        ai_requested=enable_ai,
    )
    background_tasks.add_task(_run_persisted_job, job.job_id, normalized, enable_ai)
    return job


@router.get("/jobs/{job_id}")
def get_competitor_job(request: Request, job_id: str):
    user = web_auth.require_user(request)
    return _owned_job(job_id, user.user_id)


@router.get("/jobs/{job_id}/report")
def get_competitor_job_report(request: Request, job_id: str):
    user = web_auth.current_user(request)
    if user is None:
        return web_auth.login_redirect(request)
    _owned_job(job_id, user.user_id)
    snapshot = _saved_snapshot(job_id)
    return templates.TemplateResponse(
        request,
        "tools/competitor_brief.html",
        _template_context(
            request,
            domain=snapshot.domain,
            report=_report_from_snapshot(snapshot, job_id=job_id),
            error="",
        ),
    )


@router.post("/jobs/{job_id}/feedback")
def save_competitor_job_feedback(
    request: Request,
    job_id: str,
    usefulness_rating: int = Form(...),
    missing_information: str = Form(""),
    factual_error: bool = Form(False),
):
    user = web_auth.require_user(request)
    _owned_job(job_id, user.user_id)
    job_store.save_feedback(
        ReportFeedback(
            job_id=job_id,
            owner_id=user.user_id,
            usefulness_rating=usefulness_rating,
            missing_information=missing_information,
            factual_error=factual_error,
        )
    )
    return RedirectResponse(
        url=f"/tools/competitor-brief/jobs/{job_id}/report",
        status_code=303,
    )


@router.post("/jobs/{job_id}/delete")
def delete_competitor_job(request: Request, job_id: str):
    user = web_auth.require_user(request)
    if not job_store.delete(job_id, user.user_id):
        raise HTTPException(status_code=404, detail="Job not found")
    return RedirectResponse(url="/tools/competitor-brief/history", status_code=303)


def _owned_job(job_id: str, owner_id: str):
    job = job_store.get(job_id)
    if job is None or job.owner_id != owner_id:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def _enforce_job_start_limits(owner_id: str) -> None:
    if _active_job_count(job_store.list_for_owner(owner_id)) >= settings.job_user_concurrency_limit:
        raise HTTPException(
            status_code=429,
            detail="This user already has a report running. Wait for it to finish first.",
        )
    if _active_job_count(job_store.list_all()) >= settings.job_global_concurrency_limit:
        raise HTTPException(
            status_code=429,
            detail="The research queue is full. Wait for an active report to finish first.",
        )
    if not job_start_limiter.allow(owner_id):
        raise HTTPException(
            status_code=429,
            detail="Too many reports started recently. Wait a minute and try again.",
        )


def _active_job_count(jobs) -> int:
    return sum(1 for job in jobs if job.status in ACTIVE_JOB_STATUSES)


def _saved_snapshot(job_id: str):
    raw = job_store.read_snapshot(job_id)
    if raw is None:
        raise HTTPException(status_code=404, detail="Completed job snapshot not found")
    from app.tools.competitor_brief.service import CompetitorSnapshot

    return CompetitorSnapshot.model_validate_json(raw)


def _report_from_snapshot(snapshot, *, job_id: str = ""):
    return build_report_view(
        snapshot.domain,
        snapshot.results,
        snapshot.profile,
        snapshot.business_profile,
        snapshot.ai_analysis,
        snapshot.ai_analysis_status,
        snapshot.ai_run,
        snapshot.workflow,
        snapshot.validation,
        snapshot.intelligence,
        job_id,
    )


def _pdf_response(content: bytes, domain: str, suffix: str) -> Response:
    filename = f"{domain.replace('.', '-')}-{suffix}.pdf"
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _template_context(request: Request, **values):
    return {"current_user": web_auth.current_user(request), **values}
