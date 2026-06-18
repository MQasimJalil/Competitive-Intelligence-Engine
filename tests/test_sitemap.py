import httpx
from app.schemas import ExtractionStatus
from app.scrapers.sitemap import _parse_sitemap_response


def _response(content: bytes, status_code: int = 200) -> httpx.Response:
    request = httpx.Request("GET", "https://example.com/sitemap.xml")
    return httpx.Response(status_code, content=content, request=request)


def test_parse_sitemap_keeps_only_same_site_urls():
    response = _response(
        b"""
        <urlset>
          <url><loc>https://example.com/pricing</loc></url>
          <url><loc>https://example.com/product</loc></url>
          <url><loc>https://external.com/pricing</loc></url>
        </urlset>
        """
    )

    result = _parse_sitemap_response(
        response=response,
        sitemap_url="https://example.com/sitemap.xml",
        base_url="https://example.com",
    )

    assert result.status == ExtractionStatus.OK
    assert result.urls == ["https://example.com/pricing", "https://example.com/product"]


def test_parse_sitemap_reports_invalid_xml():
    result = _parse_sitemap_response(
        response=_response(b"<urlset><broken>"),
        sitemap_url="https://example.com/sitemap.xml",
        base_url="https://example.com",
    )

    assert result.status == ExtractionStatus.PARSE_FAILED
    assert result.urls == []


def test_parse_sitemap_maps_missing_sitemap_to_no_data():
    result = _parse_sitemap_response(
        response=_response(b"", status_code=404),
        sitemap_url="https://example.com/sitemap.xml",
        base_url="https://example.com",
    )

    assert result.status == ExtractionStatus.NO_DATA


def test_parse_sitemap_index_returns_child_sitemaps():
    result = _parse_sitemap_response(
        response=_response(
            b"""
            <sitemapindex>
              <sitemap><loc>https://example.com/products.xml</loc></sitemap>
              <sitemap><loc>https://external.com/pages.xml</loc></sitemap>
            </sitemapindex>
            """
        ),
        sitemap_url="https://example.com/sitemap.xml",
        base_url="https://example.com",
    )

    assert result.status == ExtractionStatus.OK
    assert result.urls == []
    assert result.child_sitemaps == ["https://example.com/products.xml"]
