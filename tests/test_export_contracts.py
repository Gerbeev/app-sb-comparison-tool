from __future__ import annotations

import csv
import json
from pathlib import Path

from stonebranch_graph.core import Edge, Graph, Node, make_canonical_key, make_edge_id, make_node_id
from stonebranch_graph.domain import KIND_TASK, REL_DEPENDS_ON_SUCCESS, SOURCE_STONEBRANCH
from stonebranch_graph.exporters import EDGE_CSV_FIELDS, NODE_CSV_FIELDS, export_graph_bundle, load_graph_json
from stonebranch_graph.workflows import graph_bundle_files


def _graph_with_edges(count: int) -> Graph:
    graph = Graph(source_system=SOURCE_STONEBRANCH, env="PROD")
    previous_id = ""
    for idx in range(count + 1):
        name = f"JOB_{idx}"
        node_id = make_node_id(SOURCE_STONEBRANCH, "PROD", KIND_TASK, name)
        graph.add_node(
            Node(
                id=node_id,
                canonical_key=make_canonical_key("PROD", KIND_TASK, name),
                source_system=SOURCE_STONEBRANCH,
                env="PROD",
                kind=KIND_TASK,
                name=name,
                native_kind="task",
            )
        )
        if previous_id:
            graph.add_edge(
                Edge(
                    id=make_edge_id(node_id, previous_id, REL_DEPENDS_ON_SUCCESS, "references_predecessor"),
                    source=node_id,
                    target=previous_id,
                    relation=REL_DEPENDS_ON_SUCCESS,
                    source_system=SOURCE_STONEBRANCH,
                    native_relation="references_predecessor",
                )
            )
        previous_id = node_id
    return graph


def test_graph_bundle_contract_writes_declared_files_and_roundtrips_graph_json(tmp_path: Path) -> None:
    graph = _graph_with_edges(2)
    graph.warnings.append("example warning")

    export_graph_bundle(graph, tmp_path, max_graph_edges=None)

    assert all(path.exists() for path in graph_bundle_files(tmp_path))
    loaded = load_graph_json(tmp_path / "graph.json")
    assert loaded.to_dict() == graph.to_dict()

    with (tmp_path / "objects.csv").open(newline="", encoding="utf-8") as f:
        assert csv.DictReader(f).fieldnames == NODE_CSV_FIELDS
    with (tmp_path / "edges.csv").open(newline="", encoding="utf-8") as f:
        assert csv.DictReader(f).fieldnames == EDGE_CSV_FIELDS


def test_capped_graph_views_do_not_truncate_machine_readable_sources(tmp_path: Path) -> None:
    graph = _graph_with_edges(5)

    export_graph_bundle(graph, tmp_path, max_graph_edges=2)

    graph_payload = json.loads((tmp_path / "graph.json").read_text(encoding="utf-8"))
    assert len(graph_payload["edges"]) == 5
    with (tmp_path / "edges.csv").open(newline="", encoding="utf-8") as f:
        assert len(list(csv.DictReader(f))) == 5

    assert not (tmp_path / "dependency-graph.mmd").exists()
    dot = (tmp_path / "dependency-graph.dot").read_text(encoding="utf-8")
    report = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "Mermaid `.mmd` graph exports are obsolete and disabled by default" in report
    assert "Graph view capped at 2 of 5 edges" in dot
    assert dot.count(" -> ") == 2
