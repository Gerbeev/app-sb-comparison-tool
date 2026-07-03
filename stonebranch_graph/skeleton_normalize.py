"""Skeleton normalization passes from docs/mapping-theory.md section 5."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from stonebranch_graph import expr
from stonebranch_graph.skeleton import KIND_CONTAINER, Skeleton, SkeletonNode

UNSAFE_ERASURE_PREDICATES = {expr.FAILURE, expr.TERMINATED, expr.NOT_RUNNING, expr.EXIT}


@dataclass
class _ReferenceIndex:
    trigger_refs: dict[str, set[str]] = field(default_factory=dict)
    completion_refs: dict[str, set[str]] = field(default_factory=dict)
    monitor_refs: dict[str, set[str]] = field(default_factory=dict)
    children_by_parent: dict[str, set[str]] = field(default_factory=dict)
    snapshots: dict[str, _NodeReferenceSnapshot] = field(default_factory=dict)

    def referencing_ids(self, ref_id: str) -> set[str]:
        return (
            set(self.trigger_refs.get(ref_id, set()))
            | set(self.completion_refs.get(ref_id, set()))
            | set(self.monitor_refs.get(ref_id, set()))
        )

    def index_node(self, node_id: str, node: SkeletonNode) -> None:
        snapshot = _snapshot_node(node)
        self.snapshots[node_id] = snapshot
        for ref_id in snapshot.trigger_refs:
            self.trigger_refs.setdefault(ref_id, set()).add(node_id)
        for ref_id in snapshot.completion_refs:
            self.completion_refs.setdefault(ref_id, set()).add(node_id)
        if snapshot.monitor_ref:
            self.monitor_refs.setdefault(snapshot.monitor_ref, set()).add(node_id)
        if snapshot.parent is not None:
            self.children_by_parent.setdefault(snapshot.parent, set()).add(node_id)

    def remove_node(self, node_id: str) -> None:
        snapshot = self.snapshots.pop(node_id, None)
        if snapshot is None:
            return
        for ref_id in snapshot.trigger_refs:
            self._discard(self.trigger_refs, ref_id, node_id)
        for ref_id in snapshot.completion_refs:
            self._discard(self.completion_refs, ref_id, node_id)
        if snapshot.monitor_ref:
            self._discard(self.monitor_refs, snapshot.monitor_ref, node_id)
        if snapshot.parent is not None:
            self._discard(self.children_by_parent, snapshot.parent, node_id)

    def reindex_node(self, node_id: str, node: SkeletonNode) -> None:
        self.remove_node(node_id)
        self.index_node(node_id, node)

    def _discard(self, index: dict[str, set[str]], key: str, node_id: str) -> None:
        node_ids = index.get(key)
        if node_ids is None:
            return
        node_ids.discard(node_id)
        if not node_ids:
            index.pop(key, None)


@dataclass(frozen=True)
class _NodeReferenceSnapshot:
    trigger_refs: frozenset[str]
    completion_refs: frozenset[str]
    monitor_ref: str
    parent: str | None


def erase_plumbing(skeleton: Skeleton) -> Skeleton:
    """Return a copy of skeleton with dependency-only plumbing nodes erased."""

    result = Skeleton(
        nodes={node_id: _copy_node(node) for node_id, node in skeleton.nodes.items()},
        warnings=list(skeleton.warnings),
        erasures=[dict(erasure) for erasure in skeleton.erasures],
    )

    _demote_marked_containers(result)
    reference_index = _build_reference_index(result)
    max_iterations = max(len(result.nodes), 1)
    for _ in range(max_iterations):
        plumbing_ids = _plumbing_unit_ids(result)
        if not plumbing_ids:
            result.validate()
            return result

        node_id = plumbing_ids[0]
        bad_predicate = _unsafe_dependency_predicate(result, reference_index, node_id)
        if bad_predicate is not None:
            _keep_as_real_unit(result, node_id, f"depended on with predicate {bad_predicate}")
            reference_index.reindex_node(node_id, result.nodes[node_id])
            continue

        cycle_members = _cycle_members(result, node_id)
        if cycle_members:
            for cycle_id in sorted(cycle_members):
                _keep_as_real_unit(result, cycle_id, "plumbing cycle detected")
                reference_index.reindex_node(cycle_id, result.nodes[cycle_id])
            continue

        _erase_one(result, reference_index, node_id)

    for node_id in _plumbing_unit_ids(result):
        _keep_as_real_unit(result, node_id, "plumbing cycle detected")
    result.validate()
    return result


def _copy_node(node: SkeletonNode) -> SkeletonNode:
    return replace(node, meta=dict(node.meta))


def _demote_marked_containers(skeleton: Skeleton) -> None:
    for node_id in sorted(skeleton.nodes):
        node = skeleton.nodes[node_id]
        if node.kind == KIND_CONTAINER and node.meta.get("plumbing"):
            skeleton.warnings.append(
                f"kept plumbing container {node_id}: containers are never erased"
            )


def _plumbing_unit_ids(skeleton: Skeleton) -> list[str]:
    return [
        node_id
        for node_id in sorted(skeleton.nodes)
        if skeleton.nodes[node_id].kind != KIND_CONTAINER
        and bool(skeleton.nodes[node_id].meta.get("plumbing"))
    ]


def _build_reference_index(skeleton: Skeleton) -> _ReferenceIndex:
    index = _ReferenceIndex()
    for node_id, node in skeleton.nodes.items():
        index.index_node(node_id, node)
    return index


def _snapshot_node(node: SkeletonNode) -> _NodeReferenceSnapshot:
    return _NodeReferenceSnapshot(
        trigger_refs=_expr_refs(node.trigger),
        completion_refs=_expr_refs(node.completion),
        monitor_ref=_monitor_reference_target(node),
        parent=node.parent,
    )


def _expr_refs(current: expr.Expr | None) -> frozenset[str]:
    if current is None:
        return frozenset()
    return frozenset(atom.node_ref for atom in expr.atoms(current))


def _unsafe_dependency_predicate(
    skeleton: Skeleton,
    reference_index: _ReferenceIndex,
    plumbing_id: str,
) -> str | None:
    for current_id in sorted(reference_index.referencing_ids(plumbing_id)):
        if current_id == plumbing_id:
            continue
        node = skeleton.nodes[current_id]
        monitor_predicate = _monitor_reference_predicate(node, plumbing_id)
        if monitor_predicate in UNSAFE_ERASURE_PREDICATES:
            return monitor_predicate
        for current in (node.trigger, node.completion):
            if current is None:
                continue
            for atom in expr.atoms(current):
                if atom.node_ref == plumbing_id and atom.predicate in UNSAFE_ERASURE_PREDICATES:
                    return atom.predicate
    return None


def _cycle_members(skeleton: Skeleton, node_id: str) -> set[str]:
    visited: set[str] = set()
    stack: list[str] = []

    def visit(current_id: str) -> set[str]:
        if current_id in stack:
            cycle_start = stack.index(current_id)
            return set(stack[cycle_start:])
        if current_id in visited:
            return set()
        node = skeleton.nodes.get(current_id)
        if node is None or not node.meta.get("plumbing") or node.kind == KIND_CONTAINER:
            return set()

        visited.add(current_id)
        stack.append(current_id)
        replacement = _replacement_expr(node)
        for atom in expr.atoms(replacement) if replacement is not None else ():
            cycle = visit(atom.node_ref)
            if cycle:
                return cycle
        stack.pop()
        return set()

    return visit(node_id)


def _erase_one(skeleton: Skeleton, reference_index: _ReferenceIndex, node_id: str) -> None:
    node = skeleton.nodes[node_id]
    if reference_index.children_by_parent.get(node_id):
        raise AssertionError(f"Plumbing unit {node_id!r} has children")

    replacement_expr = _replacement_expr(node)
    replaced_in: set[str] = set()
    for current_id in sorted(reference_index.referencing_ids(node_id)):
        if current_id == node_id:
            continue
        original = skeleton.nodes.get(current_id)
        if original is None:
            continue
        current = _substitute_monitor_target(original, node_id, replacement_expr)
        trigger = _substitute_optional(current.trigger, node_id, replacement_expr)
        completion = _substitute_optional(current.completion, node_id, replacement_expr)
        if trigger != current.trigger or completion != current.completion:
            skeleton.nodes[current_id] = replace(current, trigger=trigger, completion=completion)
            reference_index.reindex_node(current_id, skeleton.nodes[current_id])
            replaced_in.add(current_id)
        elif current is not original:
            skeleton.nodes[current_id] = current
            reference_index.reindex_node(current_id, skeleton.nodes[current_id])
            replaced_in.add(current_id)

    del skeleton.nodes[node_id]
    reference_index.remove_node(node_id)
    skeleton.erasures.append(
        {
            "id": node_id,
            "kind": node.meta.get("plumbing"),
            "replaced_in": sorted(replaced_in),
        }
    )


def _substitute_optional(
    current: expr.Expr | None,
    node_id: str,
    replacement_expr: expr.Expr | None,
) -> expr.Expr | None:
    if current is None:
        return None
    substituted = expr.substitute(current, node_id, replacement_expr)
    return expr.canonicalize(substituted) if substituted is not None else None


def _replacement_expr(node: SkeletonNode) -> expr.Expr | None:
    plumbing_kind = node.meta.get("plumbing")
    if plumbing_kind == "task_monitor":
        monitor = node.meta.get("monitor")
        if not isinstance(monitor, dict):
            return node.trigger
        target = _string_value(monitor.get("target"))
        predicate = _string_value(monitor.get("predicate")) or expr.SUCCESS
        if not target:
            return node.trigger
        monitor_expr: expr.Expr = expr.Atom(target, predicate)
        if node.trigger is None:
            return monitor_expr
        return expr.canonicalize(expr.And((node.trigger, monitor_expr)))
    return node.trigger


def _monitor_reference_predicate(node: SkeletonNode, ref_id: str) -> str | None:
    if node.meta.get("plumbing") != "task_monitor":
        return None
    monitor = node.meta.get("monitor")
    if not isinstance(monitor, dict) or monitor.get("target") != ref_id:
        return None
    return _string_value(monitor.get("predicate")) or expr.SUCCESS


def _monitor_reference_target(node: SkeletonNode) -> str:
    if node.meta.get("plumbing") != "task_monitor":
        return ""
    monitor = node.meta.get("monitor")
    if not isinstance(monitor, dict):
        return ""
    return _string_value(monitor.get("target"))


def _substitute_monitor_target(
    node: SkeletonNode,
    ref_id: str,
    replacement_expr: expr.Expr | None,
) -> SkeletonNode:
    predicate = _monitor_reference_predicate(node, ref_id)
    if predicate not in {expr.SUCCESS, expr.DONE}:
        return node

    meta = dict(node.meta)
    monitor = dict(meta.get("monitor", {}))
    monitor.pop("target", None)
    meta["monitor"] = monitor
    trigger = _and_optional(node.trigger, replacement_expr)
    return replace(node, trigger=trigger, meta=meta)


def _and_optional(left: expr.Expr | None, right: expr.Expr | None) -> expr.Expr | None:
    if left is None:
        return right
    if right is None:
        return left
    return expr.canonicalize(expr.And((left, right)))


def _keep_as_real_unit(skeleton: Skeleton, node_id: str, reason: str) -> None:
    node = skeleton.nodes[node_id]
    meta = dict(node.meta)
    plumbing_kind = meta.pop("plumbing", None)
    skeleton.nodes[node_id] = replace(node, meta=meta)
    if plumbing_kind is not None:
        skeleton.warnings.append(f"kept plumbing node {node_id}: {reason}")


def _string_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""
