import json
from collections.abc import Iterable

from bs4 import BeautifulSoup

from app.schemas import (
    BusinessCategory,
    ExtractionResult,
    ExtractionStatus,
    ObservedClaim,
    SourceType,
)
from app.scrapers.domain import validate_public_url

_ORGANIZATION_TYPES = {"organization", "corporation", "localbusiness", "brand"}
_PRODUCT_TYPES = {"product", "productgroup", "itemlist", "collectionpage"}
_SOCIAL_HOSTS = {
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "tiktok.com",
    "x.com",
    "youtube.com",
}


def extract_structured_data(html: str, source_url: str) -> list[ExtractionResult]:
    soup = BeautifulSoup(html, "html.parser")
    claims: list[ObservedClaim] = []
    social_links: list[str] = []

    for payload in _json_ld_payloads(soup):
        for node in _walk_nodes(payload):
            types = _node_types(node)
            if types & _ORGANIZATION_TYPES:
                _append_text_claim(
                    claims,
                    node.get("description"),
                    BusinessCategory.POSITIONING,
                    "structured_description",
                    source_url,
                )
                for link in _as_strings(node.get("sameAs")):
                    try:
                        safe_link = validate_public_url(link)
                    except ValueError:
                        continue
                    if safe_link not in social_links:
                        social_links.append(safe_link)
            if types & _PRODUCT_TYPES:
                _append_text_claim(
                    claims,
                    node.get("name"),
                    BusinessCategory.PRODUCTS_MODULES,
                    "structured_product",
                    source_url,
                )

    for anchor in soup.find_all("a", href=True):
        try:
            safe_link = validate_public_url(anchor["href"])
        except ValueError:
            continue
        host = safe_link.split("/")[2].removeprefix("www.")
        if host in _SOCIAL_HOSTS and safe_link not in social_links:
            social_links.append(safe_link)

    results: list[ExtractionResult] = []
    if claims:
        results.append(
            ExtractionResult(
                value={"claims": [claim.model_dump(mode="json") for claim in claims[:12]]},
                source_url=source_url,
                extractor_name="structured_data_facts",
                confidence=0.9,
                status=ExtractionStatus.OK,
                source_type=SourceType.HTML,
                notes="Observed facts extracted from public JSON-LD structured data.",
                evidence=" | ".join(claim.evidence_excerpt for claim in claims[:4])[:1000],
            )
        )
    if social_links:
        results.append(
            ExtractionResult(
                value=social_links[:12],
                source_url=source_url,
                extractor_name="structured_social_links",
                confidence=0.9,
                status=ExtractionStatus.OK,
                source_type=SourceType.HTML,
                notes="Public social/profile links declared in JSON-LD.",
            )
        )
    return results


def _json_ld_payloads(soup: BeautifulSoup) -> Iterable[object]:
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        text = script.string or script.get_text()
        if not text.strip():
            continue
        try:
            yield json.loads(text)
        except json.JSONDecodeError:
            continue


def _walk_nodes(value: object) -> Iterable[dict]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_nodes(child)


def _node_types(node: dict) -> set[str]:
    raw = node.get("@type", [])
    values = raw if isinstance(raw, list) else [raw]
    return {str(value).casefold() for value in values}


def _as_strings(value: object) -> list[str]:
    values = value if isinstance(value, list) else [value]
    return [item for item in values if isinstance(item, str)]


def _append_text_claim(
    claims: list[ObservedClaim],
    value: object,
    category: BusinessCategory,
    fact_type: str,
    source_url: str,
) -> None:
    if not isinstance(value, str):
        return
    normalized = " ".join(value.split()).strip()
    if not normalized or any(claim.value.casefold() == normalized.casefold() for claim in claims):
        return
    claims.append(
        ObservedClaim(
            category=category,
            fact_type=fact_type,
            value=normalized[:500],
            evidence_excerpt=normalized[:1000],
            source_url=source_url,
            context="Public JSON-LD",
        )
    )
