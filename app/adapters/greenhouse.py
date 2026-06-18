from app.schemas import ExtractionResult, ExtractionStatus


def detect_greenhouse_url(links: list[str]) -> str | None:
    for link in links:
        if "boards.greenhouse.io" in link or "job-boards.greenhouse.io" in link:
            return link
    return None


def greenhouse_placeholder(source_url: str | None = None) -> ExtractionResult:
    return ExtractionResult.unavailable(
        extractor_name="greenhouse_jobs",
        source_url=source_url,
        status=ExtractionStatus.NO_DATA,
        notes=(
            "Greenhouse public Job Board API adapter scaffolded; extraction will be "
            "implemented after URL detection tests."
        ),
    )
