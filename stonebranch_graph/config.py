from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json


STONEBRANCH_FOLDER_KIND_MAP = {
    "agent_clusters": "agent_cluster",
    "agents": "agent",
    "calendars": "calendar",
    "connections": "connection",
    "credentials": "credential",
    "email_templates": "email_template",
    "scripts": "script",
    "tasks": "task",
    "triggers": "trigger",
    "variables": "variable",
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
    "references_calendar": "uses_calendar",
    "references_variable": "uses_variable",
    "references_credential": "uses_credential",
    "references_connection": "uses_connection",
    "references_agent": "runs_on",
    "references_agent_cluster": "runs_on_cluster",
    "references_agentcluster": "runs_on_cluster",
    "references_script": "runs_script",
    "references_email_template": "uses_email_template",
    "references_emailtemplate": "uses_email_template",
    "references_task": "depends_on",
    "references_job": "depends_on",
    "references_predecessor": "depends_on_success",
    "references_successor": "successor_of",
    "references_trigger": "starts",
    "condition_success": "depends_on_success",
    "condition_done": "depends_on_done",
    "condition_failure": "depends_on_failure",
    "condition_terminated": "depends_on_terminated",
    "condition_notrunning": "depends_on_notrunning",
    "box_name": "contains",
    "machine": "runs_on",
    "calendar": "uses_calendar",
    "run_calendar": "uses_calendar",
    "exclude_calendar": "excludes_calendar",
    "references_command": "runs_command",
    "command": "runs_command",
    "watch_file": "watches_file",
}

KIND_ALIASES = {
    "job": "task",
    "command_job": "task",
    "cmd": "task",
    "fw": "file_watcher",
    "filewatcher": "file_watcher",
    "machine": "agent",
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
    def default() -> "AnalyzerConfig":
        return AnalyzerConfig(
            folder_kind_map=STONEBRANCH_FOLDER_KIND_MAP,
            relation_aliases=RELATION_ALIASES,
            kind_aliases=KIND_ALIASES,
        )

    @staticmethod
    def from_file(path: Path | None) -> "AnalyzerConfig":
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



    def with_runtime_flags(self, *, include_raw_values: bool | None = None) -> "AnalyzerConfig":
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
    def empty(config: AnalyzerConfig) -> "MappingConfig":
        return MappingConfig(
            node_mappings={},
            name_rewrites=[],
            kind_aliases=config.kind_aliases or {},
        )

    @staticmethod
    def from_file(path: Path | None, config: AnalyzerConfig) -> "MappingConfig":
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
