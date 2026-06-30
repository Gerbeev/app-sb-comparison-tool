
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def run_cli(base: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "stonebranch_graph.cli", *args],
        cwd=base,
        capture_output=True,
        text=True,
        check=False,
    )


def test_example_compare(tmp_path: Path) -> None:
    base = Path(__file__).resolve().parents[1]
    out = tmp_path / "out"
    result = run_cli(
        base,
        "compare",
        "--stonebranch",
        str(base / "examples" / "stonebranch" / "PROD"),
        "--jil",
        str(base / "examples" / "jil" / "PROD"),
        "--env",
        "PROD",
        "-o",
        str(out),
    )
    assert result.returncode == 0, result.stderr
    comparison = json.loads((out / "compare" / "comparison.json").read_text(encoding="utf-8"))
    assert comparison["summary"]["matched_nodes"] >= 6
    assert comparison["summary"]["matched_edges"] >= 6


def test_no_description_false_script_reference(tmp_path: Path) -> None:
    base = Path(__file__).resolve().parents[1]
    sb = tmp_path / "sb" / "PROD"
    for folder in ["tasks", "calendars", "agents"]:
        (sb / folder).mkdir(parents=True, exist_ok=True)
    (sb / "tasks" / "JOB_A.json").write_text(
        json.dumps({"agentName": "machine01", "command": "echo hi", "description": "no refs"}),
        encoding="utf-8",
    )
    (sb / "calendars" / "CAL_A.json").write_text(
        json.dumps({"description": "business days"}), encoding="utf-8"
    )
    (sb / "agents" / "machine01.json").write_text(json.dumps({}), encoding="utf-8")

    jil = tmp_path / "jil"
    jil.mkdir()
    (jil / "x.jil").write_text(
        "insert_job: JOB_A\njob_type: c\nmachine: machine01\ncommand: echo hi\n",
        encoding="utf-8",
    )

    out = tmp_path / "out"
    result = run_cli(base, "compare", "--stonebranch", str(sb), "--jil", str(jil), "--env", "PROD", "-o", str(out))
    assert result.returncode == 0, result.stderr
    graph = json.loads((out / "stonebranch" / "graph.json").read_text(encoding="utf-8"))
    assert not any(n["name"] == "business days" for n in graph["nodes"])
    assert any(n["kind"] == "task" and n["name"] == "JOB_A" for n in graph["nodes"])
