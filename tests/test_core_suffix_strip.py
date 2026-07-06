from __future__ import annotations

import pytest

from stonebranch_graph.core import (
    DEFAULT_SUFFIX_STRIP_PATTERNS,
    comparison_kind,
    strip_migration_suffixes,
)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        # -tm / _tm task-monitor suffix, case-insensitive.
        ("REAL_LOAD-tm", "REAL_LOAD"),
        ("REAL_LOAD_tm", "REAL_LOAD"),
        ("REAL_LOAD-TM", "REAL_LOAD"),
        ("real_load-Tm", "real_load"),
        # Explicit -taskmonitor / _taskmonitor marker.
        ("REAL_LOAD-taskmonitor", "REAL_LOAD"),
        ("REAL_LOAD_TASKMONITOR", "REAL_LOAD"),
        # Trailing content-hash suffix (8+ hex chars), - or _ delimited.
        ("REAL_ARCHIVE-a1b2c3d4e5f6", "REAL_ARCHIVE"),
        ("REAL_ARCHIVE_A1B2C3D4", "REAL_ARCHIVE"),
        ("REAL_ARCHIVE-deadbeef", "REAL_ARCHIVE"),
        # Chained suffixes: hash then -tm, stripped in repeated passes.
        ("REAL_PUBLISH-tm-a1b2c3d4e5f6", "REAL_PUBLISH"),
        ("REAL_PUBLISH_a1b2c3d4e5f6_tm", "REAL_PUBLISH"),
        # No-op cases: nothing to strip.
        ("JOB_C", "JOB_C"),
        ("BOX_MAIN", "BOX_MAIN"),
        ("", ""),
    ],
)
def test_strip_migration_suffixes_defaults(name: str, expected: str) -> None:
    assert strip_migration_suffixes(name) == expected


@pytest.mark.parametrize(
    "name",
    [
        "REAL_DECADE1",  # trailing "decade1" is 7 hex-ish chars, below the 8-char minimum
        "REAL_CAFE",  # short hex-looking tail, well below the minimum
        "REAL_TEAM",  # contains "tm"-adjacent letters but not the exact -tm/_tm suffix
        "ATM-REPORT",  # "atm" prefix, not a -tm/_tm *suffix*
    ],
)
def test_strip_migration_suffixes_does_not_over_strip(name: str) -> None:
    # Negative cases: legitimate names must survive unstripped so real object
    # names are never silently mangled into false-positive matches.
    assert strip_migration_suffixes(name) == name


def test_strip_migration_suffixes_custom_patterns() -> None:
    # Config-overridable: a project-specific suffix convention can be added
    # without touching code.
    assert strip_migration_suffixes("REAL_JOB-mig", patterns=[r"[-_]mig$"]) == "REAL_JOB"
    # Empty pattern list is a no-op.
    assert strip_migration_suffixes("REAL_JOB-tm", patterns=[]) == "REAL_JOB-tm"


def test_strip_migration_suffixes_is_pure() -> None:
    # Does not mutate global state / default pattern tuple.
    before = tuple(DEFAULT_SUFFIX_STRIP_PATTERNS)
    strip_migration_suffixes("REAL_JOB-tm-deadbeefcafe")
    assert tuple(DEFAULT_SUFFIX_STRIP_PATTERNS) == before


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("workflow", "box"),
        ("file_watcher", "task"),
        ("agent_cluster", "agent"),
        ("task", "task"),
        ("box", "box"),
        ("agent", "agent"),
    ],
)
def test_comparison_kind_collapses_migration_concepts(kind: str, expected: str) -> None:
    assert comparison_kind(kind) == expected
