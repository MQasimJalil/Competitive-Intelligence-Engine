from app.scrapers.discovery import discover_homepage_candidates, discover_relevant_links


def test_discovery_keeps_only_same_site_http_links():
    html = """
    <a href='/pricing'>Pricing</a>
    <a href='https://jobs.example.com/openings'>Jobs</a>
    <a href='https://external.com/pricing'>External pricing</a>
    <a href='mailto:sales@example.com'>Contact pricing</a>
    <a href='javascript:void(0)'>Features</a>
    """
    links = discover_relevant_links(html, "https://example.com")
    assert links["pricing_packaging"] == ["https://example.com/pricing"]
    assert links["hiring_signals"] == ["https://jobs.example.com/openings"]
    assert all("external.com" not in url for group in links.values() for url in group)


def test_discovery_separates_products_capabilities_and_solutions():
    html = """
    <a href='/platform'>Platform</a>
    <a href='/features/automation'>Automation features</a>
    <a href='/solutions/agencies'>Solutions for agencies</a>
    """

    links = discover_relevant_links(html, "https://example.com")

    assert links["products_modules"] == ["https://example.com/platform"]
    assert links["capabilities"] == ["https://example.com/features/automation"]
    assert links["solutions_use_cases"] == ["https://example.com/solutions/agencies"]


def test_discovery_excludes_low_signal_policy_and_archive_pages():
    html = """
    <a href='/privacy'>Privacy</a>
    <a href='/terms'>Terms</a>
    <a href='/blog/tag/product'>Product archive</a>
    <a href='/customers/acme'>Customer story</a>
    """

    links = discover_relevant_links(html, "https://example.com")

    assert links["proof"] == ["https://example.com/customers/acme"]
    assert all("/privacy" not in url for group in links.values() for url in group)
    assert all("/terms" not in url for group in links.values() for url in group)
    assert all("/tag/" not in url for group in links.values() for url in group)


def test_discovery_does_not_match_short_keyword_inside_another_word():
    html = '<a href="/membership">Nike Membership</a>'

    candidates = discover_homepage_candidates(html, "https://example.com")

    assert len(candidates) == 1
    assert candidates[0].primary_category.value == "sales_motion"
    assert "products_modules" not in candidates[0].matched_categories


def test_discovery_removes_variant_and_tracking_query_parameters():
    html = '<a href="/products/glove?variant=123&utm_source=email">Glove product</a>'

    candidates = discover_homepage_candidates(html, "https://example.com")

    assert str(candidates[0].url) == "https://example.com/products/glove"


def test_discovery_accepts_meaningful_related_subdomain_homepage():
    candidates = discover_homepage_candidates(
        '<a href="https://agent.example.com/">Agent</a>',
        "https://example.com/",
    )

    assert len(candidates) == 1
    assert str(candidates[0].url) == "https://agent.example.com/"
    assert candidates[0].primary_category.value == "products_modules"
