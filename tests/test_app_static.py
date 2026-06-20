from app.main import app
from fastapi.testclient import TestClient


def test_static_assets_get_cache_headers():
    client = TestClient(app)

    response = client.get("/static/styles.css")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=86400"
