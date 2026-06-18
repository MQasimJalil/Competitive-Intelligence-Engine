import argparse
import asyncio
from pathlib import Path

from app.reporting.pdf import render_competitor_pdf
from app.tools.competitor_brief.service import build_preview_snapshot
from app.tools.competitor_brief.view_model import build_report_view


async def generate(domain: str, output: Path) -> Path:
    snapshot = await build_preview_snapshot(domain)
    report = build_report_view(
        snapshot.domain,
        snapshot.results,
        snapshot.profile,
        snapshot.business_profile,
        snapshot.ai_analysis,
        snapshot.ai_analysis_status,
        snapshot.ai_run,
    )
    return render_competitor_pdf(report, output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate a one-page competitor snapshot PDF.")
    parser.add_argument("domain")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/pdf/competitor-snapshot.pdf"),
    )
    args = parser.parse_args()
    print(asyncio.run(generate(args.domain, args.output)))
