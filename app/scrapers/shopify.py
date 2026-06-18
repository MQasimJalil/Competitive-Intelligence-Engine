import json
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin

from app.schemas import (
    BusinessCategory,
    ExtractionResult,
    ExtractionStatus,
    ObservedClaim,
    SourceType,
)
from app.scrapers.domain import homepage_url
from app.scrapers.http import FetchError, fetch_text
from app.scrapers.robots import can_fetch_url

SHOPIFY_PRODUCTS_LIMIT = 50


def shopify_products_url(domain: str) -> str:
    return f"{homepage_url(domain).rstrip('/')}/products.json?limit={SHOPIFY_PRODUCTS_LIMIT}"


async def fetch_shopify_products(domain: str) -> ExtractionResult:
    url = shopify_products_url(domain)
    robots = await can_fetch_url(url)
    if not robots.allowed and robots.status != ExtractionStatus.NO_DATA:
        return ExtractionResult.unavailable(
            extractor_name="shopify_product_catalog",
            source_url=url,
            status=robots.status,
            notes=robots.reason,
        )
    try:
        fetched = await fetch_text(
            url,
            allowed_content_types=(
                "application/json",
                "text/json",
                "text/plain",
                "application/javascript",
            ),
            accept="application/json,*/*;q=0.8",
        )
    except FetchError as exc:
        return ExtractionResult.unavailable(
            extractor_name="shopify_product_catalog",
            source_url=exc.source_url,
            status=exc.status,
            notes=str(exc),
            final_url=exc.final_url,
            http_status=exc.http_status,
        )
    return parse_shopify_products(fetched.text, fetched.final_url, fetched.http_status)


def parse_shopify_products(
    payload: str,
    source_url: str,
    http_status: int | None = None,
) -> ExtractionResult:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        return ExtractionResult.unavailable(
            extractor_name="shopify_product_catalog",
            source_url=source_url,
            status=ExtractionStatus.PARSE_FAILED,
            notes=f"Shopify product feed was not valid JSON: {exc.msg}",
            http_status=http_status,
        )

    products = data.get("products") if isinstance(data, dict) else None
    if not isinstance(products, list) or not products:
        return ExtractionResult.unavailable(
            extractor_name="shopify_product_catalog",
            source_url=source_url,
            notes="No products were listed in the public Shopify catalog feed.",
            http_status=http_status,
        )

    claims: list[ObservedClaim] = []
    for product in products[:SHOPIFY_PRODUCTS_LIMIT]:
        if not isinstance(product, dict):
            continue
        title = _clean(product.get("title"))
        handle = _clean(product.get("handle"))
        if not title or not handle:
            continue
        product_url = _product_url(source_url, handle)
        claims.append(
            _claim(
                "linked_product",
                title,
                title,
                product_url,
                "Public Shopify product catalog item",
            )
        )
        price_band = _variant_price_band(product.get("variants"))
        if price_band:
            claims.append(
                _claim(
                    "catalog_price",
                    price_band,
                    f"{title} {price_band}",
                    product_url,
                    "Public Shopify product variant price without a verified currency",
                )
            )

    if not claims:
        return ExtractionResult.unavailable(
            extractor_name="shopify_product_catalog",
            source_url=source_url,
            notes="No usable product titles were listed in the public Shopify catalog feed.",
            http_status=http_status,
        )

    return ExtractionResult(
        value={
            "category": BusinessCategory.PRODUCTS_MODULES,
            "page_url": source_url,
            "page_title": "Public Shopify product catalog",
            "headline": "Public Shopify product catalog",
            "claims": [claim.model_dump(mode="json") for claim in claims],
        },
        source_url=source_url,
        final_url=source_url,
        http_status=http_status,
        extractor_name="shopify_product_catalog",
        confidence=0.88,
        status=ExtractionStatus.OK,
        source_type=SourceType.PUBLIC_FEED,
        notes=(
            f"Parsed {len([claim for claim in claims if claim.fact_type == 'linked_product'])} "
            "public Shopify product listings."
        ),
        evidence=" | ".join(claim.evidence_excerpt for claim in claims[:6])[:1000],
    )


def _claim(
    fact_type: str,
    value: str,
    excerpt: str,
    source_url: str,
    context: str,
) -> ObservedClaim:
    return ObservedClaim(
        category=BusinessCategory.PRODUCTS_MODULES,
        fact_type=fact_type,
        value=value,
        evidence_excerpt=excerpt,
        source_url=source_url,
        context=context,
    )


def _product_url(source_url: str, handle: str) -> str:
    return urljoin(source_url, f"/products/{handle}")


def _variant_price_band(raw_variants) -> str:
    if not isinstance(raw_variants, list):
        return ""
    prices: list[Decimal] = []
    for variant in raw_variants:
        if not isinstance(variant, dict):
            continue
        raw_price = variant.get("price")
        if raw_price is None:
            continue
        try:
            prices.append(Decimal(str(raw_price)))
        except InvalidOperation:
            continue
    if not prices:
        return ""
    low, high = min(prices), max(prices)
    if low == high:
        return _format_decimal(low)
    return f"{_format_decimal(low)} - {_format_decimal(high)}"


def _format_decimal(value: Decimal) -> str:
    return f"{value.normalize():f}".rstrip("0").rstrip(".")


def _clean(value) -> str:
    return " ".join(str(value or "").split())
