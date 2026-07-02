# Terminal UI

Start:

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

The main menu is intentionally focused on the recommended pack workflow.

## Main dashboard

The screen shows a dashboard before the menu:

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
  1) Build Stonebranch analysis pack.
```

This dashboard is read-only. Use numbered menu items to act on the recommendation.

## Recommended workflow

### 1) Build Stonebranch analysis pack

Creates:

```text
out/stonebranch-pack/
  graph.json
  indexes/
  graphs/
  reports/
  metrics.json
  report.md
```

Use this first to parse and inspect the Stonebranch repository independently.

### 2) Build JIL analysis pack

Creates:

```text
out/jil-pack/
  graph.json
  indexes/
  graphs/
  reports/
  metrics.json
  report.md
```

Use this to parse and inspect JIL independently.

### 3) Compare analysis packs

Compares existing pack folders and writes:

```text
out/compare-pack/
  compare-pack-manifest.json
  compare/
    report.md
    comparison.json
    metrics.json
    edge-diff.csv
    command-diff.csv
    critical-diff.json
    diff-index.json
    remediation-plan.md
```

Use this for the actual migration gap analysis.

## Settings

The main Settings screen is simplified for the normal workflow:

```text
1) Stonebranch source folder
2) JIL source folder
3) Output folder
4) More settings
0) Back
```

Folder settings open the native folder picker immediately. The TUI does not ask you to type folder paths manually.

`Output folder` auto-fills the standard pack folders:

```text
<output>/stonebranch-pack
<output>/jil-pack
<output>/compare-pack
```

The extra settings are nested under `More settings`:

```text
1) Environment
2) Advanced settings
3) Save / load / reset
4) Back
```

Advanced settings are optional:

```text
1) Mapping file
2) Parser and output options
3) Custom output and graph.json paths
4) Back
```

### Basic folder settings

The first Settings screen contains the three folder choices used by the normal workflow:

```text
Stonebranch source folder
JIL source folder
Output folder
```

Each folder item opens the system folder picker immediately.

### More settings

Use `More settings` for non-folder basics and maintenance:

```text
1) Environment
2) Advanced settings
3) Save / load / reset
4) Back
```

### Advanced settings

Advanced settings are optional and hidden from the main Settings page:

```text
1) Mapping file
2) Parser and output options
3) Custom output and graph.json paths
4) Back
```

`Custom output and graph.json paths` is only needed when you want to override generated pack folders or compare existing graph.json files.


## Other tools

```text
1) Run direct compare: Stonebranch ↔ JIL
2) Compare existing graph.json files
3) Profile Stonebranch schema
4) Profile JIL schema
5) Show last output files
0) Back
```

These are intentionally one level lower than the main workflow.

## Color scheme

- green: main compare flow and success
- cyan: pack/graph generation actions
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


## v0.5.5 keyboard UX

Menu selection no longer requires Enter.

Use:

```text
1 / 2 / 3 / 4 / 5 / 0
```

directly.

## Picker UX

Folder path settings open native system folder dialogs immediately. You do not need to type folder paths manually.

The main dashboard shows selected folders, generated pack status, comparison status, and the next recommended action before the menu.

Actions use saved settings only. Build, compare, and profile commands never ask for repository or output folders directly. If required settings are missing, the action shows:

```text
1) Open Settings
2) Back
```

Use Settings to select folders/files with pickers, then run the action again.


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

For pack folders, choose one base output folder and let the tool auto-fill:

```text
<base>/stonebranch-pack
<base>/jil-pack
<base>/compare-pack
```
