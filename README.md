# Stonebranch Dependency Tool v0.5.5

JSON-first terminal tool for creating and comparing dependency analysis packs:

- Stonebranch folder-based JSON export
- AutoSys JIL files
- Detailed mismatch analysis for migration cleanup

The recommended workflow is pack-based:

```text
Stonebranch repo  → Stonebranch analysis pack
JIL repo          → JIL analysis pack
Both packs        → Comparison analysis pack
```

## Start

Run:

```cmd
run_terminal_ui.cmd
```

or:

```cmd
python -m stonebranch_graph.cli tui
```

## Main menu

```text
1) Build Stonebranch analysis pack
2) Build JIL analysis pack
3) Compare analysis packs
4) Settings
5) Other tools
0) Exit
```

The main screen intentionally contains only the recommended workflow and navigation.

## Main dashboard

Before the menu, the terminal UI shows a project dashboard:

```text
Project dashboard
  Environment: PROD  Raw: no  Deep: no  Env-aware: no

Selected folders
  Stonebranch repo:   OK / MISSING
  JIL repo:           OK / MISSING
  Output folder:      OK / WILL CREATE / MISSING

Analysis outputs
  Stonebranch pack:   READY / NOT BUILT / INCOMPLETE
  JIL pack:           READY / NOT BUILT / INCOMPLETE
  Comparison pack:    READY / NOT BUILT / INCOMPLETE

Next recommended action
  4) Settings — select missing source folders.
```

This lets you see what is configured, what has already been generated, and what to do next without opening Settings first.

## Recommended workflow

### 1) Build Stonebranch analysis pack

Creates a self-contained folder with graph, workflow/box container views, canonical diff-friendly JSON, an offline interactive HTML graph report, indexes, metrics, and reports. Mermaid `.mmd` views have been fully decommissioned.

```cmd
stonebranch-graph build-stonebranch-pack "C:\path\to\sb-orchestrator\envs\PROD" -o out\stonebranch-pack --env PROD --include-raw-values
```

### 2) Build JIL analysis pack

Creates a self-contained JIL-side analysis folder.

```cmd
stonebranch-graph build-jil-pack "C:\path\to\autosys-jil\PROD" -o out\jil-pack --env PROD --include-raw-values
```

### 3. Compare analysis packs

Compares two pack folders and writes a detailed discrepancy analysis.

```cmd
stonebranch-graph compare-packs --stonebranch-pack out\stonebranch-pack --jil-pack out\jil-pack -o out\compare-pack
```

Then generate the dry-run triage files:

```cmd
python -m stonebranch_graph.cli triage out\compare-pack
```

## Real repository dry run

Before treating comparison numbers as a migration baseline, run the real-repository dry-run checklist:

```text
docs/REAL_REPOSITORY_DRY_RUN.md
```

It explains the recommended first run, which logs and reports to inspect first, and how to generate triage outputs for collisions, edge diffs, command diffs, parser warnings, and remediation items.

## Source analysis pack contents

Both Stonebranch and JIL packs contain:

```text
README.md
pack-manifest.json
graph.json
canonical-graph.json
graph.html
graph-data.js
cytoscape.min.js
cytoscape.LICENSE
containers.json
containers.csv
metrics.json
metrics.csv
objects.csv
edges.csv
dependency-graph.dot
report.md
run.log

indexes/
  node-index.json
  edge-index.json
  adjacency.json
  reverse-adjacency.json

graphs/
  README.md

reports/
  top-connected.md
  orphans.md
  relation-summary.csv
  object-summary.csv
```

Mermaid `.mmd` graph exports have been fully decommissioned because large production repositories are hard to render and navigate in Mermaid. Use `graph.html` for the offline interactive HTML graph view powered by bundled Cytoscape.js, and use `canonical-graph.json`, `containers.json`, `objects.csv`, `edges.csv`, and `dependency-graph.dot` for deterministic review and diff tools.


`graph.json` is the source of truth. `graph.html` is the offline interactive HTML graph report generated from `graph-data.js` and the bundled `cytoscape.min.js` runtime. `canonical-graph.json` is the deterministic sorted graph projection for diff tools. `containers.json` is the workflow/box group projection: workflows/boxes are groups and tasks/jobs are children. Stonebranch dependency definition files are not exported as dependency nodes; they are normalized into task-to-task dependency edges with the original dependency file kept as edge evidence. Indexes and graph views are generated from the graph data.

