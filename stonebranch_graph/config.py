from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .domain import (
    KIND_AGENT,
    KIND_AGENT_CLUSTER,
    KIND_CALENDAR,
    KIND_CONNECTION,
    KIND_CREDENTIAL,
    KIND_EMAIL_TEMPLATE,
    KIND_FILE_WATCHER,
    KIND_SCRIPT,
    KIND_TASK,
    KIND_TRIGGER,
    KIND_VARIABLE,
    KIND_WORKFLOW,
    REL_CONTAINS,
    REL_DEPENDS_ON,
    REL_DEPENDS_ON_DONE,
    REL_DEPENDS_ON_FAILURE,
    REL_DEPENDS_ON_NOTRUNNING,
    REL_DEPENDS_ON_SUCCESS,
    REL_DEPENDS_ON_TERMINATED,
    REL_EXCLUDES_CALENDAR,
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

STONEBRANCH_FOLDER_KIND_MAP = {
    "agent_clusters": KIND_AGENT_CLUSTER,
    "agents": KIND_AGENT,
    "calendars": KIND_CALENDAR,
    "connections": KIND_CONNECTION,
    "credentials": KIND_CREDENTIAL,
    "email_templates": KIND_EMAIL_TEMPLATE,
    "file_watchers": KIND_FILE_WATCHER,
    "file_watcher": KIND_FILE_WATCHER,
    "scripts": KIND_SCRIPT,
    "tasks": KIND_TASK,
    "workflows": KIND_WORKFLOW,
    "workflow": KIND_WORKFLOW,
    "triggers": KIND_TRIGGER,
    "variables": KIND_VARIABLE,
}

IGNORED_FILENAMES = {
    ".gitkeep",
    "export_manifest.json",
}

SECRET_KEYWORDS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "private_key",
    "client_secret",
    "access_key",
    "refresh_token",
)

STONEBRANCH_NAME_KEYS = (
    "name",
    "Name",
    "title",
    "Title",
    "taskName",
    "TaskName",
    "workflowName",
    "WorkflowName",
    "variableName",
    "VariableName",
    "calendarName",
    "CalendarName",
    "credentialName",
    "CredentialName",
    "agentName",
    "AgentName",
    "agentClusterName",
    "AgentClusterName",
    "connectionName",
    "ConnectionName",
    "scriptName",
    "ScriptName",
    "triggerName",
    "TriggerName",
    "emailTemplateName",
    "EmailTemplateName",
)

STONEBRANCH_TYPE_KEYS = (
    "type",
    "Type",
    "objectType",
    "ObjectType",
    "object_type",
    "ucObjectType",
    "category",
    "Category",
)

STONEBRANCH_REFERENCE_KEYWORDS = (
    "workflow",
    "task",
    "job",
    "variable",
    "calendar",
    "credential",
    "connection",
    "agent",
    "agentcluster",
    "agent_cluster",
    "trigger",
    "script",
    "notification",
    "emailtemplate",
    "email_template",
    "predecessor",
    "successor",
    "dependency",
    "depends",
    "condition",
    "command",
    "template",
)

RELATION_ALIASES = {
    "references_calendar": REL_USES_CALENDAR,
    "references_variable": REL_USES_VARIABLE,
    "references_credential": REL_USES_CREDENTIAL,
    "references_connection": REL_USES_CONNECTION,
    "references_agent": REL_RUNS_ON,
    "references_agent_cluster": REL_RUNS_ON_CLUSTER,
    "references_agentcluster": REL_RUNS_ON_CLUSTER,
    "references_script": REL_RUNS_SCRIPT,
    "references_email_template": REL_USES_EMAIL_TEMPLATE,
    "references_emailtemplate": REL_USES_EMAIL_TEMPLATE,
    "references_task": REL_DEPENDS_ON,
    "references_job": REL_DEPENDS_ON,
    "references_predecessor": REL_DEPENDS_ON_SUCCESS,
    "references_successor": REL_SUCCESSOR_OF,
    "references_trigger": REL_STARTS,
    "starts_task": REL_STARTS,
    "starts_workflow": REL_STARTS,
    "contains_task": REL_CONTAINS,
    "contains_workflow": REL_CONTAINS,
    "references_workflow": REL_CONTAINS,
    "contained_by_workflow": REL_CONTAINS,
    "condition_success": REL_DEPENDS_ON_SUCCESS,
    "condition_done": REL_DEPENDS_ON_DONE,
    "condition_failure": REL_DEPENDS_ON_FAILURE,
    "condition_terminated": REL_DEPENDS_ON_TERMINATED,
    "condition_notrunning": REL_DEPENDS_ON_NOTRUNNING,
    "box_name": REL_CONTAINS,
    "machine": REL_RUNS_ON,
    "calendar": REL_USES_CALENDAR,
    "run_calendar": REL_USES_CALENDAR,
    "exclude_calendar": REL_EXCLUDES_CALENDAR,
    "references_command": REL_RUNS_COMMAND,
    "command": REL_RUNS_COMMAND,
    "watch_file": REL_WATCHES_FILE,
    "watchfilename": REL_WATCHES_FILE,
    "watch_file_name": REL_WATCHES_FILE,
}

