from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .config import SECRET_KEYWORDS


def is_secret_key(key: str) -> bool:
    lower = key.lower().replace("-", "_")
    return any(secret in lower for secret in SECRET_KEYWORDS)


def read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8-sig")


def first_string(data: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def normalized_kind(kind: str, aliases: dict[str, str] | None = None) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", kind.lower()).strip("_")
    aliases = aliases or {}
    built_in = {
        "universal_task": "task",
        "windows_task": "task",
        "linux_task": "task",
        "workflow_task": "task",
        "job": "task",
        "command_job": "task",
        "box_job": "box",
        "box": "box",
        "file_watcher": "file_watcher",
        "filewatcher": "file_watcher",
        "fw": "file_watcher",
        "machine": "agent",
        "agent": "agent",
        "calendar": "calendar",
        "credential": "credential",
        "connection": "connection",
        "trigger": "trigger",
        "variable": "variable",
        "script": "script",
        "email_template": "email_template",
    }
    return aliases.get(text, built_in.get(text, text or "object"))


def safe_metadata(value):
    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            if is_secret_key(str(key)):
                result[str(key)] = "[REDACTED]"
            else:
                result[str(key)] = safe_metadata(child)
        return result
    if isinstance(value, list):
        return [safe_metadata(x) for x in value]
    return value
