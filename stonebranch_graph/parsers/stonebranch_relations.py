from __future__ import annotations

import re
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
from stonebranch_graph.parsers.stonebranch_workflow import WORKFLOW_STRUCTURE_KEYS, normalized_json_key
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
