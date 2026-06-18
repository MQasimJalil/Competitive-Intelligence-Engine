import pytest
from app.adapters.openai_analysis import (
    build_evidence_prompt,
    normalize_analysis_citations,
    validate_analysis_citations,
)
from app.schemas import (
    AIAnalysis,
    BusinessCategory,
    BusinessFact,
    BusinessFactKind,
    CitedStatement,
    NormalizedBusinessProfile,
)


def _profile():
    return NormalizedBusinessProfile(
        domain="example.com",
        facts=[
            BusinessFact(
                citation_id="F001",
                kind="product",
                value="Lunar Pro",
                evidence_excerpt="Lunar Pro",
                source_url="https://example.com/lunar",
                category="products_modules",
            )
        ],
    )


def test_ai_analysis_rejects_unknown_citation():
    analysis = AIAnalysis(summary=[CitedStatement(text="A product exists.", citation_ids=["F999"])])

    with pytest.raises(ValueError, match="unknown citation"):
        validate_analysis_citations(analysis, _profile())


def test_evidence_prompt_contains_closed_evidence_ids():
    prompt = build_evidence_prompt(_profile())

    assert "F001" in prompt
    assert "Do not add general knowledge" in prompt


def test_ai_analysis_normalizes_concatenated_citation_ids():
    profile = NormalizedBusinessProfile(
        domain="example.com",
        facts=[
            BusinessFact(
                citation_id="F001",
                kind="product",
                value="Lunar Pro",
                evidence_excerpt="Lunar Pro",
                source_url="https://example.com/lunar",
                category="products_modules",
            ),
            BusinessFact(
                citation_id="F002",
                kind="price",
                value="$40",
                evidence_excerpt="$40",
                source_url="https://example.com/lunar",
                category="products_modules",
            ),
        ],
    )
    analysis = AIAnalysis(
        summary=[
            CitedStatement(
                text="A cited product exists.",
                citation_ids=["F001','F002"],
            )
        ]
    )

    normalized = normalize_analysis_citations(analysis)

    assert normalized.summary[0].citation_ids == ["F001", "F002"]
    assert validate_analysis_citations(normalized, profile) is normalized


def test_ai_analysis_accepts_over_cited_statement_and_trims_for_display():
    citations = [f"F{index:03d}" for index in range(1, 9)]
    profile = NormalizedBusinessProfile(
        domain="example.com",
        facts=[
            BusinessFact(
                citation_id=citation_id,
                kind="company_detail",
                value=f"Evidence {citation_id}",
                evidence_excerpt=f"Evidence {citation_id}",
                source_url=f"https://example.com/{citation_id}",
                category="positioning",
            )
            for citation_id in citations
        ],
    )
    analysis = AIAnalysis(
        summary=[
            CitedStatement(
                text="A statement with more citations than the customer report should show.",
                citation_ids=citations,
            )
        ]
    )

    normalized = normalize_analysis_citations(analysis)

    assert normalized.summary[0].citation_ids == citations[:5]
    assert validate_analysis_citations(normalized, profile) is normalized


def test_evidence_prompt_prioritizes_public_perception_evidence():
    profile = NormalizedBusinessProfile(
        domain="example.com",
        facts=[
            BusinessFact(
                citation_id="F001",
                kind=BusinessFactKind.PROOF,
                category=BusinessCategory.PROOF,
                value="Public Instagram comment: Best grip I have used this season",
                evidence_excerpt="Best grip I have used this season",
                source_url="https://www.instagram.com/p/abc/",
            ),
            BusinessFact(
                citation_id="F002",
                kind=BusinessFactKind.PROOF,
                category=BusinessCategory.PROOF,
                value="Reddit thread signal: latex grip is strong but delivery took a while.",
                evidence_excerpt="latex grip is strong but delivery took a while",
                source_url="https://www.reddit.com/r/goalkeepers/comments/abc/",
            ),
        ],
    )

    prompt = build_evidence_prompt(profile)

    assert "public_signals" in prompt
    assert "Public perception" in prompt
    assert "social_comment_excerpt" in prompt
    assert "reddit_thread_signal" in prompt
