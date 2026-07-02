from __future__ import annotations

import csv
import json
from pathlib import Path

from stonebranch_graph.config import AnalyzerConfig
from stonebranch_graph.domain import KIND_TASK, REL_DEPENDS_ON_FAILURE, REL_DEPENDS_ON_SUCCESS
from stonebranch_graph.exporters import export_graph_bundle
from stonebranch_graph.parsers.stonebranch_json import StonebranchJsonParser


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_stonebranch_dependency_definition_becomes_edge_not_node(tmp_path: Path) -> None:
    write_json(tmp_path / "tasks" / "load.json", {"name": "LOAD_CUSTOMERS"})
    write_json(tmp_path / "tasks" / "validate.json", {"name": "VALIDATE_CUSTOMERS"})
    write_json(
        tmp_path / "dependencies" / "validate_after_load.json",
        {
            "name": "VALIDATE_AFTER_LOAD",
            "successorTask": "VALIDATE_CUSTOMERS",
            "predecessorTask": "LOAD_CUSTOMERS",
            "dependencyType": "Success",
        },
    )

    graph = StonebranchJsonParser(AnalyzerConfig.default(), env="PROD").parse(tmp_path)

    assert {node.kind for node in graph.nodes.values()} == {KIND_TASK}
    assert all("dependency" not in node.kind.lower() for node in graph.nodes.values())

    edge = next(edge for edge in graph.edges.values() if edge.native_relation == "stonebranch_dependency_definition")
    assert edge.relation == REL_DEPENDS_ON_SUCCESS
    assert graph.nodes[edge.source].name == "VALIDATE_CUSTOMERS"
    assert graph.nodes[edge.target].name == "LOAD_CUSTOMERS"
    assert edge.evidence_file == "dependencies/validate_after_load.json"
    assert edge.evidence_key == "dependency:VALIDATE_AFTER_LOAD"


def test_stonebranch_dependency_definition_creates_synthetic_task_placeholders_only(tmp_path: Path) -> None:
    write_json(
        tmp_path / "dependencies" / "missing_tasks.json",
        {
            "dependentTask": "DOWNSTREAM_JOB",
            "prerequisiteTask": "UPSTREAM_JOB",
            "dependencyType": "failure",
        },
    )

    graph = StonebranchJsonParser(AnalyzerConfig.default(), env="PROD").parse(tmp_path)

    assert all(node.kind == KIND_TASK for node in graph.nodes.values())
    assert {node.name for node in graph.nodes.values()} == {"DOWNSTREAM_JOB", "UPSTREAM_JOB"}
    assert all(node.metadata.get("synthetic") for node in graph.nodes.values())

    edge = next(iter(graph.edges.values()))
    assert edge.relation == REL_DEPENDS_ON_FAILURE
    assert graph.nodes[edge.source].name == "DOWNSTREAM_JOB"
    assert graph.nodes[edge.target].name == "UPSTREAM_JOB"


def test_dependency_definition_array_exports_only_edges_in_bundle(tmp_path: Path) -> None:
    write_json(tmp_path / "tasks" / "a.json", {"name": "A"})
    write_json(tmp_path / "tasks" / "b.json", {"name": "B"})
    write_json(
        tmp_path / "dependencies" / "batch.json",
        [
            {"successorTaskName": "B", "predecessorTaskName": "A"},
        ],
    )
    graph = StonebranchJsonParser(AnalyzerConfig.default(), env="PROD").parse(tmp_path)

    out = tmp_path / "out"
    export_graph_bundle(graph, out)

    nodes = json.loads((out / "graph.json").read_text(encoding="utf-8"))["nodes"]
    assert all(node["kind"] != "dependency" for node in nodes)

    rows = list(csv.DictReader((out / "edges.csv").open(encoding="utf-8")))
    assert [row for row in rows if row["native_relation"] == "stonebranch_dependency_definition"]
    assert any(row["evidence_file"] == "dependencies/batch.json#[0]" for row in rows)
