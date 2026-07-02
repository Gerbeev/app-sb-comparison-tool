from __future__ import annotations

import json
from pathlib import Path

from stonebranch_graph.compare import compare_graphs, comparison_edge_key
from stonebranch_graph.config import AnalyzerConfig, MappingConfig
from stonebranch_graph.core import Edge, Graph, Node, make_canonical_key, make_edge_id, make_node_id
from stonebranch_graph.domain import (
    KIND_BOX,
    KIND_FILE,
    KIND_TASK,
    KIND_WORKFLOW,
    REL_CONTAINS,
    REL_DEPENDS_ON_SUCCESS,
    REL_SUCCESSOR_OF,
    REL_WATCHES_FILE,
    SOURCE_AUTOSYS_JIL,
    SOURCE_STONEBRANCH,
)
from stonebranch_graph.parsers.autosys_jil import AutosysJilParser
from stonebranch_graph.parsers.stonebranch_json import StonebranchJsonParser


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_stonebranch_successor_task_is_reversed_to_dependency_direction(tmp_path: Path) -> None:
    write_json(tmp_path / "tasks" / "JOB_A.json", {"name": "JOB_A", "successorTask": "JOB_B"})
    write_json(tmp_path / "tasks" / "JOB_B.json", {"name": "JOB_B"})

    graph = StonebranchJsonParser(AnalyzerConfig.default(), env="PROD").parse(tmp_path)

    job_a = make_node_id(SOURCE_STONEBRANCH, "PROD", KIND_TASK, "JOB_A")
    job_b = make_node_id(SOURCE_STONEBRANCH, "PROD", KIND_TASK, "JOB_B")

    assert any(
        edge.source == job_b
        and edge.target == job_a
        and edge.relation == REL_DEPENDS_ON_SUCCESS
        and edge.native_relation == "successor_depends_on_success"
        for edge in graph.edges.values()
    )
    assert not any(edge.relation == REL_SUCCESSOR_OF for edge in graph.edges.values())


def test_legacy_successor_of_edge_matches_autosys_success_condition() -> None:
    config = AnalyzerConfig.default()
    mapping = MappingConfig.empty(config)
    sb = Graph(source_system=SOURCE_STONEBRANCH, env="PROD")
    jil = Graph(source_system=SOURCE_AUTOSYS_JIL, env="PROD")

    for graph, source_system in ((sb, SOURCE_STONEBRANCH), (jil, SOURCE_AUTOSYS_JIL)):
        for name in ("JOB_A", "JOB_B"):
            graph.add_node(
                Node(
                    id=make_node_id(source_system, "PROD", KIND_TASK, name),
                    canonical_key=make_canonical_key("PROD", KIND_TASK, name),
                    source_system=source_system,
                    env="PROD",
                    kind=KIND_TASK,
                    name=name,
                )
            )

    sb.add_edge(
        Edge(
            id=make_edge_id(
                make_node_id(SOURCE_STONEBRANCH, "PROD", KIND_TASK, "JOB_A"),
                make_node_id(SOURCE_STONEBRANCH, "PROD", KIND_TASK, "JOB_B"),
                REL_SUCCESSOR_OF,
                "references_successor",
            ),
            source=make_node_id(SOURCE_STONEBRANCH, "PROD", KIND_TASK, "JOB_A"),
            target=make_node_id(SOURCE_STONEBRANCH, "PROD", KIND_TASK, "JOB_B"),
            relation=REL_SUCCESSOR_OF,
            source_system=SOURCE_STONEBRANCH,
            native_relation="references_successor",
        )
    )
    jil.add_edge(
        Edge(
            id=make_edge_id(
                make_node_id(SOURCE_AUTOSYS_JIL, "PROD", KIND_TASK, "JOB_B"),
                make_node_id(SOURCE_AUTOSYS_JIL, "PROD", KIND_TASK, "JOB_A"),
                REL_DEPENDS_ON_SUCCESS,
                "condition_success",
            ),
            source=make_node_id(SOURCE_AUTOSYS_JIL, "PROD", KIND_TASK, "JOB_B"),
            target=make_node_id(SOURCE_AUTOSYS_JIL, "PROD", KIND_TASK, "JOB_A"),
            relation=REL_DEPENDS_ON_SUCCESS,
            source_system=SOURCE_AUTOSYS_JIL,
            native_relation="condition_success",
        )
    )

    comparison = compare_graphs(sb, jil, mapping, config)

    assert comparison.summary["matched_edges"] == 1
    assert comparison.edges["matched"][0]["key"] == "PROD:task:job_b->depends_on_success->PROD:task:job_a"


