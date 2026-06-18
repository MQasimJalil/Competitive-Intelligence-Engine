from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.tools.competitor_brief.router import router as competitor_brief_router
from app.web.auth import router as auth_router

app = FastAPI(title=settings.app_name)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

app.include_router(auth_router)
app.include_router(competitor_brief_router)


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
        {"title": "Not found", "content": "Page not found."},
        status_code=404,
    )
