# Changelog

### R1

- Split AutoSys parser responsibilities into focused helper modules for parsed job records, JIL lexing, condition parsing, and JIL node construction while keeping `stonebranch_graph.parsers.autosys_jil.AutosysJilParser` as the public entry point.
- Split Stonebranch parser responsibilities into focused helper modules for JSON discovery/object metadata, relation/reference normalization, and registry/synthetic reference resolution while keeping `stonebranch_graph.parsers.stonebranch_json.StonebranchJsonParser` as the public entry point.
- Added regression coverage to ensure parser entrypoint files stay smaller facades and helper modules do not grow back into parser monoliths.

### R4

- Converted triage fix guidance from an inline `if`/dictionary block into rule-driven tables: `TRIAGE_FIX_RULES`, `DEFAULT_FIX_GUIDANCE`, `TRIAGE_CATEGORY_ORDER`, and `TRIAGE_REVIEW_ORDER`.
- Kept existing triage CSV/Markdown output behavior while making future finding categories easier to add after real dry runs.
- Added regression coverage for rule-table guidance, explicit guidance preservation, review ordering, and the compact `fix_guidance_for()` lookup.

### R2

- Split the monolithic comparison module into focused modules: `comparison_model.py`, `compare_engine.py`, `compare_keys.py`, `compare_payloads.py`, `compare_diagnostics.py`, `compare_export.py`, `compare_report.py`, `compare_csv_exports.py`, `compare_indexes.py`, `compare_remediation.py`, and `compare_overlay.py`.
- Kept `stonebranch_graph.compare` as a compatibility facade so existing imports such as `compare_graphs`, `export_comparison`, `normalize_key`, and `comparison_edge_key` continue to work.
- Added regression coverage for the split comparison architecture and facade exports.

### R3

- Centralized generated artifact file contracts in `stonebranch_graph/artifacts.py`.
- Updated workflow file helpers, analysis-pack manifests, comparison-pack manifests, and triage outputs to use the shared artifact contract source.
- Added regression coverage to prevent duplicate or divergent generated-file lists.

### QA21

- Added a final QA baseline handoff document: `docs/QA_BASELINE.md`.
- Added `stonebranch-graph --version` support through `python -m stonebranch_graph.cli --version`.
- Synchronized README comparison output contracts with the current generated artifacts, including `remediation-summary.json`, `overlay-graph.mmd`, and separate triage outputs.
- Documented baseline checks, real dry-run commands, source/comparison/triage output contracts, review order, archive cleanliness, and deferred items before real-repository testing.

### QA20

- Added post-dry-run fix guidance to triage findings: `suggested_fix_type`, `owner`, and `next_action`.
- Added `triage-fix-plan.md` and `triage-fix-plan.csv` to turn dry-run findings into a prioritized follow-up backlog.
- Grouped findings into actionable fix categories such as `manual_mapping_or_naming_rule`, `relation_parser_or_real_gap_triage`, `command_normalization_rule_candidate`, `real_command_migration_gap`, and `parser_rule_candidate`.
- Updated the real-repository dry-run checklist and README to include the fix-plan outputs and review flow.

### QA19

- Added a dry-run triage utility and CLI command: `python -m stonebranch_graph.cli triage <compare-pack>`.
- The triage command writes `triage-report.md`, `triage-findings.csv`, and `triage-summary.json` from existing comparison outputs.
- Triage categories classify collisions, critical edge gaps, object gaps, command syntax mapping differences, command semantic mismatches, condition mismatches, mapping issues, run-log warnings, and workflow errors.
- Updated the real-repository dry-run checklist with triage commands and recommended review order.


### QA18

- Added `docs/REAL_REPOSITORY_DRY_RUN.md`, a practical checklist for first runs on real Stonebranch/AutoSys repositories.
- Documented the recommended dry-run sequence, key output files, collision-first triage, edge-diff and command-diff review order, acceptance checklist, and sanitized feedback template for future parser/matching fixes.
- Linked the dry-run checklist from `README.md` so the real-data validation flow is visible before production migration review.

### QA17

- Added a final QA regression pass for comparison artifact contracts, pack manifest important files, Windows launcher compatibility, and baseline archive cleanliness.
- Fixed `comparison_files()` to remove the duplicate `compare/command-diff.csv` entry and list the full generated comparison artifact set, including `metrics.csv`, `collisions.csv`, `mapping-diagnostics.csv`, `remediation-summary.json`, and `overlay-graph.mmd`.
- Updated comparison pack manifests so `important_files` stays aligned with the current comparison output contract.

