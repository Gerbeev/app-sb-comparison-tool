# Stonebranch Dependency Tool v0.5.1.2

Build and compare dependency graphs from:

- Stonebranch folder-based JSON exports
- AutoSys JIL files

The tool exports both graphs as JSON and generates a comparative report.

## Commands

### Build Stonebranch graph

```bash
stonebranch-graph build-stonebranch "C:\path\to\sb-orchestrator\envs\PROD" -o out\stonebranch --env PROD
```

### Build JIL graph

```bash
stonebranch-graph build-jil "C:\path\to\autosys-jil\PROD" -o out\jil --env PROD
```

### Compare directly

```bash
stonebranch-graph compare ^
  --stonebranch "C:\path\to\sb-orchestrator\envs\PROD" ^
  --jil "C:\path\to\autosys-jil\PROD" ^
  --env PROD ^
  -o out
```

### Compare existing graph JSON files

```bash
stonebranch-graph compare-json ^
  --stonebranch-graph out\stonebranch\graph.json ^
  --jil-graph out\jil\graph.json ^
  -o out\compare-json
```

## Outputs

```text
out/
  stonebranch/
    graph.json
    objects.csv
    edges.csv
    dependency-graph.mmd
    dependency-graph.dot
    report.md

  jil/
    graph.json
    objects.csv
    edges.csv
    dependency-graph.mmd
    dependency-graph.dot
    report.md

  compare/
    comparison.json
    report.md
    missing-in-stonebranch.csv
    missing-in-jil.csv
    edge-diff.csv
    overlay-graph.mmd
```

## What is compared

- objects/jobs/tasks
- box/task hierarchy
- dependencies from JIL `condition`
- Stonebranch task references
- calendars
- agents/machines
- credentials/connections where present
- command hashes

## Safety

Secret-looking keys are redacted in metadata:

- password
- secret
- token
- api_key
- private_key
- client_secret
- refresh_token

Run locally and review generated outputs before sharing reports.


## v0.5.1.2 bug-check notes

Fixed after review:

- Stonebranch object names are kind-aware; `tasks/*.json` no longer accidentally uses `agentName` or `credentialName` as the task name.
- `description` no longer creates false `script` dependencies.
- Stonebranch `command` references now use command hashes, so they can match JIL command nodes.
- Stonebranch variable tokens now normalize to `uses_variable`.
- Trigger `taskName` references normalize to `starts` instead of `depends_on`.
- JIL box nodes that are declared with `insert_job` are not overwritten as synthetic references when used by `box_name`.


## v0.5.1 metrics

Each graph output now includes:

```text
metrics.json
metrics.csv
```

Comparison output now includes:

```text
compare/metrics.json
compare/metrics.csv
```

New comparison metrics:

- `migration_readiness_score`
- `readiness_grade`
- `node_match_rate_percent`
- `edge_match_rate_percent`
- `jil_to_stonebranch_node_coverage_percent`
- `stonebranch_to_jil_node_coverage_percent`
- `jil_to_stonebranch_edge_coverage_percent`
- `stonebranch_to_jil_edge_coverage_percent`
- `critical_dependency_loss_count`
- `critical_dependency_extra_count`
- `calendar_mismatch_count`
- `agent_machine_mismatch_count`
- `command_mismatch_count`
- `jil_conditions_not_parsed_count`
- `synthetic_nodes_total`
- `low_confidence_edges_total`
- `stonebranch_orphan_tasks`
- `jil_orphan_tasks`
- `stonebranch_tasks_without_trigger`


## v0.5.1 hardening

Added P0 fixes:

- kind-aware Stonebranch reference registry to avoid linking `${VAR}` to a task with the same name
- raw command redaction: command edges export command hashes only
- shared command normalizer for Stonebranch and JIL
- normalized key collision detection
- `collisions.csv`
- mapping diagnostics for unused mapping rules
- mapping support by `id`, `canonical_key`, normalized key, and object name
- safe profiles:
  - `profile-stonebranch`
  - `profile-jil`

Safe profile commands:

```bash
stonebranch-graph profile-stonebranch "C:\path\to\sb-orchestrator\envs\PROD" -o out\profile-stonebranch
stonebranch-graph profile-jil "C:\path\to\autosys-jil\PROD" -o out\profile-jil
```


## v0.5.1 Local Web UI

Double-click:

```cmd
run_ui.cmd
```

or run:

```cmd
stonebranch-graph ui
```

Open:

```text
http://127.0.0.1:8765
```

Supported UI modes:

- Compare Stonebranch ↔ JIL
- Build Stonebranch graph
- Build JIL graph
- Profile Stonebranch schema
- Profile JIL schema
- Compare existing `graph.json` files

Runtime toggles:

- `Include raw values`
- `Deep scan`
- `Env-aware Stonebranch`

Default mode remains safe: command evidence is stored as hash. With `Include raw values`, command/script evidence can include normalized raw command values for easier local debugging. Matching still uses hashes/canonical keys.


