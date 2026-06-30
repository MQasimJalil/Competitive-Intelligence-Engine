from pathlib import Path


def test_compose_backend_database_url_uses_container_postgres_by_default():
    compose = Path("compose.yaml").read_text(encoding="utf-8")

    assert "DATABASE_URL: ${COMPOSE_DATABASE_URL:-" in compose
    assert "@postgres:5432/competitor_brief}" in compose
