# Golden Report Benchmark

Each directory is a manually researched target report. It defines what a useful,
accurate generated report should approximate from public evidence.

Required files:

- `case.json`: case metadata and scoring weights.
- `source-evidence.json`: reviewed evidence ledger with stable `G###` IDs.
- `required-facts.json`: facts the generated report should include or avoid.
- `golden-report.md`: target customer-facing report, cited to evidence IDs.
- `reviewer-notes.md`: human review guidance and known ambiguities.
- `generated-baseline.md`: current program output captured for comparison.
- `comparison-review.md`: reviewed gap between the baseline and golden target.
- `scorecard.json`: automatic lexical fact-recall and citation-reference score.

Validate all cases:

```powershell
python scripts/validate_golden_benchmarks.py
```

Refresh current generated baselines without AI charges:

```powershell
python scripts/generate_golden_baselines.py
python scripts/score_golden_benchmarks.py
```

Golden reports are not expected to match generated prose word-for-word. They are
targets for factual coverage, prioritization, citation correctness, and business
usefulness.
