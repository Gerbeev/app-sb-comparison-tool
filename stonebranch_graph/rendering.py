from __future__ import annotations


def mmd_id(value: str) -> str:
    """Return a stable Mermaid-safe node identifier."""

    return "n_" + "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in value)


def escape_mmd(value: object) -> str:
    """Escape labels for Mermaid flowchart output."""

    return str(value).replace('"', "'").replace("|", "/")


def escape_dot(value: object) -> str:
    """Escape labels and identifiers for Graphviz DOT output."""

    return str(value).replace("\\", "\\\\").replace('"', '\\"')
