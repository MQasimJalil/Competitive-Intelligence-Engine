from app.schemas import ExtractionResult, ExtractionStatus, SourceType
from app.tools.competitor_brief.service import _collect_social_links


def test_collect_social_links_keeps_instagram_and_linkedin_only():
    results = [
        ExtractionResult(
            value=[
                "https://www.instagram.com/example/",
                "https://www.linkedin.com/company/example/",
                "https://x.com/example",
            ],
            source_url="https://example.com",
            extractor_name="structured_social_links",
            confidence=0.9,
            status=ExtractionStatus.OK,
            source_type=SourceType.HTML,
        )
    ]

    assert _collect_social_links(results) == [
        "https://www.instagram.com/example/",
        "https://www.linkedin.com/company/example/",
    ]
