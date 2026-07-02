# Analysis packs

Analysis packs separate parsing from comparison.

## Why packs

For large repositories, one-shot comparison is harder to debug. Packs give you stable folders that can be:

- inspected independently,
- archived as snapshots,
- compared repeatedly without reparsing source repositories,
- shared internally as JSON/CSV/Markdown artifacts.

## Flow

```text
Stonebranch repo  → Stonebranch analysis pack
JIL repo          → JIL analysis pack
Both packs        → Comparison analysis pack
```

## Stonebranch/JIL pack

Each source pack contains:

```text
README.md
pack-manifest.json
graph.json
metrics.json
objects.csv
edges.csv
indexes/
graphs/
reports/
```

Important files:

```text
graph.json
indexes/node-index.json
indexes/adjacency.json
reports/top-connected.md
reports/orphans.md
graphs/dependencies-only.mmd
```

## Comparison pack

The comparison pack contains:

```text
compare-pack-manifest.json
compare/report.md
compare/comparison.json
compare/metrics.json
compare/edge-diff.csv
compare/critical-diff.json
compare/diff-index.json
compare/remediation-plan.md
```

Use `remediation-plan.md` as a checklist for fixing migration gaps.
