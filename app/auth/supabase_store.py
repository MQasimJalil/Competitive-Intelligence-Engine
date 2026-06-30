from typing import Any

import httpx

from app.config import settings
from app.schemas.auth import AppUser, UserRole, UserSummary

SIGNUP_CREDIT_REASON = "signup_email_verified_bonus"


def _handle_http_error(exc: httpx.HTTPStatusError, default_message: str) -> None:
    try:
        data = exc.response.json()
        message = data.get("msg") or data.get("error_description") or data.get("error") or str(exc)
    except Exception:
        message = str(exc)
    raise ValueError(message) from exc


class SupabaseAuthClient:
    def __init__(self, *, url: str = "", anon_key: str = "", service_role_key: str = ""):
        self.url = url.rstrip("/")
        self.anon_key = anon_key
        self.service_role_key = service_role_key

    def create_user(self, *, email: str, password: str, name: str) -> dict:
        self._require_admin_config()
        try:
            response = httpx.post(
                f"{self.url}/auth/v1/admin/users",
                headers={
                    "apikey": self.service_role_key,
                    "authorization": f"Bearer {self.service_role_key}",
                    "content-type": "application/json",
                },
                json={
                    "email": email,
                    "password": password,
                    "email_confirm": True,
                    "user_metadata": {"name": name},
                },
                timeout=15.0,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            _handle_http_error(exc, "Failed to create user in Supabase")

    def sign_up(
        self, *, email: str, password: str, phone_number: str, captcha_token: str
    ) -> dict:
        self._require_public_config()
        payload = {
            "email": email,
            "password": password,
            "data": {"phone_number": phone_number},
        }
        if captcha_token:
            payload["gotrue_meta_security"] = {"captcha_token": captcha_token}
        try:
            response = httpx.post(
                f"{self.url}/auth/v1/signup",
                headers={
                    "apikey": self.anon_key,
                    "content-type": "application/json",
                },
                json=payload,
                timeout=15.0,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            _handle_http_error(exc, "Failed to sign up in Supabase")

    def sign_in_with_password(
        self, *, email: str, password: str, captcha_token: str = ""
    ) -> dict | None:
        self._require_public_config()
        payload = {"email": email, "password": password}
        if captcha_token:
            payload["gotrue_meta_security"] = {"captcha_token": captcha_token}
        response = httpx.post(
            f"{self.url}/auth/v1/token?grant_type=password",
            headers={
                "apikey": self.anon_key,
                "content-type": "application/json",
            },
            json=payload,
            timeout=15.0,
        )
        if response.status_code in {400, 401, 403}:
            try:
                data = response.json()
            except ValueError:
                data = {}
            if data.get("error_code") == "captcha_failed":
                raise ValueError("Captcha verification failed.")
            return None
        response.raise_for_status()
        return response.json()

    def _require_public_config(self) -> None:
        if not self.url or not self.anon_key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_ANON_KEY are required")

    def _require_admin_config(self) -> None:
        if not self.url or not self.service_role_key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")


class SupabaseUserStore:
    def __init__(
        self,
        metadata_store: Any,
        auth_client: SupabaseAuthClient,
        credit_store: Any | None = None,
    ):
        self.metadata_store = metadata_store
        self.auth_client = auth_client
        self.credit_store = credit_store

    def create_user(
        self,
        *,
        name: str,
        email: str,
        password: str,
        role: UserRole = "tester",
        supabase_user_id: str = "",
        phone_number: str = "",
        credit_balance: int | None = None,
        is_active: bool = True,
    ) -> AppUser:
        if self.get_by_email(email):
            raise ValueError("User already exists for this email")
        identity = (
            {"id": supabase_user_id, "email": email}
            if supabase_user_id
            else self.auth_client.create_user(email=email, password=password, name=name)
        )
        return self.metadata_store.create_user(
            name=name,
            email=identity.get("email") or email,
            password="",
            role=role,
            supabase_user_id=identity["id"],
            phone_number=phone_number,
            credit_balance=(
                settings.beta_starting_credits
                if credit_balance is None
                else credit_balance
            ),
            is_active=is_active,
        )

    def signup(
        self, *, email: str, phone_number: str, password: str, captcha_token: str
    ) -> AppUser:
        if self.get_by_email(email):
            raise ValueError("User already exists for this email")
        result = self.auth_client.sign_up(
            email=email,
            password=password,
            phone_number=phone_number,
            captcha_token=captcha_token,
        )
        identity = _session_user(result)
        if not identity:
            raise ValueError("Supabase did not return a signup user")
        return self.metadata_store.create_user(
            name=_name_from_email(identity.get("email") or email),
            email=identity.get("email") or email,
            password="",
            role="tester",
            supabase_user_id=identity["id"],
            phone_number=phone_number,
            credit_balance=0,
            is_active=False,
        )

    def authenticate(
        self, email: str, password: str, captcha_token: str = ""
    ) -> AppUser | None:
        session = self.auth_client.sign_in_with_password(
            email=email,
            password=password,
            captcha_token=captcha_token,
        )
        identity = _session_user(session)
        if not identity or not _email_confirmed(identity):
            return None
        user = self.get_by_supabase_user_id(identity.get("id", ""))
        if user is None:
            user = self.get_by_email(identity.get("email") or email)
            if user is not None:
                user.supabase_user_id = identity["id"]
                metadata = identity.get("user_metadata") or {}
                if not user.phone_number and metadata.get("phone_number"):
                    user.phone_number = str(metadata["phone_number"])
                self.metadata_store.save(user)
            else:
                metadata = identity.get("user_metadata") or {}
                admin_email = getattr(settings, "admin_email", "")
                user_email = (identity.get("email") or email).strip().casefold()
                is_admin = admin_email and user_email == admin_email.strip().casefold()
                user = self.metadata_store.create_user(
                    name=_name_from_email(identity.get("email") or email),
                    email=identity.get("email") or email,
                    password="",
                    role="admin" if is_admin else "tester",
                    supabase_user_id=identity["id"],
                    phone_number=str(metadata.get("phone_number") or ""),
                    credit_balance=0,
                    is_active=True,
                )
        if not user.is_active:
            if self._signup_credits_granted(user):
                return None
            user.is_active = True
            self.metadata_store.save(user)
        self._grant_signup_credits_once(user)
        if not user.is_active:
            return None
        return user

    def get(self, user_id: str) -> AppUser | None:
        return self.metadata_store.get(user_id)

    def get_by_email(self, email: str) -> AppUser | None:
        return self.metadata_store.get_by_email(email)

    def get_by_supabase_user_id(self, supabase_user_id: str) -> AppUser | None:
        return self.metadata_store.get_by_supabase_user_id(supabase_user_id)

    def list_users(self) -> list[UserSummary]:
        return self.metadata_store.list_users()

    def count_users(self) -> int:
        return self.metadata_store.count_users()

    def save(self, user: AppUser) -> None:
        self.metadata_store.save(user)

    def _grant_signup_credits_once(self, user: AppUser) -> None:
        if self.credit_store is None:
            return
        if self._signup_credits_granted(user):
            return
        self.credit_store.grant(
            user_id=user.user_id,
            amount=settings.signup_free_credits,
            reason=SIGNUP_CREDIT_REASON,
        )
        user.credit_balance += settings.signup_free_credits
        self.metadata_store.save(user)

    def _signup_credits_granted(self, user: AppUser) -> bool:
        if self.credit_store is None:
            return False
        return any(
            entry.reason == SIGNUP_CREDIT_REASON
            for entry in self.credit_store.list_for_user(user.user_id)
        )


def _session_user(session: dict | None) -> dict | None:
    if not session:
        return None
    if "id" in session and "email" in session:
        return session
    user = session.get("user")
    return user if isinstance(user, dict) else None


def _email_confirmed(user: dict) -> bool:
    return bool(user.get("email_confirmed_at") or user.get("confirmed_at"))


def _name_from_email(email: str) -> str:
    return email.split("@", 1)[0] or "Tester"
