import json

from app.schemas import ExtractionStatus, ObservedClaim
from app.scrapers.shopify import parse_shopify_products


def test_shopify_product_feed_creates_real_product_claims_without_guessing_currency():
    payload = {
        "products": [
            {
                "title": f"Lunar glove {index}",
                "handle": f"lunar-glove-{index}",
                "variants": [{"price": "25.00"}],
            }
            for index in range(1, 21)
        ]
    }

    result = parse_shopify_products(
        json.dumps(payload),
        "https://sologk.com/products.json?limit=50",
        200,
    )

    assert result.status == ExtractionStatus.OK
    claims = [ObservedClaim.model_validate(raw) for raw in result.value["claims"]]
    product_claims = [claim for claim in claims if claim.fact_type == "linked_product"]
    catalog_prices = [claim for claim in claims if claim.fact_type == "catalog_price"]
    visible_prices = [claim for claim in claims if claim.fact_type == "visible_price"]

    assert len(product_claims) == 20
    assert product_claims[0].value == "Lunar glove 1"
    assert str(product_claims[0].source_url) == "https://sologk.com/products/lunar-glove-1"
    assert catalog_prices[0].value == "25"
    assert visible_prices == []


def test_shopify_product_feed_returns_unavailable_for_invalid_json():
    result = parse_shopify_products("{", "https://example.com/products.json", 200)

    assert result.status == ExtractionStatus.PARSE_FAILED
