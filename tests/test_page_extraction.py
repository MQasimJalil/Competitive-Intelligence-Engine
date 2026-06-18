import asyncio

import httpx
from app.schemas import CandidateSource, ExtractionStatus, PageCandidate
from app.scrapers.http import FetchResult
from app.scrapers.robots import RobotsDecision
from app.tools.competitor_brief import page_extraction


def _candidate(category: str = "pricing_packaging") -> PageCandidate:
    return PageCandidate(
        url="https://example.com/pricing",
        primary_category=category,
        matched_categories=[category],
        source=CandidateSource.HOMEPAGE_LINK,
        score=147,
        reasons=["test"],
    )


def test_extract_candidate_page_preserves_robots_block(monkeypatch):
    async def blocked(url: str):
        return RobotsDecision(
            allowed=False,
            status=ExtractionStatus.ROBOTS_DISALLOWED,
            robots_url="https://example.com/robots.txt",
            reason="disallowed",
        )

    monkeypatch.setattr(page_extraction, "can_fetch_url", blocked)

    result = asyncio.run(page_extraction.extract_candidate_page(_candidate()))

    assert result.status == ExtractionStatus.ROBOTS_DISALLOWED
    assert result.extractor_name == "pricing_packaging_facts"
    assert result.value is None


def test_extract_candidate_page_returns_observed_structured_fact(monkeypatch):
    async def allowed(url: str):
        return RobotsDecision(
            allowed=True,
            status=ExtractionStatus.OK,
            robots_url="https://example.com/robots.txt",
            reason="allowed",
        )

    async def fetched(url: str):
        return FetchResult(
            text="""
                <main>
                  <h1>Pricing for growing teams</h1>
                  <p>Start free or choose Pro for $20/month.</p>
                  <a href="/signup">Start free</a>
                </main>
            """,
            headers=httpx.Headers({"content-type": "text/html"}),
            final_url=url,
            http_status=200,
        )

    monkeypatch.setattr(page_extraction, "can_fetch_url", allowed)
    monkeypatch.setattr(page_extraction, "fetch_text", fetched)

    result = asyncio.run(page_extraction.extract_candidate_page(_candidate()))

    assert result.status == ExtractionStatus.OK
    assert result.value["headline"] == "Pricing for growing teams"
    assert any(
        claim["fact_type"] == "visible_price" and claim["value"] == "$20/month"
        for claim in result.value["claims"]
    )
    assert result.evidence


def test_extract_ranked_pages_isolates_unexpected_candidate_failure(monkeypatch):
    async def broken(candidate):
        raise RuntimeError("broken parser")

    monkeypatch.setattr(page_extraction, "extract_candidate_page", broken)
    plan = page_extraction.CrawlPlan(selected=[_candidate()], candidate_count=1, selection_limit=1)

    results = asyncio.run(page_extraction.extract_ranked_pages(plan))

    assert len(results) == 1
    assert results[0].status == ExtractionStatus.PARSE_FAILED
