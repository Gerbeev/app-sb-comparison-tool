from __future__ import annotations

import json
from collections import defaultdict
from importlib import resources
from pathlib import Path
from typing import Any

from . import expr as trigger_expr
from .core import Graph, Node
from .domain import (
    DEPENDENCY_RELATIONS,
    KIND_BOX,
    KIND_FILE_WATCHER,
    KIND_TASK,
    KIND_WORKFLOW,
)
from .exporters import (
    build_container_view,
    canonical_edge_components,
    canonical_kind,
    canonical_node_key,
    stable_value,
    write_text_file,
)
from .graph_utils import GraphTraversalCache
from .skeleton import KIND_CONTAINER, KIND_UNIT, Skeleton, SkeletonNode, depends_on_view

HTML_GRAPH_SCHEMA_VERSION = "1.0"
CYTOSCAPE_RUNTIME_FILE = "cytoscape.min.js"
SKELETON_TRIGGER_INLINE_NODE_THRESHOLD = 4_000
"""Above this node count, omit pure SUCCESS-AND trigger strings from skeleton HTML payloads."""
SKELETON_DIFF_HTML_MAX_EDGES = 800
COMPACT_JSON_THRESHOLD = 5_000
"""Above this many jobs+edges (or skeleton nodes), stop pretty-printing graph-data.js.

indent=2 is nice for small/medium reports (readable, diff-friendly), but
roughly doubles payload size for no runtime benefit - large reports switch to
compact JSON so download/parse time doesn't scale with indentation.
"""


def _payload_size_hint(payload: dict[str, Any]) -> int:
    return len(payload.get("jobs", [])) + len(payload.get("edges", [])) + len(payload.get("nodes", []))


def _dump_graph_payload(payload: dict[str, Any]) -> str:
    indent = None if _payload_size_hint(payload) > COMPACT_JSON_THRESHOLD else 2
    return json.dumps(payload, indent=indent, ensure_ascii=False, sort_keys=True)


