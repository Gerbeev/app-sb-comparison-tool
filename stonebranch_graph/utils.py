from __future__ import annotations

import re
from pathlib import Path
from collections.abc import Iterable
from typing import Any

from .config import SECRET_KEYWORDS
from .domain import (
    KIND_AGENT,
    KIND_BOX,
    KIND_CALENDAR,
    KIND_CONNECTION,
    KIND_CREDENTIAL,
    KIND_EMAIL_TEMPLATE,
    KIND_FILE_WATCHER,
    KIND_OBJECT,
    KIND_SCRIPT,
    KIND_TASK,
    KIND_TRIGGER,
    KIND_VARIABLE,
    KIND_WORKFLOW,
)


IGNORED_SOURCE_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".pytest_cache",
    "__pycache__",
    "node_modules",
    "venv",
    ".venv",
    "out",
}


def read_json_text(path: Path) -> str:
    """Read JSON-like text with the same legacy encoding fallback used for JIL."""
    return read_text_file(path)


def has_ignored_source_part(path: Path, root: Path) -> bool:
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        parts = path.parts
    return any(part.startswith(".") or part in IGNORED_SOURCE_DIR_NAMES for part in parts[:-1])


def discover_source_files(
    input_path: Path,
    *,
    extensions: Iterable[str],
    ignored_filenames: Iterable[str] = (),
) -> list[Path]:
    """Return deterministic source files while skipping generated/hidden trees.

    The parsers use this for large repository robustness: hidden VCS folders,
    Python caches, local output folders, and virtualenvs should not be scanned
    as workload source files.
    """
    normalized_extensions = {ext.lower() for ext in extensions}
    ignored = {name for name in ignored_filenames}
    if input_path.is_file():
        return [input_path] if input_path.suffix.lower() in normalized_extensions and input_path.name not in ignored else []

    root = input_path
    return sorted(
        path
        for path in input_path.rglob("*")
        if path.is_file()
        and path.suffix.lower() in normalized_extensions
        and path.name not in ignored
        and not path.name.startswith(".")
        and not has_ignored_source_part(path, root)
    )


def is_secret_key(key: str) -> bool:
    lower = key.lower().replace("-", "_")
    return any(secret in lower for secret in SECRET_KEYWORDS)


def read_text_file(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


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
        "universal_task": KIND_TASK,
        "windows_task": KIND_TASK,
        "linux_task": KIND_TASK,
        "workflow_task": KIND_TASK,
        "workflow": KIND_WORKFLOW,
        "universal_workflow": KIND_WORKFLOW,
        "job": KIND_TASK,
        "command_job": KIND_TASK,
        "box_job": KIND_BOX,
        "box": KIND_BOX,
        "file_watcher": KIND_FILE_WATCHER,
        "filewatcher": KIND_FILE_WATCHER,
        "fw": KIND_FILE_WATCHER,
        "machine": KIND_AGENT,
        "agent": KIND_AGENT,
        "calendar": KIND_CALENDAR,
        "credential": KIND_CREDENTIAL,
        "connection": KIND_CONNECTION,
        "trigger": KIND_TRIGGER,
        "variable": KIND_VARIABLE,
        "script": KIND_SCRIPT,
        "email_template": KIND_EMAIL_TEMPLATE,
    }
    return aliases.get(text, built_in.get(text, text or KIND_OBJECT))


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
