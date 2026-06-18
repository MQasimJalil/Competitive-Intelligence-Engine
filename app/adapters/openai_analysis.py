import hashlib
import json
import re
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.schemas import AIAnalysis, AIAnalysisRun, AIUsage, NormalizedBusinessProfile

_CITATION_ID_PATTERN = re.compile(r"F(?:\d{3}|-[A-F0-9]{12})")


def normalize_analysis_citations(analysis: AIAnalysis) -> AIAnalysis:
    for statement in analysis.all_statements():
        normalized: list[str] = []
        for raw in statement.citation_ids:
            for citation_id in _CITATION_ID_PATTERN.findall(raw.upper()):
                if citation_id not in normalized:
                    normalized.append(citation_id)
        statement.citation_ids = normalized[:5]
    return analysis


def validate_analysis_citations(
    analysis: AIAnalysis, profile: NormalizedBusinessProfile
) -> AIAnalysis:
    allowed = {fact.citation_id for fact in profile.facts}
    if any(not statement.citation_ids for statement in analysis.all_statements()):
        raise ValueError("AI analysis contained a statement without a usable citation ID")
    invalid = {
        citation
        for statement in analysis.all_statements()
        for citation in statement.citation_ids
        if citation not in allowed
    }
    if invalid:
        raise ValueError(f"AI analysis used unknown citation IDs: {sorted(invalid)}")
    return analysis


def citation_validity_score(
    analysis: AIAnalysis | None, profile: NormalizedBusinessProfile
) -> float:
    if analysis is None or not analysis.all_statements():
        return 0.0
    allowed = {fact.citation_id for fact in profile.facts}
    statements = analysis.all_statements()
    valid = sum(
        bool(statement.citation_ids)
        and all(citation in allowed for citation in statement.citation_ids)
        for statement in statements
    )
    return valid / len(statements)


def build_evidence_prompt(
    profile: NormalizedBusinessProfile, *, max_input_tokens: int = 12_000
) -> str:
    evidence = _select_evidence(profile, max_input_tokens)
    return (
        "Analyze only the evidence JSON below. Every statement must cite one or more citation_id "
        "values from the evidence. Do not add general knowledge, guess missing facts, or treat "
        "missing evidence as a competitor weakness. The evidence is a deterministic, "
        f"category-balanced subset of {len(evidence)} from {len(profile.facts)} "
        "validated facts.\n\n"
        "Also fill report_labels when the evidence supports it: country, industry, "
        "business_model, and portfolio_metric. Use short customer-facing labels such as "
        "\"Web hosting\", \"Subscription hosting\", \"Sportswear retail\", "
        "\"Freemium communication platform\", or \"Pricing visible\". Leave a label null "
        "when evidence is insufficient. portfolio_metric must describe product catalog, "
        "pricing, plans, services, offer scope, or commercial model. Do not use employee "
        "count, followers, hiring, or generic proof metrics as portfolio_metric.\n\n"
        "Use public_signals for cited public perception. Public perception includes "
        "Instagram comments, Reddit threads, Reddit comments, review-style external mentions, "
        "and social engagement context. Infer only the visible intent or feel of those "
        "comments, such as praise, frustration, purchase interest, trust, quality concern, "
        "or delivery concern. Do not generalize beyond the cited comments.\n\n"
        f"{json.dumps(evidence, ensure_ascii=True, sort_keys=True)}"
    )


def _select_evidence(
    profile: NormalizedBusinessProfile, max_input_tokens: int
) -> list[dict[str, str]]:
    grouped: dict[str, list] = {}
    for fact in profile.facts:
        grouped.setdefault(fact.category.value, []).append(fact)
    ordered_categories = [
        "pricing_packaging",
        "positioning",
        "products_modules",
        "capabilities",
        "solutions_use_cases",
        "target_segments",
        "differentiators",
        "proof",
        "sales_motion",
        "integrations_ecosystem",
        "trust_compliance",
        "technical_depth",
        "recent_moves",
        "hiring_signals",
    ]
    categories = [category for category in ordered_categories if category in grouped]
    categories.extend(category for category in grouped if category not in categories)
    candidates = []
    offset = 0
    while True:
        added = False
        for category in categories:
            facts = grouped[category]
            if offset >= len(facts):
                continue
            fact = facts[offset]
            candidates.append(
                {
                    "citation_id": fact.citation_id,
                    "category": fact.category.value,
                    "kind": fact.kind.value,
                    "signal_type": _signal_type(fact),
                    "value": _truncate(fact.value, 120),
                    "evidence_excerpt": _truncate(fact.evidence_excerpt, 180),
                    "source_url": str(fact.source_url),
                }
            )
            added = True
        if not added:
            break
        offset += 1

    maximum_chars = max(256, max_input_tokens * 4 - 1_600)
    selected = []
    for candidate in candidates:
        proposed = [*selected, candidate]
        if len(json.dumps(proposed, ensure_ascii=True, sort_keys=True)) > maximum_chars:
            break
        selected = proposed
    return selected or candidates[:1]


