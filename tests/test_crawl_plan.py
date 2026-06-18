from app.schemas import CandidateSource
from app.scrapers.discovery import (
    build_crawl_plan,
    build_page_candidate,
    discover_homepage_candidates,
    discover_sitemap_candidates,
)


def test_crawl_plan_prioritizes_high_value_category_diverse_pages():
    homepage_html = """
    <a href="/pricing">Pricing</a>
    <a href="/product">Product</a>
    <a href="/product/analytics">Analytics product</a>
    <a href="/customers">Customers</a>
    <a href="/blog">Blog</a>
    """
    homepage_candidates = discover_homepage_candidates(homepage_html, "https://example.com")
    sitemap_candidates = discover_sitemap_candidates(
        [
            "https://example.com/security",
            "https://example.com/integrations",
            "https://example.com/careers",
        ],
        "https://example.com",
    )

    plan = build_crawl_plan(
        homepage_candidates=homepage_candidates,
        sitemap_candidates=sitemap_candidates,
        selection_limit=5,
    )

    assert len(plan.selected) == 5
    assert plan.selected[0].primary_category == "pricing_packaging"
    selected_categories = {candidate.primary_category for candidate in plan.selected}
    assert "products_modules" in selected_categories
    assert "proof" in selected_categories
    assert "integrations_ecosystem" in selected_categories
    assert "trust_compliance" in selected_categories


def test_homepage_candidate_beats_duplicate_sitemap_candidate():
    homepage_candidate = build_page_candidate(
        url="https://example.com/pricing",
        base_url="https://example.com",
        source=CandidateSource.HOMEPAGE_LINK,
        anchor_text="Pricing",
    )
    sitemap_candidate = build_page_candidate(
        url="https://example.com/pricing",
        base_url="https://example.com",
        source=CandidateSource.SITEMAP,
    )

    plan = build_crawl_plan(
        homepage_candidates=[homepage_candidate],
        sitemap_candidates=[sitemap_candidate],
        selection_limit=1,
    )

    assert plan.selected[0].source == CandidateSource.HOMEPAGE_LINK


def test_signup_and_policy_pages_are_not_candidates():
    html = """
    <a href="/signup">Sign up</a>
    <a href="/privacy">Privacy</a>
    <a href="/pricing">Pricing</a>
    """

    candidates = discover_homepage_candidates(html, "https://example.com")

    assert [str(candidate.url) for candidate in candidates] == ["https://example.com/pricing"]


def test_path_category_overrides_misleading_anchor_text():
    candidate = build_page_candidate(
        url="https://example.com/changelog/product-intelligence",
        base_url="https://example.com",
        source=CandidateSource.HOMEPAGE_LINK,
        anchor_text="Product intelligence for solutions teams",
    )

    assert candidate.primary_category == "recent_moves"


def test_enterprise_page_is_target_segment_not_pricing():
    candidate = build_page_candidate(
        url="https://example.com/enterprise",
        base_url="https://example.com",
        source=CandidateSource.SITEMAP,
    )

    assert candidate.primary_category == "target_segments"
