from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import traceback

RUN_LOG_FILE = "run.log"


def run_log_path(output_dir: Path) -> Path:
    return output_dir / RUN_LOG_FILE


def append_log(output_dir: Path, level: str, message: str) -> Path:
    """Append a single line to the workflow run log.

    Logging is intentionally dependency-free and best-effort. A logging failure
    must never hide the original parser/export/compare error from the user.
    """
    path = run_log_path(output_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        normalized = " ".join(str(message).splitlines()).strip()
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"{timestamp} [{level.upper()}] {normalized}\n")
    except Exception:
        # Do not let logging failures break the real workflow.
        pass
    return path


def log_info(output_dir: Path, message: str) -> Path:
    return append_log(output_dir, "INFO", message)


def log_warning(output_dir: Path, message: str) -> Path:
    return append_log(output_dir, "WARNING", message)


def log_error(output_dir: Path, message: str) -> Path:
    return append_log(output_dir, "ERROR", message)


def log_exception(output_dir: Path, operation: str, exc: Exception, *, include_traceback: bool = False) -> Path:
    path = log_error(output_dir, f"{operation} failed: {exc}")
    if include_traceback:
        append_log(output_dir, "ERROR", traceback.format_exc())
    return path


def log_graph_warnings(output_dir: Path, warnings: list[str], *, source: str = "graph") -> None:
    for warning in warnings:
        log_warning(output_dir, f"{source}: {warning}")


def log_comparison_risks(output_dir: Path, risks: list[str]) -> None:
    for risk in risks:
        log_warning(output_dir, f"comparison risk: {risk}")
