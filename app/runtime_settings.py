import json
from pathlib import Path

from pydantic import BaseModel, Field

from app.config import settings


class RuntimeSettings(BaseModel):
    ai_analysis_engine: str = Field(default="openai")


def load_runtime_settings() -> RuntimeSettings:
    path = _path()
    if not path.exists():
        return RuntimeSettings(ai_analysis_engine=settings.ai_analysis_engine)
    try:
        return RuntimeSettings.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError:
        return RuntimeSettings(ai_analysis_engine=settings.ai_analysis_engine)


def save_runtime_settings(runtime_settings: RuntimeSettings) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(runtime_settings.model_dump(), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def ai_analysis_engine() -> str:
    engine = load_runtime_settings().ai_analysis_engine.casefold()
    return engine if engine in {"openai", "dspy"} else "openai"


def set_ai_analysis_engine(engine: str) -> RuntimeSettings:
    normalized = engine.casefold()
    if normalized not in {"openai", "dspy"}:
        raise ValueError("AI engine must be openai or dspy")
    runtime_settings = RuntimeSettings(ai_analysis_engine=normalized)
    save_runtime_settings(runtime_settings)
    return runtime_settings


def _path() -> Path:
    return Path(settings.runtime_settings_path)
