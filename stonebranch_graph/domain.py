from __future__ import annotations

# Source systems persisted in graph.json and comparison reports.
SOURCE_STONEBRANCH = "stonebranch"
SOURCE_AUTOSYS_JIL = "autosys_jil"
SOURCE_AUTOSYS_JIL_ALIAS = "jil"
KNOWN_SOURCE_SYSTEMS = {SOURCE_STONEBRANCH, SOURCE_AUTOSYS_JIL, SOURCE_AUTOSYS_JIL_ALIAS}

# Normalized node kinds persisted in graph.json.
KIND_AGENT = "agent"
KIND_AGENT_CLUSTER = "agent_cluster"
KIND_BOX = "box"
KIND_CALENDAR = "calendar"
KIND_COMMAND = "command"
KIND_CONNECTION = "connection"
KIND_CREDENTIAL = "credential"
KIND_EMAIL_TEMPLATE = "email_template"
KIND_FILE = "file"
KIND_FILE_WATCHER = "file_watcher"
KIND_OBJECT = "object"
KIND_SCRIPT = "script"
KIND_TASK = "task"
KIND_TRIGGER = "trigger"
KIND_VARIABLE = "variable"
KIND_WORKFLOW = "workflow"

# Normalized edge relations persisted in graph.json.
REL_CONTAINS = "contains"
REL_DEPENDS_ON = "depends_on"
REL_DEPENDS_ON_DONE = "depends_on_done"
REL_DEPENDS_ON_FAILURE = "depends_on_failure"
REL_DEPENDS_ON_NOTRUNNING = "depends_on_notrunning"
REL_DEPENDS_ON_SUCCESS = "depends_on_success"
REL_DEPENDS_ON_TERMINATED = "depends_on_terminated"
REL_EXCLUDES_CALENDAR = "excludes_calendar"
REL_REFERENCES = "references"
REL_RUNS_COMMAND = "runs_command"
REL_RUNS_ON = "runs_on"
REL_RUNS_ON_CLUSTER = "runs_on_cluster"
REL_RUNS_SCRIPT = "runs_script"
REL_STARTS = "starts"
REL_SUCCESSOR_OF = "successor_of"
REL_USES_CALENDAR = "uses_calendar"
REL_USES_CONNECTION = "uses_connection"
REL_USES_CREDENTIAL = "uses_credential"
REL_USES_EMAIL_TEMPLATE = "uses_email_template"
REL_USES_VARIABLE = "uses_variable"
REL_WATCHES_FILE = "watches_file"

DEPENDENCY_RELATIONS = {
    REL_DEPENDS_ON,
    REL_DEPENDS_ON_SUCCESS,
    REL_DEPENDS_ON_DONE,
    REL_DEPENDS_ON_FAILURE,
    REL_DEPENDS_ON_TERMINATED,
    REL_DEPENDS_ON_NOTRUNNING,
}

CRITICAL_DEPENDENCY_RELATIONS = DEPENDENCY_RELATIONS | {REL_CONTAINS}
RUNTIME_TARGET_RELATIONS = {REL_RUNS_ON, REL_RUNS_ON_CLUSTER}
CALENDAR_RELATIONS = {REL_USES_CALENDAR, REL_EXCLUDES_CALENDAR}
SCHEDULE_RELATIONS = {REL_STARTS, REL_USES_CALENDAR, REL_EXCLUDES_CALENDAR}
COMMAND_RELATIONS = {REL_RUNS_COMMAND, REL_RUNS_SCRIPT}

PACK_CRITICAL_RELATIONS = (
    DEPENDENCY_RELATIONS
    | {REL_CONTAINS, REL_STARTS, REL_USES_CALENDAR, REL_RUNS_ON, REL_RUNS_ON_CLUSTER}
    | COMMAND_RELATIONS
)
