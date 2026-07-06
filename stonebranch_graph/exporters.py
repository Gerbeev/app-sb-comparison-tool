from __future__ import annotations

import csv
import json
from pathlib import Path
from collections.abc import Iterable, Sequence
from typing import Any

from .config import AnalyzerConfig
from .core import (
    Edge,
    Graph,
    Node,
    comparison_kind,
    comparison_name,
    normalize_name,
    strip_migration_suffixes,
)
from .graph_utils import GraphTraversalCache
from .domain import (
    ARTIFACT_NODE_KINDS,
    INFRASTRUCTURE_KINDS,
    JOB_LIKE_KINDS,
    KIND_BOX,
    KIND_OBJECT,
    KIND_TASK,
    KIND_WORKFLOW,
    REL_CONTAINS,
    REL_DEPENDS_ON_SUCCESS,
    REL_SUCCESSOR_OF,
    SOURCE_AUTOSYS_JIL,
    SOURCE_AUTOSYS_JIL_ALIAS,
    SOURCE_STONEBRANCH,
    SYSTEM_SPECIFIC_KINDS,
)
from .metrics import GraphMetrics, compute_graph_metrics, metric_rows, metrics_to_dict
from .rendering import escape_dot

TOP_LEVEL_GRAPH_MAX_EDGES = 800

NODE_CSV_FIELDS = [
    "id",
    "canonical_key",
    "source_system",
    "env",
    "kind",
    "native_kind",
    "name",
    "source_file",
    "attributes_hash",
]

EDGE_CSV_FIELDS = [
    "id",
    "source",
    "target",
    "relation",
    "source_system",
    "native_relation",
    "evidence_file",
    "evidence_path",
    "evidence_key",
    "evidence_value",
    "confidence",
]

METRICS_CSV_FIELDS = ["metric", "value"]

CONTAINER_CSV_FIELDS = [
    "container_key",
    "container_kind",
    "container_name",
    "child_count",
    "task_count",
    "nested_container_count",
    "child_keys",
    "source_file",
]

CONTAINER_KINDS = {KIND_WORKFLOW, KIND_BOX}


def export_graph_bundle(
    graph: Graph,
    output_dir: Path,
    *,
    max_graph_edges: int | None = TOP_LEVEL_GRAPH_MAX_EDGES,
    traversal: GraphTraversalCache | None = None,
    config: AnalyzerConfig | None = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    traversal = traversal or GraphTraversalCache.build(graph)
    graph_metrics = compute_graph_metrics(graph, traversal=traversal)
    write_json(output_dir / "graph.json", graph.to_dict())
    export_canonical_graph_json(graph, output_dir / "canonical-graph.json", traversal=traversal)
    from .html_graph import export_cytoscape_html_report
    export_cytoscape_html_report(graph, output_dir, traversal=traversal)
    export_containers_json(graph, output_dir / "containers.json", traversal=traversal)
    export_containers_csv(graph, output_dir / "containers.csv", traversal=traversal)
    export_nodes_csv(graph, output_dir / "objects.csv", traversal=traversal)
    export_edges_csv(graph, output_dir / "edges.csv", traversal=traversal)
    export_dot(graph, output_dir / "dependency-graph.dot", max_edges=max_graph_edges, traversal=traversal)
    suffix_patterns = (config or AnalyzerConfig.default()).suffix_strips
    export_reconciliation_keys(
        graph,
        output_dir / reconciliation_keys_filename(graph.source_system),
        patterns=suffix_patterns,
        traversal=traversal,
    )
    metrics_payload = metrics_to_dict(graph_metrics)
    write_json(output_dir / "metrics.json", metrics_payload)
    export_csv_rows(output_dir / "metrics.csv", METRICS_CSV_FIELDS, metric_rows(metrics_payload))
    export_report(
        graph,
        output_dir / "report.md",
        graph_metrics=graph_metrics,
        graph_view_max_edges=max_graph_edges,
        traversal=traversal,
    )


def write_text_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, payload: Any) -> None:
    write_text_file(path, json.dumps(payload, indent=2, ensure_ascii=False))


