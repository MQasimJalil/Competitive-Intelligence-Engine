import json
import re
from typing import Any

from app.adapters.openai_analysis import (
    _analysis_from_json,
    _cache_key,
    _error_detail,
    _estimate_cost,
    _estimate_tokens,
    _finish,
    _sha256,
    _strip_json_fence,
    build_evidence_prompt,
    normalize_analysis_citations,
    validate_analysis_citations,
)
from app.schemas import AIAnalysis, AIAnalysisRun, AIUsage, NormalizedBusinessProfile

_CITATION_ID_PATTERN = re.compile(r"F(?:\d{3}|-[A-F0-9]{12})", re.IGNORECASE)


def generate_dspy_analysis(
    profile: NormalizedBusinessProfile,
    *,
    api_key: str,
    model: str,
    provider: str = "openai",
    base_url: str = "",
    http_referer: str = "",
    app_title: str = "",
    prompt_version: str = "competitor-brief-v1",
    schema_version: str = "analysis-v1",
    cache_enabled: bool = True,
    cache_dir: str = "var/ai_cache",
    run_log_path: str = "var/logs/ai_runs.jsonl",
    max_input_tokens: int = 12_000,
    max_output_tokens: int = 2_000,
    max_cost_usd: float = 0.10,
    input_cost_per_million: float = 0.0,
    output_cost_per_million: float = 0.0,
) -> AIAnalysisRun:
    prompt = build_evidence_prompt(profile, max_input_tokens=max_input_tokens)
    evidence_hash = _sha256(prompt)
    base = {
        "provider": f"{provider}:dspy",
        "model": model,
        "prompt_version": prompt_version,
        "schema_version": schema_version,
        "evidence_hash": evidence_hash,
        "budget_limit_usd": max_cost_usd,
    }
    if not api_key or not profile.facts:
        return _finish(
            AIAnalysisRun(
                status="not_configured",
                failure_code="not_configured",
                message="API key or evidence unavailable.",
                **base,
            ),
            run_log_path,
        )

    estimated_input_tokens = _estimate_tokens(prompt)
    estimated_max_cost = _estimate_cost(
        estimated_input_tokens,
        max_output_tokens,
        input_cost_per_million,
        output_cost_per_million,
    )
    if estimated_input_tokens > max_input_tokens or (
        max_cost_usd > 0 and estimated_max_cost > max_cost_usd
    ):
        return _finish(
            AIAnalysisRun(
                status="budget_blocked",
                failure_code="budget_blocked",
                message="Estimated DSPy analysis cost or input size exceeds configured limits.",
                usage=AIUsage(
                    input_tokens=estimated_input_tokens,
                    estimated_cost_usd=estimated_max_cost,
                ),
                **base,
            ),
            run_log_path,
        )

    from pathlib import Path

    key = _cache_key("dspy", model, prompt_version, schema_version, prompt)
    cache_path = Path(cache_dir) / f"{key}.json"
    if cache_enabled and cache_path.exists():
        cached = AIAnalysisRun.model_validate_json(cache_path.read_text(encoding="utf-8"))
        cached.cached = True
        cached.status = "cache_hit"
        return _finish(cached, run_log_path)

    try:
        analysis_payload = _run_dspy(
            prompt,
            api_key=api_key,
            model=model,
            provider=provider,
            base_url=base_url,
            max_output_tokens=max_output_tokens,
        )
        analysis = validate_analysis_citations(
            normalize_analysis_citations(_analysis_from_dspy_payload(analysis_payload)),
            profile,
        )
    except ImportError as exc:
        return _finish(
            AIAnalysisRun(
                status="not_configured",
                failure_code="dspy_not_installed",
                strategy="dspy_predict",
                message=f"DSPy is not installed: {exc}",
                usage=AIUsage(input_tokens=estimated_input_tokens),
                **base,
            ),
            run_log_path,
        )
    except Exception as exc:
        return _finish(
            AIAnalysisRun(
                status="failed",
                failure_code="dspy_analysis_failed",
                strategy="dspy_predict",
                message=f"DSPy analysis failed: {_error_detail(exc)}",
                usage=AIUsage(input_tokens=estimated_input_tokens),
                **base,
            ),
            run_log_path,
        )

    run = AIAnalysisRun(
        status="ok",
        strategy="dspy_predict",
        attempt_count=1,
        analysis=analysis,
        usage=AIUsage(
            input_tokens=estimated_input_tokens,
            estimated_cost_usd=_estimate_cost(
                estimated_input_tokens,
                0,
                input_cost_per_million,
                output_cost_per_million,
            ),
        ),
        **base,
    )
    if cache_enabled:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(run.model_dump_json(indent=2), encoding="utf-8")
    return _finish(run, run_log_path)


