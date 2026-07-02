from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from stonebranch_graph.config import AnalyzerConfig
from stonebranch_graph.core import Edge, Graph, make_edge_id, redacted_preview
from stonebranch_graph.domain import (
    KIND_TASK,
    REL_CONTAINS,
    REL_DEPENDS_ON,
    REL_DEPENDS_ON_DONE,
    REL_DEPENDS_ON_FAILURE,
    REL_DEPENDS_ON_SUCCESS,
    SOURCE_STONEBRANCH,
)
from stonebranch_graph.parsers.stonebranch_registry import Registry, resolve_or_create_ref_node

# Keys of Stonebranch workflow JSON subtrees that describe the workflow graph
# structure (vertices and dependency edges). They are parsed structurally here
# and must be skipped by the generic key-based reference walker: otherwise every
# dependency edge endpoint (sourceId.taskName / targetId.taskName) is misread as
# a containment reference and the dependency itself is lost.
WORKFLOW_VERTEX_CONTAINER_KEYS = {"workflowvertices", "workflow_vertices", "vertices"}
WORKFLOW_EDGE_CONTAINER_KEYS = {"workflowedges", "workflow_edges", "edges"}
WORKFLOW_STRUCTURE_KEYS = WORKFLOW_VERTEX_CONTAINER_KEYS | WORKFLOW_EDGE_CONTAINER_KEYS

# Universal Controller workflow edge condition -> normalized dependency relation.
# Matches the AutoSys JIL condition families: s() / f() / d().
WORKFLOW_EDGE_CONDITION_RELATIONS = {
    "success": REL_DEPENDS_ON_SUCCESS,
    "failure": REL_DEPENDS_ON_FAILURE,
    "success/failure": REL_DEPENDS_ON_DONE,
    "success or failure": REL_DEPENDS_ON_DONE,
    "finished": REL_DEPENDS_ON_DONE,
    "done": REL_DEPENDS_ON_DONE,
    "completed": REL_DEPENDS_ON_DONE,
}


def normalized_json_key(key: str) -> str:
    return str(key).lower().replace("-", "_")


@dataclass(frozen=True)
class WorkflowDependency:
    predecessor: str
    successor: str
    relation: str
    condition: str
    evidence_path: str


@dataclass(frozen=True)
class WorkflowStructure:
    vertex_tasks: list[tuple[str, str]] = field(default_factory=list)
    dependencies: list[WorkflowDependency] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _string_from(value: Any, keys: tuple[str, ...]) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in keys:
            inner = value.get(key)
            if isinstance(inner, str) and inner.strip():
                return inner.strip()
    return ""


def _vertex_task_name(item: Any) -> str:
    if isinstance(item, str):
        return item.strip()
    if not isinstance(item, dict):
        return ""
    name = _string_from(item.get("task"), ("value", "name", "taskName"))
    if name:
        return name
    return _string_from(item, ("taskName", "task_name", "name"))


