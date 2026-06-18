from dataclasses import dataclass
from urllib.parse import urljoin

import httpx

from app.config import settings
from app.schemas import ExtractionStatus
from app.scrapers.domain import (
    assert_resolves_to_public_ips,
    is_same_site_url,
    normalize_domain,
    validate_public_url,
)

_ALLOWED_HTML_TYPES = (
    "text/html",
    "application/xhtml+xml",
)


@dataclass(frozen=True)
class FetchResult:
    text: str
    headers: httpx.Headers
    final_url: str
    http_status: int


class FetchError(Exception):
    def __init__(
        self,
        status: ExtractionStatus,
        message: str,
        *,
        source_url: str,
        final_url: str | None = None,
        http_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.source_url = source_url
        self.final_url = final_url
        self.http_status = http_status


def status_for_http_response(status_code: int) -> ExtractionStatus:
    if status_code == 404:
        return ExtractionStatus.NO_DATA
    if status_code == 429:
        return ExtractionStatus.RATE_LIMITED
    if status_code in {401, 403}:
        return ExtractionStatus.TOS_BLOCKED
    if status_code >= 500:
        return ExtractionStatus.NETWORK_FAILED
    if status_code >= 400:
        return ExtractionStatus.NETWORK_FAILED
    return ExtractionStatus.OK


async def fetch_text(
    url: str,
    *,
    allowed_content_types: tuple[str, ...] = _ALLOWED_HTML_TYPES,
    accept: str = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
) -> FetchResult:
    current_url = validate_public_url(url)
    assert_resolves_to_public_ips(normalize_domain(current_url))
    headers = {
        "User-Agent": settings.crawler_user_agent,
        "Accept": accept,
        "Accept-Language": "en-US,en;q=0.8",
        "Cache-Control": "no-cache",
    }

    try:
        async with httpx.AsyncClient(timeout=settings.crawl_timeout_seconds) as client:
            for _ in range(settings.crawl_max_redirects + 1):
                async with client.stream("GET", current_url, headers=headers) as response:
                    if 300 <= response.status_code < 400:
                        if "Location" not in response.headers:
                            raise FetchError(
                                ExtractionStatus.NETWORK_FAILED,
                                "Redirect response did not include a destination",
                                source_url=url,
                                final_url=str(response.url),
                                http_status=response.status_code,
                            )
                        redirected_url = validate_public_url(
                            urljoin(current_url, response.headers["Location"])
                        )
                        if not (
                            is_same_site_url(redirected_url, url)
                            or is_same_site_url(url, redirected_url)
                        ):
                            raise FetchError(
                                ExtractionStatus.TOS_BLOCKED,
                                "Cross-origin redirect was not followed",
                                source_url=url,
                                final_url=redirected_url,
                                http_status=response.status_code,
                            )
                        assert_resolves_to_public_ips(normalize_domain(redirected_url))
                        current_url = redirected_url
                        continue

                    status = status_for_http_response(response.status_code)
                    if status != ExtractionStatus.OK:
                        raise FetchError(
                            status,
                            f"HTTP {response.status_code}",
                            source_url=url,
                            final_url=str(response.url),
                            http_status=response.status_code,
                        )

                    content_type = response.headers.get("content-type", "").lower()
                    if not any(
                        content_type.startswith(allowed) for allowed in allowed_content_types
                    ):
                        raise FetchError(
                            ExtractionStatus.PARSE_FAILED,
                            f"Unsupported content type: {content_type or 'unknown'}",
                            source_url=url,
                            final_url=str(response.url),
                            http_status=response.status_code,
                        )

                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > settings.crawl_max_response_bytes:
                            raise FetchError(
                                ExtractionStatus.PARSE_FAILED,
                                "Response exceeded maximum allowed size",
                                source_url=url,
                                final_url=str(response.url),
                                http_status=response.status_code,
                            )
                        chunks.append(chunk)

                    encoding = response.encoding or "utf-8"
                    text = b"".join(chunks).decode(encoding, errors="replace")
                    return FetchResult(
                        text,
                        response.headers,
                        str(response.url),
                        response.status_code,
                    )
    except FetchError:
        raise
    except httpx.HTTPError as exc:
        raise FetchError(
            ExtractionStatus.NETWORK_FAILED,
            str(exc),
            source_url=url,
            final_url=current_url,
        ) from exc

    raise FetchError(
        ExtractionStatus.NETWORK_FAILED,
        "Maximum redirects exceeded",
        source_url=url,
        final_url=current_url,
    )
