# Agent prompt — Item 10: Fixtures, end-to-end test, docs

You are implementing Item 10 (final) of `GRAPH_SKELETON_IMPLEMENTATION_PLAN.md`. Items 1–9 merged. Goal: realistic fixtures, one end-to-end pipeline test, user docs.

## Token budget rules
Read ONLY: `examples/jil/PROD/sample.jil`, one Stonebranch example file under `examples/stonebranch/PROD` (pick the smallest), the public functions of `producers.py`/`skeleton.py`/`html_graph.py` (signatures only — grep `^def |^class `), and `pyproject.toml`. Do not re-read implementation bodies. Minimal diff.

## Task
1. **JIL fixture** `examples/jil/PROD/filewatcher_demo.jil`:
   - box `FW_DEMO_BOX`; producer job `GEN_REPORT` with `command: /apps/gen/GenReport.exe > /data/out/report_20260701.csv`, `machine: prodhost1`;
   - file watcher `WATCH_REPORT` (`job_type: f`, `watch_file: /data/out/report_%DATE%.csv`);
   - consumer `LOAD_REPORT` with `condition: s(WATCH_REPORT) & s(GEN_REPORT)`;
   - external-fed watcher `WATCH_FEED` on `/data/in/upstream_feed.dat` (no producer anywhere).
2. **Stonebranch fixture**: minimal JSON mirroring the same four objects in the export format used by `examples/stonebranch/PROD` (workflow + tasks + file monitor).
3. **End-to-end test** `tests/test_e2e_skeleton.py`: parse the JIL fixture → `infer_producer_edges` → `build_skeleton` → `build_cytoscape_graph_data`. Assert: `WATCH_REPORT` derived `data_depends_on` edge to `GEN_REPORT` exists with `inference` in {lexical_path_match→contraction chain}; `report_{date}.csv` file node classified `internal`; `upstream_feed.dat` classified `external`; layers put `LOAD_REPORT` after both predecessors; payload schema `1.1`.
4. **pytest wiring**: add `[tool.pytest.ini_options] testpaths=["tests"]` to `pyproject.toml` if absent; ensure `python -m pytest -q` runs the whole suite from a clean checkout.
5. **Docs**: `docs/skeleton-and-dataflow.md` (~1 page): what skeleton mode shows, dashed-edge semantics, watcher classification meanings, and the `producers.json` workflow for opaque producers (e.g. .NET apps whose output paths are known only to the team) with a copy-paste example. Link it from the README if one exists (`ls` first; if no README, create a stub `README.md` with tool one-liner + link).

## Acceptance
`python -m pytest -q` green (whole suite). E2E test passes. Report: suite summary line + list of created files. Do not refactor anything.
