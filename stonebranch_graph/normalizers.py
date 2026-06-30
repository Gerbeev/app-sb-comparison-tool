from __future__ import annotations

import re
import shlex

from .core import stable_hash


def normalize_command(command: str) -> str:
    compact = " ".join(str(command).split())
    if not compact:
        return ""
    try:
        # Keep behavior consistent for Stonebranch and JIL. posix=False is safer for Windows-like commands.
        parts = shlex.split(compact, posix=False)
        return " ".join(parts)
    except ValueError:
        return compact


def command_hash(command: str) -> str:
    return stable_hash(normalize_command(command), 16)


def command_evidence(command: str, *, include_raw_values: bool = False) -> str:
    if include_raw_values:
        return normalize_command(command)
    return command_hash(command)




def normalize_condition(condition: str) -> str:
    text = " ".join(str(condition).split())
    text = re.sub(r"\s*([&|()!])\s*", r"\1", text)
    return text.lower()


def condition_hash(condition: str) -> str:
    return stable_hash(normalize_condition(condition), 16)
