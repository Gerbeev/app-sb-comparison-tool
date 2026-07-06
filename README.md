# Stonebranch Dependency Tool

Build and compare dependency graphs from Stonebranch JSON exports and AutoSys JIL files.

Works fully offline — no internet access is required. The Python package has no
external runtime dependencies (`dependencies = []` in `pyproject.toml`), and the
graph viewer's JavaScript runtime (Cytoscape) is bundled locally with the package
and copied next to every generated `graph.html`, so nothing is downloaded from a CDN.

## Requirements

- Python >= 3.11

## Running

Interactive terminal UI:

```
python -m stonebranch_graph.cli tui
```

or, on Windows:

```
run_terminal_ui.cmd
```

Command-line build (example: Stonebranch pack):

```
python -m stonebranch_graph.cli build-stonebranch <source-folder> --output <output-folder>
```

Run `python -m stonebranch_graph.cli --help` for the full list of subcommands.

Generated analysis packs keep machine-readable JSON under `json/`, tabular CSV
exports under `csv/`, reconciliation key lists under `ids/`, and technical lookup
indexes under `indexes/`. The legacy `reports/` folder is still emitted for now,
but it is marked obsolete in each pack.

## Isolated / offline environments

- Set `SB_TOOL_NO_NATIVE_DIALOG=1` to skip the native OS folder/file picker entirely
  and go straight to manual path entry. This avoids any delay caused by the picker
  subsystem on networks without internet access.
