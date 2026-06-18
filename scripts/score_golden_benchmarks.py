import json
from pathlib import Path

from app.benchmarking.golden_scorer import score_golden_case

ROOT = Path("benchmarks/golden")


if __name__ == "__main__":
    scores = []
    for case_dir in sorted(path for path in ROOT.iterdir() if path.is_dir()):
        requirements = json.loads(
            (case_dir / "required-facts.json").read_text(encoding="utf-8")
        )
        score = score_golden_case(case_dir, requirements)
        (case_dir / "scorecard.json").write_text(
            score.model_dump_json(indent=2),
            encoding="utf-8",
        )
        scores.append(score)
        print(
            f"{score.domain}: required={score.required_fact_recall:.0%}, "
            f"important={score.important_fact_recall:.0%}, "
            f"citations={score.citation_reference_validity:.0%}"
        )
    print(
        "Average required fact recall: "
        f"{sum(item.required_fact_recall for item in scores) / max(1, len(scores)):.0%}"
    )
