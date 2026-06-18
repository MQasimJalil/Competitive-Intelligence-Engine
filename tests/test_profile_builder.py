from app.schemas import ExtractionResult, ExtractionStatus
from app.tools.competitor_brief.profile_builder import build_competitor_profile


def test_profile_builder_uses_observed_claims_and_business_coverage():
    results = [
        ExtractionResult(
            value="Work smarter with modern product teams.",
            source_url="https://example.com",
            extractor_name="homepage_headline",
            confidence=0.8,
            status=ExtractionStatus.OK,
        ),
        ExtractionResult(
            value={
                "category": "pricing_packaging",
                "page_url": "https://example.com/pricing",
                "page_title": "Pricing",
                "headline": "Pricing",
                "claims": [
                    {
                        "category": "pricing_packaging",
                        "fact_type": "visible_price",
                        "value": "$20/month",
                        "evidence_excerpt": "Pro costs $20/month.",
                        "source_url": "https://example.com/pricing",
                        "context": "Pricing text",
                    }
                ],
            },
            source_url="https://example.com/pricing",
            extractor_name="pricing_packaging_facts",
            confidence=0.85,
            status=ExtractionStatus.OK,
        ),
    ]

    profile = build_competitor_profile("example.com", results)

    assert profile.answered_dimensions == 2
    assert profile.source_count == 2
    assert any(
        claim.value == "$20/month" for section in profile.sections for claim in section.claims
    )


def test_profile_builder_does_not_treat_missing_evidence_as_weakness():
    profile = build_competitor_profile("example.com", [])

    assert profile.answered_dimensions == 0
    assert len(profile.unanswered_questions) == profile.total_dimensions


def test_profile_builder_prefers_informative_claim_over_generic_heading():
    results = [
        ExtractionResult(
            value={
                "category": "trust_compliance",
                "page_url": "https://example.com/security",
                "page_title": "Security",
                "headline": "Security",
                "claims": [
                    {
                        "category": "trust_compliance",
                        "fact_type": "page_claim",
                        "value": "Privacy",
                        "evidence_excerpt": "Privacy",
                        "source_url": "https://example.com/security",
                    },
                    {
                        "category": "trust_compliance",
                        "fact_type": "page_claim",
                        "value": "Enterprise-grade security with encryption at rest",
                        "evidence_excerpt": "Enterprise-grade security with encryption at rest",
                        "source_url": "https://example.com/security",
                    },
                ],
            },
            source_url="https://example.com/security",
            extractor_name="trust_compliance_facts",
            confidence=0.85,
            status=ExtractionStatus.OK,
        )
    ]

    profile = build_competitor_profile("example.com", results)
    proof_section = next(
        section for section in profile.sections if section.title == "Proof and trust"
    )

    assert proof_section.claims[0].value == "Enterprise-grade security with encryption at rest"


def test_profile_builder_requires_dated_recent_activity():
    results = [
        ExtractionResult(
            value={
                "category": "recent_moves",
                "page_url": "https://example.com/news",
                "page_title": "News",
                "headline": "Latest news",
                "claims": [
                    {
                        "category": "recent_moves",
                        "fact_type": "page_claim",
                        "value": "Read our latest news",
                        "evidence_excerpt": "Read our latest news",
                        "source_url": "https://example.com/news",
                    }
                ],
            },
            source_url="https://example.com/news",
            extractor_name="recent_moves_facts",
            confidence=0.8,
            status=ExtractionStatus.OK,
        )
    ]

    profile = build_competitor_profile("example.com", results)
    recent = next(section for section in profile.sections if section.title.startswith("Recent"))

    assert recent.claims == []


def test_profile_builder_does_not_select_two_prices_for_offer_section():
    claims = [
        {
            "category": "products_modules",
            "fact_type": "visible_price",
            "value": "£35",
            "evidence_excerpt": "£35",
            "source_url": "https://example.com/products/glove-a",
        },
        {
            "category": "products_modules",
            "fact_type": "visible_price",
            "value": "£40",
            "evidence_excerpt": "£40",
            "source_url": "https://example.com/products/glove-b",
        },
        {
            "category": "products_modules",
            "fact_type": "page_claim",
            "value": "Professional-grade Contact latex for wet and dry conditions.",
            "evidence_excerpt": "Professional-grade Contact latex for wet and dry conditions.",
            "source_url": "https://example.com/products/glove-a",
        },
    ]
    result = ExtractionResult(
        value={"claims": claims},
        source_url="https://example.com/products/glove-a",
        extractor_name="products_modules_facts",
        confidence=0.8,
        status=ExtractionStatus.OK,
    )

    profile = build_competitor_profile("example.com", [result])
    offer = next(section for section in profile.sections if section.title.startswith("Offer"))

    assert [claim.label for claim in offer.claims] == ["Visible price", "Public claim"]
