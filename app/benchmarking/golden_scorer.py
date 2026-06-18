import re
from pathlib import Path

from pydantic import BaseModel, Field

_STOPWORDS = {
    "and",
    "are",
    "at",
    "for",
    "from",
    "has",
    "its",
    "of",
    "on",
    "the",
    "through",
    "to",
    "with",
}


class GoldenFactScore(BaseModel):
    fact: str
    coverage: float = Field(ge=0.0, le=1.0)
    matched: bool


class GoldenScorecard(BaseModel):
    domain: str
    required_fact_recall: float = Field(ge=0.0, le=1.0)
    important_fact_recall: float = Field(ge=0.0, le=1.0)
    forbidden_claim_avoidance: float = Field(ge=0.0, le=1.0)
    citation_reference_validity: float = Field(ge=0.0, le=1.0)
    required_facts: list[GoldenFactScore]
    important_facts: list[GoldenFactScore]
    forbidden_claims_found: list[str]


def score_golden_case(case_dir: Path, requirements: dict) -> GoldenScorecard:
    baseline = (case_dir / "generated-baseline.md").read_text(encoding="utf-8")
    required = [_fact_score(item["fact"], baseline) for item in requirements.get("required", [])]
    important = [_fact_score(item["fact"], baseline) for item in requirements.get("important", [])]
    forbidden_found = [
        claim
        for claim in requirements.get("must_not_claim", [])
        if _positive_claim_found(claim, baseline)
    ]
    return GoldenScorecard(
        domain=case_dir.name,
        required_fact_recall=_recall(required),
        important_fact_recall=_recall(important),
        forbidden_claim_avoidance=(
            1 - len(forbidden_found) / max(1, len(requirements.get("must_not_claim", [])))
        ),
        citation_reference_validity=_citation_validity(baseline),
        required_facts=required,
        important_facts=important,
        forbidden_claims_found=forbidden_found,
    )


def _fact_score(fact: str, baseline: str) -> GoldenFactScore:
    coverage = _coverage(fact, baseline)
    return GoldenFactScore(fact=fact, coverage=coverage, matched=coverage >= 0.45)


def _coverage(fact: str, baseline: str) -> float:
    expected = _tokens(fact)
    observed = _tokens(baseline)
    return round(len(expected.intersection(observed)) / max(1, len(expected)), 4)


def _positive_claim_found(claim: str, baseline: str) -> bool:
    for sentence in re.split(r"[\n.!?]+", baseline):
        if _coverage(claim, sentence) >= 0.75 and not re.search(
            r"\b(no|not|never|unavailable|unclear)\b",
            sentence,
            re.IGNORECASE,
        ):
            return True
    return False


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value.casefold())
        if len(token) > 2 and token not in _STOPWORDS
    }


def _recall(items: list[GoldenFactScore]) -> float:
    return round(sum(item.matched for item in items) / max(1, len(items)), 4)


def _citation_validity(baseline: str) -> float:
    referenced = {int(item) for item in re.findall(r"\[source (\d+)\]", baseline)}
    declared = {int(item) for item in re.findall(r"^- \[(\d+)\]", baseline, re.MULTILINE)}
    if not referenced:
        return 0.0
    return round(len(referenced.intersection(declared)) / len(referenced), 4)
