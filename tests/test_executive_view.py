from app.schemas import (
    AIAnalysis,
    AIReportLabels,
    BusinessCategory,
    BusinessFact,
    CitedStatement,
    ExtractionResult,
    ExtractionStatus,
    NormalizedBusinessProfile,
    ObservedClaim,
)
from app.tools.competitor_brief.business_normalizer import build_normalized_business_profile
from app.tools.competitor_brief.executive_view import build_executive_report
from app.tools.competitor_brief.profile_builder import build_competitor_profile


def _result(claims):
    values = [
        claim.model_dump(mode="json") if isinstance(claim, ObservedClaim) else claim
        for claim in claims
    ]
    source_url = values[0].get("source_url", "https://example.com/products/glove")
    return ExtractionResult(
        value={"claims": values},
        source_url=source_url,
        extractor_name="products_modules_facts",
        confidence=0.8,
        status=ExtractionStatus.OK,
    )


def test_executive_report_surfaces_apify_social_proof():
    results = [
        _result(
            [
                ObservedClaim(
                    category=BusinessCategory.PROOF,
                    fact_type="social_followers",
                    value="Instagram profile sologk shows 12,000 followers.",
                    evidence_excerpt="followersCount=12000",
                    source_url="https://www.instagram.com/sologk/",
                    context="Public Instagram metadata",
                ),
                ObservedClaim(
                    category=BusinessCategory.PROOF,
                    fact_type="social_post_engagement",
                    value="Instagram post engagement: 410 likes, 22 comments.",
                    evidence_excerpt="New launch caption",
                    source_url="https://www.instagram.com/p/abc/",
                    context="Public Instagram post metrics",
                ),
            ]
        )
    ]
    profile = build_competitor_profile("sologk.com", results)
    business = build_normalized_business_profile("sologk.com", results)

    report = build_executive_report("sologk.com", results, profile, business)

    proof_section = next(
        section
        for section in report.sections
        if section.title == "Customer trust and recent activity"
    )
    assert any("Instagram profile" in point.text for point in proof_section.points)


def test_executive_report_classifies_ecommerce_and_technology_sites():
    ecommerce_result = _result(
        [
            ObservedClaim(
                category=BusinessCategory.PRODUCTS_MODULES,
                fact_type="linked_product",
                value="Lunar Pro",
                evidence_excerpt="Lunar Pro",
                source_url="https://shop.example/products/lunar",
            ),
            ObservedClaim(
                category=BusinessCategory.PRICING_PACKAGING,
                fact_type="visible_price",
                value="£40.00",
                evidence_excerpt="£40.00",
                source_url="https://shop.example/products/lunar",
            ),
        ]
    )
    tech_result = _result(
        [
            ObservedClaim(
                category=BusinessCategory.PRODUCTS_MODULES,
                fact_type="page_claim",
                value="A product development platform for modern software teams.",
                evidence_excerpt="A product development platform for modern software teams.",
                source_url="https://linear.example",
            )
        ]
    )

    ecommerce_profile = build_competitor_profile("shop.example", [ecommerce_result])
    tech_profile = build_competitor_profile("linear.example", [tech_result])

    assert (
        build_executive_report("shop.example", [ecommerce_result], ecommerce_profile).business_type
        == "Ecommerce"
    )
    assert (
        build_executive_report("linear.example", [tech_result], tech_profile).business_type
        == "Technology / SaaS"
    )


def test_executive_report_simplifies_prices_products_and_sources():
    results = [
        _result(
            [
                {
                    "category": "positioning",
                    "fact_type": "page_claim",
                    "value": "Goalkeeper gloves designed around price and quality.",
                    "evidence_excerpt": "Goalkeeper gloves designed around price and quality.",
                    "source_url": "https://example.com/about",
                },
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
                    "value": "£35",
                    "evidence_excerpt": "£35",
                    "source_url": "https://example.com/products/lunar",
                },
                {
                    "category": "products_modules",
                    "fact_type": "visible_price",
                    "value": "£40",
                    "evidence_excerpt": "£40",
                    "source_url": "https://example.com/products/eclipse",
                },
            ]
        )
    ]
    profile = build_competitor_profile("example.com", results)

    report = build_executive_report("example.com", results, profile)

    assert report.at_a_glance_source_number == 1
    assert report.quick_facts[0].value == "Lunar Pro"
    assert report.quick_facts[1].value == "£35 - £40"
    assert report.sources


