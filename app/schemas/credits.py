from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


class CreditLedgerEntry(BaseModel):
    entry_id: str = Field(default_factory=lambda: uuid4().hex)
    user_id: str
    job_id: str = ""
    amount: int
    reason: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("reason")
    @classmethod
    def clean_reason(cls, value: str) -> str:
        reason = "_".join(value.strip().casefold().split())
        if not reason:
            raise ValueError("Credit reason is required")
        return reason
