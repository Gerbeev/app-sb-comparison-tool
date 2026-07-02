# Comparison model

The tool does not compare diagrams directly. It compares normalized graph JSON.

## Node identity

Each node has:

```json
{
  "id": "stonebranch:PROD:task:JOB_A",
  "canonical_key": "PROD:task:job_a",
  "source_system": "stonebranch",
  "env": "PROD",
  "kind": "task",
  "name": "JOB_A"
}
```

Kinds are unified across systems for comparison keys while the original kind is
preserved in graph.json and reports:

```text
workflow      -> box    (AutoSys box == Stonebranch workflow)
agent_cluster -> agent  (AutoSys machine is commonly migrated to an agent cluster)
```

## Edge identity

Edges are compared as:

```text
source canonical key -> relation -> target canonical key
```

Example:

```text
PROD:task:job_a -> depends_on_success -> PROD:task:job_b
```

Relations are unified for comparison: `runs_on_cluster` compares as `runs_on`.
Multiple edges that normalize to the same comparison key on one side are the
same semantic edge discovered through different evidence; one deterministic
representative is used for matching and the duplicates stay visible in the
collision diagnostics.

## Stonebranch workflow structure

`workflowVertices` and `workflowEdges` are parsed structurally:

- each vertex becomes `workflow -> contains -> task`
- each workflow edge becomes `successor -> depends_on_<condition> -> predecessor`
  (dependent -> prerequisite, the same direction as AutoSys condition edges)

Edge conditions map to the AutoSys condition families: `Success` ->
`depends_on_success`, `Failure` -> `depends_on_failure`, `Success/Failure` /
`Finished` -> `depends_on_done`. Unknown conditions fall back to the generic
`depends_on`. The generic reference walker skips these subtrees so dependency
endpoints are never misread as containment references.

## Relaxed dependency matching

A generic `depends_on` on one side matches a specific `depends_on_*` between the
same source and target on the other side. These pairs are reported in
`edges.matched_relaxed` and counted in `relaxed_dependency_matches` instead of
producing two false "missing dependency" rows. Conflicting specific conditions
(success vs failure) remain mismatches.

## Stonebranch-only objects

Object kinds that cannot exist in JIL (trigger, credential, connection, script,
email_template) and relations JIL cannot express (starts, uses_credential,
uses_connection, uses_email_template, runs_script, references) are reported in
informational `stonebranch_only` buckets and are not counted as mismatches or
readiness penalties. Match rates use comparable totals.

## Variable references

Variable tokens (`${...}`, `%...%`, `{{...}}`, `@(...)`) become `uses_variable`
edges only when found in command-like fields (command, script, parameters,
args), matching the JIL parser which extracts variables from the command
attribute only.

## JIL condition extraction

Supported patterns:

```text
s(JOB_A)
success(JOB_A)
d(JOB_B)
done(JOB_B)
f(JOB_C)
failure(JOB_C)
t(JOB_D)
terminated(JOB_D)
n(JOB_E)
notrunning(JOB_E)
```

Complex boolean expressions are not evaluated as logic. The parser extracts referenced jobs and status functions while preserving raw condition text on the node metadata.
