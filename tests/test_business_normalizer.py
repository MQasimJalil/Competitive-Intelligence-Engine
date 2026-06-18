from app.schemas import ExtractionResult, ExtractionStatus
from app.tools.competitor_brief.business_normalizer import build_normalized_business_profile


def test_normalizer_pairs_product_and_prices_from_same_page():
    result = ExtractionResult(
        value={
            "page_url": "https://example.com/products/lunar",
            "page_title": "Lunar glove",
            "claims": [
                {
                    "category": "products_modules",
                    "fact_type": "page_headline",
                    "value": "Lunar Pro",
                    "evidence_excerpt": "Lunar Pro",
                    "source_url": "https://example.com/products/lunar",
                },
                {
                    "category": "products_modules",
                    "fact_type": "visible_price",
                    "value": "$40",
                    "evidence_excerpt": "Lunar Pro - $40",
                    "source_url": "https://example.com/products/lunar",
                },
            ],
        },
        source_url="https://example.com/products/lunar",
        extractor_name="products_modules_facts",
        confidence=0.8,
        status=ExtractionStatus.OK,
    )

    profile = build_normalized_business_profile("example.com", [result])

    assert profile.offers[0].name == "Lunar Pro"
    assert profile.offers[0].prices == ["$40"]
    assert profile.facts[0].citation_id.startswith("F-")
    assert profile.facts[0].source_title == "Lunar glove"


def test_normalizer_generates_stable_content_derived_citation_ids():
    result = ExtractionResult(
        value={
            "claims": [
                {
                    "category": "positioning",
                    "fact_type": "page_claim",
                    "value": "A stable public claim.",
                    "evidence_excerpt": "A stable public claim.",
                    "source_url": "https://example.com/",
                }
            ]
        },
        source_url="https://example.com/",
        extractor_name="positioning_facts",
        confidence=0.8,
        status=ExtractionStatus.OK,
    )

    first = build_normalized_business_profile("example.com", [result])
    second = build_normalized_business_profile("example.com", [result])

    assert first.facts[0].citation_id == second.facts[0].citation_id


def test_normalizer_deduplicates_claims_that_share_a_citation_id():
    result = ExtractionResult(
        value={
            "claims": [
                {
                    "category": "positioning",
                    "fact_type": "page_claim",
                    "value": "Built for athletes",
                    "evidence_excerpt": "Built for athletes",
                    "source_url": "https://example.com/",
                },
                {
                    "category": "positioning",
                    "fact_type": "page_claim",
                    "value": "Built  for athletes",
                    "evidence_excerpt": "Built  for athletes",
                    "source_url": "https://example.com/",
                },
            ]
        },
        source_url="https://example.com/",
        extractor_name="positioning_facts",
        confidence=0.8,
        status=ExtractionStatus.OK,
    )

    profile = build_normalized_business_profile("example.com", [result])

    assert len(profile.facts) == 1


def test_normalizer_recategorizes_mission_text_from_careers_page():
    result = ExtractionResult(
        value={
            "claims": [
                {
                    "category": "hiring_signals",
                    "fact_type": "page_claim",
                    "value": (
                        "OUR MISSION is to democratize access to intelligence "
                        "through humanistic AI."
                    ),
                    "evidence_excerpt": (
                        "OUR MISSION is to democratize access to intelligence "
                        "through humanistic AI."
                    ),
                    "source_url": "https://example.com/careers",
                }
            ]
        },
        source_url="https://example.com/careers",
        extractor_name="hiring_signals_facts",
        confidence=0.8,
        status=ExtractionStatus.OK,
    )

    profile = build_normalized_business_profile("example.com", [result])

    assert profile.facts[0].kind.value == "company_detail"
