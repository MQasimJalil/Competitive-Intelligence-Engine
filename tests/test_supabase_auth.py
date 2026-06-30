from app.auth.supabase_store import SupabaseAuthClient, SupabaseUserStore
from app.schemas.auth import AppUser, summarize_user


class FakeSupabaseAuthClient(SupabaseAuthClient):
    def __init__(self):
        self.created = []
        self.signed_up = []
        self.sessions = {}

    def create_user(self, *, email: str, password: str, name: str) -> dict:
        self.created.append((email, password, name))
        return {"id": "supabase-user-1", "email": email}

    def sign_up(
        self, *, email: str, password: str, phone_number: str, captcha_token: str
    ) -> dict:
        self.signed_up.append((email, password, phone_number, captcha_token))
        return {
            "user": {
                "id": "supabase-signup-1",
                "email": email,
                "user_metadata": {"phone_number": phone_number},
            }
        }

    def sign_in_with_password(
        self, *, email: str, password: str, captcha_token: str = ""
    ) -> dict | None:
        return self.sessions.get((email, password, captcha_token)) or self.sessions.get(
            (email, password)
        )


class CaptchaFailedAuthClient(FakeSupabaseAuthClient):
    def sign_in_with_password(
        self, *, email: str, password: str, captcha_token: str = ""
    ) -> dict | None:
        raise ValueError("Captcha verification failed.")


class InMemoryMetadataStore:
    def __init__(self):
        self.users = {}

    def create_user(self, **values):
        user = AppUser(
            name=values["name"],
            email=values["email"],
            password_hash=values["password"],
            role=values.get("role", "tester"),
            supabase_user_id=values.get("supabase_user_id", ""),
            phone_number=values.get("phone_number", ""),
            credit_balance=values.get("credit_balance", 0),
            is_active=values.get("is_active", True),
        )
        self.users[user.user_id] = user
        return user

    def save(self, user):
        self.users[user.user_id] = user

    def get(self, user_id):
        return self.users.get(user_id)

    def get_by_email(self, email):
        normalized = email.strip().casefold()
        return next((user for user in self.users.values() if user.email == normalized), None)

    def get_by_supabase_user_id(self, supabase_user_id):
        return next(
            (
                user
                for user in self.users.values()
                if user.supabase_user_id == supabase_user_id
            ),
            None,
        )

    def list_users(self):
        return [summarize_user(user) for user in self.users.values()]

    def count_users(self):
        return len(self.users)


def test_supabase_user_store_creates_auth_identity_and_app_metadata(tmp_path):
    metadata_store = InMemoryMetadataStore()
    auth_client = FakeSupabaseAuthClient()
    store = SupabaseUserStore(metadata_store, auth_client)

    user = store.create_user(
        name="Beta Tester",
        email="tester@example.com",
        password="temporary-password",
        role="tester",
        credit_balance=5,
    )

    assert auth_client.created == [
        ("tester@example.com", "temporary-password", "Beta Tester")
    ]
    assert user.supabase_user_id == "supabase-user-1"
    assert user.password_hash == ""
    assert user.credit_balance == 5
    assert user.is_active is True
    assert store.get_by_supabase_user_id("supabase-user-1").user_id == user.user_id


def test_supabase_user_store_authenticates_to_active_app_user():
    metadata_store = InMemoryMetadataStore()
    auth_client = FakeSupabaseAuthClient()
    store = SupabaseUserStore(metadata_store, auth_client)
    user = metadata_store.create_user(
        name="Beta Tester",
        email="tester@example.com",
        password="unused-local-password",
        supabase_user_id="supabase-user-1",
    )
    auth_client.sessions[("tester@example.com", "correct-password")] = {
        "user": {
            "id": "supabase-user-1",
            "email": "tester@example.com",
            "email_confirmed_at": "2026-06-29T00:00:00Z",
        }
    }

    authenticated = store.authenticate("tester@example.com", "correct-password")

    assert authenticated.user_id == user.user_id


def test_supabase_user_store_passes_login_captcha_token():
    metadata_store = InMemoryMetadataStore()
    auth_client = FakeSupabaseAuthClient()
    store = SupabaseUserStore(metadata_store, auth_client)
    user = metadata_store.create_user(
        name="Beta Tester",
        email="tester@example.com",
        password="unused-local-password",
        supabase_user_id="supabase-user-1",
    )
    auth_client.sessions[("tester@example.com", "correct-password", "captcha-token")] = {
        "user": {
            "id": "supabase-user-1",
            "email": "tester@example.com",
            "email_confirmed_at": "2026-06-29T00:00:00Z",
        }
    }

    authenticated = store.authenticate(
        "tester@example.com",
        "correct-password",
        captcha_token="captcha-token",
    )

    assert authenticated.user_id == user.user_id


def test_supabase_user_store_surfaces_login_captcha_failure():
    store = SupabaseUserStore(InMemoryMetadataStore(), CaptchaFailedAuthClient())

    try:
        store.authenticate("tester@example.com", "correct-password")
    except ValueError as exc:
        assert "Captcha" in str(exc)
    else:
        raise AssertionError("Expected captcha failure")


