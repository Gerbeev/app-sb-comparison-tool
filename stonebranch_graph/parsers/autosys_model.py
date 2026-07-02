from __future__ import annotations

from dataclasses import dataclass


@dataclass
class JilJob:
    name: str
    action: str
    attributes: dict[str, str]
    source_file: str
    start_line: int


def count_jobs_by_source_file(jobs: list[JilJob]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for job in jobs:
        counts[job.source_file] = counts.get(job.source_file, 0) + 1
    return counts