### QA16

- Added `compare/command-diff.csv` with command diff status, strict/semantic match flags, normalization reasons, variables, env tokens, script basenames, hashes, and safe semantic previews for Excel review.
- Added command normalization diagnostics in `comparison.json`, `report.md`, and `remediation-plan.md`, including normalization reason categories, variable names, env tokens, script basenames, and safe semantic previews.
- Extended semantic command normalization to fold environment-specific script base paths into `<script_path>/<script-name>` while preserving script filenames and arguments.
- Added conservative script-path regression tests: data-file paths stay strict, different script filenames remain semantic mismatches, and equal script basenames can match across Stonebranch/AutoSys base directories.
- Added semantic command normalization on top of strict command hashing so Stonebranch and AutoSys variable masks such as `${VAR}`, `$${var}`, `%%VAR`, `%VAR%`, and `#VAR#` can compare by meaning while preserving strict hashes.
- Command graph nodes now use the semantic command hash for `runs_command` matching, reducing false missing command-edge gaps caused only by scheduler variable syntax or known environment-token differences.
- Comparison command differences are now classified as `command_syntax_diff_only` or `command_semantic_mismatch`; syntax-only differences do not increment `command_mismatch_count`.
- AutoSys command variable references now create `uses_variable` edges so command-variable dependencies can match Stonebranch variable-token edges.
- Added regression tests for semantic command hashes, syntax-only command diffs, real semantic mismatches, report output, and remediation guidance.
- Updated `run_terminal_ui.cmd` to call `python -m stonebranch_graph.cli tui` instead of `py -3`, improving compatibility on Windows machines without the Python launcher alias.

### QA15

- Added an end-to-end production-like migration fixture for Stonebranch `IB_CT_CVA_1109_P1_*` workflow/tasks/file-watcher exports versus AutoSys `IB_CT_CVA_1109_EN_*.jil` files containing `IB_CT_CVA_1109_0en0_*` boxes/jobs.
- Verified direct comparison matches workflow/box containment, task/job dependencies, runtime agents, calendars, command hashes, and file-watcher `watch_file` relations by real object name without environment-token noise.
- Added checks that the comparison edge diff stays normalized and does not leak `P1`/`0en0` object-name prefixes into matched edge keys.

### QA14

- Normalized Stonebranch `successorTask` relations to the same dependency direction as AutoSys conditions: successor/dependent job -> `depends_on_success` -> prerequisite job.
- Added comparison compatibility for legacy `successor_of` edges so older `graph.json` files can still match AutoSys success-condition dependencies.
- Normalized task-level Stonebranch `workflowName` membership to `workflow -> contains -> task` instead of the reversed `task -> contains -> workflow` shape.
- Added comparison compatibility for legacy reversed `contains` edges where task/file-watcher nodes pointed to workflow/box containers.
- Added Stonebranch file-watcher folder support and `watch_file` relation parsing so Stonebranch and AutoSys file-watch dependencies can match as `watches_file` edges.
- Added relation-normalization regression tests for successor dependencies, workflow containment, legacy comparison compatibility, and watch-file edges.

### QA13

- Added explicit diagnostics for enterprise-name collisions where different full object names collapse to the same comparison key after business/environment prefix stripping.
- Collision diagnostics now include reason, original names, business codes, environment tokens, real names, source files, and enterprise naming metadata.
- Comparison reports now include a normalized-key collision section so unsafe automatic matches are visible in human-readable output.
- Expanded `collisions.csv` with collision reason and enterprise naming columns for migration review.
- Added regression tests proving enterprise-name collisions are excluded from automatic matching and exported in JSON/CSV/Markdown diagnostics.

### QA12

- Improved Stonebranch workflow/task containment parsing so workflow folders are recognized as `workflow` nodes and workflow task lists create `contains` edges to tasks.
- Fixed Stonebranch trigger `workflowName` references so they create `trigger -> starts -> workflow` edges instead of synthetic task starts.
- Added nested Stonebranch workflow containment support through workflow-name references inside workflow objects.
- Compared Stonebranch `workflow` containers against AutoSys `box` containers as the same migration containment concept while preserving original graph node kinds.
- Added regression tests for workflow-to-task containment, nested workflows, trigger-to-workflow starts, and Stonebranch workflow vs AutoSys box comparison matching.

### QA11

