import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from app.benchmarking import score_snapshot
from app.schemas import BusinessFactKind
from app.tools.competitor_brief.service import build_preview_snapshot


async def run(manifest_path: Path, output_path: Path, limit: int | None) -> None:
    cases = json.loads(manifest_path.read_text(encoding="utf-8"))
    if limit:
        cases = cases[:limit]
    scores = []
    for index, case in enumerate(cases, start=1):
        print(f"[{index}/{len(cases)}] {case['domain']}")
        try:
            snapshot = await build_preview_snapshot(case["domain"], enable_ai=False)
            score = score_snapshot(
                snapshot,
                expected_kinds=[BusinessFactKind(item) for item in case["expected_kinds"]],
                minimum_facts=case["minimum_facts"],
            )
            scored = score.model_dump(mode="json")
            scored["manual_review"] = {
                "clarity_1_to_5": None,
                "decision_usefulness_1_to_5": None,
                "evidence_selection_1_to_5": None,
                "reviewer_notes": "",
            }
            scores.append(scored)
        except Exception as exc:
            scores.append({"domain": case["domain"], "error": str(exc)})

    valid = [item for item in scores if "usefulness_proxy" in item]
    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "manifest": str(manifest_path),
        "case_count": len(scores),
        "successful_cases": len(valid),
        "average_usefulness_proxy": round(
            sum(item["usefulness_proxy"] for item in valid) / max(1, len(valid)), 4
        ),
        "scores": scores,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Saved {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run the deterministic competitor-brief benchmark."
    )
    parser.add_argument("--manifest", type=Path, default=Path("benchmarks/domains.json"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmark-results/latest.json"),
    )
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    asyncio.run(run(args.manifest, args.output, args.limit))
