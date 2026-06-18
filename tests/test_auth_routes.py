from app.auth.store import FileUserStore
from app.jobs.store import FileJobStore
from app.main import app
from app.schemas import JobStatus
from app.tools.competitor_brief import router as router_module
from app.tools.competitor_brief.service import CompetitorSnapshot
from app.web import auth as web_auth
from fastapi.testclient import TestClient


def _configure_auth(monkeypatch, tmp_path):
    user_store = FileUserStore(tmp_path / "users")
    job_store = FileJobStore(tmp_path / "jobs")
    monkeypatch.setattr(web_auth, "user_store", user_store)
    monkeypatch.setattr(router_module, "user_store", user_store)
    monkeypatch.setattr(router_module, "job_store", job_store)
    return user_store, job_store


def _login(client: TestClient, email: str, password: str):
    return client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )


def test_history_requires_login(tmp_path, monkeypatch):
    _configure_auth(monkeypatch, tmp_path)
    client = TestClient(app)

    response = client.get("/tools/competitor-brief/history", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/auth/login")


def test_logged_in_user_sees_only_their_own_library(tmp_path, monkeypatch):
    user_store, job_store = _configure_auth(monkeypatch, tmp_path)
    user = user_store.create_user(
        name="Tester One",
        email="tester@example.com",
        password="tester-password",
    )
    visible = job_store.create("visible.example", owner_id=user.user_id)
    hidden = job_store.create("hidden.example", owner_id="another-user")
    client = TestClient(app)

    login_response = _login(client, "tester@example.com", "tester-password")
    response = client.get("/tools/competitor-brief/history")

    assert login_response.status_code == 303
    assert response.status_code == 200
    assert "visible.example" in response.text
    assert "hidden.example" not in response.text
    assert visible.job_id in response.text
    assert hidden.job_id not in response.text


def test_non_admin_cannot_open_admin_dashboard(tmp_path, monkeypatch):
    user_store, _job_store = _configure_auth(monkeypatch, tmp_path)
    user_store.create_user(
        name="Tester One",
        email="tester@example.com",
        password="tester-password",
        role="tester",
    )
    client = TestClient(app)
    _login(client, "tester@example.com", "tester-password")

    response = client.get("/tools/competitor-brief/admin")

    assert response.status_code == 403


def test_admin_dashboard_shows_user_names_without_report_subjects(tmp_path, monkeypatch):
    user_store, job_store = _configure_auth(monkeypatch, tmp_path)
    admin = user_store.create_user(
        name="Admin User",
        email="admin@example.com",
        password="admin-password",
        role="admin",
    )
    tester = user_store.create_user(
        name="Tester User",
        email="tester@example.com",
        password="tester-password",
    )
    job_store.create("secret-target.example", owner_id=tester.user_id, ai_requested=True)
    admin_job = job_store.create("admin-target.example", owner_id=admin.user_id)
    admin_job.status = JobStatus.COMPLETE
    job_store.save(admin_job)
    client = TestClient(app)
    _login(client, "admin@example.com", "admin-password")

    response = client.get("/tools/competitor-brief/admin")

    assert response.status_code == 200
    assert "Admin User" in response.text
    assert "Tester User" in response.text
    assert "secret-target.example" not in response.text
    assert "admin-target.example" not in response.text


def test_admin_can_create_named_tester_account(tmp_path, monkeypatch):
    user_store, _job_store = _configure_auth(monkeypatch, tmp_path)
    user_store.create_user(
        name="Admin User",
        email="admin@example.com",
        password="admin-password",
        role="admin",
    )
    client = TestClient(app)
    _login(client, "admin@example.com", "admin-password")

    response = client.post(
        "/tools/competitor-brief/admin/users",
        data={
            "name": "Research Tester",
            "email": "tester@example.com",
            "password": "tester-password",
            "role": "tester",
        },
        follow_redirects=False,
    )

    saved = user_store.get_by_email("tester@example.com")
    assert response.status_code == 303
    assert response.headers["location"] == "/tools/competitor-brief/admin"
    assert saved is not None
    assert saved.name == "Research Tester"
    assert saved.role == "tester"


def test_admin_cannot_open_another_users_report_by_job_id(tmp_path, monkeypatch):
    user_store, job_store = _configure_auth(monkeypatch, tmp_path)
    user_store.create_user(
        name="Admin User",
        email="admin@example.com",
        password="admin-password",
        role="admin",
    )
    tester = user_store.create_user(
        name="Tester User",
        email="tester@example.com",
        password="tester-password",
    )
    job = job_store.create("private-target.example", owner_id=tester.user_id)
    snapshot = CompetitorSnapshot(
        domain="private-target.example",
        homepage="https://private-target.example/",
        results=[],
    )
    job_store.save_artifacts(
        job.job_id,
        snapshot_json=snapshot.model_dump_json(),
        pdf=b"%PDF",
        evidence_pdf=b"%PDF",
    )
    client = TestClient(app)
    _login(client, "admin@example.com", "admin-password")

    response = client.get(f"/tools/competitor-brief/jobs/{job.job_id}/report")

    assert response.status_code == 404
    assert "private-target.example" not in response.text
