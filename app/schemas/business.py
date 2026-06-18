from datetime import UTC, datetime
from enum import StrEnum

from pydantic import AnyHttpUrl, BaseModel, Field

from app.schemas.facts import BusinessCategory


class BusinessFactKind(StrEnum):
    PRODUCT = "product"
    PRICE = "price"
    PACKAGING = "packaging"
    AUDIENCE = "audience"
    DIFFERENTIATOR = "differentiator"
    PROOF = "proof"
    COMPANY_DETAIL = "company_detail"
    RECENT_ACTIVITY = "recent_activity"


class BusinessFact(BaseModel):
    citation_id: str = Field(pattern=r"^F(?:\d{3}|-[A-F0-9]{12})$")
    kind: BusinessFactKind
    value: str = Field(min_length=1, max_length=500)
    evidence_excerpt: str = Field(min_length=1, max_length=1_000)
    source_url: AnyHttpUrl
    source_title: str = Field(default="", max_length=300)
    category: BusinessCategory
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ProductOffer(BaseModel):
    name: str
    prices: list[str] = Field(default_factory=list)
    citation_ids: list[str] = Field(default_factory=list)


class NormalizedBusinessProfile(BaseModel):
    domain: str
    facts: list[BusinessFact] = Field(default_factory=list)
    offers: list[ProductOffer] = Field(default_factory=list)
