from app.scrapers.rendered import has_sparse_business_html


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
