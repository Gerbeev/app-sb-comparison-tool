from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .artifacts import ANALYSIS_PACK_FILE_NAMES, COMPARISON_FILE_NAMES
from .compare import compare_graphs, export_comparison
from .config import AnalyzerConfig, MappingConfig
from .core import Graph
from .exporters import export_csv_rows, export_graph_bundle, load_graph_json, write_json, write_text_file
from .graph_utils import GraphTraversalCache
from .logging_utils import log_comparison_risks, log_graph_warnings, log_info
from .domain import (
    CALENDAR_RELATIONS,
    KIND_BOX,
    KIND_TASK,
    KIND_WORKFLOW,
    REL_CONTAINS,
    REL_DEPENDS_ON,
    REL_STARTS,
    REL_USES_VARIABLE,
    RUNTIME_TARGET_RELATIONS,
)
from .rendering import escape_mmd, mmd_id


def create_analysis_pack(
    *,
    graph: Graph,
    output_dir: Path,
    pack_type: str,
    source_path: Path,
    env: str,
    include_raw_values: bool,
    deep_scan: bool = False,
    env_aware: bool = False,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    traversal = GraphTraversalCache.build(graph)

    export_graph_bundle(graph, output_dir, traversal=traversal)
    write_pack_manifest(
        graph=graph,
        output_dir=output_dir,
        pack_type=pack_type,
        source_path=source_path,
        env=env,
        include_raw_values=include_raw_values,
        deep_scan=deep_scan,
        env_aware=env_aware,
    )
    write_indexes(graph, output_dir / "indexes", traversal=traversal)
    write_graph_views(graph, output_dir / "graphs", traversal=traversal)
    write_detailed_reports(graph, output_dir / "reports", traversal=traversal)
    write_pack_readme(graph, output_dir, pack_type)


def write_pack_manifest(
    *,
    graph: Graph,
    output_dir: Path,
    pack_type: str,
    source_path: Path,
    env: str,
    include_raw_values: bool,
    deep_scan: bool,
    env_aware: bool,
) -> None:
    manifest = {
        "pack_schema_version": "1.0",
        "pack_type": pack_type,
        "source_system": graph.source_system,
        "env": env,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_path": str(source_path),
        "graph_file": "graph.json",
        "metrics_file": "metrics.json",
        "objects_file": "objects.csv",
        "edges_file": "edges.csv",
        "settings": {
            "include_raw_values": include_raw_values,
            "deep_scan": deep_scan,
            "env_aware": env_aware,
        },
        "counts": {
            "nodes": len(graph.nodes),
            "edges": len(graph.edges),
        },
        "important_files": list(ANALYSIS_PACK_FILE_NAMES),
    }
    write_json(output_dir / "pack-manifest.json", manifest)


def write_indexes(graph: Graph, index_dir: Path, *, traversal: GraphTraversalCache | None = None) -> None:
    index_dir.mkdir(parents=True, exist_ok=True)
    traversal = traversal or GraphTraversalCache.build(graph)

    nodes_by_id = {node.id: node.__dict__ for node in traversal.sorted_nodes}
    nodes_by_name: dict[str, list[str]] = defaultdict(list)
    nodes_by_kind: dict[str, list[str]] = defaultdict(list)
    nodes_by_canonical: dict[str, list[str]] = defaultdict(list)

    for node in traversal.sorted_nodes:
        nodes_by_name[node.name.lower()].append(node.id)
        nodes_by_kind[node.kind].append(node.id)
        nodes_by_canonical[node.canonical_key.lower()].append(node.id)

    edges_by_id = {edge.id: edge.__dict__ for edge in traversal.sorted_edges}
    edges_by_relation: dict[str, list[str]] = defaultdict(list)
    adjacency: dict[str, list[dict[str, Any]]] = defaultdict(list)
    reverse_adjacency: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for edge in traversal.sorted_edges:
        edges_by_relation[edge.relation].append(edge.id)
        adjacency[edge.source].append(
            {
                "edge_id": edge.id,
                "target": edge.target,
                "relation": edge.relation,
                "native_relation": edge.native_relation,
                "confidence": edge.confidence,
            }
        )
        reverse_adjacency[edge.target].append(
            {
                "edge_id": edge.id,
                "source": edge.source,
                "relation": edge.relation,
                "native_relation": edge.native_relation,
                "confidence": edge.confidence,
            }
        )

    write_json(index_dir / "node-index.json", {
        "by_id": nodes_by_id,
        "by_name": dict(sorted(nodes_by_name.items())),
        "by_kind": dict(sorted(nodes_by_kind.items())),
        "by_canonical_key": dict(sorted(nodes_by_canonical.items())),
    })
    write_json(index_dir / "edge-index.json", {
        "by_id": edges_by_id,
        "by_relation": dict(sorted(edges_by_relation.items())),
    })
    write_json(index_dir / "adjacency.json", dict(sorted(adjacency.items())))
    write_json(index_dir / "reverse-adjacency.json", dict(sorted(reverse_adjacency.items())))


def write_graph_views(graph: Graph, graph_dir: Path, *, traversal: GraphTraversalCache | None = None) -> None:
    graph_dir.mkdir(parents=True, exist_ok=True)
    traversal = traversal or GraphTraversalCache.build(graph)
    write_mermaid(graph, graph_dir / "full.mmd", traversal=traversal)
    write_mermaid(graph, graph_dir / "tasks-only.mmd", node_kinds={KIND_TASK, KIND_BOX, KIND_WORKFLOW}, traversal=traversal)
    write_mermaid(graph, graph_dir / "triggers-to-tasks.mmd", relations={REL_STARTS}, traversal=traversal)
    write_mermaid(graph, graph_dir / "dependencies-only.mmd", relation_prefixes=(REL_DEPENDS_ON,), relations={REL_CONTAINS}, traversal=traversal)
    write_mermaid(graph, graph_dir / "runtime.mmd", relations=RUNTIME_TARGET_RELATIONS, traversal=traversal)
    write_mermaid(graph, graph_dir / "calendars.mmd", relations=CALENDAR_RELATIONS, traversal=traversal)
    write_mermaid(graph, graph_dir / "variables.mmd", relations={REL_USES_VARIABLE}, traversal=traversal)


def write_mermaid(
    graph: Graph,
    path: Path,
    *,
    node_kinds: set[str] | None = None,
    relations: set[str] | None = None,
    relation_prefixes: tuple[str, ...] = (),
    max_edges: int = 800,
    traversal: GraphTraversalCache | None = None,
) -> None:
    traversal = traversal or GraphTraversalCache.build(graph)
    selected_edges = []
    for edge in traversal.sorted_edges:
        if relations is not None and edge.relation not in relations:
            if not any(edge.relation.startswith(prefix) for prefix in relation_prefixes):
                continue
        source = graph.nodes.get(edge.source)
        target = graph.nodes.get(edge.target)
        if not source or not target:
            continue
        if node_kinds is not None and source.kind not in node_kinds and target.kind not in node_kinds:
            continue
        selected_edges.append(edge)

    capped = len(selected_edges) > max_edges
    selected_edges = selected_edges[:max_edges]

    node_ids = {edge.source for edge in selected_edges} | {edge.target for edge in selected_edges}
    if not selected_edges and node_kinds:
        node_ids = {node.id for node in traversal.sorted_nodes if node.kind in node_kinds}

    lines = ["flowchart LR"]
    if capped:
        lines.append(f'  note["Graph capped at {max_edges} edges. Use graph.json/indexes for full analysis."]')

    for node_id in sorted(node_ids):
        node = graph.nodes.get(node_id)
        if not node:
            continue
        label = f"{node.kind}: {node.name}"
        lines.append(f'  {mmd_id(node.id)}["{escape_mmd(label)}"]')

    for edge in selected_edges:
        lines.append(f"  {mmd_id(edge.source)} -->|{escape_mmd(edge.relation)}| {mmd_id(edge.target)}")

    write_text_file(path, "\n".join(lines) + "\n")


def write_detailed_reports(graph: Graph, reports_dir: Path, *, traversal: GraphTraversalCache | None = None) -> None:
    reports_dir.mkdir(parents=True, exist_ok=True)
    traversal = traversal or GraphTraversalCache.build(graph)
    inbound = traversal.inbound
    outbound = traversal.outbound

    top_connected = sorted(
        traversal.sorted_nodes,
        key=lambda n: inbound.get(n.id, 0) + outbound.get(n.id, 0),
        reverse=True,
    )[:100]

    lines = [
        "# Top connected objects",
        "",
        "| Kind | Object | In | Out | Total | Source |",
        "|---|---|---:|---:|---:|---|",
    ]
    for node in top_connected:
        inc = inbound.get(node.id, 0)
        out = outbound.get(node.id, 0)
        lines.append(f"| {node.kind} | `{node.name}` | {inc} | {out} | {inc + out} | `{node.source_file}` |")
    write_text_file(reports_dir / "top-connected.md", "\n".join(lines) + "\n")

    orphan_nodes = [
        node for node in traversal.sorted_nodes
        if inbound.get(node.id, 0) == 0 and outbound.get(node.id, 0) == 0
    ]
    lines = [
        "# Orphan objects",
        "",
        "Objects below have no detected inbound or outbound dependencies.",
        "",
        "| Kind | Object | Source | Synthetic |",
        "|---|---|---|---|",
    ]
    for node in sorted(orphan_nodes, key=lambda n: (n.kind, n.name))[:1000]:
        lines.append(
            f"| {node.kind} | `{node.name}` | `{node.source_file}` | {bool(node.metadata.get('synthetic'))} |"
        )
    write_text_file(reports_dir / "orphans.md", "\n".join(lines) + "\n")

    relation_rows = (
        {"relation": relation, "count": count}
        for relation, count in sorted(traversal.relation_counts.items(), key=lambda item: (-item[1], item[0]))
    )
    export_csv_rows(reports_dir / "relation-summary.csv", ["relation", "count"], relation_rows)

    kind_rows = (
        {"kind": kind, "count": count}
        for kind, count in sorted(traversal.kind_counts.items(), key=lambda item: (-item[1], item[0]))
    )
    export_csv_rows(reports_dir / "object-summary.csv", ["kind", "count"], kind_rows)


def write_pack_readme(graph: Graph, output_dir: Path, pack_type: str) -> None:
    text = f"""# {pack_type} analysis pack

This folder is a self-contained analysis pack for `{graph.source_system}`.

## Start here

1. `report.md` - human-readable summary.
2. `graph.json` - full machine-readable graph.
3. `metrics.json` - graph metrics.
4. `indexes/node-index.json` - lookup by id, name, kind, canonical key.
5. `indexes/adjacency.json` - outgoing dependency index.
6. `indexes/reverse-adjacency.json` - incoming dependency index.
7. `graphs/*.mmd` - Mermaid graph views.
8. `reports/top-connected.md` - most connected objects.
9. `reports/orphans.md` - isolated objects.

## Important note

`graph.json` is the source of truth. Indexes and graph views are generated from it and can be regenerated.
"""
    write_text_file(output_dir / "README.md", text)


def compare_analysis_packs(
    *,
    stonebranch_pack: Path,
    jil_pack: Path,
    output_dir: Path,
    config: AnalyzerConfig,
    mapping_path: Path | None = None,
) -> None:
    sb_graph_path = stonebranch_pack / "graph.json"
    jil_graph_path = jil_pack / "graph.json"
    if not sb_graph_path.exists():
        raise FileNotFoundError(f"Stonebranch pack graph.json not found: {sb_graph_path}")
    if not jil_graph_path.exists():
        raise FileNotFoundError(f"JIL pack graph.json not found: {jil_graph_path}")

    sb_graph = load_graph_json(sb_graph_path)
    jil_graph = load_graph_json(jil_graph_path)
    mapping = MappingConfig.from_file(mapping_path, config)

    comparison = compare_graphs(sb_graph, jil_graph, mapping, config)
    export_comparison(comparison, output_dir, sb_graph, jil_graph)
    log_graph_warnings(output_dir, sb_graph.warnings, source="stonebranch pack")
    log_graph_warnings(output_dir, jil_graph.warnings, source="jil pack")
    log_comparison_risks(output_dir, comparison.risks)
    log_info(output_dir, f"Compared analysis packs: matched_nodes={comparison.summary['matched_nodes']} matched_edges={comparison.summary['matched_edges']}")

    write_compare_pack_manifest(output_dir, stonebranch_pack, jil_pack, comparison.summary)


def write_compare_pack_manifest(output_dir: Path, stonebranch_pack: Path, jil_pack: Path, summary: dict[str, Any]) -> None:
    manifest = {
        "pack_schema_version": "1.0",
        "pack_type": "comparison-analysis-pack",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "stonebranch_pack": str(stonebranch_pack),
        "jil_pack": str(jil_pack),
        "summary": summary,
        "important_files": list(COMPARISON_FILE_NAMES),
    }
    write_json(output_dir / "compare-pack-manifest.json", manifest)
