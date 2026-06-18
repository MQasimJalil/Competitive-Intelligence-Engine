from bs4 import BeautifulSoup

from app.schemas import ExtractionResult, ExtractionStatus, SourceType

SIGNATURES = {
    "Next.js hint": ("__next", "_next/static", "__NEXT_DATA__"),
    "Nuxt hint": ("__nuxt", "_nuxt/"),
    "Shopify hint": ("cdn.shopify.com", "Shopify.theme"),
    "Webflow hint": ("webflow", "data-wf-page"),
    "WordPress hint": ("wp-content", "wp-includes"),
    "HubSpot hint": ("hubspot", "hs-scripts"),
    "Segment hint": ("segment.com/analytics", "analytics.js"),
    "Intercom hint": ("intercom", "widget.intercom.io"),
    "Cloudflare hint": ("cloudflare",),
    "Vercel hint": ("vercel",),
}


def detect_tech_signals(html: str, headers: dict[str, str], source_url: str) -> ExtractionResult:
    soup = BeautifulSoup(html, "html.parser")
    haystack = " ".join(
        [
            html[:200_000],
            " ".join(str(tag.get("src", "")) for tag in soup.find_all("script")),
            " ".join(str(tag.get("href", "")) for tag in soup.find_all("link")),
            " ".join(f"{key}: {value}" for key, value in headers.items()),
        ]
    ).lower()
    matches = [
        name
        for name, needles in SIGNATURES.items()
        if any(needle.lower() in haystack for needle in needles)
    ]
    if not matches:
        return ExtractionResult.unavailable(
            extractor_name="tech_signals",
            source_url=source_url,
            notes="No public tech stack hints detected",
        )
    return ExtractionResult(
        value={"label": "Tech stack hints", "hints": matches},
        source_url=source_url,
        extractor_name="tech_signals",
        confidence=0.65,
        status=ExtractionStatus.OK,
        source_type=SourceType.MIXED_PUBLIC_SIGNALS,
        notes=(
            "Signals are hints from public HTML, scripts, and headers; not guaranteed stack facts."
        ),
    )
