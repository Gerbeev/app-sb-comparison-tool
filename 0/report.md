# stonebranch dependency graph report

## Summary

- Env: **PROD**
- Objects: **9**
- Dependencies: **10**

## Quality metrics

- Synthetic nodes: **2**
- Low-confidence edges: **0**
- Orphan nodes: **0**
- Orphan tasks: **0**
- Tasks without inbound dependency: **1**
- Tasks without outbound dependency: **0**
- Tasks without trigger: **1**
- Condition nodes: **0**
- Conditions not parsed: **0**

## Object types

| Kind | Count |
|---|---:|
| command | 2 |
| task | 2 |
| agent | 1 |
| calendar | 1 |
| credential | 1 |
| trigger | 1 |
| variable | 1 |

## Relation types

| Relation | Count |
|---|---:|
| runs_command | 2 |
| runs_on | 2 |
| uses_calendar | 2 |
| depends_on_success | 1 |
| starts | 1 |
| uses_credential | 1 |
| uses_variable | 1 |

## Warnings

- Created 2 synthetic nodes for unresolved references.

## Most connected objects

| Kind | Object | In | Out | Total |
|---|---|---:|---:|---:|
| task | `JOB_A` | 2 | 5 | 7 |
| task | `JOB_B` | 0 | 3 | 3 |
| agent | `machine01` | 2 | 0 | 2 |
| calendar | `BUSINESS_DAYS` | 2 | 0 | 2 |
| trigger | `TRG_JOB_A` | 0 | 2 | 2 |
| credential | `CRED_APP` | 1 | 0 | 1 |
| variable | `RUN_DATE` | 1 | 0 | 1 |
| command | `839f31339ca67757` | 1 | 0 | 1 |
| command | `abe08ff03ed79b2a` | 1 | 0 | 1 |
