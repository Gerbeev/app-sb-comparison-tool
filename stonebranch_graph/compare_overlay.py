from __future__ import annotations

from pathlib import Path

from .comparison_model import Comparison
from .core import Graph
from .rendering import escape_mmd, mmd_id

def write_overlay_mermaid(path: Path, comparison: Comparison, stonebranch: Graph, jil: Graph) -> None:
    lines = ["flowchart LR", "  classDef sbOnly fill:#ffe6e6,stroke:#cc0000,stroke-width:1px;", "  classDef jilOnly fill:#e6ecff,stroke:#0047cc,stroke-width:1px;", "  classDef matched fill:#e9ffe6,stroke:#178a00,stroke-width:1px;"]
    for item in comparison.nodes.get("missing_in_jil", [])[:300]:
        lines.append(f'  {mmd_id("sb_" + item["canonical_key"])}["SB only: {escape_mmd(item["kind"] + ": " + item["name"])}"]:::sbOnly')
    for item in comparison.nodes.get("missing_in_stonebranch", [])[:300]:
        lines.append(f'  {mmd_id("jil_" + item["canonical_key"])}["JIL only: {escape_mmd(item["kind"] + ": " + item["name"])}"]:::jilOnly')
    for pair in comparison.nodes.get("matched", [])[:300]:
        sb = pair["stonebranch"]
        lines.append(f'  {mmd_id("matched_" + sb["canonical_key"])}["Matched: {escape_mmd(sb["kind"] + ": " + sb["name"])}"]:::matched')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
