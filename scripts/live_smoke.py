import argparse
import asyncio

from app.tools.competitor_brief.service import build_preview_snapshot


async def inspect_domain(domain: str, *, show_claims: bool) -> bool:
    snapshot = await build_preview_snapshot(domain)
    claim_count = (
        sum(len(section.claims) for section in snapshot.profile.sections)
        if snapshot.profile
        else 0
    )
    print(
        f"{domain}: profile={bool(snapshot.profile)} claims={claim_count} "
        f"results={len(snapshot.results)}"
    )
    for result in snapshot.results:
        if result.status.value != "ok":
            print(f"  {result.extractor_name}: {result.status.value} - {result.notes}")
    if show_claims and snapshot.profile:
        for section in snapshot.profile.sections:
            for claim in section.claims:
                print(f"  {section.title}: {claim.value} [{claim.source_url}]")
    return claim_count > 0


async def main(domains: list[str], *, show_claims: bool) -> int:
    outcomes = [await inspect_domain(domain, show_claims=show_claims) for domain in domains]
    return 0 if all(outcomes) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run real-domain crawler smoke checks.")
    parser.add_argument("domains", nargs="+")
    parser.add_argument("--show-claims", action="store_true")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.domains, show_claims=args.show_claims)))
