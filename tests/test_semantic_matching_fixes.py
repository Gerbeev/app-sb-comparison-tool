from __future__ import annotations

import json
from pathlib import Path

from stonebranch_graph.compare import compare_graphs
from stonebranch_graph.config import AnalyzerConfig, MappingConfig
from stonebranch_graph.core import make_node_id
from stonebranch_graph.domain import (
    KIND_AGENT_CLUSTER,
    KIND_TASK,
    KIND_TRIGGER,
    KIND_VARIABLE,
    KIND_WORKFLOW,
    REL_CONTAINS,
    REL_DEPENDS_ON_FAILURE,
    REL_DEPENDS_ON_SUCCESS,
    REL_STARTS,
    SOURCE_STONEBRANCH,
)
from stonebranch_graph.parsers.autosys_jil import AutosysJilParser
from stonebranch_graph.parsers.stonebranch_json import StonebranchJsonParser


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def parse_sb(root: Path):
    return StonebranchJsonParser(AnalyzerConfig.default(), env="PROD").parse(root)


def parse_jil(root: Path):
    return AutosysJilParser(AnalyzerConfig.default(), env="PROD").parse(root)


def compare(sb, jil):
    config = AnalyzerConfig.default()
    return compare_graphs(sb, jil, MappingConfig.empty(config), config)


def edge_triples(graph):
    return {
        (graph.nodes[e.source].name, e.relation, graph.nodes[e.target].name)
        for e in graph.edges.values()
        if e.source in graph.nodes and e.target in graph.nodes
    }


def sb_workflow_export(condition: dict | str | None = "dict") -> dict:
    edge: dict = {"sourceId": {"value": "1"}, "targetId": {"value": "2"}}
    if condition == "dict":
        edge["condition"] = {"value": "Success"}
    elif condition is not None:
        edge["condition"] = condition
    return {
        "name": "DAILY_BOX",
        "type": "taskWorkflow",
        "workflowVertices": [
            {"task": {"value": "JOB_A"}, "vertexId": "1", "vertexX": 100, "vertexY": 100},
            {"task": {"value": "JOB_B"}, "vertexId": "2", "vertexX": 300, "vertexY": 100},
        ],
        "workflowEdges": [edge],
    }


def test_workflow_vertices_and_edges_become_contains_and_dependencies(tmp_path: Path) -> None:
    write_json(tmp_path / "workflows" / "DAILY_BOX.json", sb_workflow_export())
    write_json(tmp_path / "tasks" / "JOB_A.json", {"name": "JOB_A"})
    write_json(tmp_path / "tasks" / "JOB_B.json", {"name": "JOB_B"})

    graph = parse_sb(tmp_path)
    triples = edge_triples(graph)

    assert ("DAILY_BOX", REL_CONTAINS, "JOB_A") in triples
    assert ("DAILY_BOX", REL_CONTAINS, "JOB_B") in triples
    # The dependency points dependent -> prerequisite, like AutoSys conditions.
    assert ("JOB_B", REL_DEPENDS_ON_SUCCESS, "JOB_A") in triples
    # Edge endpoints must not be misread as containment or create vertex-id nodes.
    assert not any(node.name in {"1", "2"} for node in graph.nodes.values())
    assert len([t for t in triples if t[1] == REL_CONTAINS]) == 2


def test_workflow_edge_failure_condition_maps_to_failure_dependency(tmp_path: Path) -> None:
    write_json(tmp_path / "workflows" / "DAILY_BOX.json", sb_workflow_export(condition={"value": "Failure"}))
    write_json(tmp_path / "tasks" / "JOB_A.json", {"name": "JOB_A"})
    write_json(tmp_path / "tasks" / "JOB_B.json", {"name": "JOB_B"})

    triples = edge_triples(parse_sb(tmp_path))
    assert ("JOB_B", REL_DEPENDS_ON_FAILURE, "JOB_A") in triples


def test_workflow_edges_with_embedded_task_names_resolve_without_vertex_ids(tmp_path: Path) -> None:
    payload = {
        "name": "DAILY_BOX",
        "workflowVertices": [{"task": {"value": "JOB_A"}}, {"task": {"value": "JOB_B"}}],
        "workflowEdges": [
            {"condition": {"value": "Success"}, "sourceId": {"taskName": "JOB_A"}, "targetId": {"taskName": "JOB_B"}}
        ],
    }
    write_json(tmp_path / "workflows" / "DAILY_BOX.json", payload)
    write_json(tmp_path / "tasks" / "JOB_A.json", {"name": "JOB_A"})
    write_json(tmp_path / "tasks" / "JOB_B.json", {"name": "JOB_B"})

    triples = edge_triples(parse_sb(tmp_path))
    assert ("JOB_B", REL_DEPENDS_ON_SUCCESS, "JOB_A") in triples


