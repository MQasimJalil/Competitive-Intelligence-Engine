import asyncio
from dataclasses import dataclass

from app.config import settings
from app.schemas import (
    CrawlPlan,
    ExtractionResult,
    ExtractionStatus,
    PageCandidate,
    SourceType,
)
from app.scrapers.discovery import discover_homepage_candidates
from app.scrapers.gtm_facts import extract_gtm_page_fact
from app.scrapers.http import FetchError, fetch_text
from app.scrapers.rendered import fetch_rendered_text
from app.scrapers.robots import can_fetch_url


async def extract_ranked_pages(plan: CrawlPlan) -> list[ExtractionResult]:
    semaphore = asyncio.Semaphore(settings.crawl_concurrency)

    async def extract_with_limit(candidate: PageCandidate) -> ExtractionResult:
        async with semaphore:
            try:
                return await extract_candidate_page(candidate)
            except Exception as exc:
                return ExtractionResult.unavailable(
                    extractor_name=f"{candidate.primary_category}_facts",
                    source_url=str(candidate.url),
                    status=ExtractionStatus.PARSE_FAILED,
                    notes=f"Unexpected extraction failure: {exc}",
                )

    return await asyncio.gather(*(extract_with_limit(candidate) for candidate in plan.selected))


@dataclass(frozen=True)
class ExtractionBatch:
    results: list[ExtractionResult]
    discovered_candidates: list[PageCandidate]


async def extract_ranked_pages_with_candidates(plan: CrawlPlan) -> ExtractionBatch:
    semaphore = asyncio.Semaphore(settings.crawl_concurrency)

    async def extract_with_limit(
        candidate: PageCandidate,
    ) -> tuple[ExtractionResult, list[PageCandidate]]:
        async with semaphore:
            try:
                return await _extract_candidate_page(candidate)
            except Exception as exc:
                return (
                    ExtractionResult.unavailable(
                        extractor_name=f"{candidate.primary_category}_facts",
                        source_url=str(candidate.url),
                        status=ExtractionStatus.PARSE_FAILED,
                        notes=f"Unexpected extraction failure: {exc}",
                    ),
                    [],
                )

    extracted = await asyncio.gather(
        *(extract_with_limit(candidate) for candidate in plan.selected)
    )
    return ExtractionBatch(
        results=[result for result, _ in extracted],
        discovered_candidates=[
            candidate for _, candidates in extracted for candidate in candidates
        ],
    )


async def extract_candidate_page(candidate: PageCandidate) -> ExtractionResult:
    result, _ = await _extract_candidate_page(candidate)
    return result


async def _extract_candidate_page(
    candidate: PageCandidate,
) -> tuple[ExtractionResult, list[PageCandidate]]:
    source_url = str(candidate.url)
    robots = await can_fetch_url(source_url)
    if not robots.allowed and robots.status != ExtractionStatus.NO_DATA:
        return (
            ExtractionResult.unavailable(
                extractor_name=f"{candidate.primary_category}_facts",
                source_url=source_url,
                status=robots.status,
                notes=f"Selected page was not fetched: {robots.reason}",
            ),
            [],
        )

    try:
        fetched = await fetch_text(source_url)
    except FetchError as exc:
        return (
            ExtractionResult.unavailable(
                extractor_name=f"{candidate.primary_category}_facts",
                source_url=exc.source_url,
                status=exc.status,
                notes=str(exc),
                final_url=exc.final_url,
                http_status=exc.http_status,
            ),
            [],
        )
    except ValueError as exc:
        return (
            ExtractionResult.unavailable(
                extractor_name=f"{candidate.primary_category}_facts",
                source_url=source_url,
                status=ExtractionStatus.NETWORK_FAILED,
                notes=str(exc),
            ),
            [],
        )

    fact = extract_gtm_page_fact(fetched.text, fetched.final_url, candidate.primary_category)
    if settings.rendered_browser_enabled and not fact.headline and not fact.claims:
        try:
            rendered = await fetch_rendered_text(fetched.final_url)
            fact = extract_gtm_page_fact(
                rendered.text,
                rendered.final_url,
                candidate.primary_category,
            )
            fetched = fetched.__class__(
                text=rendered.text,
                headers=fetched.headers,
                final_url=rendered.final_url,
                http_status=rendered.http_status,
            )
        except FetchError:
            pass
    if not fact.headline and not fact.claims:
        return (
            ExtractionResult.unavailable(
                extractor_name=f"{candidate.primary_category}_facts",
                source_url=source_url,
                final_url=fetched.final_url,
                http_status=fetched.http_status,
                notes="The page loaded but exposed no usable visible business facts.",
            ),
            discover_homepage_candidates(fetched.text, fetched.final_url),
        )

    evidence = " | ".join(claim.evidence_excerpt for claim in fact.claims[:4])
    confidence = 0.85 if fact.headline and len(fact.claims) >= 3 else 0.7
    return (
        ExtractionResult(
            value=fact.model_dump(mode="json"),
            source_url=source_url,
            final_url=fetched.final_url,
            http_status=fetched.http_status,
            extractor_name=f"{candidate.primary_category}_facts",
            confidence=confidence,
            status=ExtractionStatus.OK,
            source_type=SourceType.HTML,
            notes=(
                f"Observed facts extracted from the selected {candidate.primary_category} page. "
                "No business interpretation has been added."
            ),
            evidence=evidence[:1000],
        ),
        discover_homepage_candidates(fetched.text, fetched.final_url),
    )
