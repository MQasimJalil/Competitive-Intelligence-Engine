from app.benchmarking.golden_scorer import score_golden_case


def test_golden_scorer_measures_fact_recall_and_citations(tmp_path):
    (tmp_path / "generated-baseline.md").write_text(
        "Product costs $20. [source 1]\n\n## Sources\n- [1] Pricing: https://example.com",
        encoding="utf-8",
    )
    requirements = {
        "required": [{"fact": "The product costs $20."}],
        "important": [{"fact": "The product serves enterprises."}],
        "must_not_claim": ["The product is the market leader."],
    }

    score = score_golden_case(tmp_path, requirements)

    assert score.required_fact_recall == 1.0
    assert score.important_fact_recall == 0.0
    assert score.forbidden_claim_avoidance == 1.0
    assert score.citation_reference_validity == 1.0
