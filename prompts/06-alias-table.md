# Prompt 06 — Logical-id alias table (N1)

## Objective

Implement normalization rule **N1** from `docs/mapping-theory.md` §5: comparison is anchored
on a maintained per-system alias table `nativeName → logicalId`, converting graph comparison
into keyed record comparison. Also carries the plumbing markers for AutoSys gate jobs
(consumed by prompt 05) and replaces the ad-hoc `AliasTable` protocol stubs used by the
builders.

## Context — read ONLY these

1. `docs/mapping-theory.md` §5 N1, N3 (gate jobs "marked as such in the alias table").
2. `docs/mapping-explained.md` §6 rule 1.
3. `stonebranch_graph/config.py` — `MappingConfig` (the legacy mapping format you extend
   alongside, not break).
4. `examples/mapping.json` — legacy file shape.
5. The `AliasTable` protocol as defined in `skeleton_autosys.py` / `skeleton_stonebranch.py`.

## Requirements

### A. File format — `alias.json` (new, sits next to the legacy mapping file)

```jsonc
{
  "version": 1,
  "logical_ids": {
    "autosys":     { "ACME_LOAD_ORDERS": "etl/load_orders" },
    "stonebranch": { "acme-load-orders": "etl/load_orders" }
  },
  "plumbing": {
    "autosys":     ["GATE_FANIN_X", "DUMMY_*"],
    "stonebranch": []
  }
}
```

1. Keys in `logical_ids` are native object names, matched case-insensitively after
   `core.normalize_name`. Values are either a full containment-path logical id (used
   verbatim) or a bare leaf (participates in path derivation) — distinguished by presence of
   `/`. Document this in the module docstring.
2. `plumbing` entries support trailing-`*` glob (prefix match) — enough for gate-job naming
   conventions without regex cost.
3. Loader: `AliasTable.from_file(path: Path | None) -> AliasTable`; `None` → empty table.
   Unknown top-level keys → warning list on the table, not an exception.

### B. Module — `stonebranch_graph/alias.py`

`AliasTable` dataclass implementing exactly the protocol the builders already call:
- `logical_id(system: str, native_name: str) -> str | None`
- `is_plumbing(system: str, native_name: str) -> bool`
- plus `usage` tracking: record every hit and every miss-after-lookup so unused entries can
  be reported (mirrors the existing `unused_mappings` diagnostic in `compare.py`).
- `unused_entries() -> list[tuple[str, str]]` (system, native_name).

Precompute per-system dicts and sorted glob prefixes at load; lookups must be O(1)/O(log n) —
this runs once per node for thousands of nodes.

### C. Wiring

1. Replace the builders' local protocol definitions with `from .alias import AliasTable`
   (keep signatures identical).
2. `AutosysJilParser`-side gate jobs: `build_autosys_skeleton` already sets
   `meta["plumbing"]` from `alias.is_plumbing` (prompt 03 B.8) — verify and add a test.
3. Do not touch `MappingConfig` or the legacy compare path; the alias table is
   skeleton-pipeline-only. The legacy `mapping.json` remains valid for `--legacy-compare`.

### D. Tests — `tests/test_alias.py`

Full-path vs leaf values; case-insensitive native lookup; glob plumbing; unused-entry
reporting; empty/missing file; both builders honoring alias ids (one test each, reusing
existing fixtures).

## Out of scope

Comparison engine, CLI flags (prompt 10 adds `--alias`), migration of legacy mapping files.

## Acceptance criteria

1. Tests pass; all previous suites pass; `ruff check` clean.
2. With an alias file mapping `ACME_LOAD_ORDERS` (JIL) and `acme-load-orders` (SB) to the
   same logical id, the two builders emit nodes with identical skeleton ids.

## Cost guidance

Small module (~120 lines). Read nothing beyond the listed context; builders' call sites are
already shaped for this API.
