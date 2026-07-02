# Agent prompt — Item 1: Domain vocabulary extension

You are implementing Item 1 of `GRAPH_SKELETON_IMPLEMENTATION_PLAN.md` in this repo (Python package `stonebranch_graph`).

## Token budget rules
Read ONLY: `stonebranch_graph/domain.py`, `stonebranch_graph/core.py`, and grep `compare.py` for `COMPARABLE_EDGE_RELATIONS|ARTIFACT_EDGE_RELATIONS` usage (context lines only, not the whole file). Do not read parsers, html_graph, tui, exporters. No refactoring, no reformatting of untouched lines. Minimal diff.

## Task
1. In `domain.py` add:
   - `REL_PRODUCES_FILE = "produces_file"`, `REL_DATA_DEPENDS_ON = "data_depends_on"` (alphabetical placement with other REL_ constants).
   - `DATA_FLOW_RELATIONS = {REL_WATCHES_FILE, REL_PRODUCES_FILE, REL_DATA_DEPENDS_ON}`
   - `DERIVED_EDGE_RELATIONS = {REL_DATA_DEPENDS_ON}`
   - `INFERRED_EDGE_RELATIONS = {REL_PRODUCES_FILE}`
   - Ensure both new relations are EXCLUDED from `COMPARABLE_EDGE_RELATIONS` and from `ONE_SIDED_EDGE_RELATIONS`; add them to `ARTIFACT_EDGE_RELATIONS` (with a comment: derived/inferred analytical edges, never migration facts).
2. In `core.py` extend `Edge` dataclass with two new optional fields (keep frozen):
   - `derived: bool = False`
   - `inference: str = ""`
   Defaults must keep `Edge(**edge_data)` working for old `graph.json` files (verify `Graph.from_dict` needs no change; `asdict` picks new fields up automatically).

## Acceptance
- `python -c "from stonebranch_graph.core import Graph"` + round-trip: build a Graph with one old-style edge dict (no new keys) via `from_dict`, then `to_dict` — no exceptions.
- New sets importable from `domain.py`.
- Diff touches only the two files.

Report changed lines count and paste the final new constants block. Stop after that — do not implement other plan items.
