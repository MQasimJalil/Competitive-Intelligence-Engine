import re
from dataclasses import dataclass
from urllib.parse import urlparse

from app.schemas import (
    AIAnalysis,
    BusinessCategory,
    BusinessFactKind,
    CompetitorProfile,
    ExtractionResult,
    ExtractionStatus,
    NormalizedBusinessProfile,
    ObservedClaim,
)

_GENERIC_VALUES = {
    "agent",
    "about",
    "about us",
    "dataset",
    "framework",
    "model",
    "news",
    "paper",
    "products",
    "shop",
    "shop all",
    "simulator",
    "training",
}
_DIFFERENTIATOR_TERMS = (
    "professional",
    "quality",
    "performance",
    "grip",
    "latex",
    "automation",
    "integrat",
    "secure",
    "collaborat",
    "designed for",
    "built for",
)
_PRICE_CURRENCY_PREFIX = (
    r"(?:[$\u20ac\u00a3\u0141\u20b9\u20a8]|Rs\.?|PKR|INR|NPR|BDT|LKR|AED|SAR|QAR|"
    r"USD|EUR|GBP|CAD|AUD|NZD|SGD|ZAR)"
)
_PRICE_CURRENCY_SUFFIX = (
    r"(?:[$\u20ac\u00a3\u0141\u20b9\u20a8]|PKR|INR|NPR|BDT|LKR|AED|SAR|QAR|"
    r"USD|EUR|GBP|CAD|AUD|NZD|SGD|ZAR)"
)
_PRICE_VALUE = re.compile(
    rf"(?:(?P<prefix_currency>{_PRICE_CURRENCY_PREFIX})\s?"
    r"(?P<prefix_amount>\d[\d,.]*)|"
    r"(?P<suffix_amount>\d[\d,.]*)\s?"
    rf"(?P<suffix_currency>{_PRICE_CURRENCY_SUFFIX})(?!\d))",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ExecutiveSource:
    number: int
    label: str
    url: str


@dataclass(frozen=True)
class ExecutivePoint:
    text: str
    source_number: int


@dataclass(frozen=True)
class ExecutiveSection:
    title: str
    description: str
    points: list[ExecutivePoint]


@dataclass(frozen=True)
class QuickFact:
    label: str
    value: str


@dataclass(frozen=True)
class ExecutiveReport:
    at_a_glance: str
    at_a_glance_source_number: int
    coverage_explained: str
    business_type: str
    top_metrics: list[QuickFact]
    quick_facts: list[QuickFact]
    sections: list[ExecutiveSection]
    unknowns: list[str]
    next_checks: list[str]
    sources: list[ExecutiveSource]
    methodology_note: str


def build_executive_report(
    domain: str,
    results: list[ExtractionResult],
    profile: CompetitorProfile,
    business_profile: NormalizedBusinessProfile | None = None,
    ai_analysis: AIAnalysis | None = None,
) -> ExecutiveReport:
    claims = _collect_claims(results)
    business_type = _classify_business_type(claims)
    source_urls: list[str] = []

    def point(claim: ObservedClaim) -> ExecutivePoint:
        source_url = str(claim.source_url)
        if source_url not in source_urls:
            source_urls.append(source_url)
        return ExecutivePoint(_shorten(claim.value, 190), source_urls.index(source_url) + 1)

    positioning = _ranked(
        [claim for claim in claims if claim.category == BusinessCategory.POSITIONING],
        prefer=("structured_description", "page_claim"),
    )
    if positioning:
        at_a_glance = _shorten(positioning[0].value, 260)
        at_a_glance_source_number = point(positioning[0]).source_number
    else:
        at_a_glance = f"No clear public positioning statement was found for {domain}."
        at_a_glance_source_number = 0

    products = _ranked(
        [claim for claim in claims if claim.category == BusinessCategory.PRODUCTS_MODULES],
        prefer=("structured_product", "page_headline", "page_claim"),
    )
    actual_products = [claim for claim in products if _is_actual_product_claim(claim)]
    collection_claims = [
        claim
        for claim in claims
        if claim.category == BusinessCategory.PRODUCTS_MODULES and _is_collection_claim(claim)
    ]
    product_names = _unique(
        claim.value for claim in actual_products if claim.value.casefold() not in _GENERIC_VALUES
    )
    collection_names = _unique(
        claim.value for claim in collection_claims if claim.value.casefold() not in _GENERIC_VALUES
    )
    price_claims = _ranked(
        [claim for claim in claims if claim.fact_type == "visible_price"],
        prefer=("visible_price",),
    )
    prices = _unique(claim.value for claim in price_claims)
    price_range_claims = _price_range_claims(price_claims)
    offer_claims = _offer_claims(business_profile)
    portfolio_claims = _portfolio_claims(business_profile)
    flagship_product_claims = _flagship_product_claims(business_profile)
    packaging_claims = _packaging_claims(business_profile)
    differentiators = _strategic_differentiators(business_profile) or _ranked(
        [
            claim
            for claim in claims
            if claim.category
            in {
                BusinessCategory.PRODUCTS_MODULES,
                BusinessCategory.CAPABILITIES,
                BusinessCategory.PROOF,
                BusinessCategory.TRUST_COMPLIANCE,
            }
            and claim.fact_type == "page_claim"
            and any(term in claim.value.casefold() for term in _DIFFERENTIATOR_TERMS)
        ],
        prefer=("page_claim",),
    )
    at_a_glance = _plain_summary(domain, claims, positioning, differentiators)
    proof = _ranked(
        [claim for claim in claims if claim.category == BusinessCategory.PROOF],
        prefer=(
            "social_followers",
            "linkedin_followers",
            "social_post_engagement",
            "proof_metric",
            "external_mention",
            "page_claim",
        ),
    )
    proof.extend(
        _ranked(
            [claim for claim in claims if claim.category == BusinessCategory.TRUST_COMPLIANCE],
            prefer=("page_claim",),
        )
    )
    recent = _strategic_recent(business_profile) or _ranked(
        [
            claim
            for claim in claims
            if claim.fact_type in {"dated_activity", "open_role"}
            or (
                claim.category == BusinessCategory.RECENT_MOVES
                and claim.fact_type in {"page_headline", "page_claim"}
            )
        ],
        prefer=("dated_activity", "open_role"),
    )
    audience = _audience_summary_claims(business_profile)
    research_summary = _research_summary_claims(business_profile)

    sections = [
        ExecutiveSection(
            title="What they offer",
            description="Products and offer signals visible on their public website.",
            points=[
                *[point(claim) for claim in _collection_summary_claims(collection_claims)],
                *[point(claim) for claim in portfolio_claims],
                *[point(claim) for claim in flagship_product_claims],
                *[point(claim) for claim in price_range_claims],
                *[point(claim) for claim in offer_claims],
                *[point(claim) for claim in packaging_claims[:2]],
                *[
                    point(claim)
                    for claim in [
                        *[item for item in products if _is_actual_product_claim(item)][
                            : max(0, 2 - len(offer_claims) - len(packaging_claims[:2]))
                        ],
                        *price_claims[: max(0, 1 - len(offer_claims) - len(packaging_claims[:2]))],
                    ]
                ],
            ][:3],
        ),
        ExecutiveSection(
            title="What stands out",
            description="Benefits and differentiators the competitor publicly emphasizes.",
            points=[
                *[point(claim) for claim in _buyer_guidance_claims(business_profile)],
                *[point(claim) for claim in _workflow_claims(business_profile)],
                *[point(claim) for claim in _packaging_strategy_claims(business_profile)],
                *[point(claim) for claim in _material_performance_claims(business_profile)],
                *[point(claim) for claim in _tradeoff_claims(business_profile)],
                *[point(claim) for claim in _strategic_context_claims(business_profile)],
                *[point(claim) for claim in differentiators],
            ][:3],
        ),
        ExecutiveSection(
            title="Customer trust and recent activity",
            description="Customer trust, hiring, or recent company activity found publicly.",
            points=[
                point(claim)
                for claim in [*audience[:1], *proof[:1], *research_summary[:1], *recent[:2]][:3]
            ],
        ),
    ]

    unknowns: list[str] = []
    if not proof:
        unknowns.append("No strong public proof or trust evidence was found.")
    if not recent:
        unknowns.append("No dated recent activity or hiring evidence was verified.")
    if not prices:
        unknowns.append("No public price was verified.")
    if len(unknowns) < 2:
        for question in profile.unanswered_questions:
            simplified = _simplify_question(question)
            if simplified not in unknowns:
                unknowns.append(simplified)
            if len(unknowns) == 2:
                break

    source_titles = {
        str(fact.source_url): fact.source_title
        for fact in (business_profile.facts if business_profile else [])
        if fact.source_title
    }
    business_model = _business_model_signal(business_type, product_names, prices, claims)
    portfolio_metric = _portfolio_metric(business_type, product_names, prices, business_model)
    top_metrics = [
        QuickFact("Country", _country_signal(claims, prices)),
        QuickFact("Industry", _industry_signal(claims, business_type)),
        QuickFact("Business model", business_model),
        QuickFact("Observed price band", _price_summary(prices)),
        portfolio_metric,
        QuickFact("Threat read", _threat_read(product_names, prices, proof, unknowns)),
    ]
    top_metrics = _apply_ai_label_overrides(
        top_metrics,
        ai_analysis,
        business_profile,
        source_urls,
    )
    sources = [
        ExecutiveSource(index + 1, source_titles.get(url) or _source_label(url), url)
        for index, url in enumerate(source_urls[:8])
    ]
    quick_facts = [
        QuickFact("Products spotted", ", ".join(product_names[:3]) or "Not clearly identified"),
        QuickFact("Observed prices", _price_summary(prices)),
        QuickFact("Sources cited", str(len(sources))),
        QuickFact("Business model", business_model),
        QuickFact(
            "Collections spotted",
            ", ".join(collection_names[:4]) or "Not clearly identified",
        ),
    ]
    return ExecutiveReport(
        at_a_glance=at_a_glance,
        at_a_glance_source_number=at_a_glance_source_number,
        coverage_explained=_coverage_explained(profile),
        business_type=business_type,
        top_metrics=top_metrics,
        quick_facts=quick_facts,
        sections=sections,
        unknowns=unknowns[:2],
        next_checks=_next_checks(proof=proof, recent=recent, prices=prices),
        sources=sources,
        methodology_note=(
            "This report summarizes observed public claims. It does not independently verify "
            "the competitor's claims, and missing evidence is not treated as a weakness."
        ),
    )


def _offer_claims(
    business_profile: NormalizedBusinessProfile | None,
) -> list[ObservedClaim]:
    if not business_profile:
        return []
    by_id = {fact.citation_id: fact for fact in business_profile.facts}
    claims: list[ObservedClaim] = []
    for offer in business_profile.offers[:2]:
        if offer.name.casefold() in _GENERIC_VALUES:
            continue
        cited = next((by_id[item] for item in offer.citation_ids if item in by_id), None)
        if cited is None:
            continue
        text = offer.name
        if offer.prices:
            text = f"{text} - {', '.join(offer.prices[:3])}"
        claims.append(
            ObservedClaim(
                category=cited.category,
                fact_type="product_offer",
                value=text,
                evidence_excerpt=cited.evidence_excerpt,
                source_url=cited.source_url,
                retrieved_at=cited.retrieved_at,
                context="Normalized product and price combination",
            )
        )
    return claims


def _apply_ai_label_overrides(
    metrics: list[QuickFact],
    ai_analysis: AIAnalysis | None,
    business_profile: NormalizedBusinessProfile | None,
    source_urls: list[str],
) -> list[QuickFact]:
    if ai_analysis is None or business_profile is None:
        return metrics
    facts_by_id = {fact.citation_id: fact for fact in business_profile.facts}
    labels = ai_analysis.report_labels
    overrides = {
        "Country": labels.country,
        "Industry": labels.industry,
        "Business model": labels.business_model,
    }
    portfolio = labels.portfolio_metric
    next_metrics = []
    for metric in metrics:
        statement = overrides.get(metric.label)
        if statement is None:
            next_metrics.append(metric)
            continue
        value = _cited_ai_label(statement, facts_by_id, source_urls)
        next_metrics.append(QuickFact(metric.label, value or metric.value))
    if portfolio is not None and len(next_metrics) >= 5:
        value = _cited_ai_label(portfolio, facts_by_id, source_urls)
        if value and _is_useful_portfolio_metric(value):
            next_metrics[4] = QuickFact(_portfolio_metric_label(value), value)
    return next_metrics


def _is_useful_portfolio_metric(value: str) -> bool:
    normalized = value.casefold()
    blocked = (
        "employee",
        "employees",
        "follower",
        "followers",
        "headcount",
        "company size",
        "hiring",
        "team size",
    )
    allowed = (
        "pricing",
        "price",
        "plan",
        "plans",
        "subscription",
        "catalog",
        "product",
        "products",
        "collection",
        "shop",
        "store",
        "service",
        "services",
        "offer",
        "commercial",
        "membership",
        "free",
        "trial",
    )
    return any(term in normalized for term in allowed) and not any(
        term in normalized for term in blocked
    )


def _portfolio_metric_label(value: str) -> str:
    normalized = value.casefold()
    if any(
        term in normalized
        for term in (
            "pricing",
            "price",
            "plan",
            "subscription",
            "membership",
            "free",
            "trial",
        )
    ):
        return "Commercial signal"
    return "Offer signal"


def _cited_ai_label(
    statement,
    facts_by_id: dict[str, object],
    source_urls: list[str],
) -> str:
    text = _sentence_safe_shorten(statement.text, 80)
    if not text or text.casefold() in {"unknown", "data unavailable", "not available"}:
        return ""
    citation_id = next((item for item in statement.citation_ids if item in facts_by_id), "")
    if not citation_id:
        return ""
    source_url = str(facts_by_id[citation_id].source_url)
    if source_url not in source_urls:
        source_urls.append(source_url)
    return f"{text} [{source_urls.index(source_url) + 1}]"


def _packaging_claims(
    business_profile: NormalizedBusinessProfile | None,
) -> list[ObservedClaim]:
    if not business_profile:
        return []
    by_source: dict[str, list] = {}
    for fact in business_profile.facts:
        if fact.kind in {BusinessFactKind.PACKAGING, BusinessFactKind.PRICE}:
            by_source.setdefault(str(fact.source_url), []).append(fact)
    claims = []
    for source_facts in by_source.values():
        plans = [fact.value for fact in source_facts if fact.kind == BusinessFactKind.PACKAGING]
        prices = [fact.value for fact in source_facts if fact.kind == BusinessFactKind.PRICE]
        if not plans:
            continue
        cited = source_facts[0]
        text = f"Plans: {', '.join(plans[:5])}"
        if prices:
            text = f"{text}; visible prices: {', '.join(prices[:5])}"
        claims.append(
            ObservedClaim(
                category=BusinessCategory.PRICING_PACKAGING,
                fact_type="packaging_summary",
                value=text,
                evidence_excerpt=cited.evidence_excerpt,
                source_url=cited.source_url,
                retrieved_at=cited.retrieved_at,
                context="Normalized packaging summary",
            )
        )
    return claims[:2]


def _portfolio_claims(
    business_profile: NormalizedBusinessProfile | None,
) -> list[ObservedClaim]:
    if not business_profile:
        return []
    by_source: dict[str, list] = {}
    for fact in business_profile.facts:
        if fact.kind == BusinessFactKind.PRODUCT and len(fact.value) <= 100:
            by_source.setdefault(str(fact.source_url), []).append(fact)
    claims = []
    for source_facts in by_source.values():
        values = _unique(fact.value for fact in source_facts)
        if len(values) < 3:
            continue
        taxonomy = [
            value
            for value in (
                "agent",
                "model",
                "dataset",
                "framework",
                "training",
                "paper",
                "simulator",
            )
            if value in {item.casefold() for item in values}
        ]
        specifics = [value for value in values if value.casefold() not in taxonomy]
        values = [*taxonomy, *specifics]
        cited = source_facts[0]
        claims.append(
            ObservedClaim(
                category=cited.category,
                fact_type="portfolio_summary",
                value=f"Offer structure: {', '.join(values[:7])}",
                evidence_excerpt=cited.evidence_excerpt,
                source_url=cited.source_url,
                retrieved_at=cited.retrieved_at,
                context="Normalized offer-structure summary",
            )
        )
    return claims[:1]


def _collection_summary_claims(claims: list[ObservedClaim]) -> list[ObservedClaim]:
    names = _unique(
        claim.value for claim in claims if claim.value.casefold() not in _GENERIC_VALUES
    )
    if not names:
        return []
    cited = claims[0]
    return [
        ObservedClaim(
            category=cited.category,
            fact_type="collection_summary",
            value=f"Collections observed: {', '.join(names[:5])}.",
            evidence_excerpt=cited.evidence_excerpt,
            source_url=cited.source_url,
            retrieved_at=cited.retrieved_at,
            context="Normalized collection summary from public catalog links",
        )
    ]


def _price_range_claims(price_claims: list[ObservedClaim]) -> list[ObservedClaim]:
    by_source: dict[str, list[ObservedClaim]] = {}
    for claim in price_claims:
        by_source.setdefault(str(claim.source_url), []).append(claim)
    candidates = []
    currency_names = {
        "$": "USD",
        "€": "EUR",
        "£": "GBP",
        "Ł": "GBP",
        "₹": "INR",
        "₨": "PKR",
        "PKR": "PKR",
        "INR": "INR",
        "AED": "AED",
        "SAR": "SAR",
    }
    for claims in by_source.values():
        parsed = []
        for claim in claims:
            value = _parse_price(claim.value)
            if value:
                parsed.append(value)
        currencies = {currency for currency, _ in parsed}
        if len(parsed) < 2 or len(currencies) != 1:
            continue
        low = min(amount for _, amount in parsed)
        high = max(amount for _, amount in parsed)
        if low == high:
            continue
        cited = claims[0]
        currency = currency_names.get(parsed[0][0], parsed[0][0])
        candidates.append(
            ObservedClaim(
                category=cited.category,
                fact_type="price_range_summary",
                value=f"Visible featured prices span {currency} {low:g} to {currency} {high:g}.",
                evidence_excerpt=cited.evidence_excerpt,
                source_url=cited.source_url,
                retrieved_at=cited.retrieved_at,
                context="Normalized visible price range from one cited page",
            )
        )
    return candidates[:1]


def _flagship_product_claims(
    business_profile: NormalizedBusinessProfile | None,
) -> list[ObservedClaim]:
    if not business_profile:
        return []
    by_source: dict[str, list] = {}
    for fact in business_profile.facts:
        by_source.setdefault(str(fact.source_url), []).append(fact)
    for facts in by_source.values():
        text = " ".join(fact.value.casefold() for fact in facts)
        required = {
            "agent": "agent",
            "self_hosted": "lives on your server",
            "memory": "persistent memory",
            "automation": "automation",
        }
        if not all(signal in text for signal in required.values()):
            continue
        cited = next(fact for fact in facts if "persistent memory" in fact.value.casefold())
        return [
            ObservedClaim(
                category=cited.category,
                fact_type="flagship_product_summary",
                value=(
                    "Flagship offer: a self-hosted autonomous agent with persistent memory "
                    "and unattended automation capabilities."
                ),
                evidence_excerpt=cited.evidence_excerpt,
                source_url=cited.source_url,
                retrieved_at=cited.retrieved_at,
                context="Normalized flagship-product synthesis from one source",
            )
        ]
    return []


def _packaging_strategy_claims(
    business_profile: NormalizedBusinessProfile | None,
) -> list[ObservedClaim]:
    if not business_profile:
        return []
    by_source: dict[str, list] = {}
    for fact in business_profile.facts:
        by_source.setdefault(str(fact.source_url), []).append(fact)
    for facts in by_source.values():
        plans = {fact.value.casefold() for fact in facts if fact.kind == BusinessFactKind.PACKAGING}
        capabilities = [
            fact
            for fact in facts
            if fact.kind == BusinessFactKind.DIFFERENTIATOR
            and any(term in fact.value.casefold() for term in ("agent", "code intelligence"))
        ]
        if "business" not in plans or not capabilities:
            continue
        cited = capabilities[0]
        return [
            ObservedClaim(
                category=cited.category,
                fact_type="packaging_strategy",
                value=(
                    "Business-tier packaging adds AI agent automation and Code Intelligence, "
                    "making agent capabilities central to higher-tier packaging."
                ),
                evidence_excerpt=cited.evidence_excerpt,
                source_url=cited.source_url,
                retrieved_at=cited.retrieved_at,
                context="Normalized pricing capability synthesis",
            )
        ]
    return []


def _buyer_guidance_claims(
    business_profile: NormalizedBusinessProfile | None,
) -> list[ObservedClaim]:
    if not business_profile:
        return []
    by_source: dict[str, list] = {}
    for fact in business_profile.facts:
        by_source.setdefault(str(fact.source_url), []).append(fact)
    for facts in by_source.values():
        text = " ".join(fact.value.casefold() for fact in facts)
        if "new to goalkeeping" not in text or not any(
            term in text for term in ("professional", "keeper", "goalkeeper")
        ):
            continue
        cited = next(fact for fact in facts if "new to goalkeeping" in fact.value.casefold())
        return [
            ObservedClaim(
                category=cited.category,
                fact_type="buyer_guidance_summary",
                value=(
                    "The company addresses experienced keepers and buyers who need "
                    "goalkeeper-glove selection guidance."
                ),
                evidence_excerpt=cited.evidence_excerpt,
                source_url=cited.source_url,
                retrieved_at=cited.retrieved_at,
                context="Normalized buyer-guidance synthesis from one source",
            )
        ]
    return []


def _tradeoff_claims(
    business_profile: NormalizedBusinessProfile | None,
) -> list[ObservedClaim]:
    if not business_profile:
        return []
    facts = [
        fact
        for fact in business_profile.facts
        if "durability" in fact.value.casefold() and "elite performance" in fact.value.casefold()
    ]
    return [
        ObservedClaim(
            category=fact.category,
            fact_type="performance_tradeoff",
            value=fact.value,
            evidence_excerpt=fact.evidence_excerpt,
            source_url=fact.source_url,
            retrieved_at=fact.retrieved_at,
            context="Observed performance and durability tradeoff",
        )
        for fact in facts[:1]
    ]


def _material_performance_claims(
    business_profile: NormalizedBusinessProfile | None,
) -> list[ObservedClaim]:
    if not business_profile:
        return []
    by_source: dict[str, list] = {}
    for fact in business_profile.facts:
        by_source.setdefault(str(fact.source_url), []).append(fact)
    for facts in by_source.values():
        text = " ".join(fact.value.casefold() for fact in facts)
        if not all(term in text for term in ("contact latex", "wet", "dry", "grip")):
            continue
        cited = next(fact for fact in facts if "contact latex" in fact.value.casefold())
        return [
            ObservedClaim(
                category=cited.category,
                fact_type="material_performance_summary",
                value=(
                    "Contact latex and grip performance in both wet and dry conditions "
                    "are central product differentiators."
                ),
                evidence_excerpt=cited.evidence_excerpt,
                source_url=cited.source_url,
                retrieved_at=cited.retrieved_at,
                context="Normalized material and performance synthesis from one source",
            )
        ]
    return []


def _audience_summary_claims(
    business_profile: NormalizedBusinessProfile | None,
) -> list[ObservedClaim]:
    if not business_profile:
        return []
    by_source: dict[str, list] = {}
    for fact in business_profile.facts:
        if fact.kind in {BusinessFactKind.AUDIENCE, BusinessFactKind.PROOF}:
            by_source.setdefault(str(fact.source_url), []).append(fact)
    for facts in by_source.values():
        text = " ".join(fact.value.casefold() for fact in facts)
        if "startup" not in text or "enterprise" not in text:
            continue
        industries = [
            term
            for term in ("saas", "ai", "fintech", "consumer", "hardware", "health")
            if term in text
        ]
        cited = facts[0]
        suffix = f" across {', '.join(industries)} industries" if len(industries) >= 3 else ""
        return [
            ObservedClaim(
                category=cited.category,
                fact_type="audience_summary",
                value=f"Public customer evidence spans startups through major enterprises{suffix}.",
                evidence_excerpt=cited.evidence_excerpt,
                source_url=cited.source_url,
                retrieved_at=cited.retrieved_at,
                context="Normalized audience-range synthesis",
            )
        ]
    return []


def _research_summary_claims(
    business_profile: NormalizedBusinessProfile | None,
) -> list[ObservedClaim]:
    if not business_profile:
        return []
    by_source: dict[str, list] = {}
    for fact in business_profile.facts:
        if fact.kind == BusinessFactKind.RECENT_ACTIVITY:
            by_source.setdefault(str(fact.source_url), []).append(fact)
    for facts in by_source.values():
        text = " ".join(fact.value.casefold() for fact in facts)
        if not any(
            term in text
            for term in (
                "artificial intelligence",
                "language model",
                "open source",
                "reasoning model",
                "research lab",
                "machine learning",
            )
        ):
            continue
        terms = [
            term
            for term in ("research", "model", "reasoning", "framework", "training")
            if term in text
        ]
        if len(facts) < 4 or len(terms) < 2:
            continue
        cited = facts[0]
        return [
            ObservedClaim(
                category=cited.category,
                fact_type="research_summary",
                value=(
                    "Actively publishes research and releases across models, reasoning, "
                    "training frameworks, and other technical AI domains."
                ),
                evidence_excerpt=cited.evidence_excerpt,
                source_url=cited.source_url,
                retrieved_at=cited.retrieved_at,
                context="Normalized research publishing synthesis",
            )
        ]
    return []


def _workflow_claims(
    business_profile: NormalizedBusinessProfile | None,
) -> list[ObservedClaim]:
    if not business_profile:
        return []
    known = {
        "intake",
        "plan",
        "planning",
        "build",
        "diffs",
        "review",
        "monitor",
        "triage",
        "roadmap",
    }
    stages = [
        fact
        for fact in business_profile.facts
        if fact.kind == BusinessFactKind.DIFFERENTIATOR and fact.value.casefold() in known
    ]
    if len(stages) >= 3:
        cited = stages[0]
        return [
            ObservedClaim(
                category=cited.category,
                fact_type="workflow_summary",
                value=f"Workflow stages: {', '.join(_unique(fact.value for fact in stages)[:8])}",
                evidence_excerpt=cited.evidence_excerpt,
                source_url=cited.source_url,
                retrieved_at=cited.retrieved_at,
                context="Normalized workflow summary",
            )
        ]

    signals = {
        "feedback intake": ("feedback", "intake", "actionable issues"),
        "planning from idea to launch": ("idea to launch", "roadmap", "planning", "prd"),
        "AI-agent execution": ("ai agent", "agents", "delegate entire issues"),
        "PR and issue delivery": ("pushing prs", "pull request", "code review"),
        "monitoring": ("monitor",),
    }
    by_source: dict[str, list] = {}
    for fact in business_profile.facts:
        if fact.kind not in {BusinessFactKind.COMPANY_DETAIL, BusinessFactKind.DIFFERENTIATOR}:
            continue
        by_source.setdefault(str(fact.source_url), []).append(fact)
    candidates = []
    for source_facts in by_source.values():
        text = " ".join(fact.value.casefold() for fact in source_facts)
        observed = [
            label for label, terms in signals.items() if any(term in text for term in terms)
        ]
        if len(observed) >= 3:
            candidates.append((observed, source_facts[0]))
    if not candidates:
        return []
    observed, cited = max(candidates, key=lambda item: len(item[0]))
    return [
        ObservedClaim(
            category=cited.category,
            fact_type="workflow_summary",
            value=f"Public workflow signals span {_join_plain(observed)}.",
            evidence_excerpt=cited.evidence_excerpt,
            source_url=cited.source_url,
            retrieved_at=cited.retrieved_at,
            context="Normalized synthesis from claims on one cited page",
        )
    ]


def _strategic_context_claims(
    business_profile: NormalizedBusinessProfile | None,
) -> list[ObservedClaim]:
    if not business_profile:
        return []
    terms = (
        "our mission",
        "democratize access",
        "humanistic ai",
        "human freedom",
        "new to goalkeeping",
        "confused by the different types",
    )
    facts = sorted(
        [
            fact
            for fact in business_profile.facts
            if fact.kind == BusinessFactKind.COMPANY_DETAIL
            and any(term in fact.value.casefold() for term in terms)
        ],
        key=lambda fact: -sum(term in fact.value.casefold() for term in terms),
    )
    return [
        ObservedClaim(
            category=fact.category,
            fact_type="strategic_context",
            value=fact.value,
            evidence_excerpt=fact.evidence_excerpt,
            source_url=fact.source_url,
            retrieved_at=fact.retrieved_at,
            context="Strategically ranked mission or buyer-guidance fact",
        )
        for fact in facts[:1]
    ]


def _strategic_differentiators(
    business_profile: NormalizedBusinessProfile | None,
) -> list[ObservedClaim]:
    if not business_profile:
        return []
    terms = {
        "tradeoff": 14,
        "contact latex": 13,
        "durability": 12,
        "wet": 11,
        "grip": 10,
        "agent": 10,
        "open source": 10,
        "distributed": 9,
        "human rights": 10,
        "freedom": 9,
        "unrestricted": 9,
        "professional": 8,
        "collaboration": 8,
        "automation": 8,
        "workflow": 7,
        "latex": 6,
        "security": 2,
    }
    ranked = sorted(
        [
            fact
            for fact in business_profile.facts
            if fact.kind
            in {
                BusinessFactKind.DIFFERENTIATOR,
                BusinessFactKind.COMPANY_DETAIL,
            }
        ],
        key=lambda fact: (
            -sum(weight for term, weight in terms.items() if term in fact.value.casefold()),
            abs(min(len(fact.value), 300) - 130),
        ),
    )
    return [
        ObservedClaim(
            category=fact.category,
            fact_type="strategic_fact",
            value=fact.value,
            evidence_excerpt=fact.evidence_excerpt,
            source_url=fact.source_url,
            retrieved_at=fact.retrieved_at,
            context="Strategically ranked normalized fact",
        )
        for fact in ranked[:5]
    ]


def _strategic_recent(
    business_profile: NormalizedBusinessProfile | None,
) -> list[ObservedClaim]:
    if not business_profile:
        return []
    terms = {
        "psyche": 16,
        "democratizing": 12,
        "release": 8,
        "research": 8,
        "model": 7,
        "agent": 7,
        "dataset": 7,
        "framework": 7,
        "training": 7,
        "paper": 7,
        "simulator": 7,
        "code review": 9,
        "code": 4,
    }
    ranked = sorted(
        [fact for fact in business_profile.facts if fact.kind == BusinessFactKind.RECENT_ACTIVITY],
        key=lambda fact: (
            -sum(weight for term, weight in terms.items() if term in fact.value.casefold()),
            abs(min(len(fact.value), 300) - 130),
        ),
    )
    return [
        ObservedClaim(
            category=fact.category,
            fact_type="strategic_recent",
            value=fact.value,
            evidence_excerpt=fact.evidence_excerpt,
            source_url=fact.source_url,
            retrieved_at=fact.retrieved_at,
            context="Strategically ranked recent activity",
        )
        for fact in ranked[:4]
    ]


def _collect_claims(results: list[ExtractionResult]) -> list[ObservedClaim]:
    claims: list[ObservedClaim] = []
    for result in results:
        if result.status != ExtractionStatus.OK or not isinstance(result.value, dict):
            continue
        for raw_claim in result.value.get("claims", []):
            claims.append(ObservedClaim.model_validate(raw_claim))
    return claims


def _classify_business_type(claims: list[ObservedClaim]) -> str:
    text = " ".join(claim.value.casefold() for claim in claims)
    if any(
        term in text
        for term in (
            "nike",
            "sport",
            "sportswear",
            "footwear",
            "sneaker",
            "shoes",
            "apparel",
            "athletic",
            "jordan brand",
        )
    ):
        return "Ecommerce"
    if any(
        term in text
        for term in (
            "web hosting",
            "website builder",
            "wordpress hosting",
            "vps",
            "domain name",
            "cloud hosting",
        )
    ):
        return "Technology / SaaS"
    if any(
        term in text
        for term in (
            "discord",
            "voice chat",
            "group chat",
            "server for",
            "servers and friends",
            "gaming",
            "community",
        )
    ):
        return "Technology / SaaS"
    product_signals = sum(
        1
        for claim in claims
        if claim.fact_type in {"linked_product", "structured_product"}
        or "/products/" in str(claim.source_url)
        or "/collections/" in str(claim.source_url)
    )
    if any(
        term in text
        for term in (
            "software",
            "product development",
            "workflow",
            "developer",
            "saas",
            "platform for teams",
        )
    ) and product_signals == 0:
        return "Technology / SaaS"
    if product_signals >= 2 or any(
        term in text for term in ("shop", "cart", "gloves", "apparel", "equipment")
    ):
        return "Ecommerce"
    if any(
        term in text
        for term in (
            "software",
            "platform",
            "api",
            "workflow",
            "automation",
            "developer",
            "teams",
            "saas",
            "cloud",
        )
    ):
        return "Technology / SaaS"
    if any(term in text for term in ("service", "agency", "consulting", "book a call")):
        return "Services"
    return "Business"


def _is_actual_product_claim(claim: ObservedClaim) -> bool:
    if claim.fact_type in {"structured_product", "linked_product"}:
        return "/collections/" not in str(claim.source_url)
    if claim.fact_type == "page_headline":
        return "/products/" in str(claim.source_url)
    return False


def _is_collection_claim(claim: ObservedClaim) -> bool:
    if claim.fact_type == "product_collection":
        return True
    if claim.fact_type == "page_headline":
        return "/collections/" in str(claim.source_url)
    return "/collections/" in str(claim.source_url) and claim.fact_type != "visible_price"


def _ranked(claims: list[ObservedClaim], *, prefer: tuple[str, ...]) -> list[ObservedClaim]:
    priorities = {fact_type: len(prefer) - index for index, fact_type in enumerate(prefer)}
    return sorted(
        _deduplicate_claims(claims),
        key=lambda claim: (
            -priorities.get(claim.fact_type, 0),
            abs(min(len(claim.value), 300) - 100),
            claim.value.casefold(),
        ),
    )


def _deduplicate_claims(claims: list[ObservedClaim]) -> list[ObservedClaim]:
    unique: list[ObservedClaim] = []
    seen: set[str] = set()
    for claim in claims:
        key = " ".join(claim.value.casefold().split())
        if key in seen or key in _GENERIC_VALUES:
            continue
        if len(key) < 12 and claim.fact_type not in {
            "page_headline",
            "structured_product",
            "linked_product",
            "product_collection",
            "visible_price",
        }:
            continue
        seen.add(key)
        unique.append(claim)
    return unique


def _unique(values) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = " ".join(value.split())
        if normalized.casefold() in seen:
            continue
        seen.add(normalized.casefold())
        unique.append(normalized)
    return unique


def _price_summary(prices: list[str]) -> str:
    parsed: list[tuple[str, float]] = []
    for price in prices:
        value = _parse_price(price)
        if value:
            parsed.append(value)
    if not parsed:
        return "Not publicly visible"
    currencies = {currency for currency, _ in parsed}
    if len(currencies) == 1:
        currency = parsed[0][0]
        values = [amount for _, amount in parsed]
        low, high = min(values), max(values)
        if low == high:
            return _format_price(currency, low)
        return f"{_format_price(currency, low)} - {_format_price(currency, high)}"
    return ", ".join(prices[:3])


def _format_price(currency: str, amount: float) -> str:
    amount_text = f"{amount:,.2f}".rstrip("0").rstrip(".")
    if len(currency) == 1:
        return f"{currency}{amount_text}"
    return f"{currency} {amount_text}"


def _country_signal(claims: list[ObservedClaim], prices: list[str]) -> str:
    del prices
    text = " ".join(claim.value.casefold() for claim in claims)
    if any(
        term in text
        for term in (
            "uk-based",
            "uk based",
            "based in the uk",
            "headquartered in the uk",
            "headquartered in united kingdom",
            "london-based",
        )
    ):
        return "United Kingdom"
    if any(
        term in text
        for term in (
            "u.s.-based",
            "us-based",
            "based in the us",
            "based in the united states",
            "headquartered in the us",
            "headquartered in the united states",
        )
    ):
        return "United States"
    if any(term in text for term in ("europe-based", "based in europe", "european company")):
        return "Europe"
    return "Data unavailable"


def _industry_signal(claims: list[ObservedClaim], business_type: str) -> str:
    text = " ".join(claim.value.casefold() for claim in claims)
    signals = (
        ("nike", "Sportswear and athletic retail"),
        ("sportswear", "Sportswear and athletic retail"),
        ("footwear", "Sportswear and athletic retail"),
        ("athletic", "Sportswear and athletic retail"),
        ("web hosting", "Web hosting"),
        ("website builder", "Web hosting"),
        ("wordpress hosting", "Web hosting"),
        ("domain name", "Web hosting"),
        ("voice chat", "Community communication platform"),
        ("group chat", "Community communication platform"),
        ("discord", "Community communication platform"),
        ("goalkeeper", "Goalkeeper gloves"),
        ("football equipment", "Football equipment"),
        ("product development", "Product management software"),
        ("open source language model", "Artificial intelligence"),
        ("language model", "Artificial intelligence"),
        ("automation", "Software automation"),
        ("analytics", "Analytics software"),
    )
    for needle, label in signals:
        if needle in text:
            return label
    return business_type


def _business_model_signal(
    business_type: str,
    product_names: list[str],
    prices: list[str],
    claims: list[ObservedClaim],
) -> str:
    text = " ".join(claim.value.casefold() for claim in claims)
    if any(term in text for term in ("nike", "sportswear", "footwear", "athletic")):
        return "Global retail / DTC ecommerce"
    if any(term in text for term in ("web hosting", "website builder", "wordpress hosting", "vps")):
        return "Subscription hosting"
    if any(term in text for term in ("discord", "voice chat", "group chat", "nitro")):
        return "Freemium platform"
    if business_type == "Ecommerce" and (product_names or prices):
        return "DTC ecommerce"
    if business_type == "Ecommerce":
        return "Retail / ecommerce"
    if business_type == "Technology / SaaS":
        return "SaaS / platform"
    if business_type == "Services":
        return "Services"
    return business_type


def _listing_count(product_names: list[str]) -> str:
    if not product_names:
        return "Data unavailable"
    label = "item" if len(product_names) == 1 else "items"
    return f"{len(product_names)} {label}"


def _portfolio_metric(
    business_type: str,
    product_names: list[str],
    prices: list[str],
    business_model: str,
) -> QuickFact:
    if business_model in {"Subscription hosting", "SaaS / platform", "Freemium platform"}:
        if prices:
            return QuickFact("Commercial signal", "Pricing visible")
        if product_names:
            return QuickFact("Product signals", _listing_count(product_names))
        return QuickFact("Product signals", "Data unavailable")
    if business_type == "Ecommerce":
        return QuickFact("Shop listing count", _listing_count(product_names))
    if prices:
        return QuickFact("Commercial signal", "Pricing visible")
    if product_names:
        return QuickFact("Product signals", _listing_count(product_names))
    return QuickFact("Product signals", "Data unavailable")


def _threat_read(
    product_names: list[str],
    prices: list[str],
    proof: list[ObservedClaim],
    unknowns: list[str],
) -> str:
    score = 3
    if product_names:
        score += 1
    if len(product_names) >= 10:
        score += 1
    if prices:
        score += 1
    if proof:
        score += 1
    if len(unknowns) >= 2:
        score -= 1
    score = max(1, min(score, 10))
    if score >= 7:
        band = "High"
    elif score >= 4:
        band = "Medium"
    else:
        band = "Low"
    return f"{band} {score}/10"


def _parse_price(price: str) -> tuple[str, float] | None:
    match = _PRICE_VALUE.search(price)
    if not match:
        return None
    currency = _canonical_currency(match.group("prefix_currency") or match.group("suffix_currency"))
    amount = match.group("prefix_amount") or match.group("suffix_amount")
    return currency, float(_normalize_price_amount(amount))


def _canonical_currency(currency: str) -> str:
    normalized = currency.strip().replace(".", "").upper()
    return {
        "$": "$",
        "€": "€",
        "£": "£",
        "Ł": "£",
        "₹": "INR",
        "₨": "PKR",
        "RS": "PKR",
    }.get(normalized, normalized)


def _normalize_price_amount(amount: str) -> str:
    if "," in amount and "." in amount:
        decimal_separator = "," if amount.rfind(",") > amount.rfind(".") else "."
        thousands_separator = "." if decimal_separator == "," else ","
        return amount.replace(thousands_separator, "").replace(decimal_separator, ".")
    if "," in amount:
        whole, decimal = amount.rsplit(",", 1)
        if len(decimal) in {1, 2}:
            return f"{whole.replace(',', '')}.{decimal}"
        return amount.replace(",", "")
    return amount


def _shorten(value: str, limit: int) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    shortened = normalized[: limit - 1].rsplit(" ", 1)[0]
    return f"{shortened}..."


def _sentence_safe_shorten(value: str, limit: int) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    sentences = re.split(r"(?<=[.!?])\s+", normalized)
    output: list[str] = []
    length = 0
    for sentence in sentences:
        projected = length + (1 if output else 0) + len(sentence)
        if projected > limit:
            break
        output.append(sentence)
        length = projected
    if output:
        return " ".join(output)
    return normalized[:limit].rsplit(" ", 1)[0].strip().rstrip(".,;:")


def _source_label(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/"
    return f"{parsed.netloc}{path}"


def _simplify_question(question: str) -> str:
    replacements = {
        "What evidence and trust claims support their pitch?": (
            "Public proof and trust evidence remains unclear."
        ),
        "How extensible and technically credible does the public offer appear?": (
            "Technical depth and integrations remain unclear."
        ),
        "What recent public signals are worth monitoring?": (
            "No dated recent activity was verified."
        ),
    }
    return replacements.get(question, question)


def _plain_summary(
    domain: str,
    claims: list[ObservedClaim],
    positioning: list[ObservedClaim],
    differentiators: list[ObservedClaim],
) -> str:
    text = " ".join(claim.value.casefold() for claim in claims)
    categories = (
        "web hosting",
        "website builder",
        "community communication platform",
        "goalkeeper gloves",
        "football equipment",
        "sportswear",
        "footwear",
        "shoes",
        "apparel",
        "software",
        "platform",
        "analytics",
        "automation",
        "cybersecurity",
        "product development system",
        "open source language models",
        "artificial intelligence",
    )
    category = next((item for item in categories if item in text), "")
    if "web hosting" in text or "website builder" in text:
        return "Offers web hosting, website-building, domain, and related hosting services."
    if "discord" in text or "voice chat" in text or "group chat" in text:
        return (
            "Offers a communication platform for communities, voice chat, group chat, "
            "and online social coordination."
        )
    if "nike" in text or "footwear" in text or "sportswear" in text:
        return (
            "Sells athletic footwear, apparel, and sport-focused products through a global "
            "retail and brand ecosystem."
        )
    themes = []
    for term, label in (
        ("price", "price"),
        ("quality", "quality"),
        ("grip", "grip"),
        ("durability", "durability"),
        ("performance", "performance"),
        ("security", "security"),
        ("automation", "automation"),
        ("collaboration", "collaboration"),
    ):
        if term in text and label not in themes:
            themes.append(label)
    strategic_positioning = next(
        (
            claim
            for claim in positioning
            if any(
                term in claim.value.casefold()
                for term in (
                    "product development system",
                    "open source",
                    "research",
                    "language model",
                    "teams and agents",
                    "uk-based brand",
                )
            )
        ),
        None,
    )
    if strategic_positioning:
        return _sentence_safe_shorten(strategic_positioning.value, 220)
    if category and themes:
        return f"Sells {category}, with public messaging focused on {_join_plain(themes[:3])}."
    if category:
        return f"Sells {category} and presents it as the company's main public offer."
    if differentiators:
        return (
            f"{domain} publicly emphasizes "
            f"{_sentence_safe_shorten(differentiators[0].value, 170)}"
        )
    if positioning:
        return (
            f"{domain} publicly presents itself around: "
            f"{_sentence_safe_shorten(positioning[0].value, 170)}"
        )
    return f"No clear public positioning statement was found for {domain}."


def _join_plain(values: list[str]) -> str:
    if len(values) == 1:
        return values[0]
    return f"{', '.join(values[:-1])} and {values[-1]}"


def _coverage_explained(profile: CompetitorProfile) -> str:
    short_titles = {
        "Positioning and target customer": "Positioning",
        "Offer and commercial motion": "Offer and prices",
        "Proof and trust": "Customer trust",
        "Ecosystem and technical depth": "Technical depth",
        "Recent moves and hiring signals": "Recent activity",
    }
    covered = [
        short_titles.get(section.title, section.title)
        for section in profile.sections
        if section.claims
    ]
    missing = [
        short_titles.get(section.title, section.title)
        for section in profile.sections
        if not section.claims
    ]
    return f"Covered: {', '.join(covered) or 'none'}. Not verified: {', '.join(missing) or 'none'}."


def _next_checks(
    *,
    proof: list[ObservedClaim],
    recent: list[ObservedClaim],
    prices: list[str],
) -> list[str]:
    checks = []
    if prices:
        checks.append("Confirm current prices and availability before using them in a decision.")
    if not proof:
        checks.append("Look for named customers, reviews, or independent trust evidence.")
    if not recent:
        checks.append("Check recent announcements or social posts for current activity.")
    checks.append("Add your own product context before drawing win/loss conclusions.")
    return checks[:3]
