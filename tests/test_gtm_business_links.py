from app.scrapers.gtm_facts import extract_gtm_page_fact


def _values(fact, fact_type: str) -> set[str]:
    return {claim.value for claim in fact.claims if claim.fact_type == fact_type}


def test_pricing_extractor_captures_plan_names():
    html = "<main><h1>Pricing</h1><h2>Free</h2><h2>Business</h2><p>$16/month</p></main>"

    fact = extract_gtm_page_fact(html, "https://example.com/pricing", "pricing_packaging")

    assert _values(fact, "pricing_plan") == {"Free", "Business"}


def test_product_extractor_captures_linked_products_and_collections():
    html = (
        '<main><a href="/collections/lunar">Lunar</a>'
        '<a href="/products/lunar-2">Lunar 2 $40</a></main>'
    )

    fact = extract_gtm_page_fact(html, "https://example.com/", "products_modules")

    assert _values(fact, "product_collection") == {"Lunar"}
    assert _values(fact, "linked_product") == {"Lunar 2"}


def test_product_extractor_keeps_twenty_visible_product_links():
    html = (
        "<main>"
        + "".join(
            f'<article><a href="/products/glove-{index}">Glove {index}</a></article>'
            for index in range(1, 21)
        )
        + "</main>"
    )

    fact = extract_gtm_page_fact(html, "https://example.com/collections/all", "products_modules")

    products = _values(fact, "linked_product")
    assert len(products) == 20
    assert "Glove 1" in products
    assert "Glove 20" in products
