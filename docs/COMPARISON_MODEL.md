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

## Edge identity

Edges are compared as:

```text
source canonical key -> relation -> target canonical key
```

Example:

```text
PROD:task:job_a -> depends_on_success -> PROD:task:job_b
```

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
