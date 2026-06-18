from dataclasses import dataclass

from bs4 import BeautifulSoup
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

from app.config import settings
from app.schemas import ExtractionStatus
from app.scrapers.domain import (
    assert_resolves_to_public_ips,
    is_same_site_url,
    normalize_domain,
    validate_public_url,
)
from app.scrapers.http import FetchError, status_for_http_response


@dataclass(frozen=True)
class RenderedFetchResult:
    text: str
    final_url: str
    http_status: int


def has_sparse_business_html(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    root = soup.find("main") or soup.body or soup
    visible = root.get_text(" ", strip=True)
    business_nodes = root.find_all(["h1", "h2", "h3", "p", "a"])
    return len(visible) < 300 and len(business_nodes) < 5


async def fetch_rendered_text(url: str) -> RenderedFetchResult:
    source_url = validate_public_url(url)
    assert_resolves_to_public_ips(normalize_domain(source_url))
    timeout_ms = int(settings.rendered_browser_timeout_seconds * 1000)

    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                channel=settings.rendered_browser_channel or None,
                headless=True,
            )
            context = await browser.new_context(user_agent=settings.crawler_user_agent)
            page = await context.new_page()

            async def guard_request(route, request) -> None:
                if request.resource_type in {"image", "media", "font"}:
                    await route.abort()
                    return
                if request.is_navigation_request():
                    try:
                        safe_url = validate_public_url(request.url)
                        if not (
                            is_same_site_url(safe_url, source_url)
                            or is_same_site_url(source_url, safe_url)
                        ):
                            await route.abort()
                            return
                        assert_resolves_to_public_ips(normalize_domain(safe_url))
                    except ValueError:
                        await route.abort()
                        return
                await route.continue_()

            await page.route("**/*", guard_request)
            response = await page.goto(
                source_url,
                wait_until="domcontentloaded",
                timeout=timeout_ms,
            )
            if response is None:
                raise FetchError(
                    ExtractionStatus.NETWORK_FAILED,
                    "Rendered browser returned no document response",
                    source_url=source_url,
                )

            status = status_for_http_response(response.status)
            if status != ExtractionStatus.OK:
                raise FetchError(
                    status,
                    f"Rendered browser received HTTP {response.status}",
                    source_url=source_url,
                    final_url=page.url,
                    http_status=response.status,
                )

            await page.wait_for_timeout(1_000)
            final_url = validate_public_url(page.url)
            if not (
                is_same_site_url(final_url, source_url) or is_same_site_url(source_url, final_url)
            ):
                raise FetchError(
                    ExtractionStatus.TOS_BLOCKED,
                    "Rendered browser navigated to a different site",
                    source_url=source_url,
                    final_url=final_url,
                    http_status=response.status,
                )
            html = await page.content()
            await context.close()
            await browser.close()
            return RenderedFetchResult(html, final_url, response.status)
    except FetchError:
        raise
    except PlaywrightTimeoutError as exc:
        raise FetchError(
            ExtractionStatus.NETWORK_FAILED,
            "Rendered browser timed out",
            source_url=source_url,
        ) from exc
    except PlaywrightError as exc:
        raise FetchError(
            ExtractionStatus.NETWORK_FAILED,
            f"Rendered browser failed: {exc}",
            source_url=source_url,
        ) from exc