def test_workflow_dependencies_match_jil_conditions_end_to_end(tmp_path: Path) -> None:
    sb_root = tmp_path / "sb"
    write_json(sb_root / "workflows" / "DAILY_BOX.json", sb_workflow_export())
    write_json(sb_root / "tasks" / "JOB_A.json", {"name": "JOB_A"})
    write_json(sb_root / "tasks" / "JOB_B.json", {"name": "JOB_B"})

    jil_root = tmp_path / "jil"
    jil_root.mkdir()
    (jil_root / "daily.jil").write_text(
        "\n".join(
            [
                "insert_job: DAILY_BOX",
                "job_type: b",
                "insert_job: JOB_A",
                "job_type: c",
                "box_name: DAILY_BOX",
                "insert_job: JOB_B",
                "job_type: c",
                "box_name: DAILY_BOX",
                "condition: s(JOB_A)",
            ]
        ),
        encoding="utf-8",
    )

    comparison = compare(parse_sb(sb_root), parse_jil(jil_root))

    assert comparison.summary["matched_nodes"] == 3
    assert comparison.summary["missing_in_stonebranch"] == 0
    assert comparison.summary["missing_in_jil"] == 0
    matched_keys = {item["key"] for item in comparison.edges["matched"]}
    assert "PROD:task:job_b->depends_on_success->PROD:task:job_a" in matched_keys
    assert "PROD:box:daily_box->contains->PROD:task:job_a" in matched_keys
    assert "PROD:box:daily_box->contains->PROD:task:job_b" in matched_keys
    assert comparison.summary["missing_edges_in_stonebranch"] == 0
    assert comparison.summary["missing_edges_in_jil"] == 0
    assert comparison.summary["critical_dependency_loss_count"] == 0


def test_variable_tokens_extracted_only_from_command_like_fields(tmp_path: Path) -> None:
    write_json(
        tmp_path / "tasks" / "JOB_A.json",
        {
            "name": "JOB_A",
            "summary": "Writes to ${NOT_A_REFERENCE} folder",
            "logPath": "/logs/%SOME_PATH_TOKEN%/out.log",
            "command": "run.sh ${REAL_VAR}",
        },
    )

    graph = parse_sb(tmp_path)
    variable_names = {node.name for node in graph.nodes.values() if node.kind == KIND_VARIABLE}

    assert "REAL_VAR" in variable_names
    assert "NOT_A_REFERENCE" not in variable_names
    assert "SOME_PATH_TOKEN" not in variable_names


def test_agent_cluster_matches_jil_machine(tmp_path: Path) -> None:
    sb_root = tmp_path / "sb"
    write_json(sb_root / "tasks" / "JOB_A.json", {"name": "JOB_A", "agentClusterName": "machine01"})
    write_json(sb_root / "agent_clusters" / "machine01.json", {"name": "machine01"})

    jil_root = tmp_path / "jil"
    jil_root.mkdir()
    (jil_root / "job.jil").write_text(
        "insert_job: JOB_A\njob_type: c\nmachine: machine01\n",
        encoding="utf-8",
    )

    sb_graph = parse_sb(sb_root)
    assert any(node.kind == KIND_AGENT_CLUSTER for node in sb_graph.nodes.values())

    comparison = compare(sb_graph, parse_jil(jil_root))

    assert comparison.summary["matched_nodes"] == 2
    matched_keys = {item["key"] for item in comparison.edges["matched"]}
    assert "PROD:task:job_a->runs_on->PROD:agent:machine01" in matched_keys
    assert comparison.summary["agent_machine_mismatch_count"] == 0


def test_generic_dependency_matches_specific_condition_as_relaxed(tmp_path: Path) -> None:
    sb_root = tmp_path / "sb"
    write_json(sb_root / "tasks" / "JOB_A.json", {"name": "JOB_A"})
    write_json(sb_root / "tasks" / "JOB_B.json", {"name": "JOB_B", "dependentTaskName": "JOB_A"})

    jil_root = tmp_path / "jil"
    jil_root.mkdir()
    (jil_root / "job.jil").write_text(
        "insert_job: JOB_A\njob_type: c\ninsert_job: JOB_B\njob_type: c\ncondition: s(JOB_A)\n",
        encoding="utf-8",
    )

    comparison = compare(parse_sb(sb_root), parse_jil(jil_root))

    assert comparison.summary["relaxed_dependency_matches"] == 1
    assert comparison.summary["missing_edges_in_stonebranch"] == 0
    assert comparison.summary["missing_edges_in_jil"] == 0
    assert comparison.summary["critical_dependency_loss_count"] == 0
    relaxed = comparison.edges["matched_relaxed"][0]
    assert relaxed["match_type"] == "dependency_family_relaxed"
    assert relaxed["jil_key"] == "PROD:task:job_b->depends_on_success->PROD:task:job_a"