def _run_dspy(
    prompt: str,
    *,
    api_key: str,
    model: str,
    provider: str,
    base_url: str,
    max_output_tokens: int,
) -> str:
    import dspy

    class CompetitorAnalysisSignature(dspy.Signature):
        """Convert validated competitor evidence into cited JSON analysis."""

        evidence_prompt: str = dspy.InputField()
        analysis_json: str = dspy.OutputField(
            desc=(
                "JSON object with report_labels, summary, differentiators, "
                "commercial_observations, public_signals, risks_and_unknowns. "
                "Every statement must include citation_ids from the evidence."
            )
        )

    lm_options: dict[str, Any] = {
        "api_key": api_key,
        "max_tokens": max_output_tokens,
    }
    if base_url:
        lm_options["api_base"] = base_url
    lm = dspy.LM(_dspy_model_name(provider, model), **lm_options)
    module = dspy.Predict(CompetitorAnalysisSignature)
    with dspy.context(lm=lm):
        prediction = module(evidence_prompt=prompt)
    return prediction.analysis_json


def _dspy_model_name(provider: str, model: str) -> str:
    normalized = provider.casefold()
    if normalized == "openrouter":
        return f"openrouter/{model}"
    if "/" in model:
        return model
    return f"{normalized}/{model}"


def _analysis_from_dspy_payload(content: str) -> AIAnalysis:
    try:
        return _analysis_from_json(content)
    except Exception:
        payload = json.loads(_strip_json_fence(content))
        if isinstance(payload, dict):
            for wrapper in ("analysis", "result", "data"):
                if isinstance(payload.get(wrapper), dict):
                    payload = payload[wrapper]
                    break
        if not isinstance(payload, dict):
            raise
        return AIAnalysis.model_validate(_coerce_analysis_payload(payload))


def _coerce_analysis_payload(payload: dict[str, Any]) -> dict[str, Any]:
    limits = {
        "summary": 3,
        "differentiators": 4,
        "commercial_observations": 4,
        "public_signals": 4,
        "risks_and_unknowns": 4,
    }
    coerced: dict[str, Any] = {"report_labels": _coerce_report_labels(payload.get("report_labels"))}
    for key, limit in limits.items():
        raw_items = payload.get(key, [])
        if not isinstance(raw_items, list):
            raw_items = [raw_items] if raw_items else []
        coerced[key] = [
            statement
            for statement in (_coerce_statement(item) for item in raw_items[:limit])
            if statement["citation_ids"]
        ]
    return coerced


def _coerce_report_labels(value: Any) -> dict[str, Any]:
    labels = {}
    if not isinstance(value, dict):
        return labels
    for key in ("country", "industry", "business_model", "portfolio_metric"):
        raw = value.get(key)
        if raw:
            statement = _coerce_statement(raw)
            if statement["citation_ids"]:
                labels[key] = statement
    return labels


def _coerce_statement(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        return {"text": _remove_inline_citations(value), "citation_ids": _citations_from(value)}
    if not isinstance(value, dict):
        return {"text": str(value), "citation_ids": []}
    text = str(
        value.get("text")
        or value.get("statement")
        or value.get("finding")
        or value.get("value")
        or ""
    )
    citation_ids = (
        value.get("citation_ids")
        or value.get("citations")
        or value.get("citation_id")
        or value.get("source_ids")
        or value.get("sources")
        or []
    )
    return {
        "text": _remove_inline_citations(text),
        "citation_ids": _citations_from(citation_ids) or _citations_from(text),
    }


def _citations_from(value: Any) -> list[str]:
    values = value if isinstance(value, list) else [value]
    normalized = []
    for item in values:
        for citation_id in _CITATION_ID_PATTERN.findall(str(item).upper()):
            if citation_id not in normalized:
                normalized.append(citation_id)
    return normalized


def _remove_inline_citations(value: str) -> str:
    cleaned = _CITATION_ID_PATTERN.sub("", value)
    return re.sub(r"\s+", " ", cleaned.replace("[]", "")).strip()
