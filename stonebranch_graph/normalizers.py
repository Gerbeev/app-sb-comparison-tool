from __future__ import annotations

import re
import shlex
from typing import Any

from .core import stable_hash


VAR_REFERENCE_RE = re.compile(
    r"""
    (?:\$\$\{(?P<autosys_braced>[A-Za-z_][A-Za-z0-9_.-]*)\})
    |(?:\$\$(?P<autosys_plain>[A-Za-z_][A-Za-z0-9_.-]*))
    |(?:\$\{(?P<shell_braced>[A-Za-z_][A-Za-z0-9_.-]*)\})
    |(?:\$\((?P<shell_paren>[A-Za-z_][A-Za-z0-9_.-]*)\))
    |(?:%%(?P<autosys_percent>[A-Za-z_][A-Za-z0-9_.-]*))
    |(?:%(?P<windows_percent>[A-Za-z_][A-Za-z0-9_.-]*)%)
    |(?:\#(?P<hash_var>[A-Za-z_][A-Za-z0-9_.-]*)\#)
    |(?:\$(?P<shell_plain>[A-Za-z_][A-Za-z0-9_.-]*))
    """,
    re.VERBOSE,
)

ENV_ASSIGNMENT_RE = re.compile(
    r"(?i)(?P<prefix>(?:--?env|environment|app_env)\s*(?:=|:)?\s*)(?P<env_token>p\d+|en|0[a-z]{2}0|prod|production|dev|qa)\b"
)


SCRIPT_PATH_EXTENSIONS = {
    ".bat",
    ".cmd",
    ".ksh",
    ".ps1",
    ".py",
    ".pl",
    ".sh",
    ".sql",
}

SCRIPT_PATH_RE = re.compile(
    r"""
    (?P<path>
        (?:[A-Za-z]:[\\/]|/)
        [^"']*?[\\/]
        [^\s"']+?
        (?:\.bat|\.cmd|\.ksh|\.ps1|\.py|\.pl|\.sh|\.sql)
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


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


def normalize_command_variable_name(name: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", str(name).strip().lower()).strip("_")


def command_variable_names(command: str) -> list[str]:
    names: list[str] = []
    for match in VAR_REFERENCE_RE.finditer(normalize_command(command)):
        name = next((value for value in match.groupdict().values() if value), "")
        normalized = normalize_command_variable_name(name)
        if normalized and normalized not in names:
            names.append(normalized)
    return names



def script_path_basename(path: str) -> str:
    cleaned = str(path).strip().strip("\"'")
    normalized = cleaned.replace("\\", "/")
    return normalized.rsplit("/", 1)[-1]


def normalize_command_script_paths(command: str) -> str:
    """Normalize script base paths while preserving script filenames.

    This is intentionally conservative: only absolute Unix/Windows paths with a
    known script-like extension are folded into <SCRIPT_PATH>/<filename>. Data
    files and relative script names are left unchanged.
    """
    text = normalize_command(command)
    if not text:
        return ""

    def replace_path(match: re.Match[str]) -> str:
        basename = script_path_basename(match.group("path"))
        return f"<SCRIPT_PATH>/{basename}"

    try:
        tokens = shlex.split(text, posix=False)
    except ValueError:
        return SCRIPT_PATH_RE.sub(replace_path, text)
    return " ".join(SCRIPT_PATH_RE.sub(replace_path, token) for token in tokens)


def command_script_basenames(command: str) -> list[str]:
    """Return script filenames whose absolute base paths are normalized semantically."""
    text = normalize_command(command)
    if not text:
        return []
    try:
        tokens = shlex.split(text, posix=False)
    except ValueError:
        tokens = [text]

    basenames: list[str] = []
    for token in tokens:
        for match in SCRIPT_PATH_RE.finditer(token):
            basename = script_path_basename(match.group("path"))
            if basename and basename not in basenames:
                basenames.append(basename)
    return basenames


def command_env_tokens(command: str) -> list[str]:
    """Return env-like tokens normalized only in env assignment/argument contexts."""
    tokens: list[str] = []
    for match in ENV_ASSIGNMENT_RE.finditer(normalize_command(command)):
        token = normalize_command_variable_name(match.group("env_token"))
        if token and token not in tokens:
            tokens.append(token)
    return tokens


def command_normalization_diagnostics(command: str) -> dict[str, Any]:
    """Return safe diagnostics explaining semantic command normalization.

    The payload intentionally avoids raw command text. It exposes only variable
    names, env tokens in env-like contexts, script basenames, and hashes/previews
    needed to understand why strict and semantic command hashes differ.
    """
    variables = command_variable_names(command)
    env_tokens = command_env_tokens(command)
    script_basenames = command_script_basenames(command)
    semantic = normalize_command_semantic(command)

    reasons: list[str] = []
    if variables:
        reasons.append("variable_syntax")
    if env_tokens:
        reasons.append("environment_token")
    if script_basenames:
        reasons.append("script_path")
    if normalize_command(command) and not reasons:
        reasons.append("case_whitespace_or_quoting")

    return {
        "normalization_reasons": reasons,
        "variable_names": variables,
        "env_tokens": env_tokens,
        "script_basenames": script_basenames,
        "semantic_preview": semantic[:240],
        "semantic_preview_truncated": len(semantic) > 240,
    }


def normalize_command_semantic(command: str) -> str:
    """Normalize command text for cross-scheduler semantic comparison.

    The strict command hash still uses normalize_command(). This semantic form keeps
    argument order and variable names, but normalizes scheduler-specific variable
    wrappers such as ${DATE}, $${date}, %%DATE, %DATE%, and #DATE#.
    """
    text = normalize_command_script_paths(command)
    if not text:
        return ""

    def replace_var(match: re.Match[str]) -> str:
        name = next((value for value in match.groupdict().values() if value), "")
        normalized = normalize_command_variable_name(name)
        return f"<VAR:{normalized}>" if normalized else "<VAR>"

    text = VAR_REFERENCE_RE.sub(replace_var, text)
    text = ENV_ASSIGNMENT_RE.sub(lambda m: f"{m.group('prefix')}<ENV>", text)
    return " ".join(text.split()).lower()


def semantic_command_hash(command: str) -> str:
    return stable_hash(normalize_command_semantic(command), 16)


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
