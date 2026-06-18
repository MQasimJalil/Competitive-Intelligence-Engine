from datetime import UTC, datetime

from pydantic import AnyHttpUrl, BaseModel, Field

from app.schemas.facts import BusinessCategory


class ProfileClaim(BaseModel):
    category: BusinessCategory
    label: str = Field(min_length=1, max_length=120)
    value: str = Field(min_length=1, max_length=500)
    evidence_excerpt: str = Field(min_length=1, max_length=1_000)
    source_url: AnyHttpUrl
    retrieved_at: datetime


class ProfileSection(BaseModel):
    title: str
    question: str
    claims: list[ProfileClaim] = Field(default_factory=list, max_length=3)


class CompetitorProfile(BaseModel):
    domain: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    title: str = "Public-source competitor profile"
    sections: list[ProfileSection]
    unanswered_questions: list[str] = Field(default_factory=list, max_length=8)
    source_count: int = Field(ge=0)
    answered_dimensions: int = Field(ge=0)
    total_dimensions: int = Field(ge=1)
