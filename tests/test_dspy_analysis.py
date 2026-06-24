import json

from app.adapters.dspy_analysis import _analysis_from_dspy_payload, generate_dspy_analysis
from app.schemas import NormalizedBusinessProfile


def test_dspy_adapter_accepts_shared_analysis_options_without_key(tmp_path):
    run = generate_dspy_analysis(
        NormalizedBusinessProfile(domain="example.com"),
        api_key="",
        model="openai/gpt-5.4",
        provider="openrouter",
        base_url="https://openrouter.ai/api/v1",
        http_referer="http://127.0.0.1:49160",
        app_title="Competitive Intelligence Engine",
        cache_dir=str(tmp_path / "cache"),
        run_log_path=str(tmp_path / "logs" / "ai_runs.jsonl"),
    )

    assert run.status == "not_configured"
    assert run.failure_code == "not_configured"


def test_dspy_payload_coerces_common_citation_shapes():
    analysis = _analysis_from_dspy_payload(
        json.dumps(
            {
                "report_labels": {
                    "industry": "Goalkeeper gloves [F001]",
                    "business_model": {
                        "text": "DTC ecommerce",
                        "citations": ["F001"],
                    },
                },
                "summary": ["Solo GK sells gloves online [F001]"],
                "differentiators": [
                    {
                        "statement": "Pricing is visible on product pages",
                        "citation_id": "F001",
                    }
                ],
                "commercial_observations": [],
                "public_signals": [],
                "risks_and_unknowns": [],
            }
        )
    )

    assert analysis.report_labels.industry.text == "Goalkeeper gloves"
    assert analysis.report_labels.industry.citation_ids == ["F001"]
    assert analysis.summary[0].citation_ids == ["F001"]
    assert analysis.differentiators[0].text == "Pricing is visible on product pages"


def test_dspy_payload_drops_uncited_labels_and_statements():
    analysis = _analysis_from_dspy_payload(
        json.dumps(
            {
                "report_labels": {
                    "country": "United Kingdom",
                    "industry": "Goalkeeper gloves [F001]",
                },
                "summary": [
                    {"text": "This claim has no citation", "citation_ids": []},
                    {"text": "This claim is cited", "citation_ids": ["F001"]},
                ],
            }
        )
    )

    assert analysis.report_labels.country is None
    assert analysis.report_labels.industry.citation_ids == ["F001"]
    assert len(analysis.summary) == 1
    assert analysis.summary[0].text == "This claim is cited"