## Comparison analysis pack contents

```text
compare-pack-manifest.json
run.log

compare/
  report.md
  comparison.json
  metrics.json
  metrics.csv
  edge-diff.csv
  command-diff.csv
  compare-graph.html
  compare-graph-data.js
  cytoscape.min.js
  cytoscape.LICENSE
  triage-report.md        # created by: python -m stonebranch_graph.cli triage <compare-pack>
  triage-findings.csv     # created by: python -m stonebranch_graph.cli triage <compare-pack>
  triage-summary.json     # created by: python -m stonebranch_graph.cli triage <compare-pack>
  missing-in-stonebranch.csv
  missing-in-jil.csv
  collisions.csv
  mapping-diagnostics.csv
  diff-index.json
  critical-diff.json
  remediation-plan.md
```

Start with:

```text
compare/report.md
compare/metrics.json
compare/critical-diff.json
compare/remediation-plan.md
```

`remediation-plan.md` is a checklist for closing migration gaps.

`run.log` records workflow start/completion messages, parser warnings, comparison risks, and errors. It is a diagnostic file; `graph.json`, CSV files, and Markdown reports remain the source of truth for analysis results.


## Enterprise naming compatibility

The comparison layer understands the enterprise object-name pattern used by the migration repositories:

```text
IB_CT_CVA_1109_P1_<real Stonebranch job name>
IB_CT_CVA_1109_EN_<real AutoSys box file name>
IB_CT_CVA_1109_0en0_<real AutoSys job or box name>
```

For canonical matching, the tool keeps the original object name in `Node.name` and `Node.id`, but compares the object by the real suffix after the business code and environment token. For example, these names match the same canonical object:

```text
IB_CT_CVA_1109_P1_LOAD_CUSTOMERS
IB_CT_CVA_1109_0en0_LOAD_CUSTOMERS
```

Both become:

```text
PROD:task:load_customers
```

The detected prefix, business code, environment token, and real name are also stored in node metadata under `enterprise_naming` for diagnostics.

If multiple full object names collapse to the same comparison key, the tool does not auto-match them. It reports the conflict in `comparison.json`, `report.md`, and `collisions.csv` with the original names, business codes, environment tokens, and source files. This avoids false-positive matches when two systems use the same real suffix under different business codes.

## Settings menu

The main Settings screen is intentionally short. It only shows the fields needed for the normal workflow:

```text
1) Stonebranch source folder
2) JIL source folder
3) Output folder
4) More settings
0) Back
```

Folder items open the system folder picker immediately. You do not type folder paths manually.

`Output folder` is the recommended way to configure outputs. When selected, the TUI automatically fills:

```text
out/stonebranch-pack
out/jil-pack
out/compare-pack
```

More settings are nested so the main screen stays simple:

```text
1) Environment
2) Advanced settings
3) Save / load / reset
4) Back
```

Advanced settings contain optional items only:

```text
1) Mapping file
2) Parser and output options
3) Custom output and graph.json paths
4) Back
```

Settings are stored in:

```text
.stonebranch-tool-settings.json
```

## Other tools

Secondary actions are available under `Other tools`:

```text
1) Run direct compare: Stonebranch ↔ JIL
2) Compare existing graph.json files
3) Profile Stonebranch schema
4) Profile JIL schema
5) Show last output files
0) Back
```

## Runtime options

### Include raw values

Default is off. Command/script evidence is represented as a stable hash.

When enabled, graph edges may include normalized raw command/script values. Matching still uses stable identifiers/hashes where applicable.

Command comparison uses two levels:

```text
strict command hash     exact normalized command string
semantic command hash   command string with scheduler variable wrappers, env tokens, and script base paths normalized
```

This helps Stonebranch and AutoSys commands match when they differ only by variable syntax, for example `${BUSINESS_DATE}` versus `$${business_date}`, known environment-token syntax such as `--env P1` versus `--env 0en0`, or script base paths such as `/u01/stonebranch/scripts/load.sh` versus `/opt/autosys/bin/load.sh`. Such cases are reported as `command_syntax_diff_only` instead of critical semantic command mismatches. Command review details are exported to `compare/command-diff.csv` for spreadsheet filtering by status, normalization reasons, variables, env tokens, and script basenames.

