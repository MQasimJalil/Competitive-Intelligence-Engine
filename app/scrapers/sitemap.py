from dataclasses import dataclass, field
from urllib.parse import urljoin
from xml.etree import ElementTree

import httpx

from app.config import settings
from app.schemas import ExtractionStatus
from app.scrapers.domain import (
    assert_resolves_to_public_ips,
    homepage_url,
    is_same_site_url,
    normalize_domain,
    validate_public_url,
)
from app.scrapers.http import status_for_http_response


@dataclass(frozen=True)
class SitemapResult:
    urls: list[str]
    sitemap_url: str
    status: ExtractionStatus
    notes: str
    child_sitemaps: list[str] = field(default_factory=list)
    final_url: str | None = None
    http_status: int | None = None


async def fetch_sitemap(domain: str) -> SitemapResult:
    base_url = homepage_url(normalize_domain(domain))
    current_url = f"{base_url}/sitemap.xml"
    headers = {"User-Agent": settings.crawler_user_agent, "Accept": "application/xml,text/xml"}

    try:
        assert_resolves_to_public_ips(normalize_domain(current_url))
        async with httpx.AsyncClient(timeout=settings.crawl_timeout_seconds) as client:
            for _ in range(settings.crawl_max_redirects + 1):
                response = await client.get(current_url, headers=headers, follow_redirects=False)
                if 300 <= response.status_code < 400 and "Location" in response.headers:
                    redirected_url = urljoin(current_url, response.headers["Location"])
                    redirected_url = validate_public_url(redirected_url)
                    if not (
                        is_same_site_url(redirected_url, base_url)
                        or is_same_site_url(base_url, redirected_url)
                    ):
                        return SitemapResult(
                            urls=[],
                            sitemap_url=f"{base_url}/sitemap.xml",
                            status=ExtractionStatus.TOS_BLOCKED,
                            notes="Sitemap redirected to a different site",
                            final_url=redirected_url,
                            http_status=response.status_code,
                        )
                    current_url = redirected_url
                    assert_resolves_to_public_ips(normalize_domain(current_url))
                    continue
                parsed = _parse_sitemap_response(
                    response=response,
                    sitemap_url=f"{base_url}/sitemap.xml",
                    base_url=base_url,
                )
                if not parsed.child_sitemaps:
                    return parsed

                urls: list[str] = []
                for child_url in parsed.child_sitemaps[:10]:
                    if len(urls) >= settings.crawl_max_sitemap_urls:
                        break
                    assert_resolves_to_public_ips(normalize_domain(child_url))
                    child_response = await client.get(
                        child_url,
                        headers=headers,
                        follow_redirects=False,
                    )
                    child = _parse_sitemap_response(
                        response=child_response,
                        sitemap_url=child_url,
                        base_url=base_url,
                    )
                    for discovered_url in child.urls:
                        if discovered_url not in urls:
                            urls.append(discovered_url)
                        if len(urls) >= settings.crawl_max_sitemap_urls:
                            break
                return SitemapResult(
                    urls=urls,
                    sitemap_url=parsed.sitemap_url,
                    status=ExtractionStatus.OK if urls else ExtractionStatus.NO_DATA,
                    notes=(
                        f"Found {len(urls)} URLs across "
                        f"{len(parsed.child_sitemaps[:10])} child sitemaps"
                    ),
                    child_sitemaps=parsed.child_sitemaps,
                    final_url=parsed.final_url,
                    http_status=parsed.http_status,
                )
    except (httpx.HTTPError, ValueError) as exc:
        return SitemapResult(
            urls=[],
            sitemap_url=f"{base_url}/sitemap.xml",
            status=ExtractionStatus.NETWORK_FAILED,
            notes=str(exc),
            final_url=current_url,
        )

    return SitemapResult(
        urls=[],
        sitemap_url=f"{base_url}/sitemap.xml",
        status=ExtractionStatus.NETWORK_FAILED,
        notes="Maximum sitemap redirects exceeded",
        final_url=current_url,
    )


def _parse_sitemap_response(
    *,
    response: httpx.Response,
    sitemap_url: str,
    base_url: str,
) -> SitemapResult:
    status = status_for_http_response(response.status_code)
    if status != ExtractionStatus.OK:
        return SitemapResult(
            urls=[],
            sitemap_url=sitemap_url,
            status=status,
            notes=f"HTTP {response.status_code}",
            final_url=str(response.url),
            http_status=response.status_code,
        )
    if len(response.content) > settings.crawl_max_response_bytes:
        return SitemapResult(
            urls=[],
            sitemap_url=sitemap_url,
            status=ExtractionStatus.PARSE_FAILED,
            notes="Sitemap exceeded maximum allowed size",
            final_url=str(response.url),
            http_status=response.status_code,
        )

    try:
        root = ElementTree.fromstring(response.content)
    except ElementTree.ParseError as exc:
        return SitemapResult(
            urls=[],
            sitemap_url=sitemap_url,
            status=ExtractionStatus.PARSE_FAILED,
            notes=f"Invalid sitemap XML: {exc}",
            final_url=str(response.url),
            http_status=response.status_code,
        )

    is_index = root.tag.endswith("sitemapindex")
    urls: list[str] = []
    child_sitemaps: list[str] = []
    for element in root.iter():
        if not element.tag.endswith("loc") or not element.text:
            continue
        raw_url = element.text.strip()
        if not is_same_site_url(raw_url, base_url):
            continue
        try:
            safe_url = validate_public_url(raw_url)
        except ValueError:
            continue
        target = child_sitemaps if is_index else urls
        if safe_url not in target:
            target.append(safe_url)
        if len(target) == settings.crawl_max_sitemap_urls:
            break

    return SitemapResult(
        urls=urls,
        sitemap_url=sitemap_url,
        status=ExtractionStatus.OK if urls or child_sitemaps else ExtractionStatus.NO_DATA,
        notes=(
            f"Found {len(child_sitemaps)} child sitemaps"
            if child_sitemaps
            else f"Found {len(urls)} same-site sitemap URLs"
            if urls
            else "No usable URLs found"
        ),
        child_sitemaps=child_sitemaps,
        final_url=str(response.url),
        http_status=response.status_code,
    )


async def fetch_sitemap_urls(domain: str) -> list[str]:
    return (await fetch_sitemap(domain)).urls