KIND_ALIASES = {
    "job": KIND_TASK,
    "command_job": KIND_TASK,
    "cmd": KIND_TASK,
    "fw": KIND_FILE_WATCHER,
    "filewatcher": KIND_FILE_WATCHER,
    "machine": KIND_AGENT,
}


@dataclass(frozen=True)
class AnalyzerConfig:
    folder_kind_map: dict[str, str] | None = None
    ignored_filenames: tuple[str, ...] = tuple(IGNORED_FILENAMES)
    stonebranch_name_keys: tuple[str, ...] = STONEBRANCH_NAME_KEYS
    stonebranch_type_keys: tuple[str, ...] = STONEBRANCH_TYPE_KEYS
    stonebranch_reference_keywords: tuple[str, ...] = STONEBRANCH_REFERENCE_KEYWORDS
    relation_aliases: dict[str, str] | None = None
    kind_aliases: dict[str, str] | None = None
    max_evidence_value_len: int = 180
    include_raw_values: bool = False

    @staticmethod
    def default() -> AnalyzerConfig:
        return AnalyzerConfig(
            folder_kind_map=STONEBRANCH_FOLDER_KIND_MAP,
            relation_aliases=RELATION_ALIASES,
            kind_aliases=KIND_ALIASES,
        )

    @staticmethod
    def from_file(path: Path | None) -> AnalyzerConfig:
        if path is None:
            return AnalyzerConfig.default()

        data = json.loads(path.read_text(encoding="utf-8"))
        base = AnalyzerConfig.default()
        return AnalyzerConfig(
            folder_kind_map=data.get("folder_kind_map", base.folder_kind_map),
            ignored_filenames=tuple(data.get("ignored_filenames", list(base.ignored_filenames))),
            stonebranch_name_keys=tuple(data.get("stonebranch_name_keys", base.stonebranch_name_keys)),
            stonebranch_type_keys=tuple(data.get("stonebranch_type_keys", base.stonebranch_type_keys)),
            stonebranch_reference_keywords=tuple(
                data.get("stonebranch_reference_keywords", base.stonebranch_reference_keywords)
            ),
            relation_aliases=data.get("relation_aliases", base.relation_aliases),
            kind_aliases=data.get("kind_aliases", base.kind_aliases),
            max_evidence_value_len=int(data.get("max_evidence_value_len", base.max_evidence_value_len)),
            include_raw_values=bool(data.get("include_raw_values", base.include_raw_values)),
        )



    def with_runtime_flags(self, *, include_raw_values: bool | None = None) -> AnalyzerConfig:
        return AnalyzerConfig(
            folder_kind_map=self.folder_kind_map,
            ignored_filenames=self.ignored_filenames,
            stonebranch_name_keys=self.stonebranch_name_keys,
            stonebranch_type_keys=self.stonebranch_type_keys,
            stonebranch_reference_keywords=self.stonebranch_reference_keywords,
            relation_aliases=self.relation_aliases,
            kind_aliases=self.kind_aliases,
            max_evidence_value_len=self.max_evidence_value_len,
            include_raw_values=self.include_raw_values if include_raw_values is None else include_raw_values,
        )


@dataclass(frozen=True)
class MappingConfig:
    node_mappings: dict[str, str]
    name_rewrites: list[dict[str, str]]
    kind_aliases: dict[str, str]

    @staticmethod
    def empty(config: AnalyzerConfig) -> MappingConfig:
        return MappingConfig(
            node_mappings={},
            name_rewrites=[],
            kind_aliases=config.kind_aliases or {},
        )

    @staticmethod
    def from_file(path: Path | None, config: AnalyzerConfig) -> MappingConfig:
        if path is None:
            return MappingConfig.empty(config)

        data = json.loads(path.read_text(encoding="utf-8"))
        mappings: dict[str, str] = {}
        for item in data.get("node_mappings", []):
            left = item.get("stonebranch") or item.get("left") or item.get("source")
            right = item.get("jil") or item.get("right") or item.get("target")
            if left and right:
                mappings[str(left)] = str(right)

        # Also support simple object form: {"mappings": {"left": "right"}}
        for left, right in data.get("mappings", {}).items():
            mappings[str(left)] = str(right)

        return MappingConfig(
            node_mappings=mappings,
            name_rewrites=list(data.get("name_rewrites", data.get("name_rules", []))),
            kind_aliases=data.get("kind_aliases", config.kind_aliases or {}),
        )
