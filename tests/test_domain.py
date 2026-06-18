import pytest
from app.scrapers.domain import (
    homepage_url,
    is_same_site_url,
    normalize_domain,
    validate_public_url,
)


def test_normalize_domain_removes_scheme_and_www():
    assert normalize_domain("https://www.Example.com/pricing") == "example.com"


def test_homepage_url_uses_https():
    assert homepage_url("example.com") == "https://example.com"


def test_normalize_domain_rejects_empty():
    with pytest.raises(ValueError):
        normalize_domain("   ")


@pytest.mark.parametrize(
    "raw",
    [
        "localhost",
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "[::1]",
        "https://example.com@127.0.0.1",
        "ftp://example.com",
    ],
)
def test_normalize_domain_rejects_non_public_targets(raw):
    with pytest.raises(ValueError):
        normalize_domain(raw)


def test_validate_public_url_preserves_canonical_host():
    assert (
        validate_public_url("https://www.Example.com/pricing") == "https://www.example.com/pricing"
    )


def test_validate_public_url_rejects_nonstandard_ports():
    with pytest.raises(ValueError):
        validate_public_url("https://example.com:8443/pricing")


def test_is_same_site_url_allows_subdomains_and_rejects_external():
    assert is_same_site_url("https://jobs.example.com/openings", "https://example.com")
    assert not is_same_site_url("https://evil-example.com/pricing", "https://example.com")
