from pydantic import BaseModel, Field

from app.adapters.openai_analysis import citation_validity_score
from app.schemas import BusinessFactKind
from app.tools.competitor_brief.service import CompetitorSnapshot


class BenchmarkScore(BaseModel):
    domain: str
    fact_count: int
    source_count: int
    expected_kind_recall: float = Field(ge=0.0, le=1.0)
    coverage_score: float = Field(ge=0.0, le=1.0)
    offer_score: float = Field(ge=0.0, le=1.0)
    citation_score: float | None = Field(default=None, ge=0.0, le=1.0)
    usefulness_proxy: float = Field(ge=0.0, le=1.0)
    notes: list[str] = Field(default_factory=list)


def score_snapshot(
    snapshot: CompetitorSnapshot,
    *,
    expected_kinds: list[BusinessFactKind],
    minimum_facts: int,
) -> BenchmarkScore:
    business = snapshot.business_profile
    facts = business.facts if business else []
    found_kinds = {fact.kind for fact in facts}
    expected_kind_recall = (
        len(found_kinds.intersection(expected_kinds)) / len(expected_kinds)
        if expected_kinds
        else 1.0
    )
    coverage_score = min(1.0, len(facts) / max(1, minimum_facts))
    offer_score = min(1.0, len(business.offers) / 2) if business else 0.0
    citation_score = (
        citation_validity_score(snapshot.ai_analysis, business)
        if snapshot.ai_analysis and business
        else None
    )
    usefulness_proxy = round(
        expected_kind_recall * 0.45 + coverage_score * 0.35 + offer_score * 0.20,
        4,
    )
    notes = []
    missing = [kind.value for kind in expected_kinds if kind not in found_kinds]
    if missing:
        notes.append(f"Missing expected kinds: {', '.join(missing)}")
    if not business or not business.offers:
        notes.append("No product-price offer combinations found.")
    return BenchmarkScore(
        domain=snapshot.domain,
        fact_count=len(facts),
        source_count=len({str(fact.source_url) for fact in facts}),
        expected_kind_recall=round(expected_kind_recall, 4),
        coverage_score=round(coverage_score, 4),
        offer_score=round(offer_score, 4),
        citation_score=citation_score,
        usefulness_proxy=usefulness_proxy,
        notes=notes,
    )
