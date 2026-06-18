from datetime import datetime

from app.schemas import (
    BusinessCategory,
    CompetitorProfile,
    ExtractionResult,
    ExtractionStatus,
    ObservedClaim,
    ProfileClaim,
    ProfileSection,
)

SECTION_DEFINITIONS = (
    (
        "Positioning and target customer",
        "Who do they say they serve, and what outcome do they promise?",
        {
            BusinessCategory.POSITIONING,
            BusinessCategory.TARGET_SEGMENTS,
            BusinessCategory.SOLUTIONS_USE_CASES,
        },
    ),
    (
        "Offer and commercial motion",
        "What do they sell, and how do buyers start or buy?",
        {
            BusinessCategory.PRODUCTS_MODULES,
            BusinessCategory.CAPABILITIES,
            BusinessCategory.PRICING_PACKAGING,
            BusinessCategory.SALES_MOTION,
        },
    ),
    (
        "Proof and trust",
        "What evidence and trust claims support their pitch?",
        {BusinessCategory.PROOF, BusinessCategory.TRUST_COMPLIANCE},
    ),
    (
        "Ecosystem and technical depth",
        "How extensible and technically credible does the public offer appear?",
        {BusinessCategory.INTEGRATIONS_ECOSYSTEM, BusinessCategory.TECHNICAL_DEPTH},
    ),
    (
        "Recent moves and hiring signals",
        "What recent public signals are worth monitoring?",
        {BusinessCategory.RECENT_MOVES, BusinessCategory.HIRING_SIGNALS},
    ),
)

FACT_LABELS = {
    "visible_price": "Visible price",
    "proof_metric": "Proof metric",
    "cta": "Buyer CTA",
    "keyword_mention": "Observed signal",
    "page_headline": "Page headline",
    "page_claim": "Public claim",
    "structured_description": "Structured company description",
    "structured_product": "Structured product",
    "linked_product": "Linked product",
    "pricing_plan": "Pricing plan",
    "product_collection": "Product collection",
    "portfolio_type": "Portfolio type",
    "workflow_stage": "Workflow stage",
}

FACT_PRIORITY = {
    "visible_price": 100,
    "proof_metric": 95,
    "cta": 90,
    "page_headline": 60,
    "structured_description": 88,
    "structured_product": 82,
    "linked_product": 78,
    "pricing_plan": 92,
    "product_collection": 86,
    "portfolio_type": 86,
    "workflow_stage": 86,
    "page_claim": 80,
    "keyword_mention": 40,
}

LOW_INFORMATION_VALUES = {
    "privacy",
    "security",
    "customers",
    "integrations",
    "pricing",
    "enterprise",
    "features",
    "about solo",
    "news",
    "products",
    "shop by collection",
}


def build_competitor_profile(domain: str, results: list[ExtractionResult]) -> CompetitorProfile:
    observed = _collect_observed_claims(results)
    sections: list[ProfileSection] = []
    unanswered: list[str] = []

    for title, question, categories in SECTION_DEFINITIONS:
        matching = [claim for claim in observed if claim.category in categories]
        if title == "Recent moves and hiring signals":
            matching = [
                claim for claim in matching if claim.fact_type in {"dated_activity", "open_role"}
            ]
        selected = _select_section_claims(matching, limit=2)
        sections.append(
            ProfileSection(
                title=title,
                question=question,
                claims=[_to_profile_claim(claim) for claim in selected],
            )
        )
        if not selected:
            unanswered.append(question)

    source_count = len({str(claim.source_url) for claim in observed})
    answered = sum(1 for section in sections if section.claims)
    return CompetitorProfile(
        domain=domain,
        sections=sections,
        unanswered_questions=unanswered,
        source_count=source_count,
        answered_dimensions=answered,
        total_dimensions=len(sections),
    )


def _collect_observed_claims(results: list[ExtractionResult]) -> list[ObservedClaim]:
    claims: list[ObservedClaim] = []
    for result in results:
        if result.status != ExtractionStatus.OK:
            continue
        if result.extractor_name in {"homepage_headline", "meta_description"}:
            if isinstance(result.value, str) and result.source_url:
                claims.append(
                    ObservedClaim(
                        category=BusinessCategory.POSITIONING,
                        fact_type="page_claim",
                        value=result.value,
                        evidence_excerpt=result.value,
                        source_url=result.source_url,
                        retrieved_at=result.retrieved_at,
                        context="Homepage positioning text",
                    )
                )
            continue
        if not result.extractor_name.endswith("_facts"):
            continue
        if not isinstance(result.value, dict):
            continue
        for raw_claim in result.value.get("claims", []):
            claims.append(ObservedClaim.model_validate(raw_claim))
    return claims


def _select_section_claims(claims: list[ObservedClaim], limit: int) -> list[ObservedClaim]:
    informative = [claim for claim in claims if _is_informative_claim(claim)]
    ranked = sorted(
        informative,
        key=lambda claim: (
            -FACT_PRIORITY.get(claim.fact_type, 0),
            abs(min(len(claim.value), 300) - 120),
            claim.value.casefold(),
        ),
    )
    selected: list[ObservedClaim] = []
    seen_values: set[str] = set()
    seen_categories: set[BusinessCategory] = set()
    seen_fact_types: set[str] = set()

    for claim in ranked:
        key = claim.value.casefold()
        if key in seen_values or claim.category in seen_categories:
            continue
        selected.append(claim)
        seen_values.add(key)
        seen_categories.add(claim.category)
        seen_fact_types.add(claim.fact_type)
        if len(selected) == limit:
            return selected

    for claim in ranked:
        key = claim.value.casefold()
        if key in seen_values:
            continue
        if claim.fact_type == "visible_price" and claim.fact_type in seen_fact_types:
            continue
        selected.append(claim)
        seen_values.add(key)
        seen_fact_types.add(claim.fact_type)
        if len(selected) == limit:
            break
    return selected


def _is_informative_claim(claim: ObservedClaim) -> bool:
    value = " ".join(claim.value.split())
    if (
        claim.fact_type in {"page_claim", "page_headline"}
        and value.casefold() in LOW_INFORMATION_VALUES
    ):
        return False
    if claim.fact_type in {"page_claim", "page_headline"}:
        if len(value) < 20 or len(value) > 500 or value.count(";") > 4:
            return False
    return True


def _to_profile_claim(claim: ObservedClaim) -> ProfileClaim:
    return ProfileClaim(
        category=claim.category,
        label=FACT_LABELS.get(claim.fact_type, claim.fact_type.replace("_", " ").title()),
        value=claim.value,
        evidence_excerpt=claim.evidence_excerpt,
        source_url=claim.source_url,
        retrieved_at=claim.retrieved_at,
    )


def profile_generated_label(generated_at: datetime) -> str:
    return generated_at.strftime("%Y-%m-%d %H:%M UTC")
