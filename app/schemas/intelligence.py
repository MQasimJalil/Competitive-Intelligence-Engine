from pydantic import BaseModel, Field

from app.schemas.business import BusinessFact, NormalizedBusinessProfile, ProductOffer


class StructuredIntelligenceProfile(BaseModel):
    domain: str
    company_overview: list[BusinessFact] = Field(default_factory=list)
    pricing: list[BusinessFact] = Field(default_factory=list)
    features: list[BusinessFact] = Field(default_factory=list)
    positioning: list[BusinessFact] = Field(default_factory=list)
    target_customers: list[BusinessFact] = Field(default_factory=list)
    differentiators: list[BusinessFact] = Field(default_factory=list)
    proof: list[BusinessFact] = Field(default_factory=list)
    recent_signals: list[BusinessFact] = Field(default_factory=list)
    risks: list[BusinessFact] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    offers: list[ProductOffer] = Field(default_factory=list)

    def all_facts(self) -> list[BusinessFact]:
        ordered = [
            *self.company_overview,
            *self.pricing,
            *self.features,
            *self.positioning,
            *self.target_customers,
            *self.differentiators,
            *self.proof,
            *self.recent_signals,
            *self.risks,
        ]
        seen: set[str] = set()
        unique = []
        for fact in ordered:
            if fact.citation_id in seen:
                continue
            seen.add(fact.citation_id)
            unique.append(fact)
        return unique

    def to_business_profile(self) -> NormalizedBusinessProfile:
        return NormalizedBusinessProfile(
            domain=self.domain,
            facts=self.all_facts(),
            offers=self.offers,
        )
