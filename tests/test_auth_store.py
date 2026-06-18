from app.auth.security import (
    create_session_token,
    hash_password,
    read_session_token,
    verify_password,
)
from app.auth.store import FileUserStore


def test_file_user_store_creates_named_users_and_verifies_passwords(tmp_path):
    store = FileUserStore(tmp_path)

    user = store.create_user(
        name="Qasim Tester",
        email="qasim@example.com",
        password="correct horse battery staple",
        role="admin",
    )

    saved = store.get_by_email("QASIM@example.com")
    assert saved is not None
    assert saved.user_id == user.user_id
    assert saved.name == "Qasim Tester"
    assert saved.role == "admin"
    assert verify_password("correct horse battery staple", saved.password_hash)
    assert not verify_password("wrong password", saved.password_hash)


def test_password_hashes_are_salted():
    first = hash_password("same-password")
    second = hash_password("same-password")

    assert first != second
    assert verify_password("same-password", first)
    assert verify_password("same-password", second)


def test_file_user_store_lists_users_without_password_hashes(tmp_path):
    store = FileUserStore(tmp_path)
    store.create_user(
        name="Admin User",
        email="admin@example.com",
        password="admin-password",
        role="admin",
    )
    store.create_user(
        name="Tester User",
        email="tester@example.com",
        password="tester-password",
        role="tester",
    )

    summaries = store.list_users()

    assert [summary.email for summary in summaries] == [
        "admin@example.com",
        "tester@example.com",
    ]
    assert summaries[0].name == "Admin User"
    assert not hasattr(summaries[0], "password_hash")


def test_file_user_store_rejects_duplicate_email(tmp_path):
    store = FileUserStore(tmp_path)
    store.create_user(
        name="First User",
        email="tester@example.com",
        password="first-password",
    )

    try:
        store.create_user(
            name="Second User",
            email="TESTER@example.com",
            password="second-password",
        )
    except ValueError as exc:
        assert "already exists" in str(exc)
    else:
        raise AssertionError("Duplicate email should be rejected")


def test_session_tokens_fail_closed_when_tampered_or_malformed():
    token = create_session_token("user-123")

    assert read_session_token(token) == "user-123"
    assert read_session_token(f"{token}tampered") is None
    assert read_session_token("user.not-a-time.not-a-time.nonce.signature") is None