def test_executive_report_keeps_collections_separate_from_actual_products():
    results = [
        _result(
            [
                {
                    "category": "products_modules",
                    "fact_type": "product_collection",
                    "value": "Lunar",
                    "evidence_excerpt": "Lunar",
                    "source_url": "https://example.com/collections/lunar",
                },
                {
                    "category": "products_modules",
                    "fact_type": "product_collection",
                    "value": "Vortex",
                    "evidence_excerpt": "Vortex",
                    "source_url": "https://example.com/collections/vortex",
                },
                {
                    "category": "products_modules",
                    "fact_type": "product_collection",
                    "value": "Cobra",
                    "evidence_excerpt": "Cobra",
                    "source_url": "https://example.com/collections/cobra",
                },
                {
                    "category": "products_modules",
                    "fact_type": "linked_product",
                    "value": "Lunar 2",
                    "evidence_excerpt": "Lunar 2",
                    "source_url": "https://example.com/products/lunar-2",
                },
            ]
        )
    ]
    profile = build_competitor_profile("example.com", results)
    business_profile = build_normalized_business_profile("example.com", results)

    report = build_executive_report("example.com", results, profile, business_profile)

    quick_facts = {fact.label: fact.value for fact in report.quick_facts}
    assert quick_facts["Products spotted"] == "Lunar 2"
    assert quick_facts["Collections spotted"] == "Lunar, Vortex, Cobra"
    offer = next(section for section in report.sections if section.title == "What they offer")
    assert any(
        point.text == "Collections observed: Lunar, Vortex, Cobra." for point in offer.points
    )


def test_executive_report_builds_customer_facing_top_metrics():
    results = [
        _result(
            [
                {
                    "category": "positioning",
                    "fact_type": "page_claim",
                    "value": "Solo GK is a UK-based goalkeeper glove brand.",
                    "evidence_excerpt": "Solo GK is a UK-based goalkeeper glove brand.",
                    "source_url": "https://example.com/about",
                },
                *[
                    {
                        "category": "products_modules",
                        "fact_type": "linked_product",
                        "value": f"Lunar glove {index}",
                        "evidence_excerpt": f"Lunar glove {index}",
                        "source_url": f"https://example.com/products/lunar-{index}",
                    }
                    for index in range(1, 21)
                ],
                {
                    "category": "products_modules",
                    "fact_type": "visible_price",
                    "value": "Â£25",
                    "evidence_excerpt": "Â£25",
                    "source_url": "https://example.com/products/lunar-1",
                },
                {
                    "category": "products_modules",
                    "fact_type": "visible_price",
                    "value": "Â£40",
                    "evidence_excerpt": "Â£40",
                    "source_url": "https://example.com/products/lunar-2",
                },
            ]
        )
    ]
    profile = build_competitor_profile("example.com", results)

    report = build_executive_report("example.com", results, profile)

    metrics = {fact.label: fact.value for fact in report.top_metrics}
    assert metrics["Country"] == "United Kingdom"
    assert metrics["Industry"] == "Goalkeeper gloves"
    assert metrics["Business model"] == "DTC ecommerce"
    assert "25" in metrics["Observed price band"]
    assert "40" in metrics["Observed price band"]
    assert metrics["Shop listing count"] == "20 items"
    assert metrics["Threat read"].startswith("Medium")


def test_executive_report_summarizes_trailing_euro_symbol_prices():
    results = [
        _result(
            [
                {
                    "category": "products_modules",
                    "fact_type": "visible_price",
                    "value": "49.49 €",
                    "evidence_excerpt": "49.49 €",
                    "source_url": "https://example.com/",
                },
                {
                    "category": "products_modules",
                    "fact_type": "visible_price",
                    "value": "85.00 €",
                    "evidence_excerpt": "85.00 €",
                    "source_url": "https://example.com/",
                },
            ]
        )
    ]
    profile = build_competitor_profile("example.com", results)

    report = build_executive_report("example.com", results, profile)

    assert report.quick_facts[1].value == "€49.49 - €85"
    offer = next(section for section in report.sections if section.title == "What they offer")
    assert any(
        "Visible featured prices span EUR 49.49 to EUR 85." == point.text for point in offer.points
    )


