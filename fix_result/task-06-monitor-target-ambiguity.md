# Task 06 — Task Monitor target resolution picks an instance arbitrarily (MEDIUM)

## Problem
Concept §4 + **N6**: sub-workflows are inlined per use, so the same task name can exist as many
path-qualified instances. When a Task Monitor watches such a task, the erased dependency must point
at the **correct** instance, or the substituted trigger wires the wrong edge.

`skeleton_stonebranch.py::_monitor_payload` resolves the monitored name against
`_instance_index` (name → sorted list of ids):
- If several instances share the monitor's parent, it takes `same_parent[0]` and only warns.
- Otherwise it takes `candidates[0]` and only warns.

`candidates[0]` is "smallest id by sort order", i.e. arbitrary. A wrong pick produces a real but
silent mis-wire: the successor ends up depending on the wrong instance's status, and the diff
against AutoSys will look either matched (coincidentally) or wrong on an unrelated node.

## Fix
1. **Make ambiguity a first-class signal, not a warning.** When more than one candidate remains
   after the same-parent filter, record `spec.meta["ambiguous_monitor_target"] = {name, candidates}`
   and have `skeleton_compare` raise a risk + list these nodes in the report. Reconciliation must
   not report clean when a monitored target was guessed.
2. **Alias-qualified targeting.** Let the alias table (or the monitor record itself, if the UC
   export carries a workflow/parent hint such as `taskMonitoredWorkflow`) disambiguate by
   qualifying the monitored name with its owning workflow. Prefer an exact path match before
   falling back to same-parent, before falling back to global.
3. **Deterministic, documented fallback.** Keep a deterministic final fallback but document it and
   emit the risk from step 1 whenever the fallback is used.

## Notes
- `TASK_MONITOR_TARGET_KEYS` already lists several key variants; add any workflow-scoping key you
  find in real exports (see `IMPLEMENTATION_PLAN.md` §5 "UC export field variance").
- Keep the existing external-target path (target not found in this graph) intact; this task only
  concerns the multi-instance in-graph case.

## Acceptance (task 07 fixtures)
- A workflow reused twice, each instance containing task `load`, with a monitor watching `load`:
  when the monitor's parent/workflow hint identifies instance B, the successor's substituted
  trigger references `.../B/load`, and a risk is raised only if no hint disambiguates.
- No hint available → node listed under an "ambiguous monitor targets" report section.
