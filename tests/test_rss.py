from app.adapters.rss import _parse_feed, discover_feed_urls


def test_discover_feed_urls_keeps_same_site_rss():
    html = """
    <link rel="alternate" type="application/rss+xml" href="/feed.xml">
    <link rel="alternate" type="application/rss+xml" href="https://external.com/feed.xml">
    """

    assert discover_feed_urls(html, "https://example.com") == ["https://example.com/feed.xml"]


def test_parse_feed_creates_dated_activity_claim():
    claims = _parse_feed(
        b"""
        <rss><channel><item>
          <title>Junior Series launched</title>
          <pubDate>Mon, 01 Jun 2026 10:00:00 GMT</pubDate>
        </item></channel></rss>
        """,
        "https://example.com/feed.xml",
    )

    assert claims[0].fact_type == "dated_activity"
    assert claims[0].value == "Junior Series launched (2026-06-01)"
