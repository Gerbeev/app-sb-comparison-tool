# Metrics

## Graph metrics

Generated for each graph:

```text
stonebranch/metrics.json
stonebranch/metrics.csv
jil/metrics.json
jil/metrics.csv
```

Metrics:

- `nodes_total`
- `edges_total`
- `task_nodes`
- `synthetic_nodes`
- `low_confidence_edges`
- `orphan_nodes`
- `orphan_tasks`
- `tasks_without_inbound_dependency`
- `tasks_without_outbound_dependency`
- `tasks_without_trigger`
- `condition_nodes`
- `conditions_not_parsed`
- `object_types`
- `relation_types`

## Comparison metrics

Generated under:

```text
compare/metrics.json
compare/metrics.csv
```

### Readiness score

`migration_readiness_score` is a 0–100 score.

Grades:

- `excellent`: 95–100
- `good`: 85–94
- `review_required`: 70–84
- `high_risk`: 50–69
- `unsafe`: 0–49

The score penalizes:

- node mismatch
- edge mismatch
- missing critical JIL dependency edges in Stonebranch
- extra critical Stonebranch dependency edges not found in JIL
- calendar mismatches
- agent/machine mismatches
- command hash mismatches
- unparsed JIL conditions
- synthetic nodes
- low-confidence edges

### Critical dependency loss

`critical_dependency_loss_count` counts JIL edges missing in Stonebranch for relations:

- `depends_on`
- `depends_on_success`
- `depends_on_done`
- `depends_on_failure`
- `depends_on_terminated`
- `depends_on_notrunning`
- `contains`

This is the most important migration safety metric.
