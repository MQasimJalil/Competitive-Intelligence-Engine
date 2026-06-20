import pytest
from app.schemas import ExtractionResult, ExtractionStatus
from app.tools.competitor_brief.service import describe_collection_failure


@pytest.mark.parametrize(
    ("status", "http_status", "notes", "expected"),
    [
        (
            ExtractionStatus.TOS_BLOCKED,
            403,
            "HTTP 403",
            "The site denied automated access (HTTP 403).",
        ),
        (
            ExtractionStatus.NO_DATA,
            404,
            "HTTP 404",
            "The homepage was not found (HTTP 404). The site may have moved.",
        ),
        (
            ExtractionStatus.NETWORK_FAILED,
            503,
            "HTTP 503",
            "The site returned a server error (HTTP 503).",
        ),
        (
            ExtractionStatus.NETWORK_FAILED,
            None,
            "Domain could not be resolved",
            "We couldn't find that domain. Check the spelling or try the company's main website.",
        ),
        (
            ExtractionStatus.NETWORK_FAILED,
            None,
            "The request timed out",
            "The site did not respond before the connection timed out.",
        ),
        (
            ExtractionStatus.ROBOTS_DISALLOWED,
            None,
            "Disallowed by robots.txt",
            "The site does not allow this page to be crawled under its robots policy.",
        ),
    ],
)
def test_describe_collection_failure_returns_specific_user_message(
    status, http_status, notes, expected
):
    result = ExtractionResult.unavailable(
        extractor_name="homepage_fetch",
        source_url="https://example.com/",
        status=status,
        http_status=http_status,
        notes=notes,
    )

    assert describe_collection_failure([result]) == expected
