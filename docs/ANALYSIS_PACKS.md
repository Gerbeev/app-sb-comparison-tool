# Analysis packs

The pack workflow separates parsing from comparison.

## Recommended flow

1. Build Stonebranch analysis pack.
2. Build JIL analysis pack.
3. Compare analysis packs.

This avoids reparsing repositories for every comparison and creates stable folders for review.

## Stonebranch analysis pack

Contains the full Stonebranch graph, indexes, graph views, and detailed source-side reports.

## JIL analysis pack

Contains the full JIL graph, indexes, graph views, and detailed source-side reports.

## Comparison analysis pack

Contains the detailed mismatch analysis and remediation checklist.

Start with:

```text
compare/report.md
compare/metrics.json
compare/critical-diff.json
compare/remediation-plan.md
```

`remediation-plan.md` is intentionally formatted as a checklist so it can be used to close gaps one by one.
