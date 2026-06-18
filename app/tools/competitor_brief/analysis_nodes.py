import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from app.adapters.openai_analysis import generate_ai_analysis
from app.config import Settings
from app.schemas import AIAnalysisRun, NormalizedBusinessProfile


@dataclass(frozen=True)
class StrategicAnalysisNode:
    name: str
    version: str
    runner: Callable[[NormalizedBusinessProfile], AIAnalysisRun]

    async def run(self, profile: NormalizedBusinessProfile) -> AIAnalysisRun:
        return await asyncio.to_thread(self.runner, profile)


def build_strategic_analysis_node(settings: Settings) -> StrategicAnalysisNode | None:
    if not settings.ai_analysis_enabled or not settings.openai_api_key:
        return None

    def run(profile: NormalizedBusinessProfile) -> AIAnalysisRun:
        return generate_ai_analysis(
            profile,
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            provider=settings.ai_provider,
            base_url=settings.ai_base_url,
            http_referer=settings.ai_http_referer,
            app_title=settings.ai_app_title,
            prompt_version=settings.ai_prompt_version,
            schema_version=settings.ai_schema_version,
            cache_enabled=settings.ai_cache_enabled,
            cache_dir=settings.ai_cache_dir,
            run_log_path=settings.ai_run_log_path,
            max_input_tokens=settings.ai_max_input_tokens,
            max_output_tokens=settings.ai_max_output_tokens,
            max_cost_usd=settings.ai_max_cost_usd,
            input_cost_per_million=settings.ai_input_cost_per_million,
            output_cost_per_million=settings.ai_output_cost_per_million,
        )

    return StrategicAnalysisNode(
        name="strategic_ai_analysis",
        version=settings.ai_prompt_version,
        runner=run,
    )
