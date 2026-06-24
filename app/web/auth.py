from urllib.parse import quote

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth.audit import log_auth_event
from app.auth.limits import LoginThrottle
from app.auth.security import create_session_token, read_session_token, verify_password
from app.auth.store import user_store
from app.config import settings
from app.schemas.auth import AppUser
from app.web.csrf import require_csrf

router = APIRouter(prefix="/auth", tags=["auth"])
templates = Jinja2Templates(directory="templates")
login_throttle = LoginThrottle(
    window_seconds=settings.login_rate_limit_window_seconds,
    max_attempts=settings.login_rate_limit_max_attempts,
)


@router.get("/login")
def login_page(request: Request, next: str = "/tools/competitor-brief"):
    return templates.TemplateResponse(
        request,
        "auth/login.html",
        _template_context(error="", email="", next=_safe_next(next)),
    )


@router.post("/login")
def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form("/tools/competitor-brief"),
):
    key = _login_key(request, email)
    if not login_throttle.allow(key):
        log_auth_event(
            "login_rate_limited",
            email=email,
            ip_address=_client_ip(request),
            user_agent=request.headers.get("user-agent", ""),
            reason="too_many_attempts",
        )
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            _template_context(
                error="Too many sign-in attempts. Wait a few minutes and try again.",
                email=email,
                next=_safe_next(next),
            ),
            status_code=429,
        )
    user = user_store.get_by_email(email)
    if user is None or not verify_password(password, user.password_hash):
        log_auth_event(
            "login_failed",
            email=email,
            ip_address=_client_ip(request),
            user_agent=request.headers.get("user-agent", ""),
            reason="invalid_credentials",
        )
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            _template_context(
                error="Invalid email or password.",
                email=email,
                next=_safe_next(next),
            ),
            status_code=400,
        )
    login_throttle.reset(key)
    log_auth_event(
        "login_succeeded",
        email=email,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent", ""),
        success=True,
    )
    response = RedirectResponse(url=_safe_next(next), status_code=303)
    response.set_cookie(
        settings.session_cookie_name,
        create_session_token(user.user_id),
        max_age=settings.session_max_age_seconds,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
    )
    return response


@router.post("/logout")
def logout(request: Request, csrf_token: str = Form("")):
    require_csrf(request, csrf_token)
    response = RedirectResponse(url="/auth/login", status_code=303)
    response.delete_cookie(settings.session_cookie_name)
    return response


def current_user(request: Request) -> AppUser | None:
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        return None
    user_id = read_session_token(token)
    return user_store.get(user_id) if user_id else None


def require_user(request: Request) -> AppUser:
    user = current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Login required")
    return user


def require_admin(request: Request) -> AppUser:
    user = require_user(request)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def login_redirect(request: Request):
    return RedirectResponse(url=f"/auth/login?next={quote(request.url.path)}", status_code=303)


def _safe_next(value: str) -> str:
    if not value.startswith("/") or value.startswith("//"):
        return "/tools/competitor-brief"
    return value


def _template_context(**values):
    return {
        "support_email": settings.support_email,
        "static_asset_version": settings.static_asset_version,
        **values,
    }


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else ""


def _login_key(request: Request, email: str) -> str:
    return f"{_client_ip(request)}:{email.strip().casefold()}"
