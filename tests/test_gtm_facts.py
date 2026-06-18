from app.scrapers.gtm_facts import extract_gtm_page_fact


def _claim_values(fact, fact_type: str) -> list[str]:
    return [claim.value for claim in fact.claims if claim.fact_type == fact_type]


def test_pricing_extractor_creates_claim_level_evidence():
    html = """
    <main>
      <h1>Simple pricing that scales with your team</h1>
      <h2>Starter</h2>
      <p>Start free, then upgrade for $29/month when your team is ready.</p>
      <a href="/signup">Start free</a>
      <a href="/contact">Contact sales</a>
    </main>
    """

    fact = extract_gtm_page_fact(html, "https://example.com/pricing", "pricing_packaging")

    assert fact.headline == "Simple pricing that scales with your team"
    price_claim = next(claim for claim in fact.claims if claim.fact_type == "visible_price")
    assert price_claim.value == "$29/month"
    assert "$29/month" in price_claim.evidence_excerpt
    assert str(price_claim.source_url) == "https://example.com/pricing"
    assert "Start free" in _claim_values(fact, "cta")


def test_trust_extractor_uses_phrase_boundaries_and_removes_hidden_text():
    html = """
    <main>
      <h1>Enterprise security</h1>
      <p>Our platform supports SOC 2, GDPR, SSO, and encryption at rest.</p>
      <p hidden>HIPAA</p>
      <p aria-hidden="true">ISO 27001</p>
    </main>
    """

    fact = extract_gtm_page_fact(html, "https://example.com/security", "trust_compliance")

    mentions = _claim_values(fact, "keyword_mention")
    assert "soc 2" in mentions
    assert "gdpr" in mentions
    assert "sso" in mentions
    assert "hipaa" not in mentions
    assert "iso 27001" not in mentions


def test_proof_extractor_contextualizes_visible_metric():
    html = """
    <main>
      <h1>Trusted by modern product teams</h1>
      <p>Powering more than 33,000 organizations worldwide.</p>
    </main>
    """

    fact = extract_gtm_page_fact(html, "https://example.com/customers", "proof")

    metric = next(claim for claim in fact.claims if claim.fact_type == "proof_metric")
    assert metric.value == "33,000"
    assert metric.evidence_excerpt == "Powering more than 33,000 organizations worldwide."


def test_pricing_extractor_supports_gbp_and_euro_symbols():
    html = "<main><h1>Pricing</h1><p>Pro costs £20/month or €25/month.</p></main>"

    fact = extract_gtm_page_fact(html, "https://example.com/pricing", "pricing_packaging")

    assert "£20/month" in _claim_values(fact, "visible_price")
    assert "€25/month" in _claim_values(fact, "visible_price")


def test_product_extractor_supports_alternate_pound_character():
    html = "<main><a href='/products/cobra'>Cobra Junior Ł25.00</a></main>"

    fact = extract_gtm_page_fact(html, "https://example.com/", "products_modules")

    assert "Ł25.00" in _claim_values(fact, "visible_price")


def test_product_extractor_supports_trailing_currency_symbol():
    html = """
    <section class="product-card">
      <a href="goalkeeper-gloves-brave-gk-venom-nwb">shop</a>
      <span class="item-card__price">85.00 €</span>
    </section>
    """

    fact = extract_gtm_page_fact(html, "https://example.com/", "products_modules")

    assert "85.00 €" in _claim_values(fact, "visible_price")


def test_product_extractor_supports_rupee_currency_strings():
    html = """
    <html><body>
      <a href="/products/glove">Match glove</a>
      <span class="price">Rs. 4,999</span>
      <span>Training plan PKR 12,500</span>
      <span>Academy plan ₹3,999</span>
    </body></html>
    """

    fact = extract_gtm_page_fact(html, "https://example.com/products", "products_modules")

    prices = _claim_values(fact, "visible_price")
    assert "Rs. 4,999" in prices
    assert "PKR 12,500" in prices
    assert "₹3,999" in prices


def test_product_extractor_finds_price_next_to_product_link():
    html = """
    <main>
      <section class="product-card">
        <a href="/products/lunar"><span>Lunar glove</span></a>
        <span class="price">£25</span>
      </section>
    </main>
    """

    fact = extract_gtm_page_fact(html, "https://example.com/collections/all", "products_modules")

    price = next(claim for claim in fact.claims if claim.fact_type == "visible_price")
    assert price.value == "£25"
    assert "Lunar glove" in price.evidence_excerpt


def test_pricing_extractor_captures_tier_capabilities():
    html = """
    <main>
      <h1>Pricing</h1>
      <h2>Business</h2>
      <p>Business includes agent automations and Code Intelligence.</p>
    </main>
    """

    fact = extract_gtm_page_fact(html, "https://example.com/pricing", "pricing_packaging")

    assert "Business includes agent automations and Code Intelligence." in _claim_values(
        fact, "packaging_capability"
    )


def test_extractor_accepts_more_than_twenty_prioritized_claims():
    html = "<main><h1>Products</h1>" + "".join(
        f"<a href='/products/item-{index}'>Goalkeeper glove {index} Â£{index}.00</a>"
        for index in range(1, 31)
    ) + "</main>"

    fact = extract_gtm_page_fact(html, "https://example.com/collections/all", "products_modules")

    html = "<main><h1>Products</h1>" + "".join(
        f"<a href='/products/item-{index}'>Goalkeeper glove model-{index} ${index}.00</a>"
        for index in range(1, 31)
    ) + "</main>"
    fact = extract_gtm_page_fact(html, "https://example.com/collections/all", "products_modules")

    assert len(fact.claims) > 20
    assert len(fact.claims) <= 40
    assert "Goalkeeper glove model-30" in _claim_values(fact, "linked_product")


def test_extractor_removes_common_navigation_noise_from_claims():
    html = """
    <main>
      <h1>Skip to content â†’ Plan from idea to launch</h1>
      <p>Skip to main content Product teams use roadmaps, issues, and documents together.</p>
    </main>
    """

    fact = extract_gtm_page_fact(html, "https://example.com/", "positioning")
    values = " ".join(claim.value.casefold() for claim in fact.claims)

    assert "skip to content" not in values
    assert "skip to main content" not in values
    assert "plan from idea to launch" in values