def test_executive_report_parses_decimal_comma_prices():
    results = [
        _result(
            [
                {
                    "category": "products_modules",
                    "fact_type": "visible_price",
                    "value": "18,00 €",
                    "evidence_excerpt": "18,00 €",
                    "source_url": "https://example.com/",
                },
                {
                    "category": "products_modules",
                    "fact_type": "visible_price",
                    "value": "190,00 €",
                    "evidence_excerpt": "190,00 €",
                    "source_url": "https://example.com/",
                },
            ]
        )
    ]
    profile = build_competitor_profile("example.com", results)

    report = build_executive_report("example.com", results, profile)

    assert report.quick_facts[1].value == "€18 - €190"


def test_executive_report_parses_rupee_price_codes_and_symbols():
    results = [
        _result(
            [
                {
                    "category": "products_modules",
                    "fact_type": "visible_price",
                    "value": "Rs. 4,999",
                    "evidence_excerpt": "Rs. 4,999",
                    "source_url": "https://example.com/products/glove",
                },
                {
                    "category": "products_modules",
                    "fact_type": "visible_price",
                    "value": "PKR 12,500",
                    "evidence_excerpt": "PKR 12,500",
                    "source_url": "https://example.com/products/pro",
                },
            ]
        )
    ]
    profile = build_competitor_profile("example.com", results)

    report = build_executive_report("example.com", results, profile)

    assert report.quick_facts[1].value == "PKR 4,999 - PKR 12,500"


def test_executive_report_prefers_structured_product_price_over_noisy_visible_price():
    results = [
        _result(
            [
                {
                    "category": "products_modules",
                    "fact_type": "structured_product",
                    "value": "LUNAR 2 - PURPLE",
                    "evidence_excerpt": "LUNAR 2 - PURPLE",
                    "source_url": "https://sologk.com/products/lunar-2-purple",
                },
                {
                    "category": "products_modules",
                    "fact_type": "structured_price",
                    "value": "GBP 35.00",
                    "evidence_excerpt": "LUNAR 2 - PURPLE GBP 35.00",
                    "source_url": "https://sologk.com/products/lunar-2-purple",
                },
                {
                    "category": "products_modules",
                    "fact_type": "visible_price",
                    "value": "$70",
                    "evidence_excerpt": "Noisy script value $70",
                    "source_url": "https://sologk.com/products/lunar-2-purple",
                },
            ]
        )
    ]

    report = build_executive_report(
        "sologk.com",
        results,
        build_competitor_profile("sologk.com", results),
    )

    metrics = {fact.label: fact.value for fact in report.top_metrics}
    assert metrics["Observed price band"] == "GBP 35"
    assert "$70" not in report.quick_facts[1].value


def test_executive_report_uses_type_aware_metrics_for_hosting_and_community_sites():
    hostinger_result = _result(
        [
            {
                "category": "positioning",
                "fact_type": "page_claim",
                "value": "Hostinger offers web hosting, a website builder, domains, and VPS.",
                "evidence_excerpt": (
                    "Hostinger offers web hosting, a website builder, domains, and VPS."
                ),
                "source_url": "https://hostinger.example/",
            },
            {
                "category": "pricing_packaging",
                "fact_type": "visible_price",
                "value": "$5.99",
                "evidence_excerpt": "$5.99",
                "source_url": "https://hostinger.example/products/web-hosting",
            },
        ]
    )
    discord_result = _result(
        [
            {
                "category": "positioning",
                "fact_type": "page_claim",
                "value": "Discord is a voice chat and group chat platform for gaming communities.",
                "evidence_excerpt": (
                    "Discord is a voice chat and group chat platform for gaming communities."
                ),
                "source_url": "https://discord.example/",
            },
            {
                "category": "pricing_packaging",
                "fact_type": "page_claim",
                "value": "Nitro adds premium perks for users.",
                "evidence_excerpt": "Nitro adds premium perks for users.",
                "source_url": "https://discord.example/nitro",
            },
        ]
    )

    hostinger = build_executive_report(
        "hostinger.example",
        [hostinger_result],
        build_competitor_profile("hostinger.example", [hostinger_result]),
    )
    discord = build_executive_report(
        "discord.example",
        [discord_result],
        build_competitor_profile("discord.example", [discord_result]),
    )

    hostinger_metrics = {fact.label: fact.value for fact in hostinger.top_metrics}
    discord_metrics = {fact.label: fact.value for fact in discord.top_metrics}
    assert hostinger.business_type == "Technology / SaaS"
    assert hostinger_metrics["Industry"] == "Web hosting"
    assert hostinger_metrics["Business model"] == "Subscription hosting"
    assert "Shop listing count" not in hostinger_metrics
    assert hostinger_metrics["Commercial signal"] == "Pricing visible"
    assert discord.business_type == "Technology / SaaS"
    assert discord_metrics["Industry"] == "Community communication platform"
    assert discord_metrics["Business model"] == "Freemium platform"


