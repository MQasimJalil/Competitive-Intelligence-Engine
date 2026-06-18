from app.benchmarking import score_snapshot
from app.schemas import BusinessFact, BusinessFactKind, NormalizedBusinessProfile, ProductOffer
from app.tools.competitor_brief.service import CompetitorSnapshot


def test_benchmark_scorer_measures_expected_kinds_and_offers():
    business = NormalizedBusinessProfile(
        domain="example.com",
        facts=[
            BusinessFact(
                citation_id="F001",
                kind="product",
                value="Example product",
                evidence_excerpt="Example product",
                source_url="https://example.com/product",
                category="products_modules",
            ),
            BusinessFact(
                citation_id="F002",
                kind="price",
                value="$20",
                evidence_excerpt="$20",
                source_url="https://example.com/product",
                category="products_modules",
            ),
        ],
        offers=[
            ProductOffer(
                name="Example product",
                prices=["$20"],
                citation_ids=["F001", "F002"],
            )
        ],
    )
    snapshot = CompetitorSnapshot(
        domain="example.com",
        homepage="https://example.com",
        results=[],
        business_profile=business,
    )

    score = score_snapshot(
        snapshot,
        expected_kinds=[BusinessFactKind.PRODUCT, BusinessFactKind.PRICE],
        minimum_facts=2,
    )

    assert score.expected_kind_recall == 1.0
    assert score.coverage_score == 1.0
    assert score.offer_score == 0.5
