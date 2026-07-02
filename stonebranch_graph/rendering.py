from __future__ import annotations


def escape_dot(value: object) -> str:
    """Escape labels and identifiers for Graphviz DOT output."""

    return str(value).replace("\\", "\\\\").replace('"', '\\"')
