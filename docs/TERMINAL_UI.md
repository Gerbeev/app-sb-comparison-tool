# Terminal UI

Start:

```cmd
run_terminal_ui.cmd
```

or:

```cmd
stonebranch-graph tui
```

The UI stores settings in:

```text
.stonebranch-tool-settings.json
```

## Modes

1. Run compare: Stonebranch ↔ JIL
2. Build Stonebranch graph
3. Build JIL graph
4. Compare existing graph.json files
5. Profile Stonebranch schema
6. Profile JIL schema
7. Configure paths and options
8. Show last output files

## Output

Compare mode writes:

```text
out/
  stonebranch/graph.json
  jil/graph.json
  compare/comparison.json
  compare/metrics.json
  compare/report.md
  compare/edge-diff.csv
```
## Menu actions

### 1) Run compare: Stonebranch ↔ JIL

Builds both graphs, compares objects/dependencies, calculates migration metrics, and writes the comparative report.

Use this as the main migration audit run.

### 2) Build Stonebranch graph

Parses only the Stonebranch JSON repository and exports:

```text
graph.json
objects.csv
edges.csv
metrics.json
dependency-graph.mmd
report.md
```

Use this to validate Stonebranch parsing before comparing against JIL.

### 3) Build JIL graph

Parses only AutoSys JIL files and exports the JIL-side graph.

Use this to validate JIL parsing before comparing against Stonebranch.

### 4) Compare existing graph.json files

Compares already generated Stonebranch and JIL `graph.json` files.

Use this when repositories were already parsed and you only want to rerun comparison, usually after changing mapping rules.

### 5) Profile Stonebranch schema

Creates a safe structure report of Stonebranch JSON fields and types without values.

Use this when parser accuracy needs tuning.

### 6) Profile JIL schema

Creates a safe structure report of JIL attributes and job blocks.

Use this to understand JIL structure before graph generation.

### 7) Configure paths and options

Sets all reusable paths and runtime options:

- Stonebranch path
- JIL path
- Output folder
- Environment
- Mapping JSON
- Include raw values
- Deep scan
- Env-aware Stonebranch

### 8) Show last output files

Prints the most useful files from the last run.

Use this after a run to quickly locate reports and JSON outputs.

### 9) Save settings

Saves current settings to:

```text
.stonebranch-tool-settings.json
```

### 0) Exit

Closes the terminal UI.


## Color scheme

The terminal UI uses ANSI colors to make the menu easier to scan:

- green: main compare flow and success
- cyan: graph generation actions
- magenta: profile/schema actions
- yellow: settings/configuration
- gray: helper descriptions
- red: missing paths and errors

Disable colors:

```cmd
set NO_COLOR=1
run_terminal_ui.cmd
```

Force colors:

```cmd
set STONEBRANCH_FORCE_COLOR=1
run_terminal_ui.cmd
```


## v0.5.1 menu layout

Main menu:

```text
1) Build Stonebranch analysis pack
2) Build JIL analysis pack
3) Compare analysis packs
4) Settings
5) Other tools
0) Exit
```

The main menu intentionally contains only the recommended workflow and navigation.

### Settings submenu

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

### Other tools submenu

```text
1) Run direct compare: Stonebranch ↔ JIL
2) Compare existing graph.json files
3) Profile Stonebranch schema
4) Profile JIL schema
5) Show last output files
0) Back
```
