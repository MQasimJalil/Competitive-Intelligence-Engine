from collections import defaultdict
from hashlib import sha256

from app.schemas import (
    BusinessCategory,
    BusinessFact,
    BusinessFactKind,
    ExtractionResult,
    ExtractionStatus,
    NormalizedBusinessProfile,
    ObservedClaim,
    ProductOffer,
)

_KIND_BY_CATEGORY = {
    BusinessCategory.TARGET_SEGMENTS: BusinessFactKind.AUDIENCE,
    BusinessCategory.SOLUTIONS_USE_CASES: BusinessFactKind.AUDIENCE,
    BusinessCategory.PROOF: BusinessFactKind.PROOF,
    BusinessCategory.TRUST_COMPLIANCE: BusinessFactKind.PROOF,
    BusinessCategory.RECENT_MOVES: BusinessFactKind.RECENT_ACTIVITY,
    BusinessCategory.HIRING_SIGNALS: BusinessFactKind.RECENT_ACTIVITY,
}
_GENERIC_PRODUCT_NAMES = {
    "apparel",
    "equipment",
    "products",
    "shop",
    "shop all",
}


def build_normalized_business_profile(
    domain: str, results: list[ExtractionResult]
) -> NormalizedBusinessProfile:
    title_by_url: dict[str, str] = {}
    claims: list[ObservedClaim] = []
    for result in results:
        if result.status != ExtractionStatus.OK or not isinstance(result.value, dict):
            continue
        page_url = str(result.value.get("page_url", result.final_url or result.source_url or ""))
        title_by_url[page_url] = " ".join(str(result.value.get("page_title", "")).split())
        for raw in result.value.get("claims", []):
            claims.append(ObservedClaim.model_validate(raw))

    facts: list[BusinessFact] = []
    seen_citation_ids: set[str] = set()
    for claim in claims:
        kind = _fact_kind(claim)
        if kind is None or claim.fact_type == "keyword_mention":
            continue
        citation_id = _citation_id(kind, claim)
        if citation_id in seen_citation_ids:
            continue
        seen_citation_ids.add(citation_id)
        facts.append(
            BusinessFact(
                citation_id=citation_id,
                kind=kind,
                value=_clean_text(claim.value),
                evidence_excerpt=_clean_text(claim.evidence_excerpt),
                source_url=claim.source_url,
                source_title=title_by_url.get(str(claim.source_url), ""),
                category=claim.category,
                retrieved_at=claim.retrieved_at,
            )
        )

    return NormalizedBusinessProfile(
        domain=domain,
        facts=facts,
        offers=_build_offers(facts),
    )


def _fact_kind(claim: ObservedClaim) -> BusinessFactKind | None:
    value = claim.value.casefold()
    if any(
        phrase in value
        for phrase in (
            "our mission",
            "democratize access",
            "humanistic ai",
            "privileged few",
            "human freedom",
        )
    ):
        return BusinessFactKind.COMPANY_DETAIL
    if "best known for" in value or "we are building psyche" in value:
        return BusinessFactKind.COMPANY_DETAIL
    if claim.fact_type in {"structured_price", "visible_price"}:
        return BusinessFactKind.PRICE
    if claim.fact_type == "pricing_plan":
        return BusinessFactKind.PACKAGING
    if claim.fact_type == "packaging_capability":
        return BusinessFactKind.DIFFERENTIATOR
    if claim.fact_type == "portfolio_type":
        return BusinessFactKind.PRODUCT
    if claim.fact_type == "public_artifact":
        return BusinessFactKind.RECENT_ACTIVITY
    if claim.fact_type == "market_segments":
        return BusinessFactKind.AUDIENCE
    if claim.fact_type == "workflow_stage":
        return BusinessFactKind.DIFFERENTIATOR
    if claim.category == BusinessCategory.PRODUCTS_MODULES:
        if claim.fact_type in {
            "page_headline",
            "structured_product",
            "linked_product",
            "product_collection",
        }:
            return BusinessFactKind.PRODUCT
        if claim.fact_type == "page_claim":
            return BusinessFactKind.DIFFERENTIATOR
    if claim.category == BusinessCategory.CAPABILITIES and claim.fact_type == "page_claim":
        return BusinessFactKind.DIFFERENTIATOR
    if claim.category == BusinessCategory.POSITIONING:
        return BusinessFactKind.COMPANY_DETAIL
    return _KIND_BY_CATEGORY.get(claim.category)


def _build_offers(facts: list[BusinessFact]) -> list[ProductOffer]:
    by_source: dict[str, list[BusinessFact]] = defaultdict(list)
    for fact in facts:
        by_source[str(fact.source_url)].append(fact)
    offers: list[ProductOffer] = []
    for source_facts in by_source.values():
        products = [
            fact
            for fact in source_facts
            if fact.kind == BusinessFactKind.PRODUCT
            and fact.value.casefold() not in _GENERIC_PRODUCT_NAMES
        ]
        prices = [fact for fact in source_facts if fact.kind == BusinessFactKind.PRICE]
        for product in products[:3]:
            paired_prices = prices[:4] if len(products) == 1 else []
            offers.append(
                ProductOffer(
                    name=product.value,
                    prices=[price.value for price in paired_prices],
                    citation_ids=[
                        product.citation_id,
                        *[price.citation_id for price in paired_prices],
                    ],
                )
            )
    return offers[:8]


def _citation_id(kind: BusinessFactKind, claim: ObservedClaim) -> str:
    material = "|".join(
        (
            kind.value,
            _clean_text(claim.value).casefold(),
            str(claim.source_url).casefold(),
            _clean_text(claim.evidence_excerpt).casefold(),
        )
    )
    return f"F-{sha256(material.encode('utf-8')).hexdigest()[:12].upper()}"


def _clean_text(value: str) -> str:
    return " ".join(value.replace("\u00c2\u00a3", "\u00a3").replace("\u0141", "\u00a3").split())