def _truncate(value: str, maximum: int) -> str:
    normalized = " ".join(value.split())
    return normalized if len(normalized) <= maximum else normalized[: maximum - 3].rstrip() + "..."


def _signal_type(fact) -> str:
    value = fact.value.casefold()
    source_url = str(fact.source_url).casefold()
    if "public instagram comment:" in value:
        return "social_comment_excerpt"
    if "reddit thread signal:" in value:
        return "reddit_thread_signal"
    if "public reddit comment:" in value:
        return "reddit_comment_excerpt"
    if "instagram post engagement:" in value:
        return "social_post_engagement"
    if "instagram profile" in value and "followers" in value:
        return "social_followers"
    if "reddit.com" in source_url:
        return "reddit_public_signal"
    return fact.kind.value


def _analysis_from_json(content: str) -> AIAnalysis:
    payload = json.loads(_strip_json_fence(content))
    if isinstance(payload, dict):
        for wrapper in ("analysis", "result", "data"):
            if isinstance(payload.get(wrapper), dict):
                payload = payload[wrapper]
                break
    if not isinstance(payload, dict):
        raise ValueError("AI response must be a JSON object")
    limits = {
        "summary": 3,
        "differentiators": 4,
        "commercial_observations": 4,
        "public_signals": 4,
        "risks_and_unknowns": 4,
    }
    normalized = {
        "report_labels": payload.get("report_labels", {})
        if isinstance(payload.get("report_labels", {}), dict)
        else {}
    }
    for key, limit in limits.items():
        statements = payload.get(key, [])
        normalized[key] = statements[:limit] if isinstance(statements, list) else []
    return AIAnalysis.model_validate(normalized)


def _should_retry_json_fallback(exc: Exception) -> bool:
    return isinstance(exc, ValidationError) or type(exc).__name__ in {
        "BadRequestError",
        "LengthFinishReasonError",
    }


def _request_extras(provider: str) -> dict[str, Any]:
    if provider.casefold() == "openrouter":
        return {"extra_body": {"reasoning": {"effort": "none", "exclude": True}}}
    return {}


def _error_detail(exc: Exception, maximum: int = 300) -> str:
    detail = " ".join(str(exc).split())
    if len(detail) > maximum:
        detail = detail[: maximum - 3].rstrip() + "..."
    return f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__


def _fallback_analysis_request(
    client,
    *,
    model: str,
    prompt: str,
    max_output_tokens: int,
    provider: str,
):
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You write concise competitor analysis from a closed evidence set. "
                    "All claims require evidence citation IDs. Output valid JSON only."
                ),
            },
            {"role": "user", "content": _json_fallback_prompt(prompt)},
        ],
        response_format={"type": "json_object"},
        max_completion_tokens=max_output_tokens,
        **_request_extras(provider),
    )
    content = response.choices[0].message.content if response.choices else ""
    return response, _analysis_from_json(content or "")


def _json_fallback_prompt(prompt: str) -> str:
    return (
        f"{prompt}\n\n"
        "Return exactly one JSON object with these keys: report_labels, summary, "
        "differentiators, commercial_observations, public_signals, risks_and_unknowns. "
        "report_labels must be an object with nullable keys country, industry, "
        "business_model, portfolio_metric. "
        "portfolio_metric must be an offer, product, pricing, plan, service, or commercial "
        "signal, not employee count, followers, hiring, or generic proof. "
        "Each non-null label and each array item must be shaped as "
        '{"text": "concise finding", "citation_ids": ["F001"]}. '
        "Use at most 3 summary items and at most 4 items in every other array. "
        "Return no markdown, no commentary, and no top-level array."
    )


