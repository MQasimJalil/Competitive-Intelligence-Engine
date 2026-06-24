import secrets
from hmac import compare_digest

from fastapi import HTTPException, Request
from starlette.responses import Response

from app.config import settings


def csrf_token_for_request(request: Request) -> str:
    token = request.cookies.get(settings.csrf_cookie_name)
    if not token:
        token = secrets.token_urlsafe(32)
    request.state.csrf_token = token
    return token


def attach_csrf_cookie(request: Request, response: Response) -> None:
    token = getattr(request.state, "csrf_token", "")
    if not token:
        return
    response.set_cookie(
        settings.csrf_cookie_name,
        token,
        max_age=settings.session_max_age_seconds,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
    )


def require_csrf(request: Request, submitted_token: str) -> None:
    if not settings.csrf_protection_enabled:
        return
    cookie_token = request.cookies.get(settings.csrf_cookie_name, "")
    if not cookie_token or not submitted_token:
        raise HTTPException(
            status_code=403,
            detail="Security token missing. Refresh and try again.",
        )
    if not compare_digest(cookie_token, submitted_token):
        raise HTTPException(
            status_code=403,
            detail="Security token invalid. Refresh and try again.",
        )
