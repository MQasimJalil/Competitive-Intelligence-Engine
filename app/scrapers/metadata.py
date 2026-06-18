from bs4 import BeautifulSoup

from app.schemas import ExtractionResult, ExtractionStatus


def extract_page_metadata(html: str, source_url: str) -> list[ExtractionResult]:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.string.strip() if soup.title and soup.title.string else ""
    description_tag = soup.find("meta", attrs={"name": "description"})
    if not description_tag:
        description_tag = soup.find("meta", attrs={"property": "og:description"})
    description = description_tag.get("content", "").strip() if description_tag else ""
    h1 = soup.find("h1")
    headline = h1.get_text(" ", strip=True) if h1 else ""
    if not headline:
        og_title = soup.find("meta", attrs={"property": "og:title"})
        headline = og_title.get("content", "").strip() if og_title else ""

    results: list[ExtractionResult] = []
    for name, value, confidence in [
        ("page_title", title, 0.9),
        ("meta_description", description, 0.85),
        ("homepage_headline", headline, 0.8),
    ]:
        if value:
            results.append(
                ExtractionResult(
                    value=value,
                    source_url=source_url,
                    extractor_name=name,
                    confidence=confidence,
                    status=ExtractionStatus.OK,
                )
            )
        else:
            results.append(ExtractionResult.unavailable(extractor_name=name, source_url=source_url))
    return results
