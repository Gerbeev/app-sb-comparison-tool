# Stonebranch Dependency Tool v0.3.2.2

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


## v0.3.2.2 bug-check notes

Fixed after review:

- Stonebranch object names are kind-aware; `tasks/*.json` no longer accidentally uses `agentName` or `credentialName` as the task name.
- `description` no longer creates false `script` dependencies.
- Stonebranch `command` references now use command hashes, so they can match JIL command nodes.
- Stonebranch variable tokens now normalize to `uses_variable`.
- Trigger `taskName` references normalize to `starts` instead of `depends_on`.
- JIL box nodes that are declared with `insert_job` are not overwritten as synthetic references when used by `box_name`.


## v0.3.2 metrics

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
