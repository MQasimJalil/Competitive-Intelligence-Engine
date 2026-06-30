from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

UserRole = Literal["admin", "tester"]


class AppUser(BaseModel):
    user_id: str = Field(default_factory=lambda: uuid4().hex)
    supabase_user_id: str = ""
    name: str
    email: str
    phone_number: str = ""
    password_hash: str
    role: UserRole = "tester"
    credit_balance: int = Field(default=0, ge=0)
    is_active: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        cleaned = " ".join(value.strip().split())
        if not cleaned:
            raise ValueError("Name is required")
        return cleaned

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        email = value.strip().casefold()
        if "@" not in email or email.startswith("@") or email.endswith("@"):
            raise ValueError("Valid email is required")
        return email


class UserSummary(BaseModel):
    user_id: str
    supabase_user_id: str = ""
    name: str
    email: str
    phone_number: str = ""
    role: UserRole
    credit_balance: int = 0
    is_active: bool = True
    created_at: datetime


def summarize_user(user: AppUser) -> UserSummary:
    return UserSummary(
        user_id=user.user_id,
        supabase_user_id=user.supabase_user_id,
        name=user.name,
        email=user.email,
        phone_number=user.phone_number,
        role=user.role,
        credit_balance=user.credit_balance,
        is_active=user.is_active,
        created_at=user.created_at,
    )
