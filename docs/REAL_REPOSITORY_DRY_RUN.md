# Real repository dry-run checklist

Use this checklist when testing the tool on real Stonebranch and AutoSys repositories for the first time. The goal is not to fix every migration gap immediately. The goal is to verify that parsing, matching, reporting, and logging behave correctly on real data.

## 0) Prepare a safe workspace

Use a separate output folder outside the source repositories when possible.

Recommended layout:

```text
migration-dry-run/
  stonebranch-export/
  autosys-jil/
  output/
    stonebranch-pack/
    jil-pack/
    compare-pack/
```

Do not enable raw values for the first run unless you explicitly need command/script evidence for debugging.

Default safe mode:

```text
--include-raw-values not used
```

Debug mode:

```text
--include-raw-values
```

Only use debug mode when the output pack can safely contain raw command/script values.

## 1) Configure through the terminal UI

Start the TUI:

```cmd
run_terminal_ui.cmd
```

Then select folders from Settings:

```text
1) Build Stonebranch analysis pack
2) Build JIL analysis pack
3) Compare analysis packs
4) Settings
5) Other tools
0) Exit
```

In Settings, choose:

```text
1) Stonebranch source folder
2) JIL source folder
3) Output folder
0) Back
```

Folder settings open the system folder picker. Do not type folder paths manually unless you are using an optional file fallback.

## 2) CLI dry-run commands

The same dry run can be executed from the command line.

Build the Stonebranch pack:

```cmd
python -m stonebranch_graph.cli build-stonebranch-pack "<STONEBRANCH_EXPORT>" -o "<OUTPUT>\stonebranch-pack" --env PROD
```

Build the AutoSys JIL pack:

```cmd
python -m stonebranch_graph.cli build-jil-pack "<AUTOSYS_JIL_REPO>" -o "<OUTPUT>\jil-pack" --env PROD
```

Compare the packs:

```cmd
python -m stonebranch_graph.cli compare-packs --stonebranch-pack "<OUTPUT>\stonebranch-pack" --jil-pack "<OUTPUT>\jil-pack" -o "<OUTPUT>\compare-pack"
```

Use `--env-aware` for Stonebranch only if your Stonebranch export layout contains environment folders such as `envs/PROD/tasks/*.json`.

Use `--deep-scan` only after the first run if known references are missing. It may find more references, but it can also create lower-confidence edges.

## 3) First files to inspect

After the run, inspect these files first:

```text
output/stonebranch-pack/run.log
output/stonebranch-pack/report.md
output/jil-pack/run.log
output/jil-pack/report.md
output/compare-pack/run.log
output/compare-pack/compare/report.md
output/compare-pack/compare/metrics.json
output/compare-pack/compare/critical-diff.json
output/compare-pack/compare/edge-diff.csv
output/compare-pack/compare/command-diff.csv
output/compare-pack/compare/collisions.csv
output/compare-pack/compare/remediation-plan.md
```

`graph.json` remains the source of truth for each side. CSV and Markdown files are review surfaces generated from it.

## 4) Source pack checks

For each source pack, check:

```text
run.log
report.md
metrics.json
objects.csv
edges.csv
```

Look for:

```text
Parser warnings
No active JIL insert_job/update_job records
Skipped Stonebranch files outside configured object-kind folders
Synthetic nodes
Low-confidence edges
Conditions not parsed
Unexpected object counts
Unexpected relation counts
```

Important warning types to review first:

```text
Duplicate Stonebranch object id
Ambiguous Stonebranch reference
No Stonebranch JSON files found
No active JIL insert_job/update_job records
Skipped non-object item in Stonebranch JSON array
Condition did not produce dependency references
```

## 5) Comparison checks

Start with:

```text
compare/report.md
compare/metrics.json
compare/critical-diff.json
```

Then review CSVs in this order:

```text
1) collisions.csv
2) edge-diff.csv
3) command-diff.csv
4) missing-in-stonebranch.csv
5) missing-in-jil.csv
6) mapping-diagnostics.csv
```

