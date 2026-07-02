from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from stonebranch_graph.config import AnalyzerConfig
from stonebranch_graph.domain import (
    KIND_AGENT,
    KIND_AGENT_CLUSTER,
    KIND_CALENDAR,
    KIND_COMMAND,
    KIND_CONNECTION,
    KIND_CREDENTIAL,
    KIND_EMAIL_TEMPLATE,
    KIND_FILE,
    KIND_OBJECT,
    KIND_SCRIPT,
    KIND_TASK,
    KIND_TRIGGER,
    KIND_VARIABLE,
    KIND_WORKFLOW,
    REL_CONTAINS,
    REL_DEPENDS_ON,
    REL_DEPENDS_ON_DONE,
    REL_DEPENDS_ON_FAILURE,
    REL_DEPENDS_ON_SUCCESS,
    REL_REFERENCES,
    REL_RUNS_COMMAND,
    REL_RUNS_ON,
    REL_RUNS_ON_CLUSTER,
    REL_RUNS_SCRIPT,
    REL_STARTS,
    REL_SUCCESSOR_OF,
    REL_USES_CALENDAR,
    REL_USES_CONNECTION,
    REL_USES_CREDENTIAL,
    REL_USES_EMAIL_TEMPLATE,
    REL_USES_VARIABLE,
    REL_WATCHES_FILE,
)
from stonebranch_graph.normalizers import command_evidence, semantic_command_hash
from stonebranch_graph.utils import is_secret_key

VAR_TOKEN_RE = re.compile(
    r"""
    (?:
        \$\{(?P<brace>[A-Za-z0-9_.:/\- ]+)\} |
        \{\{(?P<mustache>[A-Za-z0-9_.:/\- ]+)\}\} |
        %(?P<percent>[A-Za-z0-9_.:/\- ]+)% |
        @\((?P<at>[A-Za-z0-9_.:/\- ]+)\)
    )
    """,
    re.VERBOSE,
)

TARGET_KIND_BY_NATIVE_RELATION = {
    "starts_task": KIND_TASK,
    "starts_workflow": KIND_WORKFLOW,
    "contains_task": KIND_TASK,
    "contains_workflow": KIND_WORKFLOW,
    "references_workflow": KIND_WORKFLOW,
    "references_task": KIND_TASK,
    "references_job": KIND_TASK,
    "references_predecessor": KIND_TASK,
    "references_successor": KIND_TASK,
    "references_calendar": KIND_CALENDAR,
    "references_credential": KIND_CREDENTIAL,
    "references_connection": KIND_CONNECTION,
    "references_agent": KIND_AGENT,
    "references_agent_cluster": KIND_AGENT_CLUSTER,
    "references_agentcluster": KIND_AGENT_CLUSTER,
    "references_email_template": KIND_EMAIL_TEMPLATE,
    "references_emailtemplate": KIND_EMAIL_TEMPLATE,
    "references_script": KIND_SCRIPT,
    "references_variable": KIND_VARIABLE,
    "references_trigger": KIND_TRIGGER,
    "references_command": KIND_COMMAND,
    "watch_file": KIND_FILE,
    "contained_by_workflow": KIND_WORKFLOW,
    "variable_token": KIND_VARIABLE,
}

TARGET_KIND_BY_RELATION = {
    REL_STARTS: KIND_TASK,
    REL_DEPENDS_ON: KIND_TASK,
    REL_DEPENDS_ON_SUCCESS: KIND_TASK,
    REL_SUCCESSOR_OF: KIND_TASK,
    REL_USES_CALENDAR: KIND_CALENDAR,
    REL_USES_CREDENTIAL: KIND_CREDENTIAL,
    REL_USES_CONNECTION: KIND_CONNECTION,
    REL_RUNS_ON: KIND_AGENT,
    REL_RUNS_ON_CLUSTER: KIND_AGENT_CLUSTER,
    REL_USES_EMAIL_TEMPLATE: KIND_EMAIL_TEMPLATE,
    REL_RUNS_SCRIPT: KIND_SCRIPT,
    REL_USES_VARIABLE: KIND_VARIABLE,
    REL_RUNS_COMMAND: KIND_COMMAND,
    REL_WATCHES_FILE: KIND_FILE,
}

ReferenceTuple = tuple[str, str, str, str, str, str]

# Keys of Stonebranch workflow JSON subtrees that describe the workflow graph
# structure (vertices and dependency edges). They are parsed structurally by
# extract_workflow_structure and must be skipped by the generic key-based
# reference walker: otherwise every dependency edge endpoint (sourceId.taskName /
# targetId.taskName) is misread as a containment reference and the dependency
# itself is lost.
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

# Variable tokens are only meaningful references inside command-like values.
# Extracting ${...}/%...% tokens from descriptions, file paths, or layout data
# inflates the graph with synthetic variables that AutoSys JIL can never have
# (the JIL parser extracts variables from the command attribute only).
VARIABLE_TOKEN_SOURCE_KEYS = {
    "command",
    "commandline",
    "command_line",
    "exec_command",
    "script",
    "scriptbody",
    "script_body",
    "parameters",
    "args",
    "arguments",
}


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


def normalized_json_key(key: str) -> str:
    return str(key).lower().replace("-", "_")


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
    task = item.get("task")
    name = _string_from(task, ("value", "name", "taskName"))
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


