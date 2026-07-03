"""AutoSys JIL raw-record to Skeleton builder from docs/mapping-theory.md section 3."""

from __future__ import annotations

from dataclasses import dataclass

from stonebranch_graph import expr
from stonebranch_graph.jil_condition import (
    JilConditionError,
    ParsedJilCondition,
    parse_jil_condition_details,
)
from stonebranch_graph.normalizers import command_hash, semantic_command_hash
from stonebranch_graph.parsers.autosys_jil import JilJob
from stonebranch_graph.skeleton import (
    EXT_PREFIX,
    KIND_CONTAINER,
    KIND_UNIT,
    Skeleton,
    SkeletonNode,
    child_id,
    logical_leaf,
)

from .alias import AliasTable


@dataclass(frozen=True)
class _JobEntry:
    native_name: str
    job: JilJob | None
    synthetic: bool = False


def build_autosys_skeleton(
    jobs: list[JilJob], *, alias: AliasTable | None = None
) -> Skeleton:
    """Build a canonical skeleton from raw AutoSys JIL job records."""

    skeleton = Skeleton()
    entries = _register_jobs(jobs, skeleton)
    _ensure_synthetic_boxes(entries, skeleton)

    node_ids: dict[str, str] = {}
    node_parents: dict[str, str | None] = {}
    for native_name in entries:
        _resolve_node_identity(native_name, entries, node_ids, node_parents, skeleton, alias, ())
    parent_by_node_id = {
        child_node_id: node_parents[child_native_name]
        for child_native_name, child_node_id in node_ids.items()
    }
    node_ids_by_leaf = _node_ids_by_leaf(node_ids)

    for native_name, entry in entries.items():
        node_id = node_ids[native_name]
        parent_id = node_parents[native_name]
        trigger = _parse_condition(
            entry.job.attributes.get("condition", "") if entry.job else "",
            job_name=native_name,
            node_ids=node_ids,
            node_ids_by_leaf=node_ids_by_leaf,
            warnings=skeleton.warnings,
        )
        if trigger is not None:
            trigger = _drop_ancestor_refs(trigger, node_id, parent_by_node_id, skeleton.warnings)
        completion = _completion_expression(
            entry,
            node_ids,
            node_ids_by_leaf,
            skeleton.warnings,
        )
        skeleton.add_node(
            SkeletonNode(
                id=node_id,
                kind=_entry_kind(entry),
                parent=parent_id,
                trigger=trigger,
                # Section 6 has no Universal Controller analog; strict diff flags non-null
                # completion, correctly.
                completion=completion,
                meta=_entry_meta(entry, alias),
            ),
            merge_allowed=bool(alias and alias.is_merge_allowed("autosys", node_id)),
        )

    skeleton.validate()
    return skeleton


def _register_jobs(jobs: list[JilJob], skeleton: Skeleton) -> dict[str, _JobEntry]:
    entries: dict[str, _JobEntry] = {}
    for job in jobs:
        if job.name in entries:
            skeleton.warnings.append(
                f"Duplicate JIL job name {job.name!r}: keeping first definition."
            )
            continue
        entries[job.name] = _JobEntry(native_name=job.name, job=job)
    return entries


def _ensure_synthetic_boxes(entries: dict[str, _JobEntry], skeleton: Skeleton) -> None:
    for entry in list(entries.values()):
        box_name = _parent_native_name(entry)
        if not box_name or box_name in entries:
            continue
        entries[box_name] = _JobEntry(native_name=box_name, job=None, synthetic=True)
        skeleton.warnings.append(
            f"JIL box_name {box_name!r} referenced by {entry.native_name!r} is undefined; "
            "created synthetic container."
        )


def _resolve_node_identity(
    native_name: str,
    entries: dict[str, _JobEntry],
    node_ids: dict[str, str],
    node_parents: dict[str, str | None],
    skeleton: Skeleton,
    alias: AliasTable | None,
    stack: tuple[str, ...],
) -> str:
    if native_name in node_ids:
        return node_ids[native_name]
    if native_name in stack:
        skeleton.warnings.append(
            "Containment cycle while deriving AutoSys skeleton ids: "
            + " -> ".join((*stack, native_name))
        )
        node_parents[native_name] = None
        node_ids[native_name] = _logical_id_or_leaf(native_name, alias)
        return node_ids[native_name]

    entry = entries[native_name]
    parent_native = _parent_native_name(entry)
    parent_id = None
    if parent_native in entries:
        parent_id = _resolve_node_identity(
            parent_native, entries, node_ids, node_parents, skeleton, alias, (*stack, native_name)
        )

    logical = _alias_logical_id(alias, native_name)
    if logical is not None and "/" in logical.strip("/"):
        node_id = logical.strip("/")
    else:
        leaf = logical.strip("/").rsplit("/", 1)[-1] if logical else logical_leaf(native_name)
        node_id = child_id(parent_id, leaf)

    node_ids[native_name] = node_id
    node_parents[native_name] = parent_id
    return node_id


def _parent_native_name(entry: _JobEntry) -> str:
    if entry.job is None:
        return ""
    box_name = entry.job.attributes.get("box_name", "")
    if not box_name:
        return ""
    if logical_leaf(box_name) == logical_leaf(entry.native_name):
        return ""
    return box_name


def _entry_kind(entry: _JobEntry) -> str:
    if entry.synthetic:
        return KIND_CONTAINER
    job_type = (entry.job.attributes.get("job_type", "c") if entry.job else "b").lower()
    return KIND_CONTAINER if job_type in {"b", "box"} else KIND_UNIT


