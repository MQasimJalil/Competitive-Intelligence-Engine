from enum import StrEnum

from pydantic import AnyHttpUrl, BaseModel, Field, model_validator

from app.schemas.facts import BusinessCategory


class CandidateSource(StrEnum):
    HOMEPAGE_LINK = "homepage_link"
    SITEMAP = "sitemap"
    SECOND_HOP = "second_hop"


class PageCandidate(BaseModel):
    url: AnyHttpUrl
    primary_category: BusinessCategory
    matched_categories: list[BusinessCategory]
    source: CandidateSource
    score: int = Field(ge=0)
    reasons: list[str]


class CrawlPlan(BaseModel):
    selected: list[PageCandidate]
    candidate_count: int = Field(ge=0)
    selection_limit: int = Field(ge=1)

    @model_validator(mode="after")
    def selected_does_not_exceed_limit(self) -> "CrawlPlan":
        if len(self.selected) > self.selection_limit:
            raise ValueError("selected pages cannot exceed selection_limit")
        return self
