# Agent prompt — Item 8: HTML/UI — skeleton mode, derived edges, watcher tracing

You are implementing Item 8 of `GRAPH_SKELETON_IMPLEMENTATION_PLAN.md`. Item 7 is merged: `window.GRAPH_DATA` now has `files`, `skeleton` (layers/scc/derived_edges/criticality), edge `derived`/`inference` fields, schema `1.1`. All work is inside the `CYTOSCAPE_HTML` template string in `stonebranch_graph/html_graph.py`.

## Token budget rules
This file is ~1000 lines; the template is the second half. Read `html_graph.py` from the `CYTOSCAPE_HTML` definition to the end ONCE; before that, read only the payload-shape section of Item 7's test (`tests/test_html_graph_payload.py`) if present. Do not read parsers, compare, skeleton internals. No new JS libraries — the report must stay offline with the bundled `cytoscape.min.js`. Keep existing controls working; extend, don't rewrite.

## Task
1. **Mode toggle** `Full | Skeleton` button next to Expand/Collapse. Skeleton mode: only job-like nodes + dependency edges + `skeleton.derived_edges`; layout = `breadthfirst`-style using precomputed `skeleton.layers` (set node positions by layer column: x = layer * const, y = stable ordering within layer) — do not run force layout in skeleton mode.
2. **Derived edges**: `line-style: dashed`, dedicated color, `opacity: 0.4 + 0.6*confidence`, tooltip/details panel shows `inference` and confidence. Add `data_flow` checkbox to the relation filter (reuse `visibleCategories` plumbing).
3. **Watcher tracing**: clicking a `file_watcher` node highlights (existing highlight/selection classes): its file (full mode), producer jobs (via derived edges or `files[].producers`), and direct dependents. Add classification badge to watcher labels: `⇦ext` / `⇦int` / `⇦?` from `files[].classification`.
4. **Criticality**: node width/height scaled `20 + 30*criticality` px; new quick filter button `Top core` showing top-50 by criticality + edges among them.
5. **SCC overlay**: nodes sharing non-trivial `scc` id get a red border class; add warning count to the header stats.
6. Legend/help placeholder text: one line each for dashed = inferred data dependency, badges, Top core.

## Acceptance
Regenerate the report on `examples/` (`python -m stonebranch_graph.cli` — check `cli.py` `--help` output for the exact subcommand rather than reading the file). Open-in-browser is unavailable; instead assert structurally: generated `graph.html` contains the new control ids, and a quick node-count sanity via `grep -c`. All existing ids (`relationFilter`, `statusFilter`, `expand`, `collapse`) untouched. Report: list of new UI control ids + template line-count delta only.
