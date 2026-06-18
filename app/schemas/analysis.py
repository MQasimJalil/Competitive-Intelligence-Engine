from datetime import UTC, datetime

from pydantic import BaseModel, Field, model_validator


class CitedStatement(BaseModel):
    text: str = Field(min_length=1, max_length=600)
    citation_ids: list[str] = Field(min_length=1, max_length=12)


class AIReportLabels(BaseModel):
    country: CitedStatement | None = None
    industry: CitedStatement | None = None
    business_model: CitedStatement | None = None
    portfolio_metric: CitedStatement | None = None

    def all_statements(self) -> list[CitedStatement]:
        return [
            statement
            for statement in [
                self.country,
                self.industry,
                self.business_model,
                self.portfolio_metric,
            ]
            if statement is not None
        ]


class AIAnalysis(BaseModel):
    report_labels: AIReportLabels = Field(default_factory=AIReportLabels)
    summary: list[CitedStatement] = Field(default_factory=list, max_length=3)
    differentiators: list[CitedStatement] = Field(default_factory=list, max_length=4)
    commercial_observations: list[CitedStatement] = Field(default_factory=list, max_length=4)
    public_signals: list[CitedStatement] = Field(default_factory=list, max_length=4)
    risks_and_unknowns: list[CitedStatement] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def statements_have_citations(self) -> "AIAnalysis":
        for statement in self.all_statements():
            if not statement.citation_ids:
                raise ValueError("every AI statement must cite at least one evidence ID")
        return self

    def all_statements(self) -> list[CitedStatement]:
        return [
            *self.report_labels.all_statements(),
            *self.summary,
            *self.differentiators,
            *self.commercial_observations,
            *self.public_signals,
            *self.risks_and_unknowns,
        ]


class AIUsage(BaseModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    estimated_cost_usd: float = Field(default=0.0, ge=0.0)


class AIAnalysisRun(BaseModel):
    status: str
    failure_code: str = ""
    strategy: str = "native_structured"
    attempt_count: int = Field(default=0, ge=0)
    analysis: AIAnalysis | None = None
    provider: str = "openai"
    model: str
    prompt_version: str
    schema_version: str
    evidence_hash: str = ""
    cached: bool = False
    usage: AIUsage = Field(default_factory=AIUsage)
    budget_limit_usd: float = Field(default=0.0, ge=0.0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    message: str = ""