## v0.5.1 Terminal UI

This version is intentionally terminal-first: no web server and no browser UI.

Start on Windows:

```cmd
run_terminal_ui.cmd
```

Or run directly:

```cmd
stonebranch-graph tui
```

Terminal UI modes:

- Compare Stonebranch ↔ JIL
- Build Stonebranch graph
- Build JIL graph
- Compare existing `graph.json` files
- Profile Stonebranch schema
- Profile JIL schema
- Configure paths/options

Runtime options in the terminal menu:

- `Include raw values`
- `Deep scan`
- `Env-aware Stonebranch`
- `Mapping JSON`
- `Environment`
- `Output folder`

Default mode keeps command/script evidence as hashes. If `Include raw values` is enabled, normalized raw command/script evidence can be included in JSON/CSV outputs for local debugging.


## v0.5.1 Terminal UI descriptions

The terminal menu now explains every action directly in the interface:

```text
1) Run compare: Stonebranch ↔ JIL
   Builds both graphs, compares objects/dependencies, calculates metrics, and writes compare/report.md.

2) Build Stonebranch graph
   Parses only the Stonebranch JSON repository and exports graph.json, CSVs, metrics, and Mermaid.

3) Build JIL graph
   Parses only AutoSys JIL files and exports graph.json, CSVs, metrics, and Mermaid.

4) Compare existing graph.json files
   Compares previously generated graph.json files without reparsing repositories.

5) Profile Stonebranch schema
   Creates a safe schema profile of Stonebranch JSON keys/types without values.

6) Profile JIL schema
   Creates a safe profile of JIL attributes and job blocks.

7) Configure paths and options
   Sets repository paths, output folder, environment, mapping file, raw-values mode, deep scan, and env-aware mode.

8) Show last output files
   Prints the most important files from the last run.

9) Save settings
   Saves current paths/options to .stonebranch-tool-settings.json.

0) Exit
   Closes the terminal UI.
```


## v0.5.1 Terminal UI colors

The terminal UI now uses a calm ANSI color scheme:

- green for the main compare flow and successful status
- cyan for graph-building actions
- magenta for schema/profile actions
- yellow for setup/settings actions
- gray for descriptions and empty values
- red for missing paths and errors

Set `NO_COLOR=1` to disable colors.
Set `STONEBRANCH_FORCE_COLOR=1` to force ANSI colors in captured output.


## v0.5.1 Analysis packs

The recommended workflow is now pack-based:

1. Build a Stonebranch analysis pack.
2. Build a JIL analysis pack.
3. Compare the two analysis pack folders.

This gives you stable folders that can be inspected, archived, shared internally, and compared repeatedly without reparsing the original repositories.

### Stonebranch pack

```cmd
stonebranch-graph build-stonebranch-pack "C:\path\to\sb\envs\PROD" -o out\stonebranch-pack --env PROD --include-raw-values
```

### JIL pack

```cmd
stonebranch-graph build-jil-pack "C:\path\to\jil\PROD" -o out\jil-pack --env PROD --include-raw-values
```

### Compare packs

```cmd
stonebranch-graph compare-packs --stonebranch-pack out\stonebranch-pack --jil-pack out\jil-pack -o out\compare-pack
```

### Pack contents

Each source pack contains:

```text
README.md
pack-manifest.json
graph.json
metrics.json
objects.csv
edges.csv
indexes/
  node-index.json
  edge-index.json
  adjacency.json
  reverse-adjacency.json
graphs/
  full.mmd
  tasks-only.mmd
  dependencies-only.mmd
  triggers-to-tasks.mmd
  runtime.mmd
  calendars.mmd
  variables.mmd
reports/
  top-connected.md
  orphans.md
  relation-summary.csv
  object-summary.csv
```

The comparison pack contains:

```text
compare-pack-manifest.json
compare/
  report.md
  comparison.json
  metrics.json
  edge-diff.csv
  missing-in-stonebranch.csv
  missing-in-jil.csv
  diff-index.json
  critical-diff.json
  remediation-plan.md
```


## v0.5.1 Terminal UI structure

The main menu is now focused on the recommended pack workflow:

```text
1) Build Stonebranch analysis pack
2) Build JIL analysis pack
3) Compare analysis packs
4) Settings
5) Other tools
0) Exit
```

Secondary actions moved into `Other tools`:

```text
1) Run direct compare: Stonebranch ↔ JIL
2) Compare existing graph.json files
3) Profile Stonebranch schema
4) Profile JIL schema
5) Show last output files
0) Back
```

`Settings` is now a detailed submenu:

```text
1) Show current settings
2) Source repository paths
3) Analysis pack folders
4) Environment and mapping
5) Parser and output options
6) Existing graph.json paths
7) Validate paths
8) Save settings
9) Load settings
R) Reset to defaults
0) Back
```