def test_executive_report_classifies_priced_saas_without_calling_it_ecommerce():
    results = [
        _result(
            [
                {
                    "category": "positioning",
                    "fact_type": "page_claim",
                    "value": "Linear is a product development platform for software teams.",
                    "evidence_excerpt": (
                        "Linear is a product development platform for software teams."
                    ),
                    "source_url": "https://linear.example/",
                },
                {
                    "category": "pricing_packaging",
                    "fact_type": "visible_price",
                    "value": "$16",
                    "evidence_excerpt": "$16 per user per month",
                    "source_url": "https://linear.example/pricing",
                },
                {
                    "category": "pricing_packaging",
                    "fact_type": "pricing_plan",
                    "value": "Business",
                    "evidence_excerpt": "Business",
                    "source_url": "https://linear.example/pricing",
                },
            ]
        )
    ]

    report = build_executive_report(
        "linear.example",
        results,
        build_competitor_profile("linear.example", results),
    )

    metrics = {fact.label: fact.value for fact in report.top_metrics}
    assert report.business_type == "Technology / SaaS"
    assert metrics["Business model"] == "SaaS / platform"
    assert "Commercial signal" in metrics
    assert "Shop listing count" not in metrics


def test_executive_report_classifies_nike_as_sportswear_retail_not_saas():
    results = [
        _result(
            [
                {
                    "category": "positioning",
                    "fact_type": "page_claim",
                    "value": "Nike sells athletic footwear, apparel, and sport products.",
                    "evidence_excerpt": (
                        "Nike sells athletic footwear, apparel, and sport products."
                    ),
                    "source_url": "https://nike.example/",
                },
                {
                    "category": "proof",
                    "fact_type": "social_followers",
                    "value": "Instagram profile nike shows 292,000,000 followers.",
                    "evidence_excerpt": "followers=292000000",
                    "source_url": "https://instagram.example/nike",
                },
            ]
        )
    ]

    report = build_executive_report(
        "nike.example",
        results,
        build_competitor_profile("nike.example", results),
    )

    metrics = {fact.label: fact.value for fact in report.top_metrics}
    assert report.business_type == "Ecommerce"
    assert metrics["Industry"] == "Sportswear and athletic retail"
    assert metrics["Business model"] == "Global retail / DTC ecommerce"
    assert report.at_a_glance.startswith("Sells athletic footwear")


def test_ai_labels_can_override_executive_metrics_with_citations():
    results = [
        _result(
            [
                {
                    "category": "positioning",
                    "fact_type": "page_claim",
                    "value": "Nike sells athletic footwear, apparel, and sport products.",
                    "evidence_excerpt": (
                        "Nike sells athletic footwear, apparel, and sport products."
                    ),
                    "source_url": "https://nike.example/about",
                }
            ]
        )
    ]
    profile = build_competitor_profile("nike.example", results)
    business_profile = NormalizedBusinessProfile(
        domain="nike.example",
        facts=[
            BusinessFact(
                citation_id="F001",
                kind="company_detail",
                value="Nike sells athletic footwear, apparel, and sport products.",
                evidence_excerpt="Nike sells athletic footwear, apparel, and sport products.",
                source_url="https://nike.example/about",
                category="positioning",
            )
        ],
    )
    analysis = AIAnalysis(
        report_labels=AIReportLabels(
            industry=CitedStatement(
                text="Sportswear and athletic retail",
                citation_ids=["F001"],
            ),
            business_model=CitedStatement(
                text="Global retail and DTC ecommerce",
                citation_ids=["F001"],
            ),
            portfolio_metric=CitedStatement(
                text="Retail product catalog visible",
                citation_ids=["F001"],
            ),
        )
    )

    report = build_executive_report(
        "nike.example",
        results,
        profile,
        business_profile,
        analysis,
    )

    metrics = {fact.label: fact.value for fact in report.top_metrics}
    assert metrics["Industry"] == "Sportswear and athletic retail [1]"
    assert metrics["Business model"] == "Global retail and DTC ecommerce [1]"
    assert metrics["Offer signal"] == "Retail product catalog visible [1]"
    assert report.sources[0].url == "https://nike.example/about"


