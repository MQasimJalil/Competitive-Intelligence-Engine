import httpx
import pytest
from app.schemas import ExtractionStatus
from app.scrapers.robots import RobotsDecision, can_fetch_url, clear_robots_cache


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


@pytest.mark.anyio
async def test_robots_parser_is_cached_per_origin_and_user_agent(monkeypatch):
    clear_robots_cache()
    calls = 0

    def fake_resolve(host: str) -> None:
        return None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            text="User-agent: *\nDisallow: /private\n",
            request=request,
        )

    class MockClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            super().__init__(transport=httpx.MockTransport(handler))

    monkeypatch.setattr("app.scrapers.robots.assert_resolves_to_public_ips", fake_resolve)
    monkeypatch.setattr("app.scrapers.robots.httpx.AsyncClient", MockClient)

    first = await can_fetch_url("https://example.com/pricing", user_agent="bot-a")
    second = await can_fetch_url("https://example.com/features", user_agent="bot-a")
    third = await can_fetch_url("https://example.com/private/page", user_agent="bot-a")

    assert calls == 1
    assert first.allowed
    assert second.allowed
    assert not third.allowed