def find_stonebranch_references(
    data: dict[str, Any],
    source_kind: str,
    config: AnalyzerConfig,
    deep_scan: bool,
) -> list[ReferenceTuple]:
    refs: list[ReferenceTuple] = []
    skip_structure = source_kind == KIND_WORKFLOW

    def walk(value: Any, path: str, key: str) -> None:
        if isinstance(value, dict):
            for child_key, child in value.items():
                child_key_str = str(child_key)
                if skip_structure and normalized_json_key(child_key_str) in WORKFLOW_STRUCTURE_KEYS:
                    # Handled structurally by extract_workflow_structure.
                    continue
                walk(child, f"{path}.{child_key_str}", child_key_str)
            return
        if isinstance(value, list):
            for idx, child in enumerate(value):
                walk(child, f"{path}[{idx}]", key)
            return
        if not isinstance(value, str) or not value.strip() or is_secret_key(key):
            return
        cleaned = value.strip()
        native = native_relation_from_key(key, source_kind)
        if native:
            relation = normalized_relation(native, config)
            if relation == REL_RUNS_COMMAND:
                command_id = semantic_command_hash(cleaned)
                evidence = command_evidence(cleaned, include_raw_values=config.include_raw_values)
                refs.append((command_id, native, relation, path, key, evidence))
            else:
                refs.append((cleaned, native, relation, path, key, cleaned))
        if normalized_json_key(key) in VARIABLE_TOKEN_SOURCE_KEYS:
            for token in extract_variable_tokens(cleaned):
                refs.append((token, "variable_token", REL_USES_VARIABLE, path, key, token))
        if deep_scan and not native and likely_reference(cleaned):
            refs.append((cleaned, "deep_scan_reference", REL_REFERENCES, path, key, cleaned))

    walk(data, "$", "")
    return refs


def native_relation_from_key(key: str, source_kind: str) -> str | None:
    lower = key.lower().replace("-", "_")
    if source_kind == KIND_TRIGGER:
        if lower in {"taskname", "task_name"}:
            return "starts_task"
        if lower in {"workflowname", "workflow_name"}:
            return "starts_workflow"
    if source_kind == KIND_WORKFLOW:
        workflow_keys = {"workflowname", "workflow_name", "workflow", "workflows", "subworkflowname", "sub_workflow_name"}
        task_keys = {
            "taskname", "task_name", "tasknames", "task_names", "task", "tasks", "jobname", "job_name",
            "jobnames", "job_names", "job", "jobs", "workflowtaskname", "workflow_task_name",
            "workflowtasks", "workflow_tasks",
        }
        if lower in workflow_keys:
            return "contains_workflow"
        if lower in task_keys or lower.endswith("taskname") or lower.endswith("task_name"):
            return "contains_task"
    exact = {
        "predecessortask": "references_predecessor",
        "predecessor_task": "references_predecessor",
        "successortask": "references_successor",
        "successor_task": "references_successor",
        "agentclustername": "references_agent_cluster",
        "agent_cluster_name": "references_agent_cluster",
        "emailtemplatename": "references_email_template",
        "email_template_name": "references_email_template",
        "calendarname": "references_calendar",
        "calendar_name": "references_calendar",
        "credentialname": "references_credential",
        "credential_name": "references_credential",
        "connectionname": "references_connection",
        "connection_name": "references_connection",
        "agentname": "references_agent",
        "agent_name": "references_agent",
        "scriptname": "references_script",
        "script_name": "references_script",
        "variablename": "references_variable",
        "variable_name": "references_variable",
        "command": "references_command",
        "watch_file": "watch_file",
        "watchfilename": "watch_file",
        "watch_file_name": "watch_file",
    }
    if lower in exact:
        return exact[lower]
    if lower in {"workflowname", "workflow_name"}:
        return "contained_by_workflow"
    if lower.endswith("taskname") or lower.endswith("task_name"):
        return "references_task"
    return None


def normalized_relation(native_relation: str, config: AnalyzerConfig) -> str:
    return (config.relation_aliases or {}).get(native_relation, native_relation)


def directed_relation(source_id: str, target_id: str, relation: str, native_relation: str) -> tuple[str, str, str, str]:
    if native_relation == "references_successor":
        return target_id, source_id, REL_DEPENDS_ON_SUCCESS, "successor_depends_on_success"
    if native_relation == "contained_by_workflow":
        return target_id, source_id, REL_CONTAINS, native_relation
    return source_id, target_id, relation, native_relation


def extract_variable_tokens(value: str) -> list[str]:
    found: list[str] = []
    for match in VAR_TOKEN_RE.finditer(value):
        token = next((group for group in match.groups() if group), None)
        if token:
            found.append(token.strip())
    return found


def likely_reference(value: str) -> bool:
    return len(value) <= 220 and "\n" not in value and not (" " in value and not any(sep in value for sep in ("_", "-", "/", ":")))


def kind_from_relation(native_relation: str, relation: str) -> str:
    native_key = native_relation.lower()
    relation_key = relation.lower()
    if native_key in TARGET_KIND_BY_NATIVE_RELATION:
        return TARGET_KIND_BY_NATIVE_RELATION[native_key]
    if relation_key in TARGET_KIND_BY_RELATION:
        return TARGET_KIND_BY_RELATION[relation_key]

    text = (native_relation + " " + relation).lower()
    if "calendar" in text:
        return KIND_CALENDAR
    if "credential" in text:
        return KIND_CREDENTIAL
    if "connection" in text:
        return KIND_CONNECTION
    if "agent_cluster" in text or "agentcluster" in text:
        return KIND_AGENT_CLUSTER
    if "agent" in text:
        return KIND_AGENT
    if "email_template" in text or "emailtemplate" in text:
        return KIND_EMAIL_TEMPLATE
    if "script" in text:
        return KIND_SCRIPT
    if "variable" in text:
        return KIND_VARIABLE
    if "command" in text:
        return KIND_COMMAND
    if "task" in text or "job" in text or "predecessor" in text or "successor" in text:
        return KIND_TASK
    if "trigger" in text:
        return KIND_TRIGGER
    return KIND_OBJECT
