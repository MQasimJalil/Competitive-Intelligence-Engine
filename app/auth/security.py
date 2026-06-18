import base64
import hashlib
import hmac
import os
import secrets
from datetime import UTC, datetime, timedelta

from app.config import settings

_HASH_ITERATIONS = 240_000
_HASH_ALGORITHM = "sha256"


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        _HASH_ALGORITHM,
        password.encode("utf-8"),
        salt,
        _HASH_ITERATIONS,
    )
    return "pbkdf2_sha256${}${}${}".format(
        _HASH_ITERATIONS,
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, password_hash: str) -> bool:
    try:
        scheme, iterations, salt_text, digest_text = password_hash.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_text.encode("ascii"))
        actual = hashlib.pbkdf2_hmac(
            _HASH_ALGORITHM,
            password.encode("utf-8"),
            salt,
            int(iterations),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def create_session_token(user_id: str, *, now: datetime | None = None) -> str:
    issued_at = int((now or datetime.now(UTC)).timestamp())
    expires_at = issued_at + settings.session_max_age_seconds
    nonce = base64.urlsafe_b64encode(os.urandom(10)).decode("ascii").rstrip("=")
    payload = f"{user_id}.{issued_at}.{expires_at}.{nonce}"
    signature = _signature(payload)
    return f"{payload}.{signature}"


def read_session_token(token: str, *, now: datetime | None = None) -> str | None:
    parts = token.split(".")
    if len(parts) != 5:
        return None
    payload = ".".join(parts[:4])
    signature = parts[4]
    if not hmac.compare_digest(signature, _signature(payload)):
        return None
    user_id, _issued_at, expires_at, _nonce = parts[:4]
    current = int((now or datetime.now(UTC)).timestamp())
    if current > int(expires_at):
        return None
    return user_id


def cookie_max_age_delta() -> timedelta:
    return timedelta(seconds=settings.session_max_age_seconds)


def _signature(payload: str) -> str:
    digest = hmac.new(
        settings.auth_secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
