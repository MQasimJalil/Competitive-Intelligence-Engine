from app.main import app
from fastapi.testclient import TestClient


def test_static_assets_get_cache_headers():
    client = TestClient(app)

    response = client.get("/static/styles.css")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=86400"


def test_stylesheet_has_mobile_layout_regression_guards():
    client = TestClient(app)

    response = client.get("/static/styles.css")

    assert response.status_code == 200
    assert "Mobile layout regression guards" in response.text
    assert ".split-hero {" in response.text
    assert "grid-template-columns: 1fr !important;" in response.text
    assert "overflow-x: clip;" in response.text
    assert "content: attr(data-label);" in response.text