def _sorted_by_id_for_diff(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of a graph-data payload with id-bearing list fields sorted by id.

    The payload embedded in each report's `*-data.js` is already deterministic
    (`sort_keys=True`), but list fields such as `jobs` are ordered for the UI
    (grouped by container, then id) rather than purely by id. This produces a
    diff-friendly sibling where every list of objects carrying an "id" field
    is reordered to sort strictly by that id, so two reports (e.g. the
    Stonebranch side vs. the JIL side of a comparison) can be compared
    object-by-object in an external diff tool with minimal unrelated churn.
    """

    result = dict(payload)
    for key, value in payload.items():
        if isinstance(value, list) and value and all(
            isinstance(item, dict) and "id" in item for item in value
        ):
            result[key] = sorted(value, key=lambda item: str(item["id"]))
    return result


def export_graph_data_json(payload: dict[str, Any], path: Path) -> None:
    """Write a plain, sorted-by-id JSON sibling of a report's `*-data.js` payload.

    Unlike `graph-data.js` (a `window.GRAPH_DATA = {...}` literal meant to be
    loaded by the offline HTML viewer), this is plain JSON with no wrapper,
    intended for manual comparison in an external diff tool: every list of
    objects that carries an "id" field is sorted strictly by that id.
    """

    text = json.dumps(
        _sorted_by_id_for_diff(payload),
        indent=2,
        ensure_ascii=False,
        sort_keys=True,
    )
    write_text_file(path, text + "\n")

# The lightweight Cytoscape canvas only ever renders three kinds of visual
# elements: groups (workflow/box containers), jobs (task/file_watcher
# schedulable units), and the dependency edges between jobs. Everything else
# a Graph can hold (agents, calendars, credentials, connections, email
# templates, files, objects, scripts, triggers, variables) is excluded from
# the drawn graph, but is still emitted as a separate, non-visual `objects`
# list (see below) purely so the offline HTML search box can find it and show
# which jobs reference it - it never becomes a Cytoscape node/edge, and
# non-dependency relations (uses_calendar/runs_on/runs_command/...) are only
# used to compute that job<->object linkage, never turned into drawn edges.
# Skeleton payloads (build_skeleton_graph_data) already only ever contain
# container/unit nodes and trigger-derived dependency edges, so they need no
# equivalent object list.
CONTAINER_KINDS = {KIND_WORKFLOW, KIND_BOX}
JOB_NODE_KINDS = {KIND_TASK, KIND_FILE_WATCHER}

# Stonebranch has no dedicated "file monitor" node kind (it's just a KIND_TASK
# whose native type names it as a monitor), so the watcher/monitor visual
# flag is detected from the native type string in addition to the AutoSys
# KIND_FILE_WATCHER kind.
WATCHER_NATIVE_KIND_HINTS = ("monitor", "watch")


def _is_watcher_node(node: Node) -> bool:
    if node.kind == KIND_FILE_WATCHER:
        return True
    native = str(node.native_kind or "").lower()
    return any(hint in native for hint in WATCHER_NATIVE_KIND_HINTS)


def _display_name(node: Node) -> str:
    enterprise = node.metadata.get("enterprise_naming") if isinstance(node.metadata, dict) else None
    if isinstance(enterprise, dict) and enterprise.get("real_name"):
        return str(enterprise["real_name"])
    return node.name


def _html_path(value: str | None) -> str:
    return str(value or "").replace("\\", "/")


def _container_parent_map(container_view: dict[str, Any]) -> dict[str, str | None]:
    parent_by_group_key: dict[str, str | None] = {
        container["group_key"]: None for container in container_view["containers"]
    }
    container_keys = set(parent_by_group_key)
    for container in container_view["containers"]:
        for child in container["children"]:
            if child["group_key"] in container_keys:
                parent_by_group_key[child["group_key"]] = container["group_key"]
    return parent_by_group_key


def _task_group_map(container_view: dict[str, Any]) -> dict[str, str]:
    task_group: dict[str, str] = {}
    for container in container_view["containers"]:
        for child in container["children"]:
            if child["kind"] == KIND_TASK:
                task_group.setdefault(child["group_key"], container["group_key"])
    return task_group


def build_cytoscape_graph_data(
    graph: Graph,
    *,
    traversal: GraphTraversalCache | None = None,
) -> dict[str, Any]:
    """Build the lightweight source graph view-model used by graph.html.

    This is intentionally separate from `graph.json`: the raw graph remains the
    source of truth, while this payload is optimized for a large interactive
    offline HTML graph report showing only groups (workflow/box containers),
    jobs (task/file_watcher units), and the dependency edges between jobs.
    Every other node kind (agents, calendars, credentials, connections, email
    templates, files, objects, scripts, triggers, variables) is left out of
    the drawn graph but still included as a separate `objects` list (with a
    `used_by` back-reference to whichever jobs reference it via any
    non-dependency relation), purely so the HTML report's search box can find
    it - see the CONTAINER_KINDS/JOB_NODE_KINDS comment above for details.
    """

    traversal = traversal or GraphTraversalCache.build(graph)
    container_view = build_container_view(graph, traversal=traversal)
    parent_by_group_key = _container_parent_map(container_view)
    task_group_by_key = _task_group_map(container_view)

    groups = []
    for container in container_view["containers"]:
        groups.append(
            {
                "id": container["group_key"],
                "key": container["group_key"],
                "name": container["name"],
                "label": _display_name(graph.nodes[container["id"]])
                if container["id"] in graph.nodes
                else container["name"],
                "kind": container["kind"],
                "parent": parent_by_group_key.get(container["group_key"]),
                "child_count": container["child_count"],
                "task_count": container["task_count"],
                "nested_container_count": container["nested_container_count"],
                "source_file": _html_path(container["source_file"]),
                "graph_id": container["id"],
                "synthetic": container["synthetic"],
            }
        )

    jobs = []
    job_keys: set[str] = set()
    for node in traversal.sorted_nodes:
        if node.kind not in JOB_NODE_KINDS:
            continue
        key = canonical_node_key(node)
        job_keys.add(key)
        jobs.append(
            {
                "id": key,
                "key": key,
                "graph_id": node.id,
                "canonical_key": node.canonical_key,
                "name": node.name,
                "label": _display_name(node),
                "kind": canonical_kind(node.kind),
                "original_kind": node.kind,
                "group": task_group_by_key.get(key),
                "source_file": _html_path(node.source_file),
                "synthetic": bool(node.metadata.get("synthetic")),
                "watcher": _is_watcher_node(node),
                "meta": stable_value(
                    {
                        "attributes_hash": node.attributes_hash,
                        "native_kind": node.native_kind,
                        "semantic_command_hash": node.metadata.get("semantic_command_hash"),
                        "command_hash": node.metadata.get("command_hash"),
                    }
                ),
            }
        )

    # Everything that is neither a container (group) nor a job-like unit -
    # agents, calendars, credentials, connections, email templates, files,
    # objects, scripts, triggers, variables - is surfaced here as a
    # lightweight, non-visual "object" record so the offline HTML search box
    # can find it even though it is never drawn as a Cytoscape node/edge.
    # `used_by` below is populated from whichever relation (uses_calendar,
    # runs_on, uses_credential, watches_file, ...) actually connects a job to
    # it, so the report doesn't need a second relation allowlist to stay in
    # sync with DEPENDENCY_RELATIONS.
    objects = []
    object_keys: set[str] = set()
    for node in traversal.sorted_nodes:
        if node.kind in CONTAINER_KINDS or node.kind in JOB_NODE_KINDS:
            continue
        key = canonical_node_key(node)
        object_keys.add(key)
        objects.append(
            {
                "id": key,
                "key": key,
                "graph_id": node.id,
                "name": node.name,
                "label": _display_name(node),
                "kind": node.kind,
                "source_file": _html_path(node.source_file),
            }
        )

    edges = []
    depends_on: dict[str, list[str]] = defaultdict(list)
    object_refs: dict[str, set[str]] = defaultdict(set)
    used_by: dict[str, set[str]] = defaultdict(set)
    for edge in traversal.sorted_edges:
        components = canonical_edge_components(edge, graph)
        if components is None:
            continue
        source, relation, target = components
        source_key = canonical_node_key(source)
        target_key = canonical_node_key(target)

        if relation in DEPENDENCY_RELATIONS and source_key in job_keys and target_key in job_keys:
            payload = {
                "id": f"{source_key}|{relation}|{target_key}|{edge.id}",
                "source": source_key,
                "target": target_key,
                "relation": relation,
                "category": "dependencies",
                "native_relation": edge.native_relation,
                "confidence": edge.confidence,
                "evidence_file": _html_path(edge.evidence_file),
                "evidence_path": edge.evidence_path,
                "evidence_key": edge.evidence_key,
                "evidence_value": edge.evidence_value,
                "graph_edge_id": edge.id,
            }
            edges.append(payload)
            depends_on[source_key].append(target_key)
            continue

        if source_key in job_keys and target_key in object_keys:
            object_refs[source_key].add(target_key)
            used_by[target_key].add(source_key)
        elif source_key in object_keys and target_key in job_keys:
            object_refs[target_key].add(source_key)
            used_by[source_key].add(target_key)

    for job in jobs:
        job["depends_on"] = sorted(set(depends_on.get(job["id"], [])))
        job["object_refs"] = sorted(object_refs.get(job["id"], []))

    for obj in objects:
        obj["used_by"] = sorted(used_by.get(obj["id"], []))

    groups = sorted(groups, key=lambda item: (item["id"], item["kind"], item["name"]))
    jobs = sorted(jobs, key=lambda item: (item["group"] or "", item["id"], item["kind"], item["name"]))
    objects = sorted(objects, key=lambda item: (item["kind"], item["id"], item["name"]))
    edges = sorted(
        edges,
        key=lambda item: (
            item["category"],
            item["source"],
            item["relation"],
            item["target"],
            item["id"],
        ),
    )

    category_counts: dict[str, int] = defaultdict(int)
    for edge in edges:
        category_counts[edge["category"]] += 1

    return {
        "schema_version": HTML_GRAPH_SCHEMA_VERSION,
        "metadata": {
            "source_system": graph.source_system,
            "env": graph.env,
            "nodes": len(graph.nodes),
            "edges": len(graph.edges),
            "groups": len(groups),
            "jobs": len(jobs),
            "objects": len(objects),
            "warnings": len(graph.warnings),
            "relation_categories": dict(sorted(category_counts.items())),
        },
        "groups": groups,
        "jobs": jobs,
        "objects": objects,
        "edges": edges,
        "warnings": sorted(str(warning) for warning in graph.warnings),
    }


def export_graph_data_js(
    graph: Graph,
    path: Path,
    *,
    traversal: GraphTraversalCache | None = None,
    json_path: Path | None = None,
) -> None:
    payload = build_cytoscape_graph_data(graph, traversal=traversal)
    text = (
        "/* offline HTML graph data. Generated by stonebranch-dependency-tool; do not hand-edit. */\n"
        "window.GRAPH_DATA = "
        + _dump_graph_payload(payload)
        + ";\n"
    )
    write_text_file(path, text)
    export_graph_data_json(payload, json_path or path.with_suffix(".json"))


def export_cytoscape_runtime(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    asset_root = resources.files(__package__).joinpath("assets")
    target = output_dir / CYTOSCAPE_RUNTIME_FILE
    target.write_bytes(asset_root.joinpath(CYTOSCAPE_RUNTIME_FILE).read_bytes())


def export_graph_html(
    path: Path,
    *,
    data_file: str = "graph-data.js",
    title: str = "Dependency graph",
) -> None:
    export_cytoscape_runtime(path.parent)
    html = (
        CYTOSCAPE_HTML.replace("__GRAPH_DATA_FILE__", data_file)
        .replace("__GRAPH_TITLE__", title)
        .replace("__CYTOSCAPE_RUNTIME_FILE__", CYTOSCAPE_RUNTIME_FILE)
    )
    write_text_file(path, html)


def export_cytoscape_html_report(
    graph: Graph,
    output_dir: Path,
    *,
    traversal: GraphTraversalCache | None = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    traversal = traversal or GraphTraversalCache.build(graph)
    export_graph_data_js(
        graph,
        output_dir / "graph-data.js",
        traversal=traversal,
        json_path=output_dir / "json" / "graph-data.json",
    )
    export_graph_html(output_dir / "graph.html")


def build_skeleton_graph_data(skeleton: Skeleton) -> dict[str, Any]:
    """Build the Cytoscape view-model for canonical skeleton trigger semantics."""

    depends_on = depends_on_view(skeleton)
    erased_counts = _plumbing_erased_counts(skeleton)
    include_pure_success_triggers = (
        len(skeleton.nodes) <= SKELETON_TRIGGER_INLINE_NODE_THRESHOLD
    )
    nodes = [
        _skeleton_node_payload(
            node,
            depends_on,
            erased_counts,
            include_pure_success_triggers=include_pure_success_triggers,
        )
        for node in _sorted_skeleton_nodes(skeleton)
    ]
    nodes_by_id = {str(node["id"]): node for node in nodes}
    edges: list[dict[str, Any]] = []
    seen_edge_ids: set[str] = set()

    for node in _sorted_skeleton_nodes(skeleton):
        if node.trigger is None:
            continue
        for atom, or_group in _atoms_with_or_groups(node.trigger):
            if atom.node_ref not in nodes_by_id:
                stub = _external_stub_payload(atom.node_ref)
                nodes_by_id[atom.node_ref] = stub
                nodes.append(stub)
            edges.append(_skeleton_edge_payload(atom, node.id, or_group, seen_edge_ids))

    nodes = sorted(nodes, key=lambda item: (bool(item.get("external")), str(item["id"])))
    groups, jobs = _skeleton_groups_and_jobs(nodes)
    category_counts = _category_counts(edges)

    return {
        "schema_version": HTML_GRAPH_SCHEMA_VERSION,
        "metadata": {
            "report_type": "skeleton",
            "report_title": "Skeleton graph",
            "nodes": len(nodes),
            "skeleton_nodes": len(skeleton.nodes),
            "external_stubs": len([node for node in nodes if node.get("external")]),
            "edges": len(edges),
            "groups": len(groups),
            "jobs": len(jobs),
            "warnings": len(skeleton.warnings),
            "relation_categories": dict(sorted(category_counts.items())),
            "trigger_inline_node_threshold": SKELETON_TRIGGER_INLINE_NODE_THRESHOLD,
            "pure_success_triggers_elided": not include_pure_success_triggers,
        },
        "nodes": nodes,
        "groups": groups,
        "jobs": jobs,
        "edges": sorted(
            edges,
            key=lambda item: (item["source"], item["predicate"], item["target"], item["id"]),
        ),
        "warnings": sorted(str(warning) for warning in skeleton.warnings),
    }


def export_skeleton_graph_data_js(skeleton: Skeleton, path: Path) -> None:
    payload = build_skeleton_graph_data(skeleton)
    text = _graph_data_js(payload, "offline skeleton graph data")
    write_text_file(path, text)
    export_graph_data_json(payload, path.with_suffix(".json"))


def export_skeleton_html_report(skeleton: Skeleton, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    export_skeleton_graph_data_js(skeleton, output_dir / "skeleton-graph-data.js")
    export_graph_html(
        output_dir / "skeleton-graph.html",
        data_file="skeleton-graph-data.js",
        title="Skeleton graph",
    )


def build_skeleton_comparison_graph_data(
    diff_json_path_or_dict: str | Path | dict[str, Any] | Any,
    sb_skeleton: Skeleton,
    jil_skeleton: Skeleton,
) -> dict[str, Any]:
    """Build the union skeleton diff graph view-model."""

    diff = _diff_payload(diff_json_path_or_dict)
    statuses = _skeleton_diff_statuses(diff)
    sb_payload = build_skeleton_graph_data(sb_skeleton)
    jil_payload = build_skeleton_graph_data(jil_skeleton)
    sb_nodes = {str(node["id"]): node for node in sb_payload["nodes"]}
    jil_nodes = {str(node["id"]): node for node in jil_payload["nodes"]}

    nodes: list[dict[str, Any]] = []
    for node_id in sorted(set(sb_nodes) | set(jil_nodes)):
        side = _node_side(node_id, sb_nodes, jil_nodes)
        base = dict(sb_nodes.get(node_id) or jil_nodes[node_id])
        status_by_level = statuses.get(node_id, _matched_statuses())
        base["status_by_level"] = status_by_level
        base["status"] = status_by_level["logic"]
        base["side"] = side
        base["sb_trigger"] = sb_nodes.get(node_id, {}).get("trigger")
        base["jil_trigger"] = jil_nodes.get(node_id, {}).get("trigger")
        base["diff_reasons"] = _diff_reasons(diff, node_id)
        nodes.append(base)

    node_ids = {str(node["id"]) for node in nodes}
    edges = _comparison_edges(sb_payload, jil_payload, statuses, node_ids)
    total_edges_before_cap = len(edges)
    edges_capped = total_edges_before_cap > SKELETON_DIFF_HTML_MAX_EDGES
    if edges_capped:
        edges = edges[:SKELETON_DIFF_HTML_MAX_EDGES]
    groups, jobs = _skeleton_groups_and_jobs(nodes)
    status_counts = _status_counts(nodes, level="logic")
    statuses_by_level = {
        level: _status_counts(nodes, level=level) for level in ("topology", "logic", "strict")
    }

    return {
        "schema_version": HTML_GRAPH_SCHEMA_VERSION,
        "metadata": {
            "report_type": "skeleton_comparison",
            "report_title": "Skeleton comparison graph",
            "strictness_level": "logic",
            "strictness_levels": ["topology", "logic", "strict"],
            "nodes": len(nodes),
            "edges": len(edges),
            "groups": len(groups),
            "jobs": len(jobs),
            "relation_categories": dict(sorted(_category_counts(edges).items())),
            "total_edges_before_cap": total_edges_before_cap,
            "edge_cap": SKELETON_DIFF_HTML_MAX_EDGES,
            "edges_capped": edges_capped,
            "statuses": dict(sorted(status_counts.items())),
            "statuses_by_level": {
                level: dict(sorted(counts.items())) for level, counts in statuses_by_level.items()
            },
        },
        "nodes": nodes,
        "groups": groups,
        "jobs": jobs,
        "edges": edges,
        "warnings": sorted({*sb_skeleton.warnings, *jil_skeleton.warnings}),
    }


def export_skeleton_comparison_graph_data_js(
    diff_json_path_or_dict: str | Path | dict[str, Any] | Any,
    sb_skeleton: Skeleton,
    jil_skeleton: Skeleton,
    path: Path,
) -> None:
    payload = build_skeleton_comparison_graph_data(
        diff_json_path_or_dict,
        sb_skeleton,
        jil_skeleton,
    )
    text = _graph_data_js(payload, "offline skeleton comparison graph data")
    write_text_file(path, text)
    export_graph_data_json(payload, path.with_suffix(".json"))


def export_skeleton_comparison_html(
    diff_json_path_or_dict: str | Path | dict[str, Any] | Any,
    sb_skeleton: Skeleton,
    jil_skeleton: Skeleton,
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    export_skeleton_comparison_graph_data_js(
        diff_json_path_or_dict,
        sb_skeleton,
        jil_skeleton,
        output_dir / "skeleton-compare-graph-data.js",
    )
    export_graph_html(
        output_dir / "skeleton-compare-graph.html",
        data_file="skeleton-compare-graph-data.js",
        title="Skeleton comparison graph",
    )


def _graph_data_js(payload: dict[str, Any], description: str) -> str:
    return (
        f"/* {description}. Generated by stonebranch-dependency-tool; do not hand-edit. */\n"
        "window.GRAPH_DATA = "
        + _dump_graph_payload(payload)
        + ";\n"
    )


def _sorted_skeleton_nodes(skeleton: Skeleton) -> list[SkeletonNode]:
    return [skeleton.nodes[node_id] for node_id in sorted(skeleton.nodes)]


def _skeleton_node_payload(
    node: SkeletonNode,
    depends_on: dict[str, list[str]],
    erased_counts: dict[str, int],
    *,
    include_pure_success_triggers: bool,
) -> dict[str, Any]:
    meta = _skeleton_meta(node)
    trigger = _skeleton_trigger_payload(
        node,
        depends_on,
        include_pure_success_triggers=include_pure_success_triggers,
    )
    payload: dict[str, Any] = {
        "id": node.id,
        "key": node.id,
        "label": _leaf_label(node.id),
        "name": _leaf_label(node.id),
        "kind": node.kind,
        "parent": node.parent,
        "group": node.parent if node.kind == KIND_UNIT else None,
        "trigger": trigger,
        "depends_on": depends_on.get(node.id, []),
        "meta": meta,
        "source_file": _html_path(str(meta.get("src") or "")),
        "native": meta.get("native"),
        "watcher": _skeleton_is_watcher(node, meta),
    }
    if erased_counts.get(node.id):
        payload["plumbing_erased_count"] = erased_counts[node.id]
    return payload


def _skeleton_is_watcher(node: SkeletonNode, meta: dict[str, Any]) -> bool:
    """True for AutoSys file-watcher jobs and Stonebranch file-monitor tasks.

    AutoSys marks this explicitly via job_type (f/fw/file_watcher); Stonebranch
    has no dedicated kind for it, so it only shows up as a "monitor"/"watch"
    hint in the native task type string. Same detection as _is_watcher_node,
    kept separate because skeleton nodes carry meta.type instead of a Node.
    """

    if node.kind != KIND_UNIT:
        return False
    token = str(meta.get("type") or "").strip().lower()
    if token in {"f", "fw", "file_watcher", "filewatcher"}:
        return True
    return any(hint in token for hint in WATCHER_NATIVE_KIND_HINTS)


def _skeleton_trigger_payload(
    node: SkeletonNode,
    depends_on: dict[str, list[str]],
    *,
    include_pure_success_triggers: bool,
) -> str | None:
    if node.trigger is None:
        return None
    if not include_pure_success_triggers and node.id in depends_on:
        return None
    return trigger_expr.render(node.trigger)


def _external_stub_payload(node_id: str) -> dict[str, Any]:
    return {
        "id": node_id,
        "key": node_id,
        "label": _leaf_label(node_id),
        "name": _leaf_label(node_id),
        "kind": KIND_UNIT,
        "parent": None,
        "group": None,
        "trigger": None,
        "depends_on": [],
        "external": True,
        "meta": {"src": None, "native": node_id},
        "source_file": "",
        "native": node_id,
        "watcher": False,
    }


def _skeleton_meta(node: SkeletonNode) -> dict[str, Any]:
    src = node.meta.get("src") or node.meta.get("source_file")
    native = node.meta.get("native") or node.meta.get("name") or node.meta.get("type")
    meta = {"src": src, "native": native}
    for key, value in stable_value(node.meta).items():
        meta.setdefault(str(key), value)
    return meta


def _leaf_label(node_id: str) -> str:
    return node_id.rsplit("/", 1)[-1]


def _plumbing_erased_counts(skeleton: Skeleton) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for erasure in skeleton.erasures:
        for node_id in erasure.get("replaced_in", []):
            counts[str(node_id)] += 1
    return counts


def _atoms_with_or_groups(expr: trigger_expr.Expr) -> list[tuple[trigger_expr.Atom, int | None]]:
    result: list[tuple[trigger_expr.Atom, int | None]] = []
    next_group = 0

    def visit(current: trigger_expr.Expr, current_group: int | None) -> None:
        nonlocal next_group
        if isinstance(current, trigger_expr.Atom):
            result.append((current, current_group))
            return
        if isinstance(current, trigger_expr.Not):
            visit(current.child, current_group)
            return
        if isinstance(current, trigger_expr.Or):
            group = current_group
            if group is None:
                group = next_group
                next_group += 1
            for child in current.children:
                visit(child, group)
            return
        for child in current.children:
            visit(child, current_group)

    visit(trigger_expr.canonicalize(expr), None)
    return result


def _skeleton_edge_payload(
    atom: trigger_expr.Atom,
    target_id: str,
    or_group: int | None,
    seen_edge_ids: set[str],
) -> dict[str, Any]:
    base_id = f"{atom.node_ref}|{atom.predicate}|{target_id}"
    edge_id = base_id
    if edge_id in seen_edge_ids:
        suffix = atom.qualifier or (str(or_group) if or_group is not None else "duplicate")
        edge_id = f"{base_id}|{suffix}"
    counter = 2
    while edge_id in seen_edge_ids:
        edge_id = f"{base_id}|{counter}"
        counter += 1
    seen_edge_ids.add(edge_id)
    label = atom.predicate if not atom.qualifier else f"{atom.predicate}[{atom.qualifier}]"
    return {
        "id": edge_id,
        "source": atom.node_ref,
        "target": target_id,
        "predicate": atom.predicate,
        "qualifier": atom.qualifier,
        "or_group": or_group,
        "label": label,
        "relation": atom.predicate,
        "category": "dependencies",
    }


def _skeleton_groups_and_jobs(
    nodes: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    groups = [dict(node, type="group") for node in nodes if node.get("kind") == KIND_CONTAINER]
    jobs = [dict(node, type="job") for node in nodes if node.get("kind") != KIND_CONTAINER]
    return (
        sorted(groups, key=lambda item: (str(item.get("parent") or ""), str(item["id"]))),
        sorted(jobs, key=lambda item: (str(item.get("group") or ""), str(item["id"]))),
    )


def _category_counts(edges: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for edge in edges:
        counts[str(edge.get("category") or "other")] += 1
    return counts


def _diff_payload(diff_json_path_or_dict: str | Path | dict[str, Any] | Any) -> dict[str, Any]:
    if isinstance(diff_json_path_or_dict, dict):
        return diff_json_path_or_dict
    if hasattr(diff_json_path_or_dict, "to_dict"):
        return diff_json_path_or_dict.to_dict()
    path = Path(diff_json_path_or_dict)
    return json.loads(path.read_text(encoding="utf-8"))


def _skeleton_diff_statuses(diff: dict[str, Any]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for entry in diff.get("nodes", []):
        node_id = str(entry.get("id") or "")
        if not node_id:
            continue
        raw = entry.get("status_by_level") or {}
        result[node_id] = {
            level: _display_skeleton_status(str(raw.get(level) or "matched"))
            for level in ("topology", "logic", "strict")
        }
    return result


def _display_skeleton_status(status: str) -> str:
    return {
        "only_in_stonebranch": "only-sb",
        "only_in_jil": "only-jil",
    }.get(status, status)


def _matched_statuses() -> dict[str, str]:
    return {"topology": "matched", "logic": "matched", "strict": "matched"}


def _node_side(
    node_id: str,
    sb_nodes: dict[str, dict[str, Any]],
    jil_nodes: dict[str, dict[str, Any]],
) -> str:
    if node_id in sb_nodes and node_id in jil_nodes:
        return "both"
    if node_id in sb_nodes:
        return "stonebranch"
    return "jil"


def _diff_reasons(diff: dict[str, Any], node_id: str) -> list[str]:
    for entry in diff.get("nodes", []):
        if entry.get("id") == node_id:
            return list(entry.get("reasons") or [])
    return []


def _comparison_edges(
    sb_payload: dict[str, Any],
    jil_payload: dict[str, Any],
    statuses: dict[str, dict[str, str]],
    node_ids: set[str],
) -> list[dict[str, Any]]:
    edges: dict[str, dict[str, Any]] = {}

    def add(edge: dict[str, Any], side: str) -> None:
        if edge["source"] not in node_ids or edge["target"] not in node_ids:
            return
        target_status = statuses.get(edge["target"], _matched_statuses())["logic"]
        payload = dict(edge)
        payload["side"] = side
        payload["status"] = target_status
        payload["id"] = f"{side}|{edge['id']}"
        edges[payload["id"]] = payload

    for edge in sb_payload["edges"]:
        if statuses.get(edge["target"], _matched_statuses())["logic"] != "only-jil":
            add(edge, "stonebranch")

    # Changed nodes intentionally keep Stonebranch edges; the details panel shows
    # both trigger strings, which is enough for prompt-08 without JS diff overlays.
    for edge in jil_payload["edges"]:
        if statuses.get(edge["target"], _matched_statuses())["logic"] == "only-jil":
            add(edge, "jil")

    return sorted(
        edges.values(),
        key=lambda item: (item["side"], item["source"], item["predicate"], item["target"]),
    )


def _status_counts(nodes: list[dict[str, Any]], *, level: str) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for node in nodes:
        status_by_level = node.get("status_by_level") or _matched_statuses()
        counts[str(status_by_level.get(level) or "matched")] += 1
    return counts


def comparison_node_statuses(comparison: Any) -> dict[str, str]:
    statuses: dict[str, str] = {}
    for pair in comparison.nodes.get("matched", []):
        key = str(pair.get("key") or "")
        if key:
            statuses[key] = "matched"
    for item in comparison.nodes.get("missing_in_stonebranch", []):
        key = str(item.get("comparison_key") or item.get("canonical_key") or "")
        if key:
            statuses[key] = "missing_in_stonebranch"
    for item in comparison.nodes.get("missing_in_jil", []):
        key = str(item.get("comparison_key") or item.get("canonical_key") or "")
        if key:
            statuses[key] = "missing_in_jil"
    for item in comparison.attributes.get("command_differences", []):
        key = str(item.get("key") or "")
        status = str(item.get("status") or "")
        if key and status:
            statuses[key] = status
    for item in comparison.attributes.get("condition_differences", []):
        key = str(item.get("key") or "")
        if key and statuses.get(key) == "matched":
            statuses[key] = "condition_mismatch"
    for section in ("stonebranch_key_collisions", "jil_key_collisions"):
        for item in comparison.diagnostics.get(section, []):
            key = str(item.get("key") or "")
            if key and key not in statuses:
                statuses[key] = "normalized_key_collision"
    return statuses


def comparison_edge_statuses(comparison: Any) -> dict[tuple[str, str, str], str]:
    statuses: dict[tuple[str, str, str], str] = {}
    for pair in comparison.edges.get("matched", []):
        key = edge_key_tuple(pair.get("key"))
        if key:
            statuses[key] = "matched"
    for item in comparison.edges.get("missing_in_stonebranch", []):
        key = edge_payload_tuple(item)
        if key:
            statuses[key] = (
                "missing_critical_in_stonebranch"
                if key[1] in CRITICAL_HTML_RELATIONS
                else "missing_in_stonebranch"
            )
    for item in comparison.edges.get("missing_in_jil", []):
        key = edge_payload_tuple(item)
        if key:
            statuses[key] = (
                "missing_critical_in_jil"
                if key[1] in CRITICAL_HTML_RELATIONS
                else "missing_in_jil"
            )
    return statuses


def edge_key_tuple(value: Any) -> tuple[str, str, str] | None:
    if not value or not isinstance(value, str) or "->" not in value:
        return None
    parts = value.split("->", 2)
    if len(parts) != 3:
        return None
    return parts[0], parts[1], parts[2]


def edge_payload_tuple(item: dict[str, Any]) -> tuple[str, str, str] | None:
    source = str(item.get("source_key") or "")
    relation = str(item.get("relation_key") or item.get("relation") or "")
    target = str(item.get("target_key") or "")
    if source and relation and target:
        return source, relation, target
    return edge_key_tuple(item.get("comparison_key"))


def merge_compare_items(
    left: list[dict[str, Any]],
    right: list[dict[str, Any]],
    *,
    node_statuses: dict[str, str],
    edge_statuses: dict[tuple[str, str, str], str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    groups: dict[str, dict[str, Any]] = {}
    jobs: dict[str, dict[str, Any]] = {}
    edges: dict[tuple[str, str, str], dict[str, Any]] = {}

    def merge_node(target: dict[str, dict[str, Any]], item: dict[str, Any], side: str) -> None:
        key = str(item.get("id") or "")
        if not key:
            return
        existing = target.setdefault(key, dict(item))
        existing.setdefault("sides", [])
        if side not in existing["sides"]:
            existing["sides"].append(side)
        existing["status"] = node_statuses.get(key) or existing.get("status") or (
            "matched" if len(existing["sides"]) > 1 else f"{side}_only"
        )
        existing["side"] = "+".join(sorted(existing["sides"]))

    for side, payload in (("stonebranch", left), ("jil", right)):
        for item in payload[0].get("groups", []):
            merge_node(groups, item, side)
        for item in payload[0].get("jobs", []):
            merge_node(jobs, item, side)
        for item in payload[0].get("edges", []):
            key = (str(item.get("source")), str(item.get("relation")), str(item.get("target")))
            existing = edges.setdefault(key, dict(item))
            existing.setdefault("sides", [])
            if side not in existing["sides"]:
                existing["sides"].append(side)
            existing["status"] = edge_statuses.get(key) or existing.get("status") or (
                "matched" if len(existing["sides"]) > 1 else f"{side}_only"
            )
            existing["side"] = "+".join(sorted(existing["sides"]))
            existing["id"] = f"{key[0]}|{key[1]}|{key[2]}|{existing['status']}"

    return (
        sorted(groups.values(), key=lambda item: (item.get("id", ""), item.get("kind", ""), item.get("name", ""))),
        sorted(
            jobs.values(),
            key=lambda item: (item.get("group") or "", item.get("id", ""), item.get("kind", ""), item.get("name", "")),
        ),
        sorted(
            edges.values(),
            key=lambda item: (
                item.get("status", ""),
                item.get("category", ""),
                item.get("source", ""),
                item.get("relation", ""),
                item.get("target", ""),
            ),
        ),
    )


def build_comparison_graph_data(comparison: Any, stonebranch: Graph, jil: Graph) -> dict[str, Any]:
    sb_payload = build_cytoscape_graph_data(stonebranch)
    jil_payload = build_cytoscape_graph_data(jil)
    node_statuses = comparison_node_statuses(comparison)
    edge_statuses = comparison_edge_statuses(comparison)
    groups, jobs, edges = merge_compare_items(
        [sb_payload],
        [jil_payload],
        node_statuses=node_statuses,
        edge_statuses=edge_statuses,
    )

    status_counts: dict[str, int] = defaultdict(int)
    category_counts: dict[str, int] = defaultdict(int)
    for item in [*groups, *jobs, *edges]:
        status_counts[str(item.get("status") or "unknown")] += 1
    for edge in edges:
        category_counts[str(edge.get("category") or "other")] += 1

    return {
        "schema_version": HTML_GRAPH_SCHEMA_VERSION,
        "metadata": {
            "report_type": "comparison",
            "report_title": "Comparison graph",
            "source_system": "stonebranch_vs_jil",
            "env": stonebranch.env or jil.env,
            "stonebranch_nodes": len(stonebranch.nodes),
            "jil_nodes": len(jil.nodes),
            "matched_nodes": comparison.summary.get("matched_nodes", 0),
            "matched_edges": comparison.summary.get("matched_edges", 0),
            "missing_in_stonebranch": comparison.summary.get("missing_in_stonebranch", 0),
            "missing_in_jil": comparison.summary.get("missing_in_jil", 0),
            "missing_edges_in_stonebranch": comparison.summary.get("missing_edges_in_stonebranch", 0),
            "missing_edges_in_jil": comparison.summary.get("missing_edges_in_jil", 0),
            "command_syntax_diff_only": comparison.summary.get("command_syntax_diff_only", 0),
            "command_semantic_mismatches": comparison.summary.get("command_semantic_mismatches", 0),
            "readiness_score": comparison.summary.get("migration_readiness_score", 0),
            "readiness_grade": comparison.summary.get("readiness_grade", "unknown"),
            "groups": len(groups),
            "jobs": len(jobs),
            "edges": len(edges),
            "relation_categories": dict(sorted(category_counts.items())),
            "statuses": dict(sorted(status_counts.items())),
        },
        "groups": groups,
        "jobs": jobs,
        "edges": edges,
        "warnings": sorted(str(warning) for warning in [*stonebranch.warnings, *jil.warnings]),
    }


def export_comparison_graph_data_js(
    comparison: Any,
    stonebranch: Graph,
    jil: Graph,
    path: Path,
    *,
    json_path: Path | None = None,
) -> None:
    payload = build_comparison_graph_data(comparison, stonebranch, jil)
    text = (
        "/* offline comparison graph data. Generated by stonebranch-dependency-tool; do not hand-edit. */\n"
        "window.GRAPH_DATA = "
        + _dump_graph_payload(payload)
        + ";\n"
    )
    write_text_file(path, text)
    export_graph_data_json(payload, json_path or path.with_suffix(".json"))


def export_comparison_html_report(comparison: Any, stonebranch: Graph, jil: Graph, output_dir: Path) -> None:
    compare_dir = output_dir / "compare"
    compare_dir.mkdir(parents=True, exist_ok=True)
    export_comparison_graph_data_js(
        comparison,
        stonebranch,
        jil,
        compare_dir / "compare-graph-data.js",
        json_path=compare_dir / "json" / "compare-graph-data.json",
    )
    export_graph_html(compare_dir / "compare-graph.html", data_file="compare-graph-data.js", title="Comparison graph")


CRITICAL_HTML_RELATIONS = {
    "contains",
    "depends_on",
    "depends_on_success",
    "depends_on_done",
    "depends_on_failure",
    "depends_on_terminated",
    "depends_on_notrunning",
    "runs_command",
    "runs_script",
}


CYTOSCAPE_HTML = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>__GRAPH_TITLE__</title>
<style>
  :root {
    --bg:#f5f7fa; --panel:#ffffff; --panel-2:#eef1f5; --border:#d8dee6;
    --text:#1f2730; --muted:#687585; --accent:#1c7ed6;
    --ok:#2f9e44; --danger:#e03131; --warn:#f08c00; --purple:#7048e8; --watcher:#0ca678;
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; margin: 0; }
  body {
    background: var(--bg); color: var(--text);
    font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    display: flex; flex-direction: column; overflow: hidden;
  }
  header {
    display: flex; align-items: center; gap: 10px; padding: 10px 14px;
    background: var(--panel); border-bottom: 1px solid var(--border); flex-wrap: wrap; z-index: 5;
  }
  header h1 { font-size: 15px; margin: 0 8px 0 0; font-weight: 600; }
  .crumb { font-size: 12px; color: var(--muted); } .crumb b { color: var(--text); }
  .search-wrap { position: relative; }
  #search {
    background: #fff; border: 1px solid var(--border); color: var(--text);
    border-radius: 8px; padding: 7px 30px 7px 12px; width: 210px; outline: none; font-size: 13px;
  }
  #search:focus { border-color: var(--accent); box-shadow: 0 0 0 3px rgba(28,126,214,.12); }
  #searchCount { position: absolute; right: 9px; top: 50%; transform: translateY(-50%); font-size: 11px; color: var(--muted); }
  select, button {
    background: #fff; color: var(--text); border: 1px solid var(--border);
    border-radius: 8px; padding: 7px 10px; cursor: pointer; font-size: 13px; white-space: nowrap;
    transition: background .12s, border-color .12s;
  }
  button:hover, button.active { background: var(--panel-2); border-color: #c2cad3; }
  button.active { border-color: var(--accent); color: var(--accent); font-weight: 600; }
  button:active { transform: translateY(1px); }
  .sep { width: 1px; height: 24px; background: var(--border); margin: 0 4px; }
  .spacer { flex: 1; }
  .stats { color: var(--muted); font-size: 12px; display: flex; gap: 14px; flex-wrap: wrap; }
  .stats b { color: var(--text); font-weight: 600; }
  .stats .good { color: var(--ok); } .stats .bad { color: var(--danger); }

  .body { flex: 1; display: flex; min-height: 0; }
  #graphWrap { flex: 1; min-width: 0; height: 100%; position: relative; background: var(--bg); }
  #cy { width: 100%; height: 100%; display: block; }
  .runtime-error { display:none; position:absolute; inset:18px; padding:16px; border:1px solid #ffc9c9; border-radius:8px; background:#fff5f5; color:#c92a2a; z-index:2; }

  #panel {
    width: 340px; flex: none; background: var(--panel); border-left: 1px solid var(--border);
    display: flex; flex-direction: column; overflow: hidden;
  }
  #panel .p-head { padding: 14px 16px 12px; border-bottom: 1px solid var(--border); }
  #panel .p-title { font-size: 16px; font-weight: 600; word-break: break-word; }
  #panel .p-sub { font-size: 12px; color: var(--muted); margin-top: 3px; word-break: break-word; }
  #panel .p-body { padding: 12px 16px; overflow-y: auto; flex: 1; }
  .kv { display: flex; justify-content: space-between; gap: 10px; font-size: 12.5px; padding: 5px 0; border-bottom: 1px solid #eef1f5; }
  .kv .k { color: var(--muted); } .kv .v { color: var(--text); text-align: right; word-break: break-word; }
  .sec-title { font-size: 11px; text-transform: uppercase; letter-spacing: .6px; color: var(--muted); margin: 16px 0 6px; display: flex; align-items: center; gap: 6px; }
  .sec-title .arrow { font-weight: 700; } .sec-title.up .arrow { color: var(--warn); } .sec-title.down .arrow { color: var(--ok); }
  .count-pill { background: var(--panel-2); border: 1px solid var(--border); border-radius: 10px; padding: 0 7px; font-size: 11px; color: var(--text); }
  .chain-note { font-size: 11.5px; color: var(--muted); margin: 2px 0 0; }
  .dep-item { display: flex; align-items: center; gap: 8px; padding: 6px 8px; border-radius: 7px; cursor: pointer; font-size: 12.5px; transition: background .1s; }
  .dep-item:hover { background: var(--panel-2); }
  .dot { width: 9px; height: 9px; border-radius: 50%; flex: none; }
  .dot.watcher { border-radius: 2px; transform: rotate(45deg); }
  .box-dot { width: 11px; height: 11px; border-radius: 3px; flex: none; }
  .dep-item .nm { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .empty { color: var(--muted); font-size: 12px; padding: 4px 0; }
  .placeholder { color: var(--muted); font-size: 13px; line-height: 1.7; }
  .placeholder kbd { background: var(--panel-2); border: 1px solid var(--border); border-radius: 4px; padding: 0 5px; font-size: 11px; }
  .legend-row { display: flex; align-items: center; gap: 8px; margin: 4px 0; font-size: 12.5px; cursor: pointer; padding: 3px 6px; border-radius: 6px; }
  .legend-row:hover { background: var(--panel-2); }
  .swatch { width: 12px; height: 12px; border-radius: 3px; flex: none; }
  .swatch.watcher { border-radius: 2px; transform: rotate(45deg); width:10px; height:10px; }
  .edge-card { border:1px solid #eef1f5; border-radius:8px; padding:8px; margin:7px 0; background:#fbfcfe; }
  .edge-main { display:flex; gap:7px; align-items:center; cursor:pointer; font-size:12.5px; }
  .edge-main b { margin-left:auto; word-break:break-word; text-align:right; }
  .edge-meta { margin-top:4px; color:var(--muted); font-size:11px; word-break:break-word; }
  .copy-row { display:flex; gap:6px; align-items:center; flex-wrap:wrap; margin:5px 0; }
  .copy-btn { padding:4px 7px; font-size:11px; border-radius:7px; }
  code.copyable { background:#f1f3f5; border:1px solid #e9ecef; border-radius:6px; padding:3px 5px; font-size:11.5px; word-break:break-all; }
  .linkish { color:var(--accent); cursor:pointer; text-decoration:underline; text-underline-offset:2px; }
  @media (max-width: 860px) {
    body { overflow:auto; }
    .body { flex-direction: column; height: auto; min-height: calc(100vh - 60px); }
    #graphWrap { height: 58vh; min-height: 420px; }
    #panel { width: 100%; min-height: 360px; border-left:0; border-top:1px solid var(--border); }
  }
</style>
<script src="__CYTOSCAPE_RUNTIME_FILE__"></script>
<script src="__GRAPH_DATA_FILE__"></script>
</head>
<body>
  <header>
    <h1>__GRAPH_TITLE__</h1>
    <span class="crumb" id="crumb">all boxes collapsed</span>
    <div class="sep"></div>
    <div class="search-wrap">
      <input id="search" type="text" placeholder="Search task/job/workflow/object... (/)" autocomplete="off" />
      <span id="searchCount"></span>
    </div>
    <select id="statusFilter" title="Status filter">
      <option value="all">All statuses</option>
      <option value="problems">Problems</option>
      <option value="critical">Critical</option>
      <option value="missing">Missing</option>
      <option value="commands">Command diffs</option>
      <option value="syntax">Syntax only</option>
      <option value="semantic">Semantic mismatch</option>
      <option value="collisions">Collisions</option>
    </select>
    <select id="levelFilter" title="Skeleton diff level">
      <option value="topology">Topology</option>
      <option value="logic" selected>Logic</option>
      <option value="strict">Strict</option>
    </select>
    <button id="showProblems">Problems</button>
    <button id="showCritical">Critical</button>
    <button id="showMissing">Missing</button>
    <button id="showAll">Show all</button>
    <div class="sep"></div>
    <button id="expandAll">Expand all</button>
    <button id="collapseAll">Collapse all</button>
    <button id="fit">Fit</button>
    <button id="zoomOut" title="Zoom out">&minus;</button>
    <button id="zoomIn" title="Zoom in">&plus;</button>
    <button id="dir">TB</button>
    <div class="spacer"></div>
    <div class="stats">
      <span><b id="nJobs">0</b> jobs</span>
      <span><b id="nBoxes">0</b> boxes</span>
      <span><b id="nEdges">0</b> deps</span>
      <span><b id="nObjects">0</b> objects</span>
      <span id="health"></span>
    </div>
  </header>

  <div class="body">
    <main id="graphWrap">
      <div id="cy"></div>
      <div id="runtimeError" class="runtime-error"></div>
    </main>
    <aside id="panel">
      <div class="p-head">
        <div class="p-title" id="pTitle">Overview</div>
        <div class="p-sub" id="pSub">Click a box to expand it</div>
      </div>
      <div class="p-body" id="pBody"></div>
    </aside>
  </div>
<script>
(function(){
'use strict';
const DATA = window.GRAPH_DATA || {metadata:{}, groups:[], jobs:[], edges:[], warnings:[]};
const $ = id => document.getElementById(id);
const hasComparisonStatuses = !!(DATA.metadata && DATA.metadata.statuses && Object.keys(DATA.metadata.statuses).length);
const isSkeletonReport = ['skeleton','skeleton_comparison'].includes(DATA.metadata?.report_type);
const hasStrictnessLevels = !!(DATA.metadata?.strictness_levels || []).length;
const quickFilters = ['showProblems', 'showCritical', 'showMissing', 'showAll'];
if(!hasComparisonStatuses){
  $('statusFilter').style.display = 'none';
  for(const id of quickFilters) $(id).style.display = 'none';
}
if(!hasStrictnessLevels) $('levelFilter').style.display = 'none';
if(typeof window.cytoscape !== 'function'){
  $('runtimeError').style.display = 'block';
  $('runtimeError').textContent = 'Cytoscape.js runtime was not loaded. Keep cytoscape.min.js next to this HTML file.';
  return;
}

/* ---------------------------------------------------------------------
   Data indices
   ------------------------------------------------------------------- */
let activeStrictnessLevel = DATA.metadata?.strictness_level || 'logic';
function applyStrictnessStatuses(level){
  activeStrictnessLevel = level;
  for(const item of [...(DATA.groups || []), ...(DATA.jobs || []), ...(DATA.nodes || [])]){
    if(item.status_by_level) item.status = item.status_by_level[level] || item.status;
  }
  if(DATA.metadata?.statuses_by_level?.[level]) DATA.metadata.statuses = DATA.metadata.statuses_by_level[level];
}
applyStrictnessStatuses(activeStrictnessLevel);
if(hasStrictnessLevels) $('levelFilter').value = activeStrictnessLevel;

const groupById = Object.fromEntries((DATA.groups || []).map(g => [g.id, g]));
const jobById = Object.fromEntries((DATA.jobs || []).map(j => [j.id, j]));
// Objects (agents, calendars, credentials, connections, email templates,
// files, objects, scripts, triggers, variables) never appear on the
// Cytoscape canvas - they only exist so search/the side panel can surface
// them and show which jobs reference them.
const objectById = Object.fromEntries((DATA.objects || []).map(o => [o.id, o]));
const nodeById = {...groupById, ...jobById, ...objectById};
const edgeById = Object.fromEntries((DATA.edges || []).map(e => [e.id, e]));
const outEdges = {}, inEdges = {};
for(const e of DATA.edges || []){
  (outEdges[e.source] ||= []).push(e);
  (inEdges[e.target] ||= []).push(e);
}

// Containment: '' is the synthetic root bucket for top-level groups / ungrouped jobs.
const childGroupsByParent = {};
const childJobsByGroup = {};
for(const g of DATA.groups || []) (childGroupsByParent[g.parent || ''] ||= []).push(g.id);
for(const j of DATA.jobs || []) (childJobsByGroup[j.group || ''] ||= []).push(j.id);
function directChildGroups(groupId){ return childGroupsByParent[groupId === null ? '' : groupId] || []; }
function directChildJobs(groupId){ return childJobsByGroup[groupId === null ? '' : groupId] || []; }

function parentOf(id){
  if(groupById[id]) return groupById[id].parent || null;
  if(jobById[id]) return jobById[id].group || null;
  return null;
}
function ancestorChain(id){
  // Group ids from the top-level ancestor down to id's immediate parent (excludes id itself).
  const chain = [];
  let p = parentOf(id);
  while(p !== null && p !== undefined){ chain.unshift(p); p = parentOf(p); }
  return chain;
}
function topAncestorOf(id){
  const chain = ancestorChain(id);
  if(chain.length) return chain[0];
  return groupById[id] ? id : null;
}

const DOMAIN_PALETTE = ['#1c7ed6','#7048e8','#2f9e44','#e8590c','#1098ad','#d6336c','#f08c00','#5f3dc4','#0ca678','#e64980'];
const topLevelGroupIds = directChildGroups(null).slice().sort();
const domainColor = {};
topLevelGroupIds.forEach((id,i) => { domainColor[id] = DOMAIN_PALETTE[i % DOMAIN_PALETTE.length]; });
function colorFor(id){
  const dom = topAncestorOf(id);
  return (dom && domainColor[dom]) || '#868e96';
}

const descendantJobsCache = {};
function descendantJobs(groupId){
  if(descendantJobsCache[groupId]) return descendantJobsCache[groupId];
  const result = [];
  const stack = [groupId];
  while(stack.length){
    const gid = stack.pop();
    for(const jid of directChildJobs(gid)) result.push(jid);
    for(const sub of directChildGroups(gid)) stack.push(sub);
  }
  descendantJobsCache[groupId] = result;
  return result;
}

/* ---------------------------------------------------------------------
   Status / comparison helpers (only meaningful for compare* report types;
   for plain graph.html / skeleton-graph.html every status is undefined and
   statusMatches() is always true, so this simply never filters anything out).
   ------------------------------------------------------------------- */
function statusColor(status){
  if(!status) return null;
  if(isSkeletonReport) return {matched:'#94a3b8', changed:'#f08c00', 'only-sb':'#2f9e44', 'only-jil':'#e03131'}[status] || null;
  return {matched:'#2f9e44', missing_in_stonebranch:'#e03131', missing_in_jil:'#1c7ed6', missing_critical_in_stonebranch:'#c92a2a', missing_critical_in_jil:'#364fc7', command_syntax_diff_only:'#f08c00', command_semantic_mismatch:'#c92a2a', condition_mismatch:'#f08c00', normalized_key_collision:'#862e9c', stonebranch_only:'#1c7ed6', jil_only:'#e03131'}[status] || null;
}
function isProblemStatus(status){
  return !!status && !['matched','stonebranch_only','jil_only'].includes(status);
}
let activeStatusFilter = 'all';
function statusMatches(status, filter){
  filter = filter === undefined ? activeStatusFilter : filter;
  if(filter === 'all') return true;
  if(filter === 'problems') return isProblemStatus(status);
  if(filter === 'missing') return ['missing_in_stonebranch','missing_in_jil','missing_critical_in_stonebranch','missing_critical_in_jil','only-sb','only-jil'].includes(status);
  if(filter === 'critical') return ['missing_critical_in_stonebranch','missing_critical_in_jil','command_semantic_mismatch','normalized_key_collision'].includes(status);
  if(filter === 'commands') return ['command_syntax_diff_only','command_semantic_mismatch'].includes(status);
  if(filter === 'syntax') return status === 'command_syntax_diff_only';
  if(filter === 'semantic') return status === 'command_semantic_mismatch';
  if(filter === 'collisions') return status === 'normalized_key_collision';
  return true;
}
function groupHasMatchingChild(groupId){
  return descendantJobs(groupId).some(jid => statusMatches(jobById[jid]?.status));
}
function nodeMatchesCurrentStatus(entity){
  if(!entity) return false;
  if(activeStatusFilter === 'all') return true;
  if(statusMatches(entity.status)) return true;
  if(groupById[entity.id] && groupHasMatchingChild(entity.id)) return true;
  return false;
}
function edgeStatusPasses(e){
  if(activeStatusFilter === 'all') return true;
  if(statusMatches(e.status)) return true;
  if(statusMatches(jobById[e.source]?.status)) return true;
  if(statusMatches(jobById[e.target]?.status)) return true;
  return false;
}
const STATUS_SEVERITY = ['missing_critical_in_stonebranch','missing_critical_in_jil','command_semantic_mismatch','normalized_key_collision','missing_in_stonebranch','missing_in_jil','command_syntax_diff_only','condition_mismatch','only-sb','only-jil','changed','matched'];
function worstEdgeStatus(edges){
  let best, bestRank = Infinity;
  for(const e of edges){
    const idx = STATUS_SEVERITY.indexOf(e.status);
    const rank = idx === -1 ? (e.status ? 500 : 1000) : idx;
    if(rank < bestRank){ bestRank = rank; best = e.status; }
  }
  return best;
}

/* ---------------------------------------------------------------------
   Small utilities
   ------------------------------------------------------------------- */
function escapeHtml(value){
  return String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
}
function text(value, max){
  max = max || 28;
  const s = String(value ?? '');
  return s.length > max ? s.slice(0, max - 1) + '...' : s;
}
function label(entity){ return entity?.label || entity?.name || entity?.id || ''; }
function metaRows(obj){
  return Object.entries(obj || {})
    .filter(([,v]) => v !== null && v !== undefined && v !== '')
    .map(([k,v]) => `<div class="kv"><span class="k">${escapeHtml(k)}</span><span class="v">${escapeHtml(String(v))}</span></div>`)
    .join('');
}
function kv(k, v){ return `<div class="kv"><span class="k">${escapeHtml(k)}</span><span class="v">${escapeHtml(String(v ?? '—'))}</span></div>`; }
function copyButton(value, lbl){
  lbl = lbl || 'Copy';
  return value ? `<button class="copy-btn" data-copy="${escapeHtml(value)}">${escapeHtml(lbl)}</button>` : '';
}
function copyable(value){
  return value ? `<code class="copyable">${escapeHtml(value)}</code>` : '<span class="placeholder">not available</span>';
}
function copyText(value){
  if(!value) return;
  if(navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(value).catch(()=>{});
}

/* ---------------------------------------------------------------------
   Dependency-free layered layout (no dagre / no CDN - this tool runs fully
   offline). Ranks units by longest-path from sources (Kahn's algorithm),
   then packs each rank perpendicular to the flow direction.
   ------------------------------------------------------------------- */
function layeredLayout(nodeList, edgeList, opts){
  const dir = opts.dir || 'TB';
  const rankGap = opts.rankGap ?? 70;
  const nodeGap = opts.nodeGap ?? 14;
  const byId = Object.fromEntries(nodeList.map(n => [n.id, n]));
  const outgoing = {}, indeg = {};
  nodeList.forEach(n => { outgoing[n.id] = []; indeg[n.id] = 0; });
  for(const e of edgeList){
    if(!byId[e.source] || !byId[e.target] || e.source === e.target) continue;
    outgoing[e.source].push(e.target);
    indeg[e.target] += 1;
  }
  const rank = {};
  nodeList.forEach(n => { rank[n.id] = 0; });
  const indegRemaining = {...indeg};
  let queue = nodeList.filter(n => indegRemaining[n.id] === 0).map(n => n.id).sort();
  const settled = new Set(queue);
  while(queue.length){
    const id = queue.shift();
    for(const t of outgoing[id]){
      rank[t] = Math.max(rank[t], rank[id] + 1);
      indegRemaining[t] -= 1;
      if(indegRemaining[t] <= 0 && !settled.has(t)){ settled.add(t); queue.push(t); }
    }
  }
  // Any node left unsettled sits on a cycle; keep it at rank 0 rather than looping forever.
  const buckets = {};
  nodeList.forEach(n => { (buckets[rank[n.id]] ||= []).push(n); });
  const rankKeys = Object.keys(buckets).map(Number).sort((a,b) => a - b);
  const positions = {};
  let cursorMain = 0;
  rankKeys.forEach(r => {
    const bucket = buckets[r].slice().sort((a,b) => String(a.sortKey||a.id).localeCompare(String(b.sortKey||b.id)));
    const mainSize = Math.max(...bucket.map(n => dir === 'TB' ? n.h : n.w));
    const totalCross = bucket.reduce((sum,n) => sum + (dir === 'TB' ? n.w : n.h), 0) + nodeGap * Math.max(0, bucket.length - 1);
    let crossCursor = -totalCross / 2;
    bucket.forEach(n => {
      const crossSize = dir === 'TB' ? n.w : n.h;
      const crossCenter = crossCursor + crossSize / 2;
      positions[n.id] = dir === 'TB'
        ? { x: crossCenter, y: cursorMain + mainSize / 2 }
        : { x: cursorMain + mainSize / 2, y: crossCenter };
      crossCursor += crossSize + nodeGap;
    });
    cursorMain += mainSize + rankGap;
  });
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  nodeList.forEach(n => {
    const p = positions[n.id];
    minX = Math.min(minX, p.x - n.w / 2); maxX = Math.max(maxX, p.x + n.w / 2);
    minY = Math.min(minY, p.y - n.h / 2); maxY = Math.max(maxY, p.y + n.h / 2);
  });
  if(!nodeList.length){ minX = minY = maxX = maxY = 0; }
  nodeList.forEach(n => { positions[n.id].x -= minX; positions[n.id].y -= minY; });
  return { positions, width: maxX - minX, height: maxY - minY };
}

/* ---------------------------------------------------------------------
   Recursive visibility + layout. Everything starts collapsed
   (expandedGroups empty); expanding a container reveals its direct
   children (jobs and/or nested container chips) - this generalizes the
   two-level "domain -> box" example to arbitrary container nesting depth.
   ------------------------------------------------------------------- */
const JOB_SIZE = { w: 150, h: 24 };
const CHIP_SIZE = { w: 200, h: 48 };
const GROUP_PAD = { l: 20, r: 20, t: 38, b: 16 };

let expandedGroups = new Set();
let direction = 'TB';
let groupLayoutCache = {};

function resolveToUnit(id, unitIds, boundaryGroupId){
  let current = id;
  while(current !== null && current !== undefined){
    if(unitIds.has(current)) return current;
    if(groupById[current] && unitIds.has('box:' + current)) return 'box:' + current;
    if(current === boundaryGroupId) return null;
    current = parentOf(current);
  }
  return null;
}

// Candidate edges for laying out one group's direct children. At root scope
// every edge is a candidate (any edge could resolve up to a top-level chip),
// but for a nested group we only need edges that touch a job somewhere in
// that group's own subtree - looking those up via outEdges/inEdges keeps
// layoutOf() from re-scanning the full edge list once per expanded group
// (O(edges touching the subtree) instead of O(total edges) per group).
function localEdgeCandidates(groupId){
  if(groupId === null) return DATA.edges || [];
  const seen = new Set();
  const result = [];
  for(const jid of descendantJobs(groupId)){
    for(const e of (outEdges[jid] || [])) if(!seen.has(e.id)){ seen.add(e.id); result.push(e); }
    for(const e of (inEdges[jid] || [])) if(!seen.has(e.id)){ seen.add(e.id); result.push(e); }
  }
  return result;
}
function layoutOf(groupId){
  const cacheKey = groupId === null ? '\0root' : groupId;
  if(groupLayoutCache[cacheKey]) return groupLayoutCache[cacheKey];
  const childUnits = [];
  for(const sub of directChildGroups(groupId).slice().sort()){
    const g = groupById[sub];
    if(!nodeMatchesCurrentStatus(g)) continue;
    if(expandedGroups.has(sub)){
      const sz = layoutOf(sub).size;
      childUnits.push({ id: sub, kind: 'group', groupId: sub, w: sz.w, h: sz.h, sortKey: sub });
    } else {
      childUnits.push({ id: 'box:' + sub, kind: 'box', groupId: sub, w: CHIP_SIZE.w, h: CHIP_SIZE.h, sortKey: sub });
    }
  }
  for(const jid of directChildJobs(groupId).slice().sort()){
    const j = jobById[jid];
    if(!nodeMatchesCurrentStatus(j)) continue;
    childUnits.push({ id: jid, kind: 'job', groupId: null, w: JOB_SIZE.w, h: JOB_SIZE.h, sortKey: jid });
  }
  const unitIds = new Set(childUnits.map(u => u.id));
  const seenPairs = new Set();
  const localEdges = [];
  for(const e of localEdgeCandidates(groupId)){
    if(!edgeStatusPasses(e)) continue;
    const s = resolveToUnit(e.source, unitIds, groupId);
    const t = resolveToUnit(e.target, unitIds, groupId);
    if(!s || !t || s === t) continue;
    const key = s + '>>' + t;
    if(seenPairs.has(key)) continue;
    seenPairs.add(key);
    localEdges.push({ source: s, target: t });
  }
  const isRoot = groupId === null;
  const { positions, width, height } = layeredLayout(childUnits, localEdges, {
    dir: direction,
    rankGap: isRoot ? 110 : 64,
    nodeGap: isRoot ? 30 : 14,
  });
  const pad = isRoot ? { l: 0, r: 0, t: 0, b: 0 } : GROUP_PAD;
  const size = { w: width + pad.l + pad.r, h: height + pad.t + pad.b };
  const relPositions = {};
  for(const u of childUnits) relPositions[u.id] = { x: positions[u.id].x + pad.l, y: positions[u.id].y + pad.t };
  const result = { size, relPositions, childUnits };
  groupLayoutCache[cacheKey] = result;
  return result;
}

function buildVisible(){
  groupLayoutCache = {};
  const root = layoutOf(null);
  const elements = [];
  const positions = {};
  const jobIds = new Set(), boxIds = new Set(), groupIds = new Set();

  function place(unit, parentId, cx, cy){
    positions[unit.id] = { x: cx, y: cy };
    if(unit.kind === 'job'){
      jobIds.add(unit.id);
      elements.push(makeJobElement(unit.id, parentId));
    } else if(unit.kind === 'box'){
      boxIds.add(unit.id);
      elements.push(makeBoxElement(unit.id, unit.groupId, parentId));
    } else {
      groupIds.add(unit.groupId);
      elements.push(makeGroupElement(unit.groupId, parentId));
      const layout = layoutOf(unit.groupId);
      const topLeftX = cx - layout.size.w / 2, topLeftY = cy - layout.size.h / 2;
      for(const child of layout.childUnits){
        const rel = layout.relPositions[child.id];
        place(child, unit.groupId, topLeftX + rel.x, topLeftY + rel.y);
      }
    }
  }
  for(const unit of root.childUnits){
    const p = root.relPositions[unit.id];
    place(unit, null, p.x, p.y);
  }

  const endpointIds = new Set([...jobIds, ...boxIds]);
  const merged = new Map();
  for(const e of DATA.edges || []){
    if(!edgeStatusPasses(e)) continue;
    const s = resolveToUnit(e.source, endpointIds, null);
    const t = resolveToUnit(e.target, endpointIds, null);
    if(!s || !t || s === t) continue;
    const key = s + '>>' + t;
    let bucket = merged.get(key);
    if(!bucket){ bucket = { source: s, target: t, edges: [] }; merged.set(key, bucket); }
    bucket.edges.push(e);
  }
  const edgeElements = [];
  for(const [key, bucket] of merged) edgeElements.push(makeEdgeElement(key, bucket));

  return { elements: [...elements, ...edgeElements], positions, jobIds, boxIds, groupIds, endpointIds };
}

/* ---------------------------------------------------------------------
   Cytoscape element builders
   ------------------------------------------------------------------- */
function makeJobElement(id, parentId){
  const j = jobById[id];
  const dom = colorFor(id);
  const st = statusColor(j.status);
  const data = {
    id, kind: 'job', label: text(label(j), 16), fullLabel: label(j), group: j.group,
    watcher: !!j.watcher, color: dom, borderColor: st || '#fff', status: j.status || '',
  };
  if(parentId) data.parent = parentId;
  return { group: 'nodes', data, classes: `job ${j.watcher ? 'watcher' : ''} ${isProblemStatus(j.status) ? 'problem' : ''}`.trim() };
}
function makeBoxElement(id, groupId, parentId){
  const g = groupById[groupId];
  const jobs = descendantJobs(groupId);
  const count = jobs.length;
  const watcherCount = jobs.filter(jid => jobById[jid]?.watcher).length;
  const dom = colorFor(groupId);
  const suffix = watcherCount ? ` (${watcherCount} fw)` : '';
  const data = {
    id, kind: 'box', groupId, label: text(`${label(g)} · ${count}${suffix}`, 30), fullLabel: label(g),
    color: dom, borderColor: statusColor(g.status) || dom, status: g.status || '', count, watcherCount,
  };
  if(parentId) data.parent = parentId;
  return { group: 'nodes', data, classes: `box ${isProblemStatus(g.status) ? 'problem' : ''}`.trim() };
}
function makeGroupElement(groupId, parentId){
  const g = groupById[groupId];
  const dom = colorFor(groupId);
  const data = {
    id: groupId, kind: 'group', groupId, label: text(label(g), 26), fullLabel: label(g),
    color: dom, borderColor: statusColor(g.status) || dom, status: g.status || '',
  };
  if(parentId) data.parent = parentId;
  return { group: 'nodes', data, classes: `group ${isProblemStatus(g.status) ? 'problem' : ''}`.trim() };
}
function makeEdgeElement(key, bucket){
  const worst = worstEdgeStatus(bucket.edges);
  const nonSuccess = bucket.edges.some(e => e.predicate && e.predicate !== 'SUCCESS');
  const color = statusColor(worst) || (isSkeletonReport && nonSuccess ? '#be123c' : '#b8c0cb');
  const data = {
    id: key, source: bucket.source, target: bucket.target, color, status: worst || '',
    count: bucket.edges.length, label: bucket.edges.length > 1 ? String(bucket.edges.length) : '',
    refIds: bucket.edges.map(e => e.id),
  };
  return { group: 'edges', data, classes: `dep ${isProblemStatus(worst) ? 'problem' : ''} ${nonSuccess ? 'non-success' : ''}`.trim() };
}

/* ---------------------------------------------------------------------
   Cytoscape instance
   ------------------------------------------------------------------- */
// Above this many rendered elements, Cytoscape's own large-graph rendering
// mode kicks in (viewport-only edge/texture rendering instead of redrawing
// everything on every pan/zoom frame). These are constructor-only options -
// they can't be flipped on an existing instance, only chosen when creating one.
const LARGE_GRAPH_ELEMENT_THRESHOLD = 1500;
let cy = null;
let lastBuild = null;
let lastRenderModeLarge = false;

function createCy(elements, large){
  return window.cytoscape({
    container: $('cy'),
    elements,
    layout: { name: 'preset', positions: n => lastBuild.positions[n.id()] || { x: 0, y: 0 }, fit: false, padding: 40, animate: false },
    wheelSensitivity: 0.2,
    minZoom: 0.05,
    maxZoom: 3,
    hideEdgesOnViewport: large,
    textureOnViewport: large,
    motionBlur: !large,
    style: [
      { selector: 'node[kind="job"]', style: {
          'background-color': 'data(color)', 'border-width': 2, 'border-color': 'data(borderColor)',
          'width': 14, 'height': 14, 'shape': 'ellipse',
          'label': 'data(label)', 'font-size': 9, 'color': '#3a4450',
          'text-valign': 'center', 'text-halign': 'right', 'text-margin-x': 4, 'text-max-width': 120 } },
      { selector: 'node[kind="job"].watcher', style: {
          'shape': 'diamond', 'width': 16, 'height': 16, 'border-width': 2.5, 'border-color': '#0ca678' } },
      { selector: 'node[kind="box"]', style: {
          'shape': 'round-rectangle', 'background-color': 'data(color)', 'background-opacity': 0.16,
          'border-width': 1.5, 'border-color': 'data(borderColor)',
          'label': 'data(label)', 'font-size': 11.5, 'font-weight': 600, 'color': '#33404d',
          'text-valign': 'center', 'text-halign': 'center', 'text-max-width': 170,
          'width': 200, 'height': 46, 'padding': 6 } },
      { selector: 'node[kind="group"]', style: {
          'shape': 'round-rectangle', 'background-color': 'data(color)', 'background-opacity': 0.07,
          'border-width': 1.5, 'border-color': 'data(borderColor)', 'border-opacity': 0.6, 'border-style': 'dashed',
          'label': 'data(label)', 'font-size': 12, 'font-weight': 700, 'color': '#33404d',
          'text-valign': 'top', 'text-halign': 'center', 'text-margin-y': 6, 'padding': 16 } },
      { selector: 'edge.dep', style: {
          'width': 1, 'line-color': 'data(color)', 'target-arrow-color': 'data(color)', 'target-arrow-shape': 'triangle',
          'arrow-scale': 0.85, 'curve-style': 'bezier', 'opacity': 0.8, 'label': 'data(label)',
          'font-size': 9, 'color': '#475569', 'text-background-color': '#fff', 'text-background-opacity': 0.8, 'text-background-padding': 1 } },
      { selector: 'edge.dep.non-success', style: { 'width': 2, 'line-style': 'dashed' } },
      { selector: 'edge.dep.problem', style: { 'width': 2.2, 'opacity': 1 } },
      { selector: 'node.problem', style: { 'border-width': 3 } },
      { selector: 'node.sel', style: { 'border-width': 3.5, 'border-color': '#1f2730', 'font-weight': 700, 'color': '#000', 'z-index': 60 } },
      { selector: 'node.up', style: { 'border-width': 3.5, 'border-color': '#e8590c', 'color': '#b34700', 'font-weight': 600, 'z-index': 50 } },
      { selector: 'node.down', style: { 'border-width': 3.5, 'border-color': '#2f9e44', 'color': '#1d6e2f', 'font-weight': 600, 'z-index': 50 } },
      { selector: 'node.match', style: { 'border-width': 3.5, 'border-color': '#1c7ed6', 'z-index': 50 } },
      { selector: 'edge.up', style: { 'line-color': '#e8590c', 'target-arrow-color': '#e8590c', 'width': 2.4, 'opacity': 1, 'z-index': 50 } },
      { selector: 'edge.down', style: { 'line-color': '#2f9e44', 'target-arrow-color': '#2f9e44', 'width': 2.4, 'opacity': 1, 'z-index': 50 } },
      { selector: 'edge:selected', style: { 'line-color': '#111827', 'target-arrow-color': '#111827', 'width': 2.6, 'curve-style': 'bezier', 'z-index': 55 } },
    ],
  });
}
function bindCyEvents(){
  cy.on('tap', 'node[kind="job"]', ev => focusJob(ev.target.id()));
  cy.on('tap', 'node[kind="box"]', ev => expandBoxPath(ev.target.data('groupId')));
  cy.on('tap', 'node[kind="group"]', ev => collapseGroup(ev.target.data('groupId')));
  cy.on('tap', 'edge', ev => selectEdge(ev.target.id()));
  cy.on('tap', ev => { if(ev.target === cy) clearSelection(); });
}
function buildCy(opts){
  opts = opts || {};
  lastBuild = buildVisible();
  const large = lastBuild.elements.length > LARGE_GRAPH_ELEMENT_THRESHOLD;
  if(!cy || large !== lastRenderModeLarge){
    // First build, or crossing the large-graph rendering-mode threshold
    // (hideEdgesOnViewport/textureOnViewport/motionBlur are constructor-only
    // in Cytoscape) - only these two cases need a full destroy+recreate.
    if(cy) cy.destroy();
    cy = createCy(lastBuild.elements, large);
    bindCyEvents();
    lastRenderModeLarge = large;
  } else {
    // Same rendering mode as last time: diff instead of rebuilding from
    // scratch. Most clicks (expand one box, focus one job, toggle direction)
    // only actually change a small slice of a large graph's elements - the
    // rest just need their position refreshed, not to be torn down and
    // recreated, which is both slower and (for pan/zoom) more jarring.
    const nextById = new Map(lastBuild.elements.map(el => [el.data.id, el]));
    const prevEls = cy.elements();
    const addDefs = [];
    const staleIds = new Set();
    nextById.forEach((def, id) => {
      const existing = cy.getElementById(id);
      if(!existing.length){ addDefs.push(def); return; }
      if(JSON.stringify(existing.data()) !== JSON.stringify(def.data)){ staleIds.add(id); addDefs.push(def); }
    });
    const removeColl = prevEls.filter(el => !nextById.has(el.id()) || staleIds.has(el.id()));
    cy.batch(() => {
      if(removeColl.length) cy.remove(removeColl);
      if(addDefs.length) cy.add(addDefs);
      // Re-apply the freshly computed layout to EVERY visible leaf node, not
      // just the ones that already existed. Nodes added via cy.add() carry no
      // position and would otherwise default to (0,0) - so the children
      // revealed by expanding a box would all pile up on top of each other at
      // the origin (and drag any fit box out to "whole graph" zoom). Compound
      // parents are skipped on purpose: Cytoscape auto-sizes them around their
      // children, and calling .position() on a parent drags its whole subtree.
      cy.nodes().forEach(el => {
        if(el.isParent()) return;
        const pos = lastBuild.positions[el.id()];
        if(pos) el.position(pos);
      });
    });
  }
  if(!opts.skipFit) cy.fit(undefined, 40);
  updateStats();
  updateCrumb();
}
// Fit the viewport to specific ids (resolved to whatever is currently visible
// for each - a job, a collapsed box chip, or an expanded group) instead of
// the whole graph. Used after interactive drill-down so the zoom level stays
// close to where the user already was, rather than snapping back out to fit
// every object on screen.
function fitToVisible(ids, padding){
  if(!cy || !lastBuild) return;
  let collection = null;
  for(const id of ids){
    const vis = resolveToUnit(id, lastBuild.endpointIds, null) || (lastBuild.groupIds.has(id) ? id : null);
    if(!vis) continue;
    const ele = cy.getElementById(vis);
    if(!ele || !ele.length) continue;
    collection = collection ? collection.union(ele) : ele;
  }
  if(collection) cy.fit(collection, padding || 70);
  else cy.fit(undefined, 40);
}
// Rendered (screen-pixel) center of whatever is currently on-screen for `id`
// - the job itself, its collapsed box chip, or its expanded group container.
function renderedCenterOf(id){
  if(!cy || !lastBuild) return null;
  const vis = resolveToUnit(id, lastBuild.endpointIds, null) || (lastBuild.groupIds.has(id) ? id : null);
  if(!vis) return null;
  const ele = cy.getElementById(vis);
  if(!ele || !ele.length) return null;
  return { ...ele.renderedPosition() };
}
// Rebuild the graph while keeping the camera still. We remember where the
// clicked element sat on screen, run the mutation (which reflows the layout),
// then pan by exactly the delta so that same element stays under the cursor.
// Zoom is never touched. This is what makes expand/collapse/focus feel like
// the box opens "in place" instead of the view snapping to a new fit.
function keepViewport(anchorId, mutate){
  const savedPan = cy ? { ...cy.pan() } : null;
  const before = anchorId != null ? renderedCenterOf(anchorId) : null;
  mutate();
  if(!cy) return;
  const after = anchorId != null ? renderedCenterOf(anchorId) : null;
  if(before && after){
    cy.panBy({ x: before.x - after.x, y: before.y - after.y });
  } else if(savedPan){
    cy.pan(savedPan);
  }
}
function zoomBy(factor){
  if(!cy) return;
  const target = Math.max(cy.minZoom(), Math.min(cy.maxZoom(), cy.zoom() * factor));
  cy.zoom({ level: target, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } });
}

/* ---------------------------------------------------------------------
   Up/down adjacency (from job.depends_on, independent of collapse state)
   ------------------------------------------------------------------- */
const upOf = {}, downOf = {};
for(const j of DATA.jobs || []) upOf[j.id] = (j.depends_on || []).slice();
for(const j of DATA.jobs || []) for(const d of (j.depends_on || [])) (downOf[d] ||= []).push(j.id);
function chainSize(id, adj){
  const seen = new Set(); const q = [id];
  while(q.length){ const n = q.shift(); for(const m of (adj[n] || [])) if(!seen.has(m)){ seen.add(m); q.push(m); } }
  return seen.size;
}

/* ---------------------------------------------------------------------
   Navigation: drill-down expand/collapse + selection highlighting
   ------------------------------------------------------------------- */
function ancestorChainInclusive(groupId){ return [...ancestorChain(groupId), groupId]; }
function expandBoxPath(groupId){
  keepViewport(groupId, () => {
    expandedGroups = new Set(ancestorChainInclusive(groupId));
    buildCy({ skipFit: true });
  });
  clearHighlightClasses();
  const linked = linkedGroups(groupId);
  for(const g of linked) markMatchIfVisible(g);
  showGroupPanel(groupId);
}
function collapseGroup(groupId){
  keepViewport(groupId, () => {
    expandedGroups = new Set(ancestorChain(groupId));
    buildCy({ skipFit: true });
  });
  clearHighlightClasses();
  showGroupPanel(groupId);
}
function linkedGroups(groupId){
  const jobs = new Set(descendantJobs(groupId));
  const linked = new Set();
  for(const jid of jobs){
    for(const d of (upOf[jid] || [])) { const g = jobById[d]?.group; if(g && g !== groupId) linked.add(g); }
    for(const d of (downOf[jid] || [])) { const g = jobById[d]?.group; if(g && g !== groupId) linked.add(g); }
  }
  return linked;
}
function markMatchIfVisible(groupId){
  const vis = resolveToUnit(groupId, lastBuild.endpointIds, null) || (lastBuild.groupIds.has(groupId) ? groupId : null);
  if(vis) cy.getElementById(vis).addClass('match');
}
function focusJob(jobId){
  keepViewport(jobId, () => {
    expandedGroups = new Set(ancestorChain(jobId));
    buildCy({ skipFit: true });
  });
  clearHighlightClasses();
  cy.getElementById(jobId).addClass('sel');
  for(const d of (upOf[jobId] || [])){
    const vis = resolveToUnit(d, lastBuild.endpointIds, null);
    if(vis){ cy.getElementById(vis).addClass('up'); }
  }
  for(const d of (downOf[jobId] || [])){
    const vis = resolveToUnit(d, lastBuild.endpointIds, null);
    if(vis){ cy.getElementById(vis).addClass('down'); }
  }
  cy.edges().forEach(edge => {
    if(edge.source().hasClass('up') && edge.target().id() === jobId) edge.addClass('up');
    if(edge.target().hasClass('down') && edge.source().id() === jobId) edge.addClass('down');
  });
  showJobPanel(jobId);
}
function selectEdge(edgeVisualId){
  const ele = cy.getElementById(edgeVisualId);
  if(!ele || !ele.length) return;
  clearHighlightClasses();
  cy.elements().unselect();
  ele.select();
  ele.source().addClass('sel');
  ele.target().addClass('sel');
  showEdgePanel(edgeVisualId);
}
function clearHighlightClasses(){
  if(cy) cy.elements().removeClass('sel up down match');
}
function clearSelection(){
  clearHighlightClasses();
  showOverview();
}

/* ---------------------------------------------------------------------
   Stats / crumb
   ------------------------------------------------------------------- */
function validateGraph(){
  const ids = new Set((DATA.jobs || []).map(j => j.id));
  let missing = 0;
  const adj = {};
  for(const j of DATA.jobs || []){
    adj[j.id] = (j.depends_on || []).filter(d => { if(!ids.has(d)) missing++; return ids.has(d); });
  }
  const color = {};
  let cyc = false;
  function dfs(n){
    color[n] = 1;
    for(const m of adj[n] || []){ if(color[m] === 1){ cyc = true; return; } if(!color[m]) dfs(m); }
    color[n] = 2;
  }
  for(const j of DATA.jobs || []) if(!color[j.id]) dfs(j.id);
  return { missing, cycles: cyc ? 1 : 0 };
}
const graphProblems = validateGraph();
function updateStats(){
  $('nJobs').textContent = (DATA.jobs || []).length;
  $('nBoxes').textContent = (DATA.groups || []).length;
  $('nEdges').textContent = (DATA.edges || []).length;
  $('nObjects').textContent = (DATA.objects || []).length;
  const health = $('health');
  if(hasComparisonStatuses){
    const statuses = DATA.metadata?.statuses || {};
    const problems = Object.entries(statuses).filter(([k]) => isProblemStatus(k)).reduce((s,[,v]) => s+v, 0);
    health.innerHTML = problems ? `<span class="bad">${problems} diffs</span>` : `<span class="good">no diffs</span>`;
  } else {
    health.innerHTML = (graphProblems.missing + graphProblems.cycles)
      ? `<span class="bad">${graphProblems.cycles ? 'cycle, ' : ''}${graphProblems.missing} missing dep(s)</span>`
      : `<span class="good">valid DAG</span>`;
  }
}
function updateCrumb(){
  const n = expandedGroups.size;
  const total = (DATA.groups || []).length;
  $('crumb').innerHTML = n === 0 ? 'all boxes collapsed'
    : n === total ? '<b>all boxes</b> expanded'
    : `<b>${n}</b> of ${total} boxes expanded`;
}

/* ---------------------------------------------------------------------
   Side panel content
   ------------------------------------------------------------------- */
const pTitle = () => $('pTitle'), pSub = () => $('pSub'), pBody = () => $('pBody');
function depRow(id){
  const j = jobById[id]; if(!j) return '';
  return `<div class="dep-item" data-job="${escapeHtml(id)}"><span class="dot ${j.watcher ? 'watcher' : ''}" style="background:${colorFor(id)}"></span><span class="nm" title="${escapeHtml(id)}">${escapeHtml(label(j))}</span></div>`;
}
function boxRow(gid){
  const g = groupById[gid]; if(!g) return '';
  return `<div class="dep-item" data-box="${escapeHtml(gid)}"><span class="box-dot" style="background:${colorFor(gid)}"></span><span class="nm">${escapeHtml(label(g))}</span></div>`;
}
function objectRow(entry){
  const oid = typeof entry === 'string' ? entry : entry.id;
  const o = objectById[oid]; if(!o) return '';
  return `<div class="dep-item" data-object="${escapeHtml(oid)}"><span class="box-dot" style="background:#868e96"></span><span class="nm" title="${escapeHtml(oid)}">${escapeHtml(label(o))} <span style="color:var(--muted)">(${escapeHtml(o.kind || 'object')})</span></span></div>`;
}
function showOverview(){
  pTitle().textContent = 'Overview';
  pSub().textContent = `${DATA.metadata?.source_system || DATA.metadata?.report_title || ''} ${DATA.metadata?.env || ''}`.trim();
  let html = `<div class="sec-title">Top-level boxes</div>`;
  html += topLevelGroupIds.map(id => `<div class="legend-row" data-box="${escapeHtml(id)}"><span class="swatch" style="background:${colorFor(id)}"></span>${escapeHtml(label(groupById[id]))}</div>`).join('') || '<div class="empty">No containers in this graph</div>';
  html += `<div class="sec-title">Legend</div>`;
  html += `<div class="legend-row"><span class="dot" style="background:#868e96;position:relative;"></span>task / job</div>`;
  html += `<div class="legend-row"><span class="swatch watcher" style="background:#0ca678"></span>file watcher / monitor</div>`;
  if(hasComparisonStatuses){
    const statuses = DATA.metadata?.statuses || {};
    html += `<div class="sec-title">Status counts</div>`;
    html += Object.entries(statuses).map(([k,v]) => `<div class="kv"><span class="k"><i class="swatch" style="display:inline-block;background:${statusColor(k) || '#868e96'};vertical-align:middle;margin-right:6px;"></i>${escapeHtml(k)}</span><span class="v">${escapeHtml(v)}</span></div>`).join('');
  }
  html += `<div class="sec-title">How to navigate</div><div class="placeholder">
    Everything starts collapsed into boxes.<br>
    &bull; <b>Click a box</b> to expand it; boxes it depends on / is depended on by stay highlighted as chips.<br>
    &bull; <b>Click a job</b> to reveal it and highlight its <span style="color:var(--warn)">upstream</span> / <span style="color:var(--ok)">downstream</span> chain.<br>
    &bull; <kbd>/</kbd> search &middot; <kbd>Esc</kbd> reset</div>`;
  if((DATA.warnings || []).length){
    html += `<div class="sec-title">Warnings <span class="count-pill">${DATA.warnings.length}</span></div>`;
    html += DATA.warnings.slice(0, 40).map(w => `<div class="empty">${escapeHtml(w)}</div>`).join('');
  }
  pBody().innerHTML = html;
  bindPanelActions();
}
function showGroupPanel(gid){
  const g = groupById[gid]; if(!g) return;
  const linked = [...linkedGroups(gid)].sort();
  const jobs = descendantJobs(gid);
  pTitle().textContent = label(g);
  pSub().textContent = `Box${g.parent ? ' · in ' + label(groupById[g.parent]) : ''}`;
  let html = kv('Jobs', jobs.length) + kv('File watchers', jobs.filter(jid => jobById[jid]?.watcher).length);
  if(g.status) html += kv('Status', g.status);
  html += `<div class="sec-title">Linked boxes <span class="count-pill">${linked.length}</span></div>`;
  html += linked.length ? linked.map(boxRow).join('') : '<div class="empty">No cross-box dependencies</div>';
  pBody().innerHTML = html;
  bindPanelActions();
}
// A job with a few thousand direct dependents (common for a shared
// staging/ingestion job) would otherwise dump that many DOM nodes into the
// panel in one shot - cap the rendered list and say how many are hidden.
const DEP_LIST_RENDER_CAP = 150;
function renderDepList(ids, emptyMessage){
  if(!ids.length) return `<div class="empty">${emptyMessage}</div>`;
  const shown = ids.slice(0, DEP_LIST_RENDER_CAP).map(depRow).join('');
  const hidden = ids.length - DEP_LIST_RENDER_CAP;
  return hidden > 0 ? shown + `<div class="chain-note">+${hidden} more not shown (use search)</div>` : shown;
}
function showJobPanel(id){
  const j = jobById[id]; if(!j) return;
  const up = (upOf[id] || []).slice().sort(), down = (downOf[id] || []).slice().sort();
  pTitle().textContent = label(j);
  pSub().textContent = `${j.group ? label(groupById[j.group]) + ' · ' : ''}${id}${j.watcher ? ' · file watcher' : ''}`;
  let html = kv('Box', j.group ? label(groupById[j.group]) : '—') + kv('Kind', j.kind || j.original_kind || '');
  if(j.meta) html += metaRows(j.meta);
  if(j.status) html += kv('Status', j.status);
  if(j.trigger) html += `<div class="sec-title">Trigger</div><div class="copy-row">${copyable(j.trigger)} ${copyButton(j.trigger, 'Copy trigger')}</div>`;
  html += `<div class="sec-title up"><span class="arrow">&#9650;</span> Depends on <span class="count-pill">${up.length}</span></div>`;
  html += renderDepList(up, 'No upstream dependencies (root job)');
  const ut = chainSize(id, upOf); if(ut > up.length) html += `<div class="chain-note">${ut} jobs upstream in total</div>`;
  html += `<div class="sec-title down"><span class="arrow">&#9660;</span> Required by <span class="count-pill">${down.length}</span></div>`;
  html += renderDepList(down, 'Nothing depends on this (leaf job)');
  const dt = chainSize(id, downOf); if(dt > down.length) html += `<div class="chain-note">${dt} jobs downstream in total</div>`;
  const outgoing = outEdges[id] || [], incoming = inEdges[id] || [];
  if(outgoing.length || incoming.length){
    html += `<div class="sec-title">Evidence</div>`;
    html += [...outgoing, ...incoming].slice(0, 60).map(e => edgeCard(e, id)).join('');
  }
  pBody().innerHTML = html;
  bindPanelActions();
}
function showObjectPanel(id){
  const o = objectById[id]; if(!o) return;
  const usedBy = (o.used_by || []).slice().sort();
  pTitle().textContent = label(o);
  pSub().textContent = `${o.kind || 'object'}${o.source_file ? ' · ' + o.source_file : ''}`;
  let html = kv('Kind', o.kind || '') + kv('Source file', o.source_file || '—');
  html += `<div class="sec-title">Used by <span class="count-pill">${usedBy.length}</span></div>`;
  html += renderDepList(usedBy, 'No jobs reference this object');
  pBody().innerHTML = html;
  bindPanelActions();
}
// Shown for a search that matches several things at once (multiple jobs
// and/or objects) - individual single matches still get their own focused
// panel (showJobPanel / showObjectPanel) via runSearch.
function showSearchResultsPanel(jobMatches, objectMatches){
  pTitle().textContent = 'Search results';
  pSub().textContent = `${jobMatches.length} job(s) · ${objectMatches.length} object(s)`;
  let html = '';
  if(jobMatches.length){
    html += `<div class="sec-title">Jobs <span class="count-pill">${jobMatches.length}</span></div>`;
    html += renderDepList(jobMatches.map(j => j.id), 'No matching jobs');
  }
  if(objectMatches.length){
    html += `<div class="sec-title">Objects <span class="count-pill">${objectMatches.length}</span></div>`;
    const shown = objectMatches.slice(0, DEP_LIST_RENDER_CAP);
    html += shown.map(objectRow).join('');
    const hidden = objectMatches.length - shown.length;
    if(hidden > 0) html += `<div class="chain-note">+${hidden} more not shown (refine search)</div>`;
  }
  pBody().innerHTML = html || '<div class="empty">No matches</div>';
  bindPanelActions();
}
function edgeCard(e, selfId){
  const other = e.source === selfId ? e.target : e.source;
  const evidence = [e.relation, e.confidence, e.evidence_file, e.evidence_key, e.evidence_path].filter(Boolean).join(' | ');
  return `<div class="edge-card"><div class="edge-main" data-job="${escapeHtml(other)}"><span>${escapeHtml(e.relation || 'depends_on')}</span><span>&harr;</span><b>${escapeHtml(other)}</b></div><div class="edge-meta">${escapeHtml(evidence)}</div><div class="copy-row">${copyButton(`${e.source} -> ${e.relation} -> ${e.target}`, 'Copy edge')}</div></div>`;
}
function showEdgePanel(edgeVisualId){
  const ele = cy.getElementById(edgeVisualId);
  const refIds = ele && ele.length ? (ele.data('refIds') || []) : [];
  const realEdges = refIds.map(id => edgeById[id]).filter(Boolean);
  pTitle().textContent = 'Dependency';
  pSub().textContent = ele && ele.length ? `${ele.data('source')} -> ${ele.data('target')}` : edgeVisualId;
  let html = `<div class="sec-title">Endpoints</div>`;
  if(ele && ele.length){
    html += `<div class="kv"><span class="k">Source</span><span class="v"><span class="linkish" data-any="${escapeHtml(ele.data('source'))}">${escapeHtml(ele.data('source'))}</span></span></div>`;
    html += `<div class="kv"><span class="k">Target</span><span class="v"><span class="linkish" data-any="${escapeHtml(ele.data('target'))}">${escapeHtml(ele.data('target'))}</span></span></div>`;
  }
  html += `<div class="sec-title">Underlying edges <span class="count-pill">${realEdges.length}</span></div>`;
  html += realEdges.length ? realEdges.map(e => {
    const evidence = [e.status, e.relation, e.confidence, e.evidence_file, e.evidence_key, e.evidence_path].filter(Boolean).join(' | ');
    return `<div class="edge-card"><div class="edge-main"><span>${escapeHtml(e.source)}</span><span>&rarr;</span><b>${escapeHtml(e.target)}</b></div><div class="edge-meta">${escapeHtml(e.relation)} ${escapeHtml(evidence)}</div></div>`;
  }).join('') : '<div class="empty">No evidence recorded</div>';
  pBody().innerHTML = html;
  bindPanelActions();
}
function bindPanelActions(){
  pBody().querySelectorAll('[data-job]').forEach(el => el.addEventListener('click', ev => { ev.stopPropagation(); focusJob(el.getAttribute('data-job')); }));
  pBody().querySelectorAll('[data-box]').forEach(el => el.addEventListener('click', ev => { ev.stopPropagation(); expandBoxPath(el.getAttribute('data-box')); }));
  pBody().querySelectorAll('[data-object]').forEach(el => el.addEventListener('click', ev => { ev.stopPropagation(); showObjectPanel(el.getAttribute('data-object')); }));
  pBody().querySelectorAll('[data-any]').forEach(el => el.addEventListener('click', ev => {
    ev.stopPropagation();
    const id = el.getAttribute('data-any');
    if(jobById[id]) focusJob(id); else if(groupById[id]) expandBoxPath(id); else if(objectById[id]) showObjectPanel(id);
  }));
  pBody().querySelectorAll('[data-copy]').forEach(el => el.addEventListener('click', ev => {
    ev.stopPropagation(); copyText(el.getAttribute('data-copy'));
    const original = el.textContent; el.textContent = 'Copied'; setTimeout(() => { el.textContent = original; }, 900);
  }));
}

/* ---------------------------------------------------------------------
   Search
   ------------------------------------------------------------------- */
const searchInput = $('search'), searchCount = $('searchCount');
// A very broad query (a short/common substring) can match thousands of jobs
// scattered across just as many boxes - auto-expanding all of their ancestor
// paths at once would be exactly the "expand everything" cost we're trying
// to avoid, just triggered by typing instead of a button.
const SEARCH_EXPAND_CAP = 300;
function runSearch(){
  const q = searchInput.value.trim().toLowerCase();
  if(!q){
    searchCount.textContent = '';
    expandedGroups = new Set();
    buildCy();
    clearHighlightClasses();
    showOverview();
    return;
  }
  const jobMatches = (DATA.jobs || []).filter(j => label(j).toLowerCase().includes(q) || j.id.toLowerCase().includes(q));
  // Objects (agents, calendars, credentials, connections, email templates,
  // files, objects, scripts, triggers, variables) are never drawn on the
  // canvas, so they can't be expanded/fitted like a job match - they only
  // ever show up in the count and the side panel below.
  const objectMatches = (DATA.objects || []).filter(o =>
    label(o).toLowerCase().includes(q) || o.id.toLowerCase().includes(q) || (o.kind || '').toLowerCase().includes(q)
  );
  const toExpand = jobMatches.length > SEARCH_EXPAND_CAP ? jobMatches.slice(0, SEARCH_EXPAND_CAP) : jobMatches;
  const totalMatches = jobMatches.length + objectMatches.length;
  const totalShown = toExpand.length + objectMatches.length;
  searchCount.textContent = totalMatches > totalShown
    ? `${totalMatches} (showing first ${totalShown}, refine search)`
    : String(totalMatches);
  const paths = new Set();
  for(const m of toExpand) for(const g of ancestorChain(m.id)) paths.add(g);
  expandedGroups = paths;
  buildCy({ skipFit: true });
  clearHighlightClasses();
  toExpand.forEach(m => { const ele = cy.getElementById(m.id); if(ele.length) ele.addClass('match'); });
  if(toExpand.length) fitToVisible(toExpand.map(m => m.id), 80);
  if(jobMatches.length === 1 && objectMatches.length === 0){
    showJobPanel(jobMatches[0].id);
  } else if(jobMatches.length === 0 && objectMatches.length === 1){
    showObjectPanel(objectMatches[0].id);
  } else if(jobMatches.length || objectMatches.length){
    showSearchResultsPanel(jobMatches, objectMatches);
  }
}
let searchTimer;
searchInput.addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(runSearch, 200); });

/* ---------------------------------------------------------------------
   Toolbar
   ------------------------------------------------------------------- */
function collapseAll(){ expandedGroups = new Set(); buildCy(); clearHighlightClasses(); showOverview(); }
// Expanding every box lays out every job in the report at once - fine for a
// few hundred, worth confirming for a few thousand so a slow layout is
// something the user asked for, not a surprise freeze after one click.
const EXPAND_ALL_CONFIRM_THRESHOLD = 2000;
function expandAll(){
  const jobCount = (DATA.jobs || []).length;
  if(jobCount > EXPAND_ALL_CONFIRM_THRESHOLD){
    const ok = window.confirm(`Expand all ${jobCount} jobs? This lays out the entire graph at once and may take a few seconds.`);
    if(!ok) return;
  }
  expandedGroups = new Set((DATA.groups || []).map(g => g.id));
  buildCy();
  clearHighlightClasses();
  showOverview();
}
$('fit').onclick = () => { if(cy) cy.fit(undefined, 40); };
$('zoomIn').onclick = () => zoomBy(1.35);
$('zoomOut').onclick = () => zoomBy(1 / 1.35);
$('collapseAll').onclick = collapseAll;
$('expandAll').onclick = expandAll;
$('dir').onclick = ev => { direction = direction === 'TB' ? 'LR' : 'TB'; ev.target.textContent = direction; buildCy(); };

function setStatusFilter(value){
  activeStatusFilter = value;
  $('statusFilter').value = value;
  for(const id of quickFilters) $(id).classList.remove('active');
  if(value === 'problems') $('showProblems').classList.add('active');
  else if(value === 'critical') $('showCritical').classList.add('active');
  else if(value === 'missing') $('showMissing').classList.add('active');
  else if(value === 'all') $('showAll').classList.add('active');
  buildCy();
  clearHighlightClasses();
  showOverview();
}
if(hasComparisonStatuses){
  $('statusFilter').onchange = ev => setStatusFilter(ev.target.value);
  $('showProblems').onclick = () => setStatusFilter('problems');
  $('showCritical').onclick = () => setStatusFilter('critical');
  $('showMissing').onclick = () => setStatusFilter('missing');
  $('showAll').onclick = () => setStatusFilter('all');
}
if(hasStrictnessLevels){
  $('levelFilter').onchange = ev => {
    applyStrictnessStatuses(ev.target.value);
    buildCy();
    clearHighlightClasses();
    showOverview();
  };
}
document.addEventListener('keydown', ev => {
  if(ev.key === 'Escape'){ searchInput.value = ''; searchCount.textContent = ''; collapseAll(); searchInput.blur(); }
  if(ev.key === '/' && document.activeElement !== searchInput){ ev.preventDefault(); searchInput.focus(); }
});
window.addEventListener('resize', () => { if(cy) cy.resize(); });

/* ---------------------------------------------------------------------
   Init
   ------------------------------------------------------------------- */
buildCy();
showOverview();
})();
</script>
</body>
</html>
'''
