import asyncio
import json
from pathlib import Path

from app.tools.competitor_brief.service import build_preview_snapshot
from app.tools.competitor_brief.view_model import build_report_view

ROOT = Path("benchmarks/golden")
MIN_FACTS_FOR_BASELINE = 5


async def generate_case(case_dir: Path) -> None:
    case = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
    snapshot = await build_preview_snapshot(case["domain"], enable_ai=False)
    fact_count = len(snapshot.business_profile.facts) if snapshot.business_profile else 0
    if fact_count < MIN_FACTS_FOR_BASELINE:
        statuses = [
            {
                "extractor": result.extractor_name,
                "status": result.status.value,
                "notes": result.notes,
                "source_url": str(result.source_url) if result.source_url else None,
            }
            for result in snapshot.results
        ]
        (case_dir / "last-generation-failure.json").write_text(
            json.dumps(
                {
                    "domain": case["domain"],
                    "normalized_fact_count": fact_count,
                    "minimum_required": MIN_FACTS_FOR_BASELINE,
                    "workflow_state": (
                        snapshot.workflow.state.value if snapshot.workflow else "unknown"
                    ),
                    "results": statuses,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(
            f"  skipped: only {fact_count} normalized facts; "
            "kept the previous generated baseline"
        )
        return
    report = build_report_view(
        snapshot.domain,
        snapshot.results,
        snapshot.profile,
        snapshot.business_profile,
        snapshot.ai_analysis,
        snapshot.ai_analysis_status,
        snapshot.ai_run,
    )
    lines = [
        f"# Generated Baseline: {report.domain}",
        "",
        "AI disabled for benchmark baseline.",
        "",
        "## At A Glance",
        "",
        report.executive.at_a_glance,
        "",
        "## Quick Facts",
        "",
    ]
    lines.extend(f"- **{fact.label}:** {fact.value}" for fact in report.executive.quick_facts)
    for section in report.executive.sections:
        lines.extend(["", f"## {section.title}", ""])
        if section.points:
            lines.extend(
                f"- {point.text} [source {point.source_number}]" for point in section.points
            )
        else:
            lines.append("- Data unavailable")
    lines.extend(["", "## Evidence Gaps", ""])
    lines.extend(f"- {item}" for item in report.executive.unknowns)
    lines.extend(["", "## Sources", ""])
    lines.extend(
        f"- [{source.number}] {source.label}: {source.url}"
        for source in report.executive.sources
    )
    offer_count = len(snapshot.business_profile.offers) if snapshot.business_profile else 0
    lines.extend(
        [
            "",
            "## Baseline Inventory",
            "",
            f"- Normalized facts: {fact_count}",
            f"- Product-price offers: {offer_count}",
            f"- AI status: {snapshot.ai_analysis_status}",
            "",
        ]
    )
    (case_dir / "generated-baseline.md").write_text("\n".join(lines), encoding="utf-8")
    failure_path = case_dir / "last-generation-failure.json"
    if failure_path.exists():
        failure_path.unlink()


async def main() -> None:
    cases = sorted(path for path in ROOT.iterdir() if path.is_dir())
    for index, case_dir in enumerate(cases, start=1):
        print(f"[{index}/{len(cases)}] {case_dir.name}")
        await generate_case(case_dir)


if __name__ == "__main__":
    asyncio.run(main())
