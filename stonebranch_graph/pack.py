from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .compare import compare_graphs, export_comparison
from .config import AnalyzerConfig, MappingConfig
from .core import Graph
from .exporters import (
    export_csv_rows,
    export_graph_bundle,
    load_graph_json,
    reconciliation_keys_filename,
    write_json,
    write_text_file,
)
from .graph_utils import GraphTraversalCache
from .logging_utils import log_comparison_risks, log_graph_warnings, log_info


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
    config: AnalyzerConfig | None = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    traversal = GraphTraversalCache.build(graph)

    export_graph_bundle(graph, output_dir, traversal=traversal, config=config)
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
    write_detailed_reports(graph, output_dir / "reports", output_dir / "csv", traversal=traversal)
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
        "graph_file": "json/graph.json",
        "metrics_file": "json/metrics.json",
        "objects_file": "csv/objects.csv",
        "edges_file": "csv/edges.csv",
        "ids_file": f"ids/{reconciliation_keys_filename(graph.source_system)}",
        "deprecated_outputs": {
            "reports": {
                "status": "obsolete",
                "note": "The reports/ folder and nested report files are kept for now and are scheduled for decommissioning.",
            }
        },
        "settings": {
            "include_raw_values": include_raw_values,
            "deep_scan": deep_scan,
            "env_aware": env_aware,
        },
        "counts": {
            "nodes": len(graph.nodes),
            "edges": len(graph.edges),
        },
        "important_files": [
            "README.md",
            "report.md",
            "json/pack-manifest.json",
            "json/graph.json",
            "json/canonical-graph.json",
            f"ids/{reconciliation_keys_filename(graph.source_system)}",
            "graph.html",
            "graph-data.js",
            "cytoscape.min.js",
            "json/containers.json",
            "csv/containers.csv",
            "json/metrics.json",
            "csv/metrics.csv",
            "csv/objects.csv",
            "csv/edges.csv",
            "json/graph-data.json",
            "indexes/node-index.json",
            "indexes/adjacency.json",
            "reports/top-connected.md",
            "reports/orphans.md",
        ],
    }
    write_json(output_dir / "json" / "pack-manifest.json", manifest)


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


def write_detailed_reports(
    graph: Graph,
    reports_dir: Path,
    csv_dir: Path,
    *,
    traversal: GraphTraversalCache | None = None,
) -> None:
    reports_dir.mkdir(parents=True, exist_ok=True)
    csv_dir.mkdir(parents=True, exist_ok=True)
    traversal = traversal or GraphTraversalCache.build(graph)
    inbound = traversal.inbound
    outbound = traversal.outbound

    write_text_file(
        reports_dir / "README.md",
        "# Obsolete Reports Folder\n\n"
        "This folder is obsolete and scheduled for decommissioning. Prefer the pack-level `report.md`, `json/`, `csv/`, `ids/`, and `indexes/` outputs.\n",
    )

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
    export_csv_rows(csv_dir / "relation-summary.csv", ["relation", "count"], relation_rows)

    kind_rows = (
        {"kind": kind, "count": count}
        for kind, count in sorted(traversal.kind_counts.items(), key=lambda item: (-item[1], item[0]))
    )
    export_csv_rows(csv_dir / "object-summary.csv", ["kind", "count"], kind_rows)


def write_pack_readme(graph: Graph, output_dir: Path, pack_type: str) -> None:
    text = f"""# {pack_type} analysis pack

This folder is a self-contained analysis pack for `{graph.source_system}`.

## Start here

1. `report.md` - human-readable summary.
2. `json/pack-manifest.json` - machine-readable pack manifest.
3. `json/graph.json` - full machine-readable source-of-truth graph.
4. `json/canonical-graph.json` - deterministic diff-friendly graph projection.
5. `json/containers.json` - workflow/box group view with contained tasks/jobs.
6. `csv/containers.csv` - tabular workflow/box group membership for Excel/diff checks.
7. `json/metrics.json` - graph metrics.
8. `indexes/node-index.json` - lookup by id, name, kind, canonical key.
9. `indexes/adjacency.json` - outgoing dependency index.
10. `indexes/reverse-adjacency.json` - incoming dependency index.
11. `ids/{reconciliation_keys_filename(graph.source_system)}` - diff-ready reconciliation ids.
12. `graph.html` - offline interactive source graph report.
13. `graph-data.js` - deterministic data payload used by `graph.html`.
14. `cytoscape.min.js` - local runtime used by the HTML graph.
15. `reports/top-connected.md` - obsolete nested report, kept temporarily.
16. `reports/orphans.md` - obsolete nested report, kept temporarily.
17. `csv/object-summary.csv` and `csv/relation-summary.csv` - tabular summaries.

## Important note

`json/graph.json` is the source of truth. `json/canonical-graph.json` is sorted and stable for diff tools. `json/containers.json` is the container/group projection used to review workflow/box membership. `graph.html` is the offline interactive graph report generated from `graph-data.js` and the bundled `cytoscape.min.js` runtime. Indexes are generated from the graph and can be regenerated. The `reports/` folder is obsolete and kept only for transition.
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
    sb_graph_path = _pack_graph_path(stonebranch_pack)
    jil_graph_path = _pack_graph_path(jil_pack)
    if not sb_graph_path.exists():
        raise FileNotFoundError(f"Stonebranch pack json/graph.json not found: {sb_graph_path}")
    if not jil_graph_path.exists():
        raise FileNotFoundError(f"JIL pack json/graph.json not found: {jil_graph_path}")

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


def _pack_graph_path(pack_dir: Path) -> Path:
    current = pack_dir / "json" / "graph.json"
    if current.exists():
        return current
    return pack_dir / "graph.json"


def write_compare_pack_manifest(output_dir: Path, stonebranch_pack: Path, jil_pack: Path, summary: dict[str, Any]) -> None:
    manifest = {
        "pack_schema_version": "1.0",
        "pack_type": "comparison-analysis-pack",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "stonebranch_pack": str(stonebranch_pack),
        "jil_pack": str(jil_pack),
        "summary": summary,
        "important_files": [
            "json/compare-pack-manifest.json",
            "compare/report.md",
            "compare/json/comparison.json",
            "compare/json/metrics.json",
            "compare/csv/metrics.csv",
            "compare/csv/edge-diff.csv",
            "compare/csv/command-diff.csv",
            "compare/compare-graph.html",
            "compare/compare-graph-data.js",
            "compare/cytoscape.min.js",
            "compare/json/compare-graph-data.json",
            "compare/csv/missing-in-stonebranch.csv",
            "compare/csv/missing-in-jil.csv",
            "compare/csv/collisions.csv",
            "compare/csv/mapping-diagnostics.csv",
            "compare/json/diff-index.json",
            "compare/json/critical-diff.json",
            "compare/json/remediation-summary.json",
            "compare/remediation-plan.md",
            "compare/json/reconciliation.json",
        ],
    }
    write_json(output_dir / "json" / "compare-pack-manifest.json", manifest)
