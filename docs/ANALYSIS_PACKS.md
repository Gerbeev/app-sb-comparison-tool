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
graphs/README.md
canonical-graph.json
graph.html
graph-data.js
cytoscape.min.js
cytoscape.LICENSE
containers.json
```

## Comparison pack

The comparison pack contains:

```text
compare-pack-manifest.json
compare/report.md
compare/comparison.json
compare/metrics.json
compare/edge-diff.csv
compare/command-diff.csv
compare/compare-graph.html
compare/compare-graph-data.js
compare/cytoscape.min.js
compare/cytoscape.LICENSE
compare/critical-diff.json
compare/diff-index.json
compare/remediation-plan.md
```

Use `remediation-plan.md` as a checklist for fixing migration gaps. Use `compare/compare-graph.html` as the offline visual overlay for matched, missing, critical, command-difference, and condition-difference statuses.

## Graph visualization

Mermaid `.mmd` graph exports have been fully decommissioned. For large repositories, use source-pack `graph.html` for the offline interactive HTML graph powered by bundled Cytoscape.js, comparison-pack `compare/compare-graph.html` for visual migration status overlay, and `canonical-graph.json`, `containers.json`, `objects.csv`, `edges.csv`, and `dependency-graph.dot` for deterministic review and diff tools. The HTML reports include a bundled `cytoscape.min.js` runtime, relation filters, status filters, quick `Problems` / `Critical` / `Missing` buttons, visible graph counters, and side-panel status counts so large graphs can be narrowed before expanding all workflow/box groups.

The HTML side panel also includes copyable node IDs, graph IDs, edge keys, relation evidence, source/target navigation, and URL-hash deep links for selected nodes/edges.
