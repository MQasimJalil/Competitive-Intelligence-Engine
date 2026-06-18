from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin
from xml.etree import ElementTree

import httpx
from bs4 import BeautifulSoup

from app.config import settings
from app.schemas import (
    BusinessCategory,
    ExtractionResult,
    ExtractionStatus,
    ObservedClaim,
    SourceType,
)
from app.scrapers.domain import (
    assert_resolves_to_public_ips,
    is_same_site_url,
    normalize_domain,
    validate_public_url,
)

_FEED_TYPES = {"application/rss+xml", "application/atom+xml"}


def discover_feed_urls(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    feeds: list[str] = []
    for link in soup.find_all("link", href=True):
        rel = {str(value).casefold() for value in link.get("rel", [])}
        feed_type = str(link.get("type", "")).casefold()
        if "alternate" not in rel or feed_type not in _FEED_TYPES:
            continue
        try:
            url = validate_public_url(urljoin(base_url, link["href"]))
        except ValueError:
            continue
        if is_same_site_url(url, base_url) and url not in feeds:
            feeds.append(url)
    return feeds[:3]


async def fetch_recent_activity(feed_urls: list[str]) -> ExtractionResult:
    claims: list[ObservedClaim] = []
    source_url = feed_urls[0] if feed_urls else None
    try:
        async with httpx.AsyncClient(timeout=settings.crawl_timeout_seconds) as client:
            for feed_url in feed_urls[:3]:
                assert_resolves_to_public_ips(normalize_domain(feed_url))
                response = await client.get(
                    feed_url,
                    headers={
                        "User-Agent": settings.crawler_user_agent,
                        "Accept": (
                            "application/rss+xml,application/atom+xml,application/xml,text/xml"
                        ),
                    },
                    follow_redirects=False,
                )
                if response.status_code != 200:
                    continue
                claims.extend(_parse_feed(response.content, feed_url))
    except (httpx.HTTPError, ValueError) as exc:
        return ExtractionResult.unavailable(
            extractor_name="recent_activity_facts",
            source_url=source_url,
            status=ExtractionStatus.NETWORK_FAILED,
            notes=str(exc),
        )

    if not claims:
        return ExtractionResult.unavailable(
            extractor_name="recent_activity_facts",
            source_url=source_url,
            notes="No dated RSS or Atom activity was found.",
        )
    return ExtractionResult(
        value={"claims": [claim.model_dump(mode="json") for claim in claims[:8]]},
        source_url=source_url,
        extractor_name="recent_activity_facts",
        confidence=0.9,
        status=ExtractionStatus.OK,
        source_type=SourceType.PUBLIC_FEED,
        notes="Dated public activity extracted from RSS or Atom feeds.",
        evidence=" | ".join(claim.evidence_excerpt for claim in claims[:4])[:1000],
    )


def _parse_feed(content: bytes, feed_url: str) -> list[ObservedClaim]:
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError:
        return []

    claims: list[ObservedClaim] = []
    for entry in root.iter():
        if not (entry.tag.endswith("item") or entry.tag.endswith("entry")):
            continue
        title = _child_text(entry, {"title"})
        raw_date = _child_text(entry, {"pubDate", "published", "updated"})
        published = _parse_date(raw_date)
        if not title or published is None:
            continue
        date_label = published.date().isoformat()
        claims.append(
            ObservedClaim(
                category=BusinessCategory.RECENT_MOVES,
                fact_type="dated_activity",
                value=f"{title} ({date_label})"[:500],
                evidence_excerpt=f"{title} — {raw_date}"[:1000],
                source_url=feed_url,
                retrieved_at=datetime.now(UTC),
                context="Public RSS/Atom entry",
            )
        )
        if len(claims) == 8:
            break
    return claims


def _child_text(element: ElementTree.Element, names: set[str]) -> str:
    for child in element:
        if any(child.tag.endswith(name) for name in names) and child.text:
            return " ".join(child.text.split())
    return ""


def _parse_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