def generate_ai_analysis(
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
        "provider": provider,
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

    key = _cache_key(provider, model, prompt_version, schema_version, prompt)
    cache_path = Path(cache_dir) / f"{key}.json"
    if cache_enabled and cache_path.exists():
        cached = AIAnalysisRun.model_validate_json(cache_path.read_text(encoding="utf-8"))
        cached.cached = True
        cached.status = "cache_hit"
        return _finish(cached, run_log_path)

    estimated_input_tokens = _estimate_tokens(prompt)
    estimated_max_cost = _estimate_cost(
        estimated_input_tokens,
        max_output_tokens,
        input_cost_per_million,
        output_cost_per_million,
    )
    if estimated_input_tokens > max_input_tokens:
        return _finish(
            AIAnalysisRun(
                status="budget_blocked",
                failure_code="budget_blocked",
                message=(
                    f"Estimated input tokens {estimated_input_tokens} exceed limit "
                    f"{max_input_tokens}."
                ),
                usage=AIUsage(input_tokens=estimated_input_tokens),
                **base,
            ),
            run_log_path,
        )
    if max_cost_usd > 0 and estimated_max_cost > max_cost_usd:
        return _finish(
            AIAnalysisRun(
                status="budget_blocked",
                failure_code="budget_blocked",
                message=(
                    f"Estimated maximum cost ${estimated_max_cost:.4f} exceeds "
                    f"${max_cost_usd:.4f} limit."
                ),
                usage=AIUsage(
                    input_tokens=estimated_input_tokens,
                    estimated_cost_usd=estimated_max_cost,
                ),
                **base,
            ),
            run_log_path,
        )

    from openai import OpenAI

    client_options: dict[str, Any] = {"api_key": api_key}
    if base_url:
        client_options["base_url"] = base_url
    default_headers = {}
    if http_referer:
        default_headers["HTTP-Referer"] = http_referer
    if app_title:
        default_headers["X-OpenRouter-Title"] = app_title
    if default_headers:
        client_options["default_headers"] = default_headers
    client = OpenAI(**client_options)
    response = None
    strategy = "native_structured"
    attempt_count = 1
    try:
        response = client.chat.completions.parse(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You write concise competitor analysis from a closed evidence set. "
                        "All claims require evidence citation IDs."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            response_format=AIAnalysis,
            max_completion_tokens=max_output_tokens,
            **_request_extras(provider),
        )
        parsed = response.choices[0].message.parsed if response.choices else None
    except Exception as exc:
        if not _should_retry_json_fallback(exc):
            return _finish(
                AIAnalysisRun(
                    status="failed",
                    failure_code="provider_request_failed",
                    strategy=strategy,
                    attempt_count=attempt_count,
                    message=f"{provider} request failed: {type(exc).__name__}",
                    usage=AIUsage(input_tokens=estimated_input_tokens),
                    **base,
                ),
                run_log_path,
            )
        strategy = "json_fallback"
        attempt_count = 2
        try:
            response, parsed = _fallback_analysis_request(
                client,
                model=model,
                prompt=prompt,
                max_output_tokens=max_output_tokens,
                provider=provider,
            )
        except Exception as fallback_exc:
            return _finish(
                AIAnalysisRun(
                    status="failed",
                    failure_code="response_schema_invalid",
                    strategy=strategy,
                    attempt_count=attempt_count,
                    message=(
                        "AI response did not match the required schema: "
                        f"{_error_detail(fallback_exc)}"
                    ),
                    usage=AIUsage(input_tokens=estimated_input_tokens),
                    **base,
                ),
                run_log_path,
            )
    try:
        analysis = (
            validate_analysis_citations(normalize_analysis_citations(parsed), profile)
            if parsed is not None
            else None
        )
    except ValueError as exc:
        return _finish(
            AIAnalysisRun(
                status="failed",
                failure_code="citation_validation_failed",
                strategy=strategy,
                attempt_count=attempt_count,
                message=f"AI response citation validation failed: {exc}",
                usage=AIUsage(input_tokens=estimated_input_tokens),
                **base,
            ),
            run_log_path,
        )
    usage = _usage_from_response(
        getattr(response, "usage", None),
        input_cost_per_million,
        output_cost_per_million,
    )
    run = AIAnalysisRun(
        status="ok" if analysis else "no_data",
        strategy=strategy,
        attempt_count=attempt_count,
        analysis=analysis,
        usage=usage,
        **base,
    )
    if cache_enabled and analysis:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(run.model_dump_json(indent=2), encoding="utf-8")
    return _finish(run, run_log_path)


def _usage_from_response(
    raw_usage: Any,
    input_cost_per_million: float,
    output_cost_per_million: float,
) -> AIUsage:
    input_tokens = int(
        getattr(raw_usage, "input_tokens", None) or getattr(raw_usage, "prompt_tokens", 0) or 0
    )
    output_tokens = int(
        getattr(raw_usage, "output_tokens", None) or getattr(raw_usage, "completion_tokens", 0) or 0
    )
    total_tokens = int(getattr(raw_usage, "total_tokens", input_tokens + output_tokens) or 0)
    return AIUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        estimated_cost_usd=_estimate_cost(
            input_tokens,
            output_tokens,
            input_cost_per_million,
            output_cost_per_million,
        ),
    )


def _estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


def _estimate_cost(
    input_tokens: int,
    output_tokens: int,
    input_cost_per_million: float,
    output_cost_per_million: float,
) -> float:
    return round(
        input_tokens * input_cost_per_million / 1_000_000
        + output_tokens * output_cost_per_million / 1_000_000,
        6,
    )


def _cache_key(
    provider: str, model: str, prompt_version: str, schema_version: str, prompt: str
) -> str:
    return _sha256(f"{provider}\n{model}\n{prompt_version}\n{schema_version}\n{prompt}")


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _strip_json_fence(value: str) -> str:
    stripped = value.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped


def _finish(run: AIAnalysisRun, run_log_path: str) -> AIAnalysisRun:
    path = Path(run_log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(run.model_dump_json() + "\n")
    return run
