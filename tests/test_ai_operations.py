import json
import sys
from types import SimpleNamespace

from app.adapters.openai_analysis import generate_ai_analysis
from app.schemas import AIAnalysis, BusinessFact, CitedStatement, NormalizedBusinessProfile
from pydantic import ValidationError


def _profile():
    return NormalizedBusinessProfile(
        domain="example.com",
        facts=[
            BusinessFact(
                citation_id="F001",
                kind="product",
                value="Example product",
                evidence_excerpt="Example product",
                source_url="https://example.com/product",
                category="products_modules",
            )
        ],
    )


def _large_profile():
    categories = [
        "pricing_packaging",
        "positioning",
        "products_modules",
        "solutions_use_cases",
        "proof",
        "recent_moves",
    ]
    facts = []
    for index in range(180):
        category = categories[index % len(categories)]
        facts.append(
            BusinessFact(
                citation_id=f"F-{index:012X}",
                kind="price" if category == "pricing_packaging" else "product",
                value=f"{category} fact {index} " + ("valuable detail " * 12),
                evidence_excerpt=f"Evidence for {category} fact {index}. " + ("source text " * 24),
                source_url=f"https://example.com/{category}/{index}",
                category=category,
            )
        )
    return NormalizedBusinessProfile(domain="example.com", facts=facts)


def test_ai_preflight_blocks_oversized_input_and_logs_run(tmp_path):
    log = tmp_path / "runs.jsonl"

    run = generate_ai_analysis(
        _profile(),
        api_key="not-used-because-budget-blocks-first",
        model="test-model",
        max_input_tokens=1,
        run_log_path=str(log),
        cache_dir=str(tmp_path / "cache"),
    )

    assert run.status == "budget_blocked"
    assert run.analysis is None
    saved = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert saved["model"] == "test-model"
    assert saved["prompt_version"] == "competitor-brief-v1"


def test_ai_without_key_returns_auditable_status(tmp_path):
    run = generate_ai_analysis(
        _profile(),
        api_key="",
        model="test-model",
        run_log_path=str(tmp_path / "runs.jsonl"),
    )

    assert run.status == "not_configured"
    assert run.message


def test_ai_cost_preflight_blocks_request(tmp_path):
    run = generate_ai_analysis(
        _profile(),
        api_key="not-used-because-budget-blocks-first",
        model="test-model",
        max_cost_usd=0.001,
        input_cost_per_million=1_000,
        output_cost_per_million=1_000,
        run_log_path=str(tmp_path / "runs.jsonl"),
    )

    assert run.status == "budget_blocked"
    assert run.usage.estimated_cost_usd > run.budget_limit_usd


def test_ai_cache_prevents_repeated_api_call_and_tracks_usage(tmp_path, monkeypatch):
    calls = []
    clients = []
    parsed = AIAnalysis(summary=[CitedStatement(text="A product exists.", citation_ids=["F001"])])

    class FakeCompletions:
        def parse(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(parsed=parsed))],
                usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20, total_tokens=120),
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):
            clients.append(kwargs)
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    options = {
        "api_key": "test-key",
        "model": "test-model",
        "provider": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "http_referer": "https://example.com",
        "app_title": "Competitor Brief",
        "cache_dir": str(tmp_path / "cache"),
        "run_log_path": str(tmp_path / "runs.jsonl"),
        "input_cost_per_million": 1.0,
        "output_cost_per_million": 2.0,
    }

    first = generate_ai_analysis(_profile(), **options)
    second = generate_ai_analysis(_profile(), **options)

    assert first.status == "ok"
    assert first.usage.total_tokens == 120
    assert first.usage.estimated_cost_usd > 0
    assert second.status == "cache_hit"
    assert second.cached is True
    assert len(calls) == 1
    assert clients == [
        {
            "api_key": "test-key",
            "base_url": "https://openrouter.ai/api/v1",
            "default_headers": {
                "HTTP-Referer": "https://example.com",
                "X-OpenRouter-Title": "Competitor Brief",
            },
        }
    ]
    assert calls[0]["response_format"] is AIAnalysis
    assert first.provider == "openrouter"


