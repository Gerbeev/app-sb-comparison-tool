# Prompt 10 — Integration: CLI, TUI, examples, docs, end-to-end tests

## Objective

Wire the skeleton pipeline into the user-facing surfaces (CLI, TUI), ship runnable example
fixtures (including a Task Monitor and a sub-workflow), fix documentation inconsistencies,
and add the end-to-end golden test that locks in the whole concept.

## Context — read ONLY these

1. `stonebranch_graph/cli.py` — full file (subcommand patterns).
2. `stonebranch_graph/workflows.py` — `compare_skeleton_direct` (prompt 07) and the legacy
   workflow functions' shape (`GraphWorkflowResult`, file-list helpers).
3. `stonebranch_graph/tui_actions.py` and `stonebranch_graph/tui_prompts.py` — menu/action
   patterns (read `tui.py` only if action registration is not evident from these two).
4. `examples/` tree and `docs/mapping-explained.md` §8 (the scenario the new examples encode).
5. `README.md` — **note: the file does not exist yet** although `pyproject.toml` references
   it; create it in section E.

## Requirements

### A. CLI (argparse, mirror existing helper style)

1. `build-skeleton-stonebranch <input> -o <dir> [--alias FILE] [--env E] [--env-aware]`
   (positional input + `-o/--output`, matching `add_source_output`) → parse_raw → build →
   erase_plumbing → write `skeleton.jsonl`, `skeleton-canonical.jsonl` (strict),
   `skeleton-index.csv`, `skeleton-graph.html` bundle.
2. `build-skeleton-jil` — same for JIL sources.
3. `compare-skeleton --stonebranch <dir> --jil <dir> --output <dir> [--alias FILE] ...`
   → `workflows.compare_skeleton_direct`.
4. `compare` gains `--skeleton/--legacy` mode flag: default **skeleton** with an info line
   pointing legacy users to `--legacy` (the report redesign supersedes the old one by
   default, per project direction); `--legacy` runs the untouched old path.
5. Exit codes and logging consistent with `run_command`/`logging_utils` patterns.

### B. TUI

Add menu actions mirroring the CLI additions (build skeleton SB/JIL, compare skeletons),
reusing `tui_prompts` for path input. Keep changes minimal — one action per command,
no new UI concepts.

### C. Examples

1. Extend `examples/stonebranch/PROD/` with:
   - `workflows/WF_ETL.json` — workflow with vertices (extract/transform/load) and Success
     connectors;
   - `workflows/WF_REPORTING.json` — contains `build_report`, `publish`, and vertex
     `MON_ETL`;
   - `tasks/MON_ETL.json` — a **Task Monitor** watching `WF_ETL` for Success, feeding
     `build_report` via a connector (this is the fixture that demonstrates monitor erasure);
   - `tasks/`: extract/transform/load/build_report/publish/copy_files task definitions;
   - `workflows/WF_ARCHIVE.json` + a second Task Monitor watching task `load`.
2. Extend `examples/jil/PROD/` with `etl_example.jil` encoding the same logic the AutoSys
   way (boxes ETL/REPORTING/ARCHIVE, `condition: s(ETL)` on BUILD_REPORT, `s(LOAD)` on
   COPY_FILES).
3. `examples/alias.json` mapping both sides' native names to the shared logical ids of
   `docs/skeleton-example.json`.
4. Quick-start (goes into the new README): one command producing a zero-diff skeleton
   comparison from these examples.

### D. End-to-end golden test — `tests/test_e2e_skeleton.py`

1. Run `compare_skeleton_direct` on the example dirs with `examples/alias.json`; assert:
   - both `skeleton-canonical.jsonl` files byte-equal each other **and** equal
     `docs/skeleton-example.json` content converted to JSONL lines (ids/parents/triggers);
   - diff summary: zero changed, zero only-in-* at all three levels;
   - no node id containing `mon_etl` exists in either output (monitor erased);
   - erasure diagnostics report exactly 2 erasures on the SB side.
2. CLI smoke: invoke `cli.main([...])` in-process for the three new subcommands on the
   examples; assert exit code 0 and expected files exist.

### E. Docs cleanup

1. Fix the broken links in `docs/mapping-theory.md` §7 and `docs/mapping-explained.md` §8:
   `data/skeleton-example.json` → `skeleton-example.json` (file lives in `docs/`).
2. Add `docs/pipeline.md` (~40 lines): the implemented pipeline diagram (mapping-theory §8),
   module map (expr / skeleton / builders / normalize / compare), file outputs, and the
   sentence "Task Monitors are dependencies, not nodes — see mapping-theory §4/N3".
3. Create `README.md` (missing today; `pyproject.toml` already declares it): project
   purpose, all CLI commands with the new skeleton ones first, output file inventory,
   alias.json format pointer, legacy `--legacy` note, examples quick-start from C.4.
4. Bump version in `pyproject.toml` to `0.6.0`.

## Out of scope

Removing the legacy comparison engine (a follow-up once users sign off), pack-format
(`build-*-pack`) skeleton integration, CI configuration.

## Acceptance criteria

1. Full test suite passes: `python -m pytest -q`.
2. `python -m stonebranch_graph.cli compare-skeleton --stonebranch examples/stonebranch
   --jil examples/jil --output /tmp/cmp --alias examples/alias.json` → zero-diff report.
3. Legacy `compare --legacy` on the original `examples/` inputs still produces its report
   (spot-check exit code + report.md exists).
4. `ruff check stonebranch_graph tools tests` clean.

## Cost guidance

Fixtures are small hand-written JSON — copy field names exactly from
`skeleton_stonebranch.py`'s key-list constants so detection works on the first run. Wire CLI
by cloning the nearest existing subcommand block. Update README with targeted edits, do not
rewrite it.
