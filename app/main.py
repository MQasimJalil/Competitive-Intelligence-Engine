from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.gzip import GZipMiddleware

from app.config import settings
from app.tools.competitor_brief.router import router as competitor_brief_router
from app.web.auth import router as auth_router
from app.web.csrf import attach_csrf_cookie, csrf_token_for_request

app = FastAPI(title=settings.app_name)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
templates.env.globals["static_asset_version"] = settings.static_asset_version

app.include_router(auth_router)
app.include_router(competitor_brief_router)


@app.middleware("http")
async def add_security_and_static_headers(request: Request, call_next):
    csrf_token_for_request(request)
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers.setdefault("Cache-Control", "public, max-age=86400")
    elif "text/html" in response.headers.get("content-type", ""):
        attach_csrf_cookie(request, response)
    return response


@app.get("/", include_in_schema=False)
def home() -> RedirectResponse:
    return RedirectResponse(url="/tools/competitor-brief")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name}


@app.exception_handler(404)
def not_found(request: Request, exc: Exception):
    return templates.TemplateResponse(
        request,
        "base.html",
        {
            "title": "Not found",
            "content": "Page not found.",
            "static_asset_version": settings.static_asset_version,
        },
        status_code=404,
    )
