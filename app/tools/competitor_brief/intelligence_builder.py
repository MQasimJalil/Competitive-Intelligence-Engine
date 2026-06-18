from app.schemas import (
    BusinessCategory,
    BusinessFactKind,
    NormalizedBusinessProfile,
    StructuredIntelligenceProfile,
    ValidationReport,
)


def build_structured_intelligence(
    profile: NormalizedBusinessProfile,
    validation: ValidationReport,
) -> StructuredIntelligenceProfile:
    company_overview = []
    pricing = []
    features = []
    positioning = []
    target_customers = []
    differentiators = []
    proof = []
    recent_signals = []

    excluded = set(validation.excluded_citation_ids)
    for fact in profile.facts:
        if fact.citation_id in excluded:
            continue
        value = fact.value.casefold()
        audience_signal = any(
            term in value
            for term in (
                "for teams",
                "for enterprise",
                "startups",
                "goalkeepers",
                "keeper",
                "buyers",
                "organizations",
                "industries",
            )
        )
        if fact.kind in {BusinessFactKind.PRICE, BusinessFactKind.PACKAGING}:
            pricing.append(fact)
        elif fact.kind == BusinessFactKind.PRODUCT:
            features.append(fact)
        elif fact.kind == BusinessFactKind.AUDIENCE:
            target_customers.append(fact)
        elif fact.kind == BusinessFactKind.DIFFERENTIATOR:
            differentiators.append(fact)
        elif fact.kind == BusinessFactKind.PROOF:
            proof.append(fact)
        elif fact.kind == BusinessFactKind.RECENT_ACTIVITY:
            recent_signals.append(fact)
        elif fact.category == BusinessCategory.POSITIONING:
            positioning.append(fact)
        else:
            company_overview.append(fact)
        if fact.kind == BusinessFactKind.COMPANY_DETAIL and fact not in company_overview:
            company_overview.append(fact)
        if audience_signal and fact not in target_customers:
            target_customers.append(fact)

    populated = {
        "company overview": company_overview,
        "pricing": pricing,
        "features and products": features,
        "positioning": positioning,
        "target customers": target_customers,
        "differentiators": differentiators,
        "proof": proof,
        "recent signals": recent_signals,
    }
    unknowns = [
        f"No validated {label} evidence was found."
        for label, facts in populated.items()
        if not facts
    ]
    unknowns.extend(
        issue.message for issue in validation.issues if issue.code not in {"partial_collection"}
    )
    return StructuredIntelligenceProfile(
        domain=profile.domain,
        company_overview=company_overview,
        pricing=pricing,
        features=features,
        positioning=positioning,
        target_customers=target_customers,
        differentiators=differentiators,
        proof=proof,
        recent_signals=recent_signals,
        unknowns=unknowns,
        offers=profile.offers,
    )
