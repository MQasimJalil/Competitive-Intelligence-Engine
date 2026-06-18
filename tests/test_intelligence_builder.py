from app.schemas import (
    BusinessCategory,
    BusinessFact,
    BusinessFactKind,
    NormalizedBusinessProfile,
    ValidationReport,
)
from app.tools.competitor_brief.intelligence_builder import build_structured_intelligence


def _fact(citation_id, kind, category, value):
    return BusinessFact(
        citation_id=citation_id,
        kind=kind,
        category=category,
        value=value,
        evidence_excerpt=value,
        source_url="https://example.com",
    )


def test_structured_intelligence_groups_validated_business_facts():
    profile = NormalizedBusinessProfile(
        domain="example.com",
        facts=[
            _fact("F001", BusinessFactKind.PRICE, BusinessCategory.PRICING_PACKAGING, "$20"),
            _fact("F002", BusinessFactKind.AUDIENCE, BusinessCategory.TARGET_SEGMENTS, "Teams"),
            _fact(
                "F003",
                BusinessFactKind.DIFFERENTIATOR,
                BusinessCategory.CAPABILITIES,
                "Fast",
            ),
        ],
    )

    intelligence = build_structured_intelligence(
        profile,
        ValidationReport(ready_for_report=True, checked_fact_count=3),
    )

    assert intelligence.pricing[0].citation_id == "F001"
    assert intelligence.target_customers[0].citation_id == "F002"
    assert intelligence.differentiators[0].citation_id == "F003"
    assert len(intelligence.to_business_profile().facts) == 3
