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

# --- Cross-system comparison scopes -----------------------------------------
#
# Both parsers intentionally build rich graphs (reference nodes, command-hash
# artifact nodes, trigger/credential objects, and so on) for exploration.
# Cross-system comparison, however, must only match things that represent the
# same *essence* in both schedulers. These sets define that contract.

# Job-like kinds: schedulable objects that must migrate 1:1.
# AutoSys box <-> Stonebranch workflow, AutoSys job <-> Stonebranch task,
# AutoSys file-watcher job <-> Stonebranch file-monitor task.
JOB_LIKE_KINDS = {KIND_TASK, KIND_BOX, KIND_WORKFLOW, KIND_FILE_WATCHER}

# Infrastructure kinds: JIL cannot define them, it can only reference them
# (machine:, calendar:, command variables, watch_file:). A JIL reference is
# therefore compared against a Stonebranch definition or reference.
INFRASTRUCTURE_KINDS = {KIND_AGENT, KIND_AGENT_CLUSTER, KIND_CALENDAR, KIND_VARIABLE, KIND_FILE}

# Artifact kinds: internal helper nodes named by content hashes (commands).
# Commands are compared at attribute level (strict + semantic hash), never as
# graph objects.
ARTIFACT_NODE_KINDS = {KIND_COMMAND}

# Stonebranch-only kinds: object types that AutoSys JIL cannot express at all.
# They are reported as informational, never as migration mismatches.
SYSTEM_SPECIFIC_KINDS = {KIND_TRIGGER, KIND_CREDENTIAL, KIND_CONNECTION, KIND_EMAIL_TEMPLATE, KIND_SCRIPT}

# Relations expressible in BOTH systems: only these participate in the edge
# diff and the edge match rate.
COMPARABLE_EDGE_RELATIONS = (
    DEPENDENCY_RELATIONS
    | {
        REL_CONTAINS,
        REL_RUNS_ON,
        REL_RUNS_ON_CLUSTER,
        REL_SUCCESSOR_OF,
        REL_USES_CALENDAR,
        REL_EXCLUDES_CALENDAR,
        REL_WATCHES_FILE,
        REL_USES_VARIABLE,
    }
)

# Relations only one scheduler can express (Stonebranch triggers, credentials,
# connections, scripts, email templates). Reported as informational counts.
ONE_SIDED_EDGE_RELATIONS = {
    REL_STARTS,
    REL_USES_CREDENTIAL,
    REL_USES_CONNECTION,
    REL_USES_EMAIL_TEMPLATE,
    REL_RUNS_SCRIPT,
}

# Relations excluded from edge comparison entirely: commands are compared at
# attribute level and deep-scan references are speculative.
ARTIFACT_EDGE_RELATIONS = {REL_RUNS_COMMAND, REL_REFERENCES}
