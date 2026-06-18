from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import AnyHttpUrl, BaseModel, Field, model_validator


class ExtractionStatus(StrEnum):
    OK = "ok"
    NO_DATA = "no_data"
    ROBOTS_DISALLOWED = "robots_disallowed"
    TOS_BLOCKED = "tos_blocked"
    RATE_LIMITED = "rate_limited"
    PARSE_FAILED = "parse_failed"
    NETWORK_FAILED = "network_failed"


class SourceType(StrEnum):
    COMPANY_PAGE = "company_page"
    PUBLIC_API = "public_api"
    PUBLIC_FEED = "public_feed"
    HTML = "html"
    HEADER = "header"
    MIXED_PUBLIC_SIGNALS = "mixed_public_signals"
    DNS_HINT = "dns_hint"
    UNAVAILABLE = "unavailable"


class EvidenceKind(StrEnum):
    OBSERVED = "observed"
    INFERRED = "inferred"
    UNAVAILABLE = "unavailable"


class ExtractionResult(BaseModel):
    value: Any = None
    source_url: AnyHttpUrl | None = None
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    extractor_name: str
    confidence: float = Field(ge=0.0, le=1.0)
    status: ExtractionStatus
    source_type: SourceType = SourceType.COMPANY_PAGE
    notes: str = ""
    final_url: AnyHttpUrl | None = None
    http_status: int | None = Field(default=None, ge=100, le=599)
    evidence: str = ""
    extractor_version: str = "v1"
    evidence_kind: EvidenceKind = EvidenceKind.OBSERVED

    @model_validator(mode="after")
    def require_provenance_for_ok(self) -> "ExtractionResult":
        if self.status == ExtractionStatus.OK:
            if self.value in (None, "", [], {}):
                raise ValueError("ok extraction results must include a value")
            if self.source_url is None:
                raise ValueError("ok extraction results must include a source_url")
        return self

    @classmethod
    def unavailable(
        cls,
        *,
        extractor_name: str,
        status: ExtractionStatus = ExtractionStatus.NO_DATA,
        source_url: str | None = None,
        notes: str = "Data unavailable",
        final_url: str | None = None,
        http_status: int | None = None,
    ) -> "ExtractionResult":
        return cls(
            value=None,
            source_url=source_url,
            extractor_name=extractor_name,
            confidence=0.0,
            status=status,
            source_type=SourceType.UNAVAILABLE,
            notes=notes,
            final_url=final_url,
            http_status=http_status,
            evidence_kind=EvidenceKind.UNAVAILABLE,
        )