def test_ai_invalid_citations_return_auditable_failed_run(tmp_path, monkeypatch):
    parsed = AIAnalysis(summary=[CitedStatement(text="Unsupported claim.", citation_ids=["F999"])])

    class FakeCompletions:
        def parse(self, **kwargs):
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(parsed=parsed))],
                usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20, total_tokens=120),
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))

    run = generate_ai_analysis(
        _profile(),
        api_key="test-key",
        model="test-model",
        cache_dir=str(tmp_path / "cache"),
        run_log_path=str(tmp_path / "runs.jsonl"),
    )

    assert run.status == "failed"
    assert "citation validation failed" in run.message


def test_ai_retries_with_json_object_when_native_schema_parse_fails(tmp_path, monkeypatch):
    calls = []
    parsed = {
        "summary": [{"text": "A product exists.", "citation_ids": ["F001"]}],
        "differentiators": [],
        "commercial_observations": [],
        "risks_and_unknowns": [],
    }

    class FakeCompletions:
        def parse(self, **kwargs):
            calls.append(("parse", kwargs))
            raise ValidationError.from_exception_data("AIAnalysis", [])

        def create(self, **kwargs):
            calls.append(("create", kwargs))
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(parsed)))],
                usage=SimpleNamespace(prompt_tokens=110, completion_tokens=30, total_tokens=140),
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))

    run = generate_ai_analysis(
        _profile(),
        api_key="test-key",
        model="qwen/test",
        provider="openrouter",
        cache_dir=str(tmp_path / "cache"),
        run_log_path=str(tmp_path / "runs.jsonl"),
    )

    assert run.status == "ok"
    assert run.strategy == "json_fallback"
    assert run.attempt_count == 2
    assert run.analysis.summary[0].citation_ids == ["F001"]
    assert [name for name, _ in calls] == ["parse", "create"]


def test_ai_retries_json_fallback_when_provider_rejects_structured_output(tmp_path, monkeypatch):
    calls = []
    parsed = {
        "summary": [{"text": "A product exists.", "citation_ids": ["F001"]}],
        "differentiators": [],
        "commercial_observations": [],
        "risks_and_unknowns": [],
    }

    class LengthFinishReasonError(Exception):
        pass

    class FakeCompletions:
        def parse(self, **kwargs):
            calls.append(("parse", kwargs))
            raise LengthFinishReasonError("completion reached its token limit")

        def create(self, **kwargs):
            calls.append(("create", kwargs))
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(parsed)))],
                usage=SimpleNamespace(prompt_tokens=110, completion_tokens=30, total_tokens=140),
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))

    run = generate_ai_analysis(
        _profile(),
        api_key="test-key",
        model="provider-without-json-schema",
        provider="openrouter",
        cache_dir=str(tmp_path / "cache"),
        run_log_path=str(tmp_path / "runs.jsonl"),
    )

    assert run.status == "ok"
    assert run.strategy == "json_fallback"
    assert [name for name, _ in calls] == ["parse", "create"]


def test_ai_compacts_large_evidence_set_before_budget_preflight(tmp_path, monkeypatch):
    calls = []
    parsed = AIAnalysis(
        summary=[
            CitedStatement(
                text="The company publishes pricing evidence.",
                citation_ids=["F-000000000000"],
            )
        ]
    )

    class FakeCompletions:
        def parse(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(parsed=parsed))],
                usage=SimpleNamespace(prompt_tokens=900, completion_tokens=30, total_tokens=930),
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))

    run = generate_ai_analysis(
        _large_profile(),
        api_key="test-key",
        model="test-model",
        max_input_tokens=1_200,
        cache_dir=str(tmp_path / "cache"),
        run_log_path=str(tmp_path / "runs.jsonl"),
    )

    prompt = calls[0]["messages"][1]["content"]
    assert run.status == "ok"
    assert len(prompt) <= 1_200 * 4
    assert '"category": "pricing_packaging"' in prompt
    assert '"category": "recent_moves"' in prompt
    assert len(calls) == 1


def test_ai_invalid_fallback_schema_has_explicit_failure_code(tmp_path, monkeypatch):
    class FakeCompletions:
        def parse(self, **kwargs):
            raise ValidationError.from_exception_data("AIAnalysis", [])

        def create(self, **kwargs):
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="[]"))],
                usage=None,
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))

    run = generate_ai_analysis(
        _profile(),
        api_key="test-key",
        model="qwen/test",
        cache_dir=str(tmp_path / "cache"),
        run_log_path=str(tmp_path / "runs.jsonl"),
    )

    assert run.status == "failed"
    assert run.failure_code == "response_schema_invalid"
    assert run.attempt_count == 2
    assert "JSON object" in run.message