def test_ai_portfolio_label_rejects_company_size_signal():
    results = [
        _result(
            [
                {
                    "category": "positioning",
                    "fact_type": "page_claim",
                    "value": "Nike sells athletic footwear, apparel, and sport products.",
                    "evidence_excerpt": (
                        "Nike sells athletic footwear, apparel, and sport products."
                    ),
                    "source_url": "https://nike.example/about",
                },
                {
                    "category": "proof",
                    "fact_type": "page_claim",
                    "value": "Nike reports 79,400 employees worldwide.",
                    "evidence_excerpt": "Nike reports 79,400 employees worldwide.",
                    "source_url": "https://nike.example/company",
                },
            ]
        )
    ]
    profile = build_competitor_profile("nike.example", results)
    business_profile = NormalizedBusinessProfile(
        domain="nike.example",
        facts=[
            BusinessFact(
                citation_id="F001",
                kind="company_detail",
                value="Nike sells athletic footwear, apparel, and sport products.",
                evidence_excerpt="Nike sells athletic footwear, apparel, and sport products.",
                source_url="https://nike.example/about",
                category="positioning",
            ),
            BusinessFact(
                citation_id="F002",
                kind="proof",
                value="Nike reports 79,400 employees worldwide.",
                evidence_excerpt="Nike reports 79,400 employees worldwide.",
                source_url="https://nike.example/company",
                category="proof",
            ),
        ],
    )
    analysis = AIAnalysis(
        report_labels=AIReportLabels(
            industry=CitedStatement(
                text="Sportswear retail",
                citation_ids=["F001"],
            ),
            portfolio_metric=CitedStatement(
                text="Employee count visible",
                citation_ids=["F002"],
            ),
        )
    )

    report = build_executive_report(
        "nike.example",
        results,
        profile,
        business_profile,
        analysis,
    )

    metrics = {fact.label: fact.value for fact in report.top_metrics}
    assert metrics["Industry"] == "Sportswear retail [1]"
    assert metrics["Shop listing count"] == "Data unavailable"


def test_executive_report_does_not_infer_country_from_currency_only():
    results = [
        _result(
            [
                {
                    "category": "products_modules",
                    "fact_type": "visible_price",
                    "value": "£40",
                    "evidence_excerpt": "£40",
                    "source_url": "https://global.example/products/item",
                }
            ]
        )
    ]

    report = build_executive_report(
        "global.example",
        results,
        build_competitor_profile("global.example", results),
    )

    metrics = {fact.label: fact.value for fact in report.top_metrics}
    assert metrics["Country"] == "Data unavailable"


def test_executive_report_does_not_infer_country_from_generic_country_mentions():
    results = [
        _result(
            [
                {
                    "category": "positioning",
                    "fact_type": "page_claim",
                    "value": "Shipping is available in the United Kingdom and United States.",
                    "evidence_excerpt": (
                        "Shipping is available in the United Kingdom and United States."
                    ),
                    "source_url": "https://global.example/",
                }
            ]
        )
    ]

    report = build_executive_report(
        "global.example",
        results,
        build_competitor_profile("global.example", results),
    )

    metrics = {fact.label: fact.value for fact in report.top_metrics}
    assert metrics["Country"] == "Data unavailable"


def test_executive_report_sentence_safe_summary_avoids_mid_sentence_ellipsis():
    long_claim = (
        "This competitor gives product teams one workspace for feedback, planning, "
        "roadmaps, issues, and documentation. The second sentence contains extra detail "
        "that should not force the top summary to end halfway through a thought."
    )
    results = [
        _result(
            [
                {
                    "category": "positioning",
                    "fact_type": "page_claim",
                    "value": long_claim,
                    "evidence_excerpt": long_claim,
                    "source_url": "https://linear.example/",
                }
            ]
        )
    ]

    report = build_executive_report(
        "linear.example",
        results,
        build_competitor_profile("linear.example", results),
    )

    assert "..." not in report.at_a_glance


