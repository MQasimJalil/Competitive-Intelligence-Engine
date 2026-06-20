from app.scrapers.rendered import has_sparse_business_html, rendered_request_is_allowed


def test_sparse_business_html_detects_javascript_shell():
    assert has_sparse_business_html("<html><body><div id='app'></div></body></html>")


def test_sparse_business_html_accepts_useful_server_rendered_page():
    html = """
    <main>
      <h1>Built for modern teams</h1>
      <h2>Automate reporting</h2>
      <p>Coordinate work and ship faster across every department.</p>
      <p>Trusted by thousands of companies around the world.</p>
      <a href="/pricing">See pricing</a>
    </main>
    """
    assert not has_sparse_business_html(html)


def test_rendered_browser_blocks_private_subresource_destinations(monkeypatch):
    monkeypatch.setattr("app.scrapers.rendered.assert_resolves_to_public_ips", lambda host: None)

    assert not rendered_request_is_allowed(
        "http://169.254.169.254/latest/meta-data",
        "https://example.com",
        resource_type="script",
        is_navigation=False,
    )


def test_rendered_browser_allows_public_subresource_destinations(monkeypatch):
    monkeypatch.setattr("app.scrapers.rendered.assert_resolves_to_public_ips", lambda host: None)

    assert rendered_request_is_allowed(
        "https://cdn.example-assets.com/app.js",
        "https://example.com",
        resource_type="script",
        is_navigation=False,
    )


def test_rendered_browser_blocks_cross_site_navigation(monkeypatch):
    monkeypatch.setattr("app.scrapers.rendered.assert_resolves_to_public_ips", lambda host: None)

    assert not rendered_request_is_allowed(
        "https://unrelated.example",
        "https://example.com",
        resource_type="document",
        is_navigation=True,
    )
