from app.schemas import ExtractionResult, ExtractionStatus


def detect_lever_url(links: list[str]) -> str | None:
    for link in links:
        if "jobs.lever.co" in link:
            return link
    return None


def lever_placeholder(source_url: str | None = None) -> ExtractionResult:
    return ExtractionResult.unavailable(
        extractor_name="lever_jobs",
        source_url=source_url,
        status=ExtractionStatus.NO_DATA,
        notes=(
            "Lever public postings adapter scaffolded; extraction will be implemented "
            "after URL detection tests."
        ),
    )