def test_supabase_user_store_rejects_inactive_app_user():
    metadata_store = InMemoryMetadataStore()
    auth_client = FakeSupabaseAuthClient()
    store = SupabaseUserStore(metadata_store, auth_client)
    metadata_store.create_user(
        name="Beta Tester",
        email="tester@example.com",
        password="unused-local-password",
        supabase_user_id="supabase-user-1",
        is_active=False,
    )
    auth_client.sessions[("tester@example.com", "correct-password")] = {
        "user": {"id": "supabase-user-1", "email": "tester@example.com"}
    }

    assert store.authenticate("tester@example.com", "correct-password") is None


class InMemoryCreditStore:
    def __init__(self):
        self.entries = []

    def grant(self, *, user_id: str, amount: int, reason: str):
        self.entries.append((user_id, amount, reason))

    def list_for_user(self, user_id: str):
        return [
            type("Entry", (), {"reason": reason})()
            for entry_user_id, _amount, reason in self.entries
            if entry_user_id == user_id
        ]


def test_supabase_signup_creates_inactive_metadata_without_free_credits():
    metadata_store = InMemoryMetadataStore()
    auth_client = FakeSupabaseAuthClient()
    store = SupabaseUserStore(metadata_store, auth_client)

    user = store.signup(
        email="tester@example.com",
        phone_number="+15551234567",
        password="temporary-password",
        captcha_token="captcha-token",
    )

    assert auth_client.signed_up == [
        ("tester@example.com", "temporary-password", "+15551234567", "captcha-token")
    ]
    assert user.supabase_user_id == "supabase-signup-1"
    assert user.phone_number == "+15551234567"
    assert user.credit_balance == 0
    assert user.is_active is False


def test_verified_supabase_login_activates_user_and_grants_signup_credits_once():
    metadata_store = InMemoryMetadataStore()
    auth_client = FakeSupabaseAuthClient()
    credit_store = InMemoryCreditStore()
    store = SupabaseUserStore(metadata_store, auth_client, credit_store=credit_store)
    user = metadata_store.create_user(
        name="tester",
        email="tester@example.com",
        password="",
        supabase_user_id="supabase-user-1",
        is_active=False,
    )
    auth_client.sessions[("tester@example.com", "correct-password")] = {
        "user": {
            "id": "supabase-user-1",
            "email": "tester@example.com",
            "email_confirmed_at": "2026-06-29T00:00:00Z",
        }
    }

    authenticated = store.authenticate("tester@example.com", "correct-password")
    authenticated_again = store.authenticate("tester@example.com", "correct-password")

    assert authenticated.user_id == user.user_id
    assert authenticated_again.user_id == user.user_id
    assert metadata_store.get(user.user_id).is_active is True
    assert metadata_store.get(user.user_id).credit_balance == 2
    assert credit_store.entries == [
        (user.user_id, 2, "signup_email_verified_bonus")
    ]


class DirectSignupFakeSupabaseAuthClient(FakeSupabaseAuthClient):
    def sign_up(
        self, *, email: str, password: str, phone_number: str, captcha_token: str
    ) -> dict:
        self.signed_up.append((email, password, phone_number, captcha_token))
        return {
            "id": "supabase-signup-direct",
            "email": email,
            "user_metadata": {"phone_number": phone_number},
        }


def test_supabase_signup_handles_direct_user_object_response():
    metadata_store = InMemoryMetadataStore()
    auth_client = DirectSignupFakeSupabaseAuthClient()
    store = SupabaseUserStore(metadata_store, auth_client)

    user = store.signup(
        email="direct@example.com",
        phone_number="+15551234567",
        password="temporary-password",
        captcha_token="captcha-token",
    )

    assert user.supabase_user_id == "supabase-signup-direct"
    assert user.email == "direct@example.com"
    assert user.is_active is False


def test_supabase_login_links_existing_email_user():
    metadata_store = InMemoryMetadataStore()
    auth_client = FakeSupabaseAuthClient()
    store = SupabaseUserStore(metadata_store, auth_client)

    # User already exists in metadata store but has no supabase_user_id
    existing_user = metadata_store.create_user(
        name="Qasim Jalil",
        email="qasimjl469@gmail.com",
        password="",
        supabase_user_id="",
    )

    auth_client.sessions[("qasimjl469@gmail.com", "correct-password")] = {
        "user": {
            "id": "supabase-user-new-id",
            "email": "qasimjl469@gmail.com",
            "email_confirmed_at": "2026-06-29T00:00:00Z",
        }
    }

    authenticated = store.authenticate("qasimjl469@gmail.com", "correct-password")

    assert authenticated is not None
    assert authenticated.user_id == existing_user.user_id
    # Verifying that the supabase_user_id got updated
    assert authenticated.supabase_user_id == "supabase-user-new-id"
    assert metadata_store.get(existing_user.user_id).supabase_user_id == "supabase-user-new-id"