def test_executive_report_synthesizes_workflow_from_cited_page_claims():
    results = [
        _result(
            [
                {
                    "category": "positioning",
                    "fact_type": "page_claim",
                    "value": "Turn customer feedback into actionable issues.",
                    "evidence_excerpt": "Turn customer feedback into actionable issues.",
                    "source_url": "https://example.com/",
                },
                {
                    "category": "positioning",
                    "fact_type": "page_claim",
                    "value": "Plan from idea to launch with roadmaps and PRDs.",
                    "evidence_excerpt": "Plan from idea to launch with roadmaps and PRDs.",
                    "source_url": "https://example.com/",
                },
                {
                    "category": "positioning",
                    "fact_type": "page_claim",
                    "value": "AI agents can delegate entire issues end-to-end.",
                    "evidence_excerpt": "AI agents can delegate entire issues end-to-end.",
                    "source_url": "https://example.com/",
                },
            ]
        )
    ]
    profile = build_competitor_profile("example.com", results)
    business_profile = build_normalized_business_profile("example.com", results)

    report = build_executive_report("example.com", results, profile, business_profile)

    standout = next(section for section in report.sections if section.title == "What stands out")
    assert "feedback intake" in standout.points[0].text
    assert "planning from idea to launch" in standout.points[0].text
    assert "AI-agent execution" in standout.points[0].text


def test_executive_report_synthesizes_flagship_agent_capabilities_from_one_page():
    results = [
        _result(
            [
                {
                    "category": "products_modules",
                    "fact_type": "page_headline",
                    "value": "Hermes Agent",
                    "evidence_excerpt": "Hermes Agent",
                    "source_url": "https://example.com/hermes-agent",
                },
                {
                    "category": "products_modules",
                    "fact_type": "page_claim",
                    "value": "An autonomous agent that lives on your server.",
                    "evidence_excerpt": "An autonomous agent that lives on your server.",
                    "source_url": "https://example.com/hermes-agent",
                },
                {
                    "category": "products_modules",
                    "fact_type": "page_claim",
                    "value": "Persistent memory that learns your projects.",
                    "evidence_excerpt": "Persistent memory that learns your projects.",
                    "source_url": "https://example.com/hermes-agent",
                },
                {
                    "category": "products_modules",
                    "fact_type": "page_claim",
                    "value": "Natural language scheduling runs automations unattended.",
                    "evidence_excerpt": "Natural language scheduling runs automations unattended.",
                    "source_url": "https://example.com/hermes-agent",
                },
            ]
        )
    ]
    profile = build_competitor_profile("example.com", results)
    business_profile = build_normalized_business_profile("example.com", results)

    report = build_executive_report("example.com", results, profile, business_profile)

    offer = next(section for section in report.sections if section.title == "What they offer")
    assert any(
        all(
            term in point.text.casefold()
            for term in ("autonomous agent", "self-hosted", "memory", "automation")
        )
        for point in offer.points
    )


def test_executive_report_synthesizes_contact_latex_wet_and_dry_grip():
    results = [
        _result(
            [
                {
                    "category": "products_modules",
                    "fact_type": "page_claim",
                    "value": "The Grip: 4mm German Contact Latex.",
                    "evidence_excerpt": "The Grip: 4mm German Contact Latex.",
                    "source_url": "https://example.com/products/glove",
                },
                {
                    "category": "products_modules",
                    "fact_type": "page_claim",
                    "value": "Dry Weather: highest level of grip available.",
                    "evidence_excerpt": "Dry Weather: highest level of grip available.",
                    "source_url": "https://example.com/products/glove",
                },
                {
                    "category": "products_modules",
                    "fact_type": "page_claim",
                    "value": "Wet Weather: performs exceptionally well in the rain.",
                    "evidence_excerpt": "Wet Weather: performs exceptionally well in the rain.",
                    "source_url": "https://example.com/products/glove",
                },
            ]
        )
    ]
    profile = build_competitor_profile("example.com", results)
    business_profile = build_normalized_business_profile("example.com", results)

    report = build_executive_report("example.com", results, profile, business_profile)

    standout = next(section for section in report.sections if section.title == "What stands out")
    assert any(
        all(term in point.text.casefold() for term in ("contact latex", "wet", "dry", "grip"))
        for point in standout.points
    )
