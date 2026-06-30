# stonebranch-analysis-pack analysis pack

This folder is a self-contained analysis pack for `stonebranch`.

## Start here

1. `report.md` - human-readable summary.
2. `graph.json` - full machine-readable graph.
3. `metrics.json` - graph metrics.
4. `indexes/node-index.json` - lookup by id, name, kind, canonical key.
5. `indexes/adjacency.json` - outgoing dependency index.
6. `indexes/reverse-adjacency.json` - incoming dependency index.
7. `graphs/*.mmd` - Mermaid graph views.
8. `reports/top-connected.md` - most connected objects.
9. `reports/orphans.md` - isolated objects.

## Important note

`graph.json` is the source of truth. Indexes and graph views are generated from it and can be regenerated.
