import json
import re
from pathlib import Path

ROOT = Path("benchmarks/golden")
REQUIRED_FILES = {
    "case.json",
    "source-evidence.json",
    "required-facts.json",
    "golden-report.md",
    "reviewer-notes.md",
    "generated-baseline.md",
    "comparison-review.md",
    "scorecard.json",
}


def validate_case(case_dir: Path) -> list[str]:
    errors = []
    missing = REQUIRED_FILES - {path.name for path in case_dir.iterdir() if path.is_file()}
    if missing:
        errors.append(f"{case_dir.name}: missing {sorted(missing)}")
        return errors

    case = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
    evidence = json.loads((case_dir / "source-evidence.json").read_text(encoding="utf-8"))
    requirements = json.loads((case_dir / "required-facts.json").read_text(encoding="utf-8"))
    report = (case_dir / "golden-report.md").read_text(encoding="utf-8")

    evidence_ids = {item["id"] for item in evidence}
    if len(evidence_ids) != len(evidence):
        errors.append(f"{case_dir.name}: duplicate evidence IDs")
    if case.get("domain") != case_dir.name:
        errors.append(f"{case_dir.name}: case domain does not match directory")

    referenced = set(re.findall(r"G\d{3}", report))
    unknown_report_refs = referenced - evidence_ids
    if unknown_report_refs:
        errors.append(f"{case_dir.name}: unknown report refs {sorted(unknown_report_refs)}")
    if not referenced:
        errors.append(f"{case_dir.name}: golden report has no evidence references")

    for group in ("required", "important"):
        for item in requirements.get(group, []):
            unknown = set(item.get("evidence_ids", [])) - evidence_ids
            if unknown:
                errors.append(f"{case_dir.name}: unknown {group} refs {sorted(unknown)}")
    return errors


if __name__ == "__main__":
    all_errors = []
    cases = [path for path in ROOT.iterdir() if path.is_dir()]
    for directory in sorted(cases):
        all_errors.extend(validate_case(directory))
    if all_errors:
        raise SystemExit("\n".join(all_errors))
    print(f"Validated {len(cases)} golden benchmark cases.")
