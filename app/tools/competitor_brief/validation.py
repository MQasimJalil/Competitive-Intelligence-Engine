import re
from collections import defaultdict

from app.schemas import (
    ExtractionResult,
    ExtractionStatus,
    NormalizedBusinessProfile,
    ValidationIssue,
    ValidationReport,
    ValidationSeverity,
)

_MATERIAL_FAILURES = {
    ExtractionStatus.ROBOTS_DISALLOWED,
    ExtractionStatus.TOS_BLOCKED,
    ExtractionStatus.RATE_LIMITED,
    ExtractionStatus.PARSE_FAILED,
    ExtractionStatus.NETWORK_FAILED,
}
_NEGATIVE_PREFIXES = ("no ", "not ", "does not ", "without ")
_LOW_INFORMATION_VALUES = {
    "about",
    "about us",
    "news",
    "products",
    "shop",
    "shop all",
}


def validate_business_profile(
    results: list[ExtractionResult],
    profile: NormalizedBusinessProfile,
) -> ValidationReport:
    issues: list[ValidationIssue] = []
    excluded: set[str] = set()
    facts_by_id = {fact.citation_id: fact for fact in profile.facts}

    if not profile.facts:
        issues.append(
            ValidationIssue(
                code="no_validated_facts",
                severity=ValidationSeverity.ERROR,
                message="No normalized, source-cited business facts were available.",
            )
        )
    if len(facts_by_id) != len(profile.facts):
        issues.append(
            ValidationIssue(
                code="duplicate_citation_id",
                severity=ValidationSeverity.ERROR,
                message="Normalized facts contain duplicate citation IDs.",
            )
        )

    for offer in profile.offers:
        cited = [facts_by_id[item] for item in offer.citation_ids if item in facts_by_id]
        missing = sorted(set(offer.citation_ids) - facts_by_id.keys())
        if missing:
            issues.append(
                ValidationIssue(
                    code="unknown_offer_citation",
                    severity=ValidationSeverity.ERROR,
                    message=f"Offer {offer.name!r} references unknown citations.",
                    citation_ids=missing,
                )
            )
        source_urls = sorted({str(fact.source_url) for fact in cited})
        if len(source_urls) > 1:
            issues.append(
                ValidationIssue(
                    code="cross_source_offer",
                    severity=ValidationSeverity.ERROR,
                    message=(
                        f"Offer {offer.name!r} combines product and price evidence "
                        "from different pages."
                    ),
                    citation_ids=offer.citation_ids,
                    source_urls=source_urls,
                )
            )

    for result in results:
        if (
            result.status == ExtractionStatus.OK
            and result.confidence >= 0.85
            and result.extractor_name.endswith("_facts")
            and not result.evidence
        ):
            issues.append(
                ValidationIssue(
                    code="high_confidence_without_page_evidence",
                    severity=ValidationSeverity.WARNING,
                    message=(
                        f"{result.extractor_name} is high confidence but has no "
                        "page-level evidence summary."
                    ),
                    source_urls=[str(result.source_url)] if result.source_url else [],
                )
            )

    for fact in profile.facts:
        value = " ".join(fact.value.casefold().split())
        if value in _LOW_INFORMATION_VALUES:
            excluded.add(fact.citation_id)
            issues.append(
                ValidationIssue(
                    code="low_information_fact",
                    severity=ValidationSeverity.INFO,
                    message=f"Excluded low-information fact: {fact.value!r}.",
                    citation_ids=[fact.citation_id],
                    source_urls=[str(fact.source_url)],
                )
            )
        if fact.kind.value == "price" and fact.category.value not in {
            "pricing_packaging",
            "products_modules",
        }:
            excluded.add(fact.citation_id)
            issues.append(
                ValidationIssue(
                    code="price_from_invalid_category",
                    severity=ValidationSeverity.ERROR,
                    message="A price fact did not come from pricing or product evidence.",
                    citation_ids=[fact.citation_id],
                    source_urls=[str(fact.source_url)],
                )
            )

    issues.extend(_find_contradictions(profile))

    failed = [result for result in results if result.status in _MATERIAL_FAILURES]
    if failed:
        issues.append(
            ValidationIssue(
                code="partial_collection",
                severity=ValidationSeverity.WARNING,
                message=f"{len(failed)} collection step(s) were blocked or failed.",
                source_urls=sorted(
                    {str(result.source_url) for result in failed if result.source_url}
                ),
            )
        )

    ready = bool(profile.facts) and not any(
        issue.severity == ValidationSeverity.ERROR for issue in issues
    )
    return ValidationReport(
        ready_for_report=ready,
        checked_fact_count=len(profile.facts),
        issues=issues,
        excluded_citation_ids=sorted(excluded),
        category_fact_counts={
            category: sum(
                fact.category.value == category and fact.citation_id not in excluded
                for fact in profile.facts
            )
            for category in sorted({fact.category.value for fact in profile.facts})
        },
    )


def _find_contradictions(profile: NormalizedBusinessProfile) -> list[ValidationIssue]:
    by_key: dict[tuple[str, str], list] = defaultdict(list)
    for fact in profile.facts:
        polarity, key = _polarity_key(fact.value)
        if key:
            by_key[(fact.kind.value, key)].append((polarity, fact))

    issues = []
    for values in by_key.values():
        polarities = {polarity for polarity, _ in values}
        if polarities != {"negative", "positive"}:
            continue
        facts = [fact for _, fact in values]
        issues.append(
            ValidationIssue(
                code="possible_contradiction",
                severity=ValidationSeverity.WARNING,
                message="Observed facts contain directly opposing public claims.",
                citation_ids=[fact.citation_id for fact in facts],
                source_urls=sorted({str(fact.source_url) for fact in facts}),
            )
        )
    return issues


def _polarity_key(value: str) -> tuple[str, str]:
    normalized = re.sub(r"[^a-z0-9 ]+", " ", value.casefold())
    normalized = " ".join(normalized.split())
    for prefix in _NEGATIVE_PREFIXES:
        if normalized.startswith(prefix):
            return "negative", normalized.removeprefix(prefix)
    return "positive", normalized
