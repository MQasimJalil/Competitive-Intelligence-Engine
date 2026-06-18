import httpx
import pytest
from app.schemas import ExtractionStatus
from app.scrapers.robots import RobotsDecision, can_fetch_url


def test_robots_decision_can_represent_disallowed():
    decision = RobotsDecision(
        allowed=False,
        status=ExtractionStatus.ROBOTS_DISALLOWED,
        robots_url="https://example.com/robots.txt",
        reason="disallowed by robots.txt",
    )
    assert not decision.allowed
    assert decision.status == ExtractionStatus.ROBOTS_DISALLOWED


def test_robots_network_failure_is_not_allowed():
    decision = RobotsDecision(
        allowed=False,
        status=ExtractionStatus.NETWORK_FAILED,
        robots_url="https://example.com/robots.txt",
        reason="network failed",
    )
    assert not decision.allowed


@pytest.mark.anyio
async def test_robots_403_is_unavailable_not_an_explicit_disallow(monkeypatch):
    def fake_resolve(host: str) -> None:
        return None

    transport = httpx.MockTransport(lambda request: httpx.Response(403, request=request))

    class MockClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            super().__init__(transport=transport)

    monkeypatch.setattr("app.scrapers.robots.assert_resolves_to_public_ips", fake_resolve)
    monkeypatch.setattr("app.scrapers.robots.httpx.AsyncClient", MockClient)

    decision = await can_fetch_url("https://example.com")

    assert decision.allowed
    assert decision.status == ExtractionStatus.NO_DATA
