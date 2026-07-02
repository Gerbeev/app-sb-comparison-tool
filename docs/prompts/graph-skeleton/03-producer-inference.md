# Agent prompt — Item 3: Producer inference engine

You are implementing Item 3 of `GRAPH_SKELETON_IMPLEMENTATION_PLAN.md`. Goal: infer `produces_file` edges (job → file) so file-watcher dependencies become traceable. Items 1–2 are merged: `REL_PRODUCES_FILE`, `Edge.derived/inference`, and `file_identity.canonical_file_key` exist.

## Token budget rules
Read ONLY: `stonebranch_graph/domain.py` (constants), `stonebranch_graph/core.py` (Edge/Graph/make_edge_id), `stonebranch_graph/file_identity.py`, `stonebranch_graph/normalizers.py` (command tokenization helpers only — grep for `def ` first, read the 2–3 relevant functions), `stonebranch_graph/config.py` (AnalyzerConfig shape), CLI arg block of `cli.py` (grep `add_argument`). Nothing else. Minimal diff.

## Task
Create `stonebranch_graph/producers.py` with `infer_producer_edges(graph: Graph, mapping: dict | None) -> list[str]` (returns warnings; mutates graph by adding edges):

1. Collect watched files: nodes with `kind == KIND_FILE` that are targets of `watches_file` edges. Index by canonical key and by basename-pattern.
2. For every job-like node with a command (metadata `command_raw` if present, else the command evidence on its `runs_command` edge), tokenize with the existing normalizer tokenization and canonicalize path-shaped tokens via `canonical_file_key`.
   - **T2 `lexical_path_match`** (confidence 0.80): token canonical key equals a watched file key.
   - **T3 `basename_heuristic`** (confidence 0.50): only basename patterns match (directories differ or unresolved vars). Skip if a T2 edge already exists for the pair.
3. **T1 `explicit_mapping`** (confidence 1.00): optional `producers.json` — `{"mappings": [{"job": "<regex on job name>", "produces": ["<raw path>", ...]}]}`. T1 overrides lower tiers for the same (job,file) pair (replace edge).
4. Each edge: `relation=REL_PRODUCES_FILE`, direction job → file, `derived=False`, `inference=<tier>`, `confidence` per tier, evidence = matched token or mapping entry index. Never create new file nodes for T2/T3 (only match existing watched files); T1 may create the file node via canonical key.
5. Config/CLI: `AnalyzerConfig.producers_mapping_path: str | None`; CLI flag `--producers-mapping PATH`; call `infer_producer_edges` in the pipeline right after parsing (find call site by grepping `parse(` in `workflows.py` — read only that function).

## Acceptance
`tests/test_producers.py`: synthetic Graph with job command `run.exe > C:\out\report_20260701.csv` + watcher on `c:/out/report_{date}.csv` ⇒ exactly one T2 edge; add mapping for same pair ⇒ tier becomes T1; a path never watched ⇒ no edge. Pytest green. Report: edges emitted on `examples/jil/PROD` run (may be 0) + test summary.