def load_graph_json(path: Path) -> Graph:
    return Graph.from_dict(json.loads(path.read_text(encoding="utf-8")))




def write_canonical_json(path: Path, payload: Any) -> None:
    """Write JSON in a deterministic form intended for diff tools."""

    write_text_file(path, json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n")


# --- Reconciliation key-list export (autosys.keys.json / stonebranch.keys.json) ----
#
# A lightweight, per-system, diff-tool-friendly export of "which objects exist"
# emitted alongside every graph build. Deliberately independent of any
# cross-system mapping.json: it only applies the built-in migration-noise
# suffix stripping and kind collapsing, so two systems built without any
# mapping file still produce byte-identical lines for the same logical object.

RECONCILIATION_KEYS_FILENAME_BY_SOURCE = {
    SOURCE_STONEBRANCH: "stonebranch",
    SOURCE_AUTOSYS_JIL: "autosys",
    SOURCE_AUTOSYS_JIL_ALIAS: "autosys",
}


def reconciliation_keys_filename(source_system: str) -> str:
    prefix = RECONCILIATION_KEYS_FILENAME_BY_SOURCE.get(source_system, source_system)
    return f"{prefix}.keys.json"


def _in_reconciliation_scope(node: Node) -> bool:
    """Return whether `node` should appear in the reconciliation key list.

    Mirrors `compare.node_comparison_category`'s scoping rules (job-like
    definitions plus infrastructure, excluding artifact/system-specific kinds
    and reference-only synthetic placeholders) as a small boolean predicate.
    Duplicated here (rather than imported) because `compare.py` imports this
    module already; keep the two in sync if comparison scoping rules change.
    """
    if node.kind in ARTIFACT_NODE_KINDS or node.metadata.get("artifact"):
        return False
    if node.kind in SYSTEM_SPECIFIC_KINDS:
        return False
    synthetic = bool(node.metadata.get("synthetic"))
    if node.kind in JOB_LIKE_KINDS:
        return not synthetic
    if node.kind in INFRASTRUCTURE_KINDS:
        return True
    if node.kind == KIND_OBJECT and synthetic:
        return False
    return not synthetic


def reconciliation_id(node: Node, patterns: Sequence[str] | None = None) -> str:
    """Return the diff-friendly reconciliation ID for a single node.

    `env` is only included when the graph actually mixes more than one env
    label (see `build_reconciliation_ids`); this function always includes it
    and the caller strips the prefix for the common single-env case, keeping
    this function pure/stateless and testable in isolation.
    """
    kind = comparison_kind(node.kind)
    name = normalize_name(strip_migration_suffixes(comparison_name(node.name), patterns))
    return f"{node.env}:{kind}:{name}"


def build_reconciliation_ids(
    graph: Graph,
    patterns: Sequence[str] | None = None,
    *,
    traversal: GraphTraversalCache | None = None,
) -> list[str]:
    """Project in-scope graph nodes to sorted, deduped reconciliation IDs.

    In scope: job-like objects (tasks/boxes/workflows/file watchers) plus
    infrastructure (agents, calendars, variables, files); excluded: artifact
    nodes (command-hash helpers), Stonebranch-only system-specific kinds
    (triggers/credentials/connections/scripts/email templates), and
    reference-only synthetic placeholders with no real definition.

    `env` is dropped from the id (`kind:name` instead of `env:kind:name`)
    unless the graph mixes more than one env label, so the common single-env
    export doesn't diff on a redundant label.
    """
    traversal = traversal or GraphTraversalCache.build(graph)
    in_scope = [node for node in traversal.sorted_nodes if _in_reconciliation_scope(node)]
    envs = {node.env for node in in_scope}
    include_env = len(envs) > 1
    ids = set()
    for node in in_scope:
        full_id = reconciliation_id(node, patterns)
        ids.add(full_id if include_env else full_id.split(":", 1)[1])
    return sorted(ids)


def export_reconciliation_keys(
    graph: Graph,
    path: Path,
    *,
    patterns: Sequence[str] | None = None,
    traversal: GraphTraversalCache | None = None,
) -> None:
    """Write the flat, sorted JSON array of reconciliation ID strings.

    The primary reconciliation artifact: one array of plain strings, nothing
    else (no kind wrapper objects, no metadata, no source_file, no hashes),
    so the same logical object on both systems produces a byte-identical
    line for a plain text/Notepad++ diff.
    """
    write_canonical_json(path, build_reconciliation_ids(graph, patterns, traversal=traversal))


def canonical_kind(kind: str) -> str:
    """Return the kind used in canonical diff/export views.

    Stonebranch workflows and AutoSys boxes are the same logical container layer
    for migration review, but the original kind is still preserved separately.
    """

    if kind == KIND_WORKFLOW:
        return KIND_BOX
    return kind


def canonical_node_key(node: Node) -> str:
    if node.kind in CONTAINER_KINDS:
        return container_group_key(node.canonical_key, node.kind)
    return node.canonical_key


def stable_value(value: Any) -> Any:
    """Return a recursively sorted JSON-compatible value."""

    if isinstance(value, dict):
        return {str(key): stable_value(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, list):
        return [stable_value(item) for item in value]
    if isinstance(value, tuple):
        return [stable_value(item) for item in value]
    if isinstance(value, set):
        return sorted(stable_value(item) for item in value)
    return value


def canonical_edge_components(edge: Edge, graph: Graph) -> tuple[Node, str, Node] | None:
    """Return source/relation/target normalized for diff-friendly exports."""

    source = graph.nodes.get(edge.source)
    target = graph.nodes.get(edge.target)
    if not source or not target:
        return None

    relation = edge.relation
    if relation == REL_SUCCESSOR_OF:
        return target, REL_DEPENDS_ON_SUCCESS, source

    if relation == REL_CONTAINS and source.kind not in CONTAINER_KINDS and target.kind in CONTAINER_KINDS:
        return target, relation, source

    return source, relation, target


def build_canonical_graph_view(graph: Graph, *, traversal: GraphTraversalCache | None = None) -> dict[str, Any]:
    """Build a deterministic, diff-friendly graph projection.

    `graph.json` remains the complete source-of-truth payload. This view is
    designed for comparing Stonebranch and AutoSys exports in a regular diff
    tool, so it uses comparison-oriented keys, stable sorting, and no timestamps.
    """

    traversal = traversal or GraphTraversalCache.build(graph)
    container_view = build_container_view(graph, traversal=traversal)

    nodes: list[dict[str, Any]] = []
    for node in traversal.sorted_nodes:
        nodes.append(
            {
                "key": canonical_node_key(node),
                "kind": canonical_kind(node.kind),
                "original_kind": node.kind,
                "name": node.name,
                "source_system": node.source_system,
                "source_file": node.source_file,
                "attributes_hash": node.attributes_hash,
                "synthetic": bool(node.metadata.get("synthetic")),
                "metadata": stable_value(node.metadata),
            }
        )

    edges: list[dict[str, Any]] = []
    broken_edges: list[dict[str, Any]] = []
    for edge in traversal.sorted_edges:
        components = canonical_edge_components(edge, graph)
        if components is None:
            broken_edges.append(
                {
                    "edge_id": edge.id,
                    "source": edge.source,
                    "relation": edge.relation,
                    "target": edge.target,
                    "native_relation": edge.native_relation,
                    "evidence_file": edge.evidence_file,
                }
            )
            continue
        source, relation, target = components
        edges.append(
            {
                "source": canonical_node_key(source),
                "relation": relation,
                "target": canonical_node_key(target),
                "source_kind": canonical_kind(source.kind),
                "target_kind": canonical_kind(target.kind),
                "source_original_kind": source.kind,
                "target_original_kind": target.kind,
                "native_relation": edge.native_relation,
                "evidence_file": edge.evidence_file,
                "evidence_key": edge.evidence_key,
                "confidence": edge.confidence,
            }
        )

    nodes = sorted(nodes, key=lambda item: (item["key"], item["original_kind"], item["name"], item["source_file"]))
    edges = sorted(
        edges,
        key=lambda item: (
            item["source"],
            item["relation"],
            item["target"],
            item["native_relation"],
            item["evidence_file"],
            item["evidence_key"],
        ),
    )
    broken_edges = sorted(broken_edges, key=lambda item: (item["source"], item["relation"], item["target"], item["edge_id"]))

    return {
        "schema_version": "1.0",
        "source_system": graph.source_system,
        "env": graph.env,
        "summary": {
            "nodes": len(nodes),
            "edges": len(edges),
            "containers": len(container_view["containers"]),
            "ungrouped_tasks": len(container_view["ungrouped_tasks"]),
            "warnings": len(graph.warnings),
        },
        "containers": container_view["containers"],
        "ungrouped_tasks": container_view["ungrouped_tasks"],
        "nodes": nodes,
        "edges": edges,
        "broken_edges": broken_edges,
        "warnings": sorted(str(warning) for warning in graph.warnings),
    }


def export_canonical_graph_json(graph: Graph, path: Path, *, traversal: GraphTraversalCache | None = None) -> None:
    write_canonical_json(path, build_canonical_graph_view(graph, traversal=traversal))


def container_group_key(canonical_key: str, kind: str) -> str:
    """Return a container-comparison key for workflow/box-like groups.

    Stonebranch workflows and AutoSys boxes represent the same logical container
    layer. The raw graph preserves each native kind, while container-oriented
    exports use a box-like key so diff tools can compare the group structure.
    """

    if kind not in CONTAINER_KINDS:
        return canonical_key
    env, _, name = canonical_key.partition(":")
    if not name:
        return canonical_key
    _kind, _, real_name = name.partition(":")
    if not real_name:
        return canonical_key
    return f"{env}:{KIND_BOX}:{real_name}"


def build_container_view(graph: Graph, *, traversal: GraphTraversalCache | None = None) -> dict[str, Any]:
    """Build a deterministic workflow/box -> children view of the graph.

    This is the human/diff-friendly container model used before Cytoscape HTML:
    workflows/boxes are groups, tasks/jobs and nested workflows/boxes are
    children, and dependencies remain edges outside this container view.
    """

    traversal = traversal or GraphTraversalCache.build(graph)
    container_nodes = [node for node in traversal.sorted_nodes if node.kind in CONTAINER_KINDS]
    container_ids = {node.id for node in container_nodes}
    contained_child_ids: set[str] = set()
    children_by_container: dict[str, list[dict[str, Any]]] = {node.id: [] for node in container_nodes}

    for edge in traversal.sorted_edges:
        if edge.relation != REL_CONTAINS or edge.source not in container_ids:
            continue
        child = graph.nodes.get(edge.target)
        if not child:
            continue
        contained_child_ids.add(child.id)
        children_by_container[edge.source].append(
            {
                "id": child.id,
                "key": child.canonical_key,
                "group_key": container_group_key(child.canonical_key, child.kind),
                "kind": child.kind,
                "name": child.name,
                "source_file": child.source_file,
                "edge_id": edge.id,
                "synthetic": bool(child.metadata.get("synthetic")),
            }
        )

    containers: list[dict[str, Any]] = []
    for node in container_nodes:
        children = sorted(children_by_container[node.id], key=lambda child: (child["group_key"], child["kind"], child["name"]))
        task_count = sum(1 for child in children if child["kind"] == KIND_TASK)
        nested_container_count = sum(1 for child in children if child["kind"] in CONTAINER_KINDS)
        containers.append(
            {
                "id": node.id,
                "key": node.canonical_key,
                "group_key": container_group_key(node.canonical_key, node.kind),
                "kind": node.kind,
                "name": node.name,
                "source_file": node.source_file,
                "synthetic": bool(node.metadata.get("synthetic")),
                "child_count": len(children),
                "task_count": task_count,
                "nested_container_count": nested_container_count,
                "children": children,
            }
        )

    ungrouped_tasks = [
        {
            "id": node.id,
            "key": node.canonical_key,
            "kind": node.kind,
            "name": node.name,
            "source_file": node.source_file,
            "synthetic": bool(node.metadata.get("synthetic")),
        }
        for node in traversal.sorted_nodes
        if node.kind == KIND_TASK and node.id not in contained_child_ids
    ]

    return {
        "schema_version": "1.0",
        "source_system": graph.source_system,
        "env": graph.env,
        "summary": {
            "containers": len(containers),
            "contained_children": sum(container["child_count"] for container in containers),
            "ungrouped_tasks": len(ungrouped_tasks),
        },
        "containers": sorted(containers, key=lambda container: (container["group_key"], container["kind"], container["name"])),
        "ungrouped_tasks": sorted(ungrouped_tasks, key=lambda task: (task["key"], task["name"])),
    }


def export_containers_json(graph: Graph, path: Path, *, traversal: GraphTraversalCache | None = None) -> None:
    write_json(path, build_container_view(graph, traversal=traversal))


def export_containers_csv(graph: Graph, path: Path, *, traversal: GraphTraversalCache | None = None) -> None:
    view = build_container_view(graph, traversal=traversal)
    rows = []
    for container in view["containers"]:
        rows.append(
            {
                "container_key": container["group_key"],
                "container_kind": container["kind"],
                "container_name": container["name"],
                "child_count": container["child_count"],
                "task_count": container["task_count"],
                "nested_container_count": container["nested_container_count"],
                "child_keys": ";".join(child["group_key"] for child in container["children"]),
                "source_file": container["source_file"],
            }
        )
    export_csv_rows(path, CONTAINER_CSV_FIELDS, rows)


def export_nodes_csv(graph: Graph, path: Path, *, traversal: GraphTraversalCache | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=NODE_CSV_FIELDS)
        writer.writeheader()
        traversal = traversal or GraphTraversalCache.build(graph)
        for node in traversal.sorted_nodes:
            writer.writerow(
                {
                    "id": node.id,
                    "canonical_key": node.canonical_key,
                    "source_system": node.source_system,
                    "env": node.env,
                    "kind": node.kind,
                    "native_kind": node.native_kind,
                    "name": node.name,
                    "source_file": node.source_file,
                    "attributes_hash": node.attributes_hash,
                }
            )


def export_edges_csv(graph: Graph, path: Path, *, traversal: GraphTraversalCache | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=EDGE_CSV_FIELDS)
        writer.writeheader()
        traversal = traversal or GraphTraversalCache.build(graph)
        for edge in traversal.sorted_edges:
            writer.writerow(edge.__dict__)


def export_dot(
    graph: Graph,
    path: Path,
    *,
    max_edges: int | None = TOP_LEVEL_GRAPH_MAX_EDGES,
    traversal: GraphTraversalCache | None = None,
) -> None:
    traversal = traversal or GraphTraversalCache.build(graph)
    matching_edges = traversal.sorted_edges
    capped = max_edges is not None and len(matching_edges) > max_edges
    visible_edges = matching_edges[:max_edges] if capped else matching_edges
    visible_node_ids = {edge.source for edge in visible_edges} | {edge.target for edge in visible_edges}
    if not visible_edges:
        visible_node_ids = set(graph.nodes)

    lines = []
    if capped:
        lines.append(f"// Graph view capped at {max_edges} of {len(matching_edges)} edges. Use graph.json or edges.csv for the full dependency graph.")
    lines.extend(["digraph dependencies {", "  rankdir=LR;"])
    if capped:
        note = f"Graph view capped at {max_edges} of {len(matching_edges)} edges. Use graph.json or edges.csv for the full graph."
        lines.append(f'  "__export_note" [label="{escape_dot(note)}", shape=note];')
    for node in (node for node in traversal.sorted_nodes if node.id in visible_node_ids):
        label = f"{node.source_system}/{node.env}/{node.kind}: {node.name}"
        lines.append(f'  "{escape_dot(node.id)}" [label="{escape_dot(label)}"];')
    for edge in visible_edges:
        lines.append(
            f'  "{escape_dot(edge.source)}" -> "{escape_dot(edge.target)}" '
            f'[label="{escape_dot(edge.relation)}"];'
        )
    lines.append("}")
    write_text_file(path, "\n".join(lines) + "\n")


def export_report(
    graph: Graph,
    path: Path,
    *,
    graph_metrics: GraphMetrics | None = None,
    graph_view_max_edges: int | None = TOP_LEVEL_GRAPH_MAX_EDGES,
    traversal: GraphTraversalCache | None = None,
) -> None:
    traversal = traversal or GraphTraversalCache.build(graph)
    graph_metrics = graph_metrics or compute_graph_metrics(graph, traversal=traversal)
    lines: list[str] = []
    append_report_summary(lines, graph)
    append_quality_metrics(lines, graph_metrics)
    append_capped_graph_note(lines, graph, graph_view_max_edges)
    append_count_table(lines, title="Object types", first_column="Kind", counts=traversal.kind_counts)
    append_count_table(lines, title="Relation types", first_column="Relation", counts=traversal.relation_counts)
    append_warnings(lines, graph.warnings)
    append_most_connected(lines, traversal)
    write_text_file(path, "\n".join(lines) + "\n")


def append_report_summary(lines: list[str], graph: Graph) -> None:
    lines.extend(
        [
            f"# {graph.source_system} dependency graph report",
            "",
            "## Summary",
            "",
            f"- Env: **{graph.env}**",
            f"- Objects: **{len(graph.nodes)}**",
            f"- Dependencies: **{len(graph.edges)}**",
        ]
    )


def append_quality_metrics(lines: list[str], graph_metrics: GraphMetrics) -> None:
    lines.extend(
        [
            "",
            "## Quality metrics",
            "",
            f"- Synthetic nodes: **{graph_metrics.synthetic_nodes}**",
            f"- Low-confidence edges: **{graph_metrics.low_confidence_edges}**",
            f"- Orphan nodes: **{graph_metrics.orphan_nodes}**",
            f"- Orphan tasks: **{graph_metrics.orphan_tasks}**",
            f"- Tasks without inbound dependency: **{graph_metrics.tasks_without_inbound_dependency}**",
            f"- Tasks without outbound dependency: **{graph_metrics.tasks_without_outbound_dependency}**",
            f"- Tasks without trigger: **{graph_metrics.tasks_without_trigger}**",
            f"- Condition nodes: **{graph_metrics.condition_nodes}**",
            f"- Conditions not parsed: **{graph_metrics.conditions_not_parsed}**",
        ]
    )


def append_capped_graph_note(lines: list[str], graph: Graph, graph_view_max_edges: int | None) -> None:
    lines.extend(
        [
            "",
            "## Graph views",
            "",
            "- Mermaid `.mmd` graph exports have been fully decommissioned.",
            "- Use `graph.html` for the offline Cytoscape HTML graph report. Use `canonical-graph.json`, `containers.json`, `objects.csv`, and `edges.csv` for deterministic graph review.",
        ]
    )
    if graph_view_max_edges is None or len(graph.edges) <= graph_view_max_edges:
        return
    lines.append(
        f"- `dependency-graph.dot` is capped at **{graph_view_max_edges}** of **{len(graph.edges)}** edges. "
        "Use `graph.json` or `edges.csv` for the full dependency graph."
    )


def append_count_table(lines: list[str], *, title: str, first_column: str, counts: dict[str, int]) -> None:
    lines.extend(["", f"## {title}", "", f"| {first_column} | Count |", "|---|---:|"])
    for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"| {name} | {count} |")


def append_warnings(lines: list[str], warnings: list[str]) -> None:
    if not warnings:
        return
    lines.extend(["", "## Warnings", ""])
    lines.extend(f"- {warning}" for warning in warnings)


def append_most_connected(lines: list[str], traversal: GraphTraversalCache) -> None:
    most_connected = sorted(
        traversal.sorted_nodes,
        key=lambda node: traversal.inbound.get(node.id, 0) + traversal.outbound.get(node.id, 0),
        reverse=True,
    )[:50]
    lines.extend(
        [
            "",
            "## Most connected objects",
            "",
            "| Kind | Object | In | Out | Total |",
            "|---|---|---:|---:|---:|",
        ]
    )
    for node in most_connected:
        inbound_count = traversal.inbound.get(node.id, 0)
        outbound_count = traversal.outbound.get(node.id, 0)
        lines.append(f"| {node.kind} | `{node.name}` | {inbound_count} | {outbound_count} | {inbound_count + outbound_count} |")


def export_csv_rows(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
