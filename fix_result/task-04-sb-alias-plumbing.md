# Task 04 — Stonebranch alias-marked plumbing is ignored (MEDIUM)

## Problem
Concept rule **N3** (`mapping-theory.md` §5) defines plumbing erasure for *"UC Task Monitors,
UC Sleep/dummy tasks, AutoSys gate jobs marked as such in the alias table."* So the alias
`plumbing` list is meant to mark **dummy/gate tasks by name on both systems**.

Current behavior:
- AutoSys side honors it: `skeleton_autosys.py::_entry_meta` calls `_alias_is_plumbing(...)` →
  `alias.is_plumbing("autosys", name)` and sets `meta["plumbing"]=True`.
- Stonebranch side does **not**: `skeleton_stonebranch.py::_base_meta` sets `meta["plumbing"]`
  only from the native **type token** (`TASK_MONITOR_TYPE_TOKENS`, `SLEEP_TYPE_TOKENS`). It never
  calls `alias.is_plumbing("stonebranch", name)`.

Consequence: a Stonebranch dummy/fan-in task that is a normal command/Sleep-like task but **not**
typed "Task Monitor" cannot be erased via the alias table. The `plumbing: {stonebranch: ["MON_*"]}`
entry in `examples/alias.json` is currently dead configuration (MON_* is already erased by type),
which masks the gap. Migrations that use gate tasks on the UC side will keep glue nodes that the
AutoSys side does not have → false `only_in_stonebranch` topology diffs.

## Fix
1. In `skeleton_stonebranch.py::_StonebranchSkeletonBuilder._base_meta`, after the type-based
   detection, also check the alias table:
   ```python
   if self.alias and self.alias.is_plumbing("stonebranch", native_name) and "plumbing" not in meta:
       meta["plumbing"] = "alias"
   ```
   Guard: never mark a `container`/workflow as plumbing (containers are never erased — see
   `skeleton_normalize._demote_marked_containers`); apply only to unit specs.
2. For alias-marked (non-Task-Monitor) plumbing, the erasure replacement is the node's own trigger
   (already handled: `skeleton_normalize._replacement_expr` returns `node.trigger` for non
   `task_monitor` plumbing). Verify a gate task with incoming Success connectors and one outgoing
   dependency erases correctly (successor inherits the gate's trigger).
3. Keep the existing unsafe-predicate guard: if the gate is depended on via FAILURE/TERMINATED/
   EXIT, `skeleton_normalize._unsafe_dependency_predicate` already keeps it as real work — leave
   that behavior.

## Acceptance (task 07 fixtures)
- A UC command task `GATE_FANIN` (not Task Monitor type) listed in
  `alias.plumbing.stonebranch` is erased; its successors inherit its predecessors' triggers; no
  `GATE_FANIN` node remains in the skeleton.
- The equivalent AutoSys graph (no gate, direct condition) produces the same topology → zero
  `only_in_*` at topology level.