def test_stonebranch_task_workflow_name_is_normalized_to_workflow_contains_task(tmp_path: Path) -> None:
    write_json(tmp_path / "workflows" / "DAILY_BOX.json", {"name": "DAILY_BOX"})
    write_json(tmp_path / "tasks" / "LOAD_CUSTOMERS.json", {"name": "LOAD_CUSTOMERS", "workflowName": "DAILY_BOX"})

    graph = StonebranchJsonParser(AnalyzerConfig.default(), env="PROD").parse(tmp_path)

    workflow = make_node_id(SOURCE_STONEBRANCH, "PROD", KIND_WORKFLOW, "DAILY_BOX")
    task = make_node_id(SOURCE_STONEBRANCH, "PROD", KIND_TASK, "LOAD_CUSTOMERS")

    assert any(edge.source == workflow and edge.target == task and edge.relation == REL_CONTAINS for edge in graph.edges.values())
    assert not any(edge.source == task and edge.target == workflow and edge.relation == REL_CONTAINS for edge in graph.edges.values())


def test_legacy_reversed_contains_edge_is_normalized_for_comparison() -> None:
    config = AnalyzerConfig.default()
    mapping = MappingConfig.empty(config)
    graph = Graph(source_system=SOURCE_STONEBRANCH, env="PROD")
    task = Node(
        id="task",
        canonical_key="PROD:task:load_customers",
        source_system=SOURCE_STONEBRANCH,
        env="PROD",
        kind=KIND_TASK,
        name="LOAD_CUSTOMERS",
    )
    workflow = Node(
        id="workflow",
        canonical_key="PROD:workflow:daily_box",
        source_system=SOURCE_STONEBRANCH,
        env="PROD",
        kind=KIND_WORKFLOW,
        name="DAILY_BOX",
    )
    graph.add_node(task)
    graph.add_node(workflow)
    edge = Edge(
        id="legacy_contains",
        source=task.id,
        target=workflow.id,
        relation=REL_CONTAINS,
        source_system=SOURCE_STONEBRANCH,
        native_relation="references_workflow",
    )
    graph.add_edge(edge)

    assert comparison_edge_key(edge, graph, mapping, left=True) == "PROD:box:daily_box->contains->PROD:task:load_customers"


def test_stonebranch_watch_file_relation_matches_autosys_watch_file(tmp_path: Path) -> None:
    sb_root = tmp_path / "sb"
    jil_root = tmp_path / "jil"
    write_json(sb_root / "file_watchers" / "WATCHER.json", {"name": "WATCHER", "watch_file": "/data/incoming/*.csv"})
    jil_root.mkdir()
    (jil_root / "watcher.jil").write_text(
        "insert_job: WATCHER job_type: f\nwatch_file: /data/incoming/*.csv\n",
        encoding="utf-8",
    )

    config = AnalyzerConfig.default()
    sb_graph = StonebranchJsonParser(config, env="PROD").parse(sb_root)
    jil_graph = AutosysJilParser(config, env="PROD").parse(jil_root)

    assert any(edge.relation == REL_WATCHES_FILE for edge in sb_graph.edges.values())
    assert any(node.kind == KIND_FILE and node.name == "/data/incoming/*.csv" for node in sb_graph.nodes.values())

    comparison = compare_graphs(sb_graph, jil_graph, MappingConfig.empty(config), config)
    assert any(edge["key"] == "PROD:file_watcher:watcher->watches_file->PROD:file:/data/incoming/*.csv" for edge in comparison.edges["matched"])
