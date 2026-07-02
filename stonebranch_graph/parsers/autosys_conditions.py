from __future__ import annotations

import re

from stonebranch_graph.domain import (
    REL_DEPENDS_ON,
    REL_DEPENDS_ON_DONE,
    REL_DEPENDS_ON_FAILURE,
    REL_DEPENDS_ON_NOTRUNNING,
    REL_DEPENDS_ON_SUCCESS,
    REL_DEPENDS_ON_TERMINATED,
)

CONDITION_RE = re.compile(
    r"\b(?P<event>s|success|d|done|f|failure|t|terminated|n|notrunning)\s*\(\s*(?P<body>[^)]+?)\s*\)",
    re.IGNORECASE,
)

CONDITION_EVENT_ALIASES = {
    "s": "success",
    "success": "success",
    "d": "done",
    "done": "done",
    "f": "failure",
    "failure": "failure",
    "t": "terminated",
    "terminated": "terminated",
    "n": "notrunning",
    "notrunning": "notrunning",
}

CONDITION_RELATIONS = {
    "success": REL_DEPENDS_ON_SUCCESS,
    "done": REL_DEPENDS_ON_DONE,
    "failure": REL_DEPENDS_ON_FAILURE,
    "terminated": REL_DEPENDS_ON_TERMINATED,
    "notrunning": REL_DEPENDS_ON_NOTRUNNING,
}


def parse_condition_refs(condition: str) -> list[tuple[str, str]]:
    refs: list[tuple[str, str]] = []
    for match in CONDITION_RE.finditer(condition):
        raw_event = match.group("event").lower()
        body = match.group("body").strip()
        job_name = body.split(",", 1)[0].strip().strip('"').strip("'")
        if not job_name:
            continue
        refs.append((CONDITION_EVENT_ALIASES.get(raw_event, raw_event), job_name))
    return refs


def condition_relation(event: str) -> str:
    return CONDITION_RELATIONS.get(event, REL_DEPENDS_ON)
