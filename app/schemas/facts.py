from datetime import UTC, datetime
from enum import StrEnum

from pydantic import AnyHttpUrl, BaseModel, Field


class BusinessCategory(StrEnum):
    POSITIONING = "positioning"
    PRICING_PACKAGING = "pricing_packaging"
    PRODUCTS_MODULES = "products_modules"
    CAPABILITIES = "capabilities"
    SOLUTIONS_USE_CASES = "solutions_use_cases"
    TARGET_SEGMENTS = "target_segments"
    PROOF = "proof"
    SALES_MOTION = "sales_motion"
    INTEGRATIONS_ECOSYSTEM = "integrations_ecosystem"
    TRUST_COMPLIANCE = "trust_compliance"
    TECHNICAL_DEPTH = "technical_depth"
    RECENT_MOVES = "recent_moves"
    HIRING_SIGNALS = "hiring_signals"


class ObservedClaim(BaseModel):
    category: BusinessCategory
    fact_type: str = Field(min_length=1, max_length=80)
    value: str = Field(min_length=1, max_length=500)
    evidence_excerpt: str = Field(min_length=1, max_length=1_000)
    source_url: AnyHttpUrl
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    context: str = Field(default="", max_length=300)


class GTMPageFact(BaseModel):
    category: BusinessCategory
    page_url: AnyHttpUrl
    page_title: str = Field(default="", max_length=300)
    headline: str = Field(default="", max_length=500)
    claims: list[ObservedClaim] = Field(default_factory=list, max_length=40)