def _entry_meta(entry: _JobEntry, alias: AliasTable | None) -> dict[str, object]:
    meta: dict[str, object] = {"src": "autosys", "native": entry.native_name}
    if entry.synthetic:
        meta.update({"type": "box", "synthetic": True})
        return meta

    assert entry.job is not None
    job_type = entry.job.attributes.get("job_type", "c")
    meta.update({"type": job_type, "source_file": entry.job.source_file})
    command = entry.job.attributes.get("command")
    if command:
        meta["command_hash"] = command_hash(command)
        meta["semantic_command_hash"] = semantic_command_hash(command)
    if _alias_is_plumbing(alias, entry.native_name):
        meta["plumbing"] = True
    return meta


def _completion_expression(
    entry: _JobEntry,
    node_ids: dict[str, str],
    node_ids_by_leaf: dict[str, str],
    warnings: list[str],
) -> expr.Expr | None:
    if _entry_kind(entry) != KIND_CONTAINER or entry.job is None:
        return None

    attrs = entry.job.attributes
    box_success = attrs.get("box_success", "")
    box_failure = attrs.get("box_failure", "")
    if box_success and box_failure:
        warnings.append(
            f"AutoSys box {entry.native_name!r} has both box_success and box_failure; "
            "using box_success as completion."
        )
    if box_success:
        return _parse_condition(
            box_success,
            job_name=entry.native_name,
            node_ids=node_ids,
            node_ids_by_leaf=node_ids_by_leaf,
            warnings=warnings,
        )
    if box_failure:
        parsed = _parse_condition(
            box_failure,
            job_name=entry.native_name,
            node_ids=node_ids,
            node_ids_by_leaf=node_ids_by_leaf,
            warnings=warnings,
        )
        return expr.Not(parsed) if parsed is not None else None
    return None


def _parse_condition(
    condition: str,
    *,
    job_name: str,
    node_ids: dict[str, str],
    node_ids_by_leaf: dict[str, str],
    warnings: list[str],
) -> expr.Expr | None:
    if not condition:
        return None
    try:
        parsed = parse_jil_condition_details(condition, job_name=job_name)
    except JilConditionError as exc:
        warnings.extend(exc.warnings)
        warnings.append(f"Could not parse JIL condition for {job_name!r}: {exc}")
        return None
    warnings.extend(parsed.warnings)
    return _rewrite_condition_refs(parsed, node_ids, node_ids_by_leaf)


def _rewrite_condition_refs(
    parsed: ParsedJilCondition,
    node_ids: dict[str, str],
    node_ids_by_leaf: dict[str, str],
) -> expr.Expr:
    def rewrite(current: expr.Expr) -> expr.Expr:
        if isinstance(current, expr.Atom):
            if current.node_ref.startswith(EXT_PREFIX):
                return current
            raw_name = parsed.atom_names.get(_atom_key(current), current.node_ref)
            node_ref = node_ids.get(raw_name) or node_ids_by_leaf.get(logical_leaf(raw_name))
            if node_ref is None:
                node_ref = logical_leaf(raw_name)
            return expr.Atom(node_ref, current.predicate, current.qualifier)
        if isinstance(current, expr.And):
            return expr.And(tuple(rewrite(child) for child in current.children))
        if isinstance(current, expr.Or):
            return expr.Or(tuple(rewrite(child) for child in current.children))
        return expr.Not(rewrite(current.child))

    return expr.canonicalize(rewrite(parsed.expression))


def _node_ids_by_leaf(node_ids: dict[str, str]) -> dict[str, str]:
    return {logical_leaf(native_name): node_id for native_name, node_id in node_ids.items()}


def _drop_ancestor_refs(
    trigger: expr.Expr,
    node_id: str,
    parent_by_node_id: dict[str, str | None],
    warnings: list[str],
) -> expr.Expr | None:
    ancestors = _ancestor_ids(node_id, parent_by_node_id)
    if not ancestors:
        return trigger
    removed: set[str] = set()

    def prune(current: expr.Expr) -> expr.Expr | None:
        if isinstance(current, expr.Atom):
            if current.node_ref in ancestors:
                removed.add(current.node_ref)
                return None
            return current
        if isinstance(current, expr.And | expr.Or):
            kept = tuple(child for child in (prune(child) for child in current.children) if child)
            if not kept:
                return None
            if len(kept) == 1:
                return kept[0]
            return type(current)(kept)
        child = prune(current.child)
        return expr.Not(child) if child is not None else None

    pruned = prune(trigger)
    for ancestor in sorted(removed):
        warnings.append(
            f"Dropped AutoSys ancestor container dependency {ancestor!r} from node {node_id!r}."
        )
    return expr.canonicalize(pruned) if pruned is not None else None


def _ancestor_ids(node_id: str, parent_by_node_id: dict[str, str | None]) -> set[str]:
    current = parent_by_node_id.get(node_id)
    ancestors: set[str] = set()
    while current is not None and current not in ancestors:
        ancestors.add(current)
        current = parent_by_node_id.get(current)
    return ancestors


def _logical_id_or_leaf(native_name: str, alias: AliasTable | None) -> str:
    logical = _alias_logical_id(alias, native_name)
    return logical.strip("/") if logical else logical_leaf(native_name)


def _alias_logical_id(alias: AliasTable | None, native_name: str) -> str | None:
    if alias is None:
        return None
    logical = alias.logical_id("autosys", native_name)
    return logical or None


def _alias_is_plumbing(alias: AliasTable | None, native_name: str) -> bool:
    return alias is not None and alias.is_plumbing("autosys", native_name)


def _atom_key(atom: expr.Atom) -> tuple[str, str, str]:
    return (atom.node_ref, atom.predicate, atom.qualifier)