- Improved AutoSys JIL box/workflow containment correctness for `box_name` relationships, nested boxes, and multi-job box files.
- Added source-file box inference for enterprise-named JIL files such as `IB_CT_CVA_1109_EN_BOX.jil`, limited to multi-job files to avoid false synthetic boxes for single-job files.
- Resolved inferred `EN` file boxes to existing inner `0en0` box definitions by normalized comparison key, avoiding duplicate synthetic parent boxes.
- Fixed graph node merging so a real JIL/Stonebranch object definition replaces an earlier synthetic placeholder created from a reference.
- Improved JIL condition dependencies so references to existing boxes target `box` nodes instead of always creating synthetic `task` nodes.
- Added regression tests for nested box containment, file-level box inference, synthetic-to-real node replacement, and condition references to boxes.

### QA10

- Added large-repository source file discovery that skips hidden/generated trees such as `.git/`, `__pycache__/`, virtualenvs, and local `out/` folders.
- Made Stonebranch JSON discovery fail fast when no JSON files are found instead of silently producing an empty analysis.
- Added Stonebranch support for top-level JSON arrays, including warnings for non-object array items and unsupported JSON roots.
- Added legacy encoding fallback for Stonebranch JSON text, matching the existing JIL text fallback behavior.
- Added JIL warnings when files contain only `delete_job`/non-active content and no active `insert_job` or `update_job` records.
- Added large-repository robustness regression tests for skipped generated trees, JSON arrays, empty inputs, legacy encodings, and run-log warnings.

### QA9

- Split comparison metric calculation into rate, difference-count, graph-quality, and final assembly helpers.
- Split migration readiness scoring into an explicit penalty breakdown so formula weights are easier to review and test.
- Added metrics regression tests for directional coverage rates, critical/calendar/runtime counts, graph-quality inputs, penalty weights, and function complexity boundaries.

### QA8

- Split the large CLI `main()` function into parser construction, command dispatch, and command handler helpers so CLI behavior is easier to test and extend.
- Split `compare_graphs()` into side-index, attribute-diff, node-payload, edge-payload, diagnostics, and summary helpers while preserving the public `Comparison` output contract.
- Split `export_report()` into small report-section helpers for summary, quality metrics, capped graph notes, count tables, warnings, and most-connected objects.
- Added code-complexity regression tests that keep these refactored functions thin and prevent the same large monoliths from returning.

### QA7

- Q7 test-suite cleanup converted slow subprocess-heavy integration checks to direct workflow calls, leaving subprocess coverage only in CLI smoke tests.
- Reduced test-suite runtime by replacing most subprocess-based CLI tests with direct workflow calls while keeping CLI subprocess coverage in `tests/smoke_test.py`.
- Added a test-suite health policy that keeps subprocess usage limited and documented.
- Prevented TUI tests from writing runtime logs/settings into the project root.
- Ensured release archives exclude local runtime state such as `out/`, `.stonebranch-tool-settings.json`, `__pycache__`, and `.pytest_cache`.

### QA6

- Added lightweight `run.log` workflow logging for warnings and errors without changing the public report/graph file contracts.
- Logged parser `Graph.warnings` for Stonebranch/JIL graph builds, analysis pack builds, direct comparisons, graph.json comparisons, and pack comparisons.
- Logged comparison risks as warnings so critical migration concerns are visible in the run log as well as Markdown/JSON reports.
- Logged workflow and CLI errors before re-raising/returning failure, while keeping logging best-effort so logging failures never hide the original error.
- Added regression tests that verify warnings, comparison risks, and errors are written to `run.log`.

### QA5

- Added `GraphTraversalCache` to centralize sorted nodes, sorted edges, degree maps, and object/relation counters for export and pack generation.
- Reused a single traversal cache across `export_graph_bundle()` and `create_analysis_pack()` so CSV, Mermaid/DOT, indexes, and detailed reports no longer repeat the same sort/count/degree passes.
- Updated `compute_graph_metrics()` to accept a supplied traversal cache while preserving the public call pattern.
- Changed `export_csv_rows()` to accept streaming iterables so summary CSV generation does not require temporary row lists.
- Added performance-regression tests to prove traversal cache reuse, deterministic index outputs, and streaming CSV support.

### QA4