### 5.1) Collisions first

Resolve or explain collisions before trusting match rates.

Enterprise names such as these are normalized for comparison:

```text
IB_CT_CVA_1109_P1_LOAD_CUSTOMERS
IB_CT_CVA_1109_EN_DAILY_BOX
IB_CT_CVA_1109_0en0_LOAD_CUSTOMERS
```

If different full names collapse to the same comparison key, the tool reports the conflict instead of auto-matching it. Review `collisions.csv` before relying on missing object counts.

### 5.2) Edge diff second

Use `edge-diff.csv` for dependency and containment gaps.

High-priority relations:

```text
depends_on_success
depends_on_done
depends_on_failure
depends_on_terminated
depends_on_notrunning
contains
starts
runs_on
runs_command
runs_script
watches_file
```

Direction meanings:

```text
missing_in_stonebranch = exists in JIL, not found in Stonebranch
missing_in_jil         = exists in Stonebranch, not found in JIL
```

### 5.3) Command diff third

Use `command-diff.csv` to separate real command changes from scheduler syntax differences.

Statuses:

```text
command_syntax_diff_only  strict command differs, semantic command matches
command_semantic_mismatch strict and semantic command differ
```

Common syntax-only reasons:

```text
variable_syntax
environment_token
script_path
```

Treat `command_semantic_mismatch` as higher priority than `command_syntax_diff_only`.


## 6) Generate a triage report

After the comparison pack is created, generate a triage report:

```cmd
python -m stonebranch_graph.cli triage "<OUTPUT>\compare-pack"
```

This writes:

```text
<OUTPUT>/compare-pack/compare/triage-report.md
<OUTPUT>/compare-pack/compare/triage-findings.csv
<OUTPUT>/compare-pack/compare/triage-summary.json
```

Use the triage files to classify findings before fixing them:

```text
enterprise_naming_collision   naming collision; review mappings before trusting match rates
critical_edge_gap             likely dependency/containment/runtime gap to review first
command_syntax_mapping        variable/env/script-path syntax difference; usually mapping review
command_semantic_mismatch     real command behavior difference candidate
condition_mismatch            matched object has different condition hash
object_gap                    missing object or retired/unmapped object
parser_or_comparison_warning  warning from run.log
workflow_error                error from run.log; fix before trusting reports
```

Recommended triage order:

```text
1) collisions.csv / enterprise naming collisions
2) edge-diff.csv critical edges
3) command-diff.csv semantic mismatches
4) condition differences
5) object gaps
6) command syntax-only mapping checks
7) run.log parser/comparison warnings
```

## 7) Minimum acceptance checklist

Before using the result as a migration baseline, confirm:

```text
[ ] Stonebranch pack was created and has graph.json.
[ ] JIL pack was created and has graph.json.
[ ] Comparison pack was created and has compare/comparison.json.
[ ] run.log files do not contain unexpected errors.
[ ] collisions.csv has no unexplained enterprise-name collisions.
[ ] critical-diff.json has been reviewed.
[ ] edge-diff.csv has been reviewed for critical dependency loss.
[ ] command-diff.csv semantic mismatches have been reviewed.
[ ] remediation-plan.md has been reviewed as the working cleanup checklist.
```

## 8) What to send back for tool improvement

When real data exposes a parsing or matching issue, collect a small sanitized case:

```text
1) The relevant run.log warning/error lines.
2) The object names involved, with sensitive parts masked if needed.
3) The related rows from edge-diff.csv or command-diff.csv.
4) The source object shape, reduced to only the fields needed to reproduce the issue.
5) Whether the issue is a false missing object, false missing edge, false command mismatch, or missing warning.
```

Do not send full raw command/script values unless debug sharing is explicitly approved.

## 9) Recommended next iteration after a real dry run

After the first real dry run, group findings into:

```text
Parser gaps
Relation normalization gaps
Enterprise naming collisions
Command/script normalization gaps
Real migration gaps
```

Fix parser and normalization gaps before treating migration gap counts as final.