def test_conflicting_specific_conditions_stay_mismatched(tmp_path: Path) -> None:
    sb_root = tmp_path / "sb"
    write_json(
        sb_root / "workflows" / "WF.json",
        {
            "name": "WF",
            "workflowVertices": [{"task": {"value": "JOB_A"}, "vertexId": "1"}, {"task": {"value": "JOB_B"}, "vertexId": "2"}],
            "workflowEdges": [{"condition": {"value": "Failure"}, "sourceId": {"value": "1"}, "targetId": {"value": "2"}}],
        },
    )
    write_json(sb_root / "tasks" / "JOB_A.json", {"name": "JOB_A"})
    write_json(sb_root / "tasks" / "JOB_B.json", {"name": "JOB_B"})

    jil_root = tmp_path / "jil"
    jil_root.mkdir()
    (jil_root / "job.jil").write_text(
        "insert_job: WF\njob_type: b\n"
        "insert_job: JOB_A\njob_type: c\nbox_name: WF\n"
        "insert_job: JOB_B\njob_type: c\nbox_name: WF\ncondition: s(JOB_A)\n",
        encoding="utf-8",
    )

    comparison = compare(parse_sb(sb_root), parse_jil(jil_root))

    assert comparison.summary["relaxed_dependency_matches"] == 0
    assert comparison.summary["missing_edges_in_stonebranch"] == 1
    assert comparison.summary["missing_edges_in_jil"] == 1


def test_stonebranch_only_objects_and_edges_are_informational(tmp_path: Path) -> None:
    sb_root = tmp_path / "sb"
    write_json(sb_root / "tasks" / "JOB_A.json", {"name": "JOB_A", "credentialName": "CRED_APP"})
    write_json(sb_root / "credentials" / "CRED_APP.json", {"name": "CRED_APP"})
    write_json(sb_root / "triggers" / "TRG_DAILY.json", {"name": "TRG_DAILY", "taskName": "JOB_A"})

    jil_root = tmp_path / "jil"
    jil_root.mkdir()
    (jil_root / "job.jil").write_text("insert_job: JOB_A\njob_type: c\n", encoding="utf-8")

    comparison = compare(parse_sb(sb_root), parse_jil(jil_root))

    assert comparison.summary["matched_nodes"] == 1
    assert comparison.summary["missing_in_jil"] == 0
    assert comparison.summary["missing_edges_in_jil"] == 0
    assert comparison.summary["stonebranch_only_nodes"] == 2
    assert comparison.summary["stonebranch_only_edges"] == 2
    only_kinds = {item["kind"] for item in comparison.nodes["stonebranch_only"]}
    assert only_kinds == {"trigger", "credential"}
    only_relations = {item["relation"] for item in comparison.edges["stonebranch_only"]}
    assert only_relations == {"starts", "uses_credential"}


def test_duplicate_containment_evidence_does_not_block_edge_matching(tmp_path: Path) -> None:
    sb_root = tmp_path / "sb"
    write_json(
        sb_root / "workflows" / "WF.json",
        {"name": "WF", "tasks": ["JOB_A"], "workflowVertices": [{"task": {"value": "JOB_A"}, "vertexId": "1"}]},
    )
    write_json(sb_root / "tasks" / "JOB_A.json", {"name": "JOB_A", "workflowName": "WF"})

    jil_root = tmp_path / "jil"
    jil_root.mkdir()
    (jil_root / "job.jil").write_text(
        "insert_job: WF\njob_type: b\ninsert_job: JOB_A\njob_type: c\nbox_name: WF\n",
        encoding="utf-8",
    )

    comparison = compare(parse_sb(sb_root), parse_jil(jil_root))

    matched_keys = {item["key"] for item in comparison.edges["matched"]}
    assert "PROD:box:wf->contains->PROD:task:job_a" in matched_keys
    assert comparison.summary["missing_edges_in_stonebranch"] == 0
    assert comparison.summary["missing_edges_in_jil"] == 0


def test_trigger_task_name_resolves_to_existing_workflow(tmp_path: Path) -> None:
    write_json(tmp_path / "workflows" / "DAILY_WF.json", {"name": "DAILY_WF"})
    write_json(tmp_path / "triggers" / "TRG.json", {"name": "TRG", "taskName": "DAILY_WF"})

    graph = parse_sb(tmp_path)

    trigger_id = make_node_id(SOURCE_STONEBRANCH, "PROD", KIND_TRIGGER, "TRG")
    workflow_id = make_node_id(SOURCE_STONEBRANCH, "PROD", KIND_WORKFLOW, "DAILY_WF")
    synthetic_task_id = make_node_id(SOURCE_STONEBRANCH, "PROD", KIND_TASK, "DAILY_WF")

    assert synthetic_task_id not in graph.nodes
    assert any(
        edge.source == trigger_id and edge.target == workflow_id and edge.relation == REL_STARTS
        for edge in graph.edges.values()
    )
