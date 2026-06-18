from dataclasses import dataclass
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx

from app.config import settings
from app.schemas import ExtractionStatus
from app.scrapers.domain import (
    assert_resolves_to_public_ips,
    is_same_site_url,
    normalize_domain,
    validate_public_url,
)
from app.scrapers.http import status_for_http_response


@dataclass(frozen=True)
class RobotsDecision:
    allowed: bool
    status: ExtractionStatus
    robots_url: str
    reason: str = ""


async def can_fetch_url(url: str, user_agent: str | None = None) -> RobotsDecision:
    try:
        safe_url = validate_public_url(url)
        assert_resolves_to_public_ips(normalize_domain(safe_url))
    except ValueError as exc:
        return RobotsDecision(False, ExtractionStatus.NETWORK_FAILED, url, str(exc))

    parsed = urlparse(safe_url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    agent = user_agent or settings.crawler_user_agent
    parser = RobotFileParser()
    parser.set_url(robots_url)

    try:
        async with httpx.AsyncClient(
            timeout=settings.crawl_timeout_seconds,
        ) as client:
            current_url = robots_url
            for _ in range(settings.crawl_max_redirects + 1):
                async with client.stream(
                    "GET",
                    current_url,
                    headers={"User-Agent": agent, "Accept": "text/plain,*/*;q=0.8"},
                ) as response:
                    if 300 <= response.status_code < 400:
                        if "Location" not in response.headers:
                            return RobotsDecision(
                                False,
                                ExtractionStatus.NETWORK_FAILED,
                                robots_url,
                                "robots.txt redirect did not include a destination",
                            )
                        redirected_url = validate_public_url(
                            urljoin(current_url, response.headers["Location"])
                        )
                        if not (
                            is_same_site_url(redirected_url, safe_url)
                            or is_same_site_url(safe_url, redirected_url)
                        ):
                            return RobotsDecision(
                                False,
                                ExtractionStatus.TOS_BLOCKED,
                                robots_url,
                                "robots.txt redirected to a different site",
                            )
                        assert_resolves_to_public_ips(normalize_domain(redirected_url))
                        current_url = redirected_url
                        continue

                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > settings.robots_max_response_bytes:
                            return RobotsDecision(
                                False,
                                ExtractionStatus.PARSE_FAILED,
                                robots_url,
                                "robots.txt exceeded maximum allowed size",
                            )
                    response_status = response.status_code
                    response_encoding = response.encoding
                    break
            else:
                return RobotsDecision(
                    False,
                    ExtractionStatus.NETWORK_FAILED,
                    robots_url,
                    "Maximum robots.txt redirects exceeded",
                )
    except httpx.HTTPError as exc:
        return RobotsDecision(False, ExtractionStatus.NETWORK_FAILED, robots_url, str(exc))
    except ValueError as exc:
        return RobotsDecision(False, ExtractionStatus.NETWORK_FAILED, robots_url, str(exc))

    status = status_for_http_response(response_status)
    if 400 <= response_status < 500 and response_status != 429:
        return RobotsDecision(
            True,
            ExtractionStatus.NO_DATA,
            robots_url,
            f"robots.txt unavailable (HTTP {response_status}); no crawl rules were declared",
        )
    if status != ExtractionStatus.OK:
        return RobotsDecision(
            False,
            status,
            robots_url,
            f"robots.txt returned HTTP {response_status}",
        )

    text = bytes(content).decode(response_encoding or "utf-8", errors="replace")
    parser.parse(text.splitlines())
    allowed = parser.can_fetch(agent, safe_url)
    return RobotsDecision(
        allowed,
        ExtractionStatus.OK if allowed else ExtractionStatus.ROBOTS_DISALLOWED,
        robots_url,
        "allowed" if allowed else "disallowed by robots.txt",
    )
