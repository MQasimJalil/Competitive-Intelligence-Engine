import json
from datetime import UTC, datetime
from pathlib import Path

from app.config import settings


def log_auth_event(
    event: str,
    *,
    email: str = "",
    ip_address: str = "",
    user_agent: str = "",
    success: bool = False,
    reason: str = "",
) -> None:
    path = Path(settings.auth_audit_log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "event": event,
        "email": email.strip().casefold(),
        "ip_address": ip_address,
        "user_agent": user_agent[:240],
        "success": success,
        "reason": reason,
        "created_at": datetime.now(UTC).isoformat(),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
