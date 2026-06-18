from app.schemas import (
    BusinessCategory,
    BusinessFact,
    BusinessFactKind,
    ExtractionResult,
    ExtractionStatus,
    NormalizedBusinessProfile,
    ProductOffer,
)
from app.tools.competitor_brief.validation import validate_business_profile


def _fact(citation_id: str, value: str, source_url: str) -> BusinessFact:
    return BusinessFact(
        citation_id=citation_id,
        kind=BusinessFactKind.PRICE,
        value=value,
        evidence_excerpt=value,
        source_url=source_url,
        category=BusinessCategory.PRICING_PACKAGING,
    )


def test_validation_rejects_cross_source_product_price_offer():
    profile = NormalizedBusinessProfile(
        domain="example.com",
        facts=[
            _fact("F001", "Pro", "https://example.com/product"),
            _fact("F002", "$20", "https://example.com/pricing"),
        ],
        offers=[
            ProductOffer(
                name="Pro",
                prices=["$20"],
                citation_ids=["F001", "F002"],
            )
        ],
    )

    report = validate_business_profile([], profile)

    assert not report.ready_for_report
    assert "cross_source_offer" in {issue.code for issue in report.issues}


def test_validation_marks_failed_collection_as_partial_warning():
    profile = NormalizedBusinessProfile(
        domain="example.com",
        facts=[_fact("F001", "$20", "https://example.com/pricing")],
    )
    result = ExtractionResult.unavailable(
        extractor_name="proof_facts",
        source_url="https://example.com/customers",
        status=ExtractionStatus.NETWORK_FAILED,
    )

    report = validate_business_profile([result], profile)

    assert report.ready_for_report
    assert "partial_collection" in {issue.code for issue in report.issues}