def _vertex_id(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    for key in ("vertexId", "vertex_id", "id"):
        value = item.get(key)
        if isinstance(value, (str, int)) and str(value).strip():
            return str(value).strip()
    return ""


def _endpoint_task_name(value: Any, vertex_map: dict[str, str]) -> str:
    if isinstance(value, dict):
        name = _string_from(value, ("taskName", "task_name"))
        if name:
            return name
        if "value" in value:
            return _endpoint_task_name(value.get("value"), vertex_map)
        return ""
    token = str(value).strip() if value is not None else ""
    if not token:
        return ""
    if token in vertex_map:
        return vertex_map[token]
    if token.isdigit():
        return ""
    return token


def _edge_condition_label(item: dict[str, Any]) -> str:
    condition = item.get("condition")
    if isinstance(condition, dict):
        condition = condition.get("value") or condition.get("name") or ""
    return str(condition or "").strip()


def workflow_edge_condition_relation(condition: str) -> str:
    label = condition.strip().lower()
    if not label:
        # Universal Controller edges default to a Success condition.
        return REL_DEPENDS_ON_SUCCESS
    return WORKFLOW_EDGE_CONDITION_RELATIONS.get(label, REL_DEPENDS_ON)


def extract_workflow_structure(data: dict[str, Any]) -> WorkflowStructure:
    """Parse workflowVertices/workflowEdges into containment and dependencies.

    Vertices become workflow-contains-task references. Edges become
    successor-depends-on-predecessor dependencies with the edge condition mapped
    to the same relation family as AutoSys JIL conditions.
    """
    if not isinstance(data, dict):
        return WorkflowStructure()

    vertex_items: list[tuple[str, Any]] = []
    edge_items: list[tuple[str, Any]] = []
    for key, value in data.items():
        normalized = normalized_json_key(key)
        if not isinstance(value, list):
            continue
        if normalized in WORKFLOW_VERTEX_CONTAINER_KEYS:
            vertex_items.extend((f"$.{key}[{idx}]", item) for idx, item in enumerate(value))
        elif normalized in WORKFLOW_EDGE_CONTAINER_KEYS:
            edge_items.extend((f"$.{key}[{idx}]", item) for idx, item in enumerate(value))

    vertex_tasks: list[tuple[str, str]] = []
    vertex_map: dict[str, str] = {}
    warnings: list[str] = []
    for path, item in vertex_items:
        task_name = _vertex_task_name(item)
        if not task_name:
            warnings.append(f"Workflow vertex without a resolvable task name at {path}.")
            continue
        vertex_tasks.append((task_name, path))
        vertex_id = _vertex_id(item)
        if vertex_id:
            vertex_map[vertex_id] = task_name

    dependencies: list[WorkflowDependency] = []
    for path, item in edge_items:
        if not isinstance(item, dict):
            continue
        source_value = item.get("sourceId", item.get("source", item.get("source_id")))
        target_value = item.get("targetId", item.get("target", item.get("target_id")))
        predecessor = _endpoint_task_name(source_value, vertex_map)
        successor = _endpoint_task_name(target_value, vertex_map)
        if not predecessor or not successor:
            warnings.append(f"Workflow edge with unresolvable endpoint at {path}.")
            continue
        if predecessor == successor:
            continue
        condition = _edge_condition_label(item)
        dependencies.append(
            WorkflowDependency(
                predecessor=predecessor,
                successor=successor,
                relation=workflow_edge_condition_relation(condition),
                condition=condition or "Success",
                evidence_path=path,
            )
        )

    return WorkflowStructure(vertex_tasks=vertex_tasks, dependencies=dependencies, warnings=warnings)


def add_workflow_structure_edges(
    graph: Graph,
    registry: Registry,
    config: AnalyzerConfig,
    env: str,
    workflow_id: str,
    relative_path: str,
    data: dict[str, Any],
    append_warning: Callable[[Graph, str], None],
) -> None:
    structure = extract_workflow_structure(data)
    for warning in structure.warnings:
        append_warning(graph, f"{warning} ({relative_path})")

    def resolve(name: str, native_relation: str) -> str:
        return resolve_or_create_ref_node(
            graph=graph,
            registry=registry,
            config=config,
            env=env,
            target_kind=KIND_TASK,
            target_name=name,
            native_relation=native_relation,
            source_file=relative_path,
            append_warning=append_warning,
        )

    for task_name, evidence_path in structure.vertex_tasks:
        target_id = resolve(task_name, "workflow_vertex")
        graph.add_edge(
            Edge(
                # Keep the contains_task native relation so a containment edge
                # discovered both from a tasks list and from workflowVertices
                # deduplicates into a single edge.
                id=make_edge_id(workflow_id, target_id, REL_CONTAINS, "contains_task"),
                source=workflow_id,
                target=target_id,
                relation=REL_CONTAINS,
                source_system=SOURCE_STONEBRANCH,
                native_relation="contains_task",
                evidence_file=relative_path,
                evidence_path=evidence_path,
                evidence_key="workflowVertices",
                evidence_value=redacted_preview(task_name, config.max_evidence_value_len),
                confidence=0.95,
            )
        )

    for dependency in structure.dependencies:
        predecessor_id = resolve(dependency.predecessor, "workflow_edge")
        successor_id = resolve(dependency.successor, "workflow_edge")
        native_relation = "workflow_edge_" + dependency.condition.strip().lower().replace(" ", "_").replace("/", "_")
        graph.add_edge(
            Edge(
                id=make_edge_id(successor_id, predecessor_id, dependency.relation, native_relation),
                # AutoSys condition edges point dependent -> prerequisite, so the
                # workflow edge target (successor) depends on the source (predecessor).
                source=successor_id,
                target=predecessor_id,
                relation=dependency.relation,
                source_system=SOURCE_STONEBRANCH,
                native_relation=native_relation,
                evidence_file=relative_path,
                evidence_path=dependency.evidence_path,
                evidence_key="workflowEdges",
                evidence_value=redacted_preview(
                    f"{dependency.predecessor} -[{dependency.condition}]-> {dependency.successor}",
                    config.max_evidence_value_len,
                ),
                confidence=0.95,
            )
        )
