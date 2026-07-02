# QA baseline v0.5.5

This document is the handoff baseline for running the tool against real Stonebranch and AutoSys repositories after the QA/refactor pass.

## Baseline checks

Run these checks from the repository root before packaging or testing a real migration dataset:

```cmd
python -m pytest -q -o addopts=
python -m compileall -q stonebranch_graph tests
python -m stonebranch_graph.cli --version
python -m stonebranch_graph.cli --help
python -m stonebranch_graph.cli tui --help
```

Expected version output:

```text
stonebranch-graph 0.5.5
```

## Main dry-run commands

```cmd
python -m stonebranch_graph.cli build-stonebranch-pack "<STONEBRANCH_EXPORT>" -o "<OUTPUT>\stonebranch-pack" --env PROD
python -m stonebranch_graph.cli build-jil-pack "<AUTOSYS_JIL_REPO>" -o "<OUTPUT>\jil-pack" --env PROD
python -m stonebranch_graph.cli compare-packs --stonebranch-pack "<OUTPUT>\stonebranch-pack" --jil-pack "<OUTPUT>\jil-pack" -o "<OUTPUT>\compare-pack"
python -m stonebranch_graph.cli triage "<OUTPUT>\compare-pack"
```

Use the plain `python` command in Windows launcher scripts and documentation.

## Artifact contract source

The canonical generated-file contracts live in `stonebranch_graph/artifacts.py`. Keep workflow result files, pack manifests, documentation, and tests synchronized through that module. Triage fix guidance is centralized in `stonebranch_graph/triage.py` via `TRIAGE_FIX_RULES` and related rule tables.

## Source pack output contract

Stonebranch and JIL analysis packs are expected to contain these core files:

```text
README.md
pack-manifest.json
graph.json
metrics.json
metrics.csv
objects.csv
edges.csv
dependency-graph.mmd
dependency-graph.dot
report.md
run.log
indexes/node-index.json
indexes/edge-index.json
indexes/adjacency.json
indexes/reverse-adjacency.json
graphs/full.mmd
graphs/tasks-only.mmd
graphs/dependencies-only.mmd
graphs/triggers-to-tasks.mmd
graphs/runtime.mmd
graphs/calendars.mmd
graphs/variables.mmd
reports/top-connected.md
reports/orphans.md
reports/relation-summary.csv
reports/object-summary.csv
```

`graph.json` is the source of truth. CSV, Markdown, Mermaid, DOT, and indexes are generated from it.

## Comparison output contract

The compare commands write this core contract:

```text
run.log
compare/report.md
compare/comparison.json
compare/metrics.json
compare/metrics.csv
compare/edge-diff.csv
compare/command-diff.csv
compare/missing-in-stonebranch.csv
compare/missing-in-jil.csv
compare/collisions.csv
compare/mapping-diagnostics.csv
compare/diff-index.json
compare/critical-diff.json
compare/remediation-summary.json
compare/remediation-plan.md
compare/overlay-graph.mmd
```

`compare-packs` also writes:

```text
compare-pack-manifest.json
```

## Triage output contract

The triage command writes these files into the `compare/` directory by default:

```text
compare/triage-report.md
compare/triage-findings.csv
compare/triage-summary.json
compare/triage-fix-plan.md
compare/triage-fix-plan.csv
```

## First review order

1) Review `compare/collisions.csv` before trusting match rates.
2) Review `compare/critical-diff.json` and `compare/edge-diff.csv` for lost dependencies.
3) Review `compare/command-diff.csv` and separate `command_syntax_diff_only` from `command_semantic_mismatch`.
4) Review `compare/missing-in-stonebranch.csv` and `compare/missing-in-jil.csv` for real scope gaps.
5) Review `run.log` for parser warnings and workflow errors.
6) Run triage and use `compare/triage-fix-plan.csv` as the follow-up backlog.

## Archive cleanliness contract

Release zip files should not contain local runtime state:

```text
__pycache__/
.pytest_cache/
out/
.stonebranch-tool-settings.json
```

## Current deferred items

These items are intentionally not part of the current baseline:

```text
P6  privacy mode / safe sharing packs
P12 project profiles
P13 run full analysis wizard
P14 reports screen
P11.3 validate settings screen
```

Continue with real dry-run findings before adding broad new features.
