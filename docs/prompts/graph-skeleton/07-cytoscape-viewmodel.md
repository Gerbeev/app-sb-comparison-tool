# Agent prompt — Item 7: Cytoscape view-model extension

You are implementing Item 7 of `GRAPH_SKELETON_IMPLEMENTATION_PLAN.md`. Items 1–5 are merged (`skeleton.py`, `semantic_core.py`, `producers.py` exist). Goal: extend the data payload behind `graph.html` — data side only, NO JS/HTML changes (that is Item 8).

## Token budget rules
Read ONLY: `stonebranch_graph/html_graph.py` lines 1–260 (stop before `CYTOSCAPE_HTML`), `stonebranch_graph/skeleton.py` and `semantic_core.py` public dataclasses, `domain.py` constants. Do not read the embedded HTML/JS template, compare.py, tui. Minimal diff.

## Task
In `build_cytoscape_graph_data`:
1. `relation_category`: map `REL_PRODUCES_FILE` and `REL_DATA_DEPENDS_ON` → `"data_flow"` (keep `watches_file` → `"files"`).
2. Add top-level `files` array: for each `KIND_FILE` node — `{id, key, pattern, raw_path, watchers: [job keys], producers: [{job_key, inference, confidence}], classification}` where classification = `"internal"` (≥1 producer), `"external"` (0), `"ambiguous"` (>1 producer or any T3 producer).
3. Add top-level `skeleton` object built from `build_skeleton(graph)` + `score_skeleton`: `{layers: {job_key: int}, scc: {job_key: scc_id} (non-trivial only), derived_edges: [same edge payload shape as `edges`, with derived:true, inference, confidence], criticality: {job_key: float}, warnings: [...]}`. Map graph node ids → view keys via existing `canonical_node_key`.
4. Edge payload: add `derived` and `inference` fields (False/"" for regular edges).
5. Bump `HTML_GRAPH_SCHEMA_VERSION` to `"1.1"`. Keep all output sorted/deterministic (follow existing sorting style).

## Acceptance
`tests/test_html_graph_payload.py`: build a small synthetic Graph (producer job, file, watcher, downstream dep) → payload assertions: `data_flow` category present in `skeleton.derived_edges`, file classification `internal`, schema `1.1`, determinism (two calls, equal JSON dumps). Pytest green. Report: new payload keys + test summary only.