- Fixed comparison payload keys so matched objects and edge diffs use normalized comparison keys after enterprise business/env name stripping. This keeps reports aligned with the actual matching logic.
- Unified direct comparison exports with comparison-pack exports: `diff-index.json`, `critical-diff.json`, and `remediation-plan.md` are now generated by `export_comparison()` for direct compare, graph.json compare, and pack compare flows.
- Added condition mismatch penalties and risk messaging to migration readiness scoring.
- Included script runtime edges in critical comparison diffs by using `COMMAND_RELATIONS` in the critical relation set.
- Removed duplicate comparison diff-report generation from `pack.py`; comparison artifact generation now has a single source of truth in `compare.py`.
- Added comparison correctness regression tests for normalized enterprise keys, edge-diff CSV keys, condition mismatch scoring, critical script diffs, and complete compare-graph outputs.

### QA3.1

- Added enterprise business/env-aware name normalization for migration object names such as `IB_CT_CVA_1109_P1_JOB`, `IB_CT_CVA_1109_EN_BOX`, and `IB_CT_CVA_1109_0en0_JOB`. Canonical comparison now uses the real suffix after the business code and environment token while preserving the original object name and id.
- Added `enterprise_naming` metadata with detected prefix, business code, environment token, and real name for Stonebranch and AutoSys JIL nodes.
- Fixed AutoSys JIL `insert_job` parsing so inline attributes such as `insert_job: JOB_NAME job_type: c` no longer become part of the job name.
- Added regression tests for Stonebranch `P1` names versus AutoSys `EN`/`0en0` names and for existing prefixed canonical keys.

### QA3

- Fixed Stonebranch typed-reference resolution so a typed dependency such as `trigger.taskName` no longer binds to a same-name object of the wrong kind; the parser now creates a synthetic node of the expected kind and emits a warning.
- Fixed JIL value cleanup and calendar/list splitting so quoted names with spaces, such as `calendar: "Business Days", HOLIDAYS`, are preserved instead of being split or causing unmatched quote parsing errors.
- Added parser correctness regression tests for wrong-kind Stonebranch references and quoted JIL calendar names.

## v0.5.5 - 2026-07-01

### Fixed

- Fixed TUI Settings navigation by restoring `0) Back` on the simplified Settings screen.
- Fixed cancelled folder selection messaging so unchanged folder settings no longer show success.
- Removed a stray pre-heading changelog bullet that broke the Markdown document structure.
- Corrected Stonebranch trigger `taskName` parsing so triggers start task nodes instead of synthetic trigger nodes.
- Fixed attribute comparison to use `Node.attributes_hash`.
- Fixed TUI JIL schema profiling output paths.
- Removed obsolete terminal folder-browser instructions from README and TUI docs.

### Changed

- Added `stonebranch_graph.workflows` as a shared service layer for CLI and TUI operations.
- Consolidated graph helpers and Mermaid/DOT rendering helpers into shared modules.
- Added capped top-level Mermaid/DOT previews while keeping `graph.json` and CSV exports complete.
- Hardened Stonebranch and AutoSys JIL parsers with duplicate/ambiguous reference warnings and safer default condition evidence.
- Split TUI settings, rendering, prompts, and actions into dedicated modules.
- Updated TUI path/file prompts to use numeric choices only; folder settings open the system picker directly and optional file choices render as one numbered option per line.
- Changed TUI actions to use saved settings only; missing prerequisites now show numeric options to open Settings or go back instead of prompting for paths during execution.
- Added a main TUI project dashboard with selected folder status, pack status, comparison status, and the next recommended action.
- Simplified the TUI Settings screen: the main settings page now contains only Stonebranch source folder, JIL source folder, output folder, and More settings; advanced options are nested behind numeric 1-4 menus.
- Added `stonebranch_graph.domain` constants for source systems, node kinds, and edge relations.
- Expanded parser/export/workflow contract tests and P0 regression tests.
- Added development quality gates for `pytest` and `ruff`.
- Removed obsolete TUI methods and the unused standalone menu renderer left over from pre-P15 settings flows.
- Polished Terminal UI menu consistency. Letter shortcuts remain removed, every command is rendered on its own line, and `0)` stays reserved for Back/Exit/Cancel.

### Packaging

- Updated project version to `0.5.5`.
- Added PEP 517 build-system metadata.
- Added project README/license metadata and package discovery configuration.
- Added this changelog and MIT license file.

### Deferred

- Full privacy-mode/safe-sharing pack workflow remains intentionally deferred for a later iteration.

## v0.5.4 - 2026-06-30

- Added the pack-first terminal workflow.
- Added Stonebranch/JIL graph build and comparison outputs.
- Added analysis pack reports, metrics, Mermaid/DOT views, and CSV/JSON artifacts.
- Removed obsolete legacy launchers/docs.