### Deep scan

Enables broader string reference detection in Stonebranch JSON. This can find more references, but may produce false positives.

### Env-aware Stonebranch

Derives environment from folder layout like:

```text
envs/PROD/tasks/*.json
envs/DEV/tasks/*.json
```

## Key metrics

Comparison metrics include:

```text
migration_readiness_score
readiness_grade
node_match_rate_percent
edge_match_rate_percent
critical_dependency_loss_count
critical_dependency_extra_count
calendar_mismatch_count
agent_machine_mismatch_count
command_mismatch_count
command_syntax_diff_only
command_semantic_mismatches
condition_mismatch_count
synthetic_nodes_total
low_confidence_edges_total
```

Readiness grades:

```text
95–100  excellent
85–94   good
70–84   review_required
50–69   high_risk
0–49    unsafe
```


### Test suite policy

Prefer direct workflow calls in tests instead of spawning the CLI with `subprocess`. Keep subprocess-based coverage limited to the small CLI smoke tests in `tests/smoke_test.py`. This keeps the suite fast while preserving command-line coverage.

## Development quality gates

Install development tools with:

```cmd
python -m pip install -e .[dev]
```

Run the local safety checks before packaging or releasing changes:

```cmd
python -m pytest
python -m ruff check .
python -m ruff format --check .
```

Use auto-formatting when needed:

```cmd
python -m ruff format .
```

Runtime dependencies remain empty; `pytest` and `ruff` are development-only tools.

## Release notes

See `CHANGELOG.md` for the full release history.

The v0.5.5 line adds parser correctness fixes, workflow/TUI refactoring, shared rendering helpers, export safeguards, domain constants, stronger tests, and dev quality gates.

Previous v0.5.4 cleanup removed obsolete legacy launchers/docs:

```text
run_compare_example.cmd
run_compare_your_repo.cmd
docs/HARDENING_v0.5.4.md
stonebranch_graph/parsers/base.py
```

Also cleaned unused imports and added pack workflow tests.


## Terminal UX

Menu actions use numbered selection:

```text
Press the shown number directly.
No Enter is required for menu actions.
```

Folder path settings open the native system folder picker immediately. You do not need to type paths manually.

The main dashboard shows selected folders, pack status, comparison status, and the next recommended action before the menu.

Build/compare/profile actions use saved settings only. They do not ask for source or output folders during execution. If a required folder or file is missing, the action shows a numbered choice:

```text
1) Open Settings
2) Back
```

Open Settings, select the required folder/file with the picker, save if needed, and then run the action again.


```text
Settings → Stonebranch source folder → opens folder picker
Settings → JIL source folder → opens folder picker
Settings → Output folder → opens folder picker and auto-fills pack folders
Cancel keeps the current value
```

Optional file settings, such as mapping.json, use numbered picker controls, each option on its own line:

```text
1) Open file picker
2) Keep current
3) Manual input fallback
4) Empty, only for optional file paths
```

For pack outputs, use:

```text
Settings → Output folder
```

The tool auto-fills:

```text
<base>\stonebranch-pack
<base>\jil-pack
<base>\compare-pack
```


## QA20.7 comparison HTML graph

Comparison packs now include `compare/compare-graph.html`, `compare/compare-graph-data.js`, and local `compare/cytoscape.min.js`, an offline Cytoscape visual overlay for matched, missing, critical, and command/condition-difference statuses.

## QA20.8 large graph HTML usability

`graph.html` and `compare/compare-graph.html` now include status filters and quick buttons for `Problems`, `Critical`, `Missing`, and `Show all`. The side panel shows current visible node/edge counts and comparison status counts, which helps narrow very large workflow/job graphs before expanding all groups.

## QA20.9 HTML side panel evidence and deep links

`graph.html` and `compare/compare-graph.html` now show copyable node IDs, graph IDs, edge keys, evidence fields, and source/target navigation in the side panel. Selecting a node or edge updates the URL hash, so a focused view can be reopened or shared locally.
