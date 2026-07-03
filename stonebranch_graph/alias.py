"""Logical-id aliases for skeleton comparison.

Alias files map per-system native object names to skeleton logical ids. Native
names are matched case-insensitively after :func:`core.normalize_name`. Alias
values containing ``/`` are treated as full containment-path logical ids and are
used verbatim by builders; values without ``/`` are bare leaves that participate
in the builder's normal path derivation.

``plumbing`` entries mark dependency helper jobs, such as AutoSys fan-in gates.
Entries are exact native names unless they end with ``*``, in which case they
match any normalized native name with that prefix.

``merge`` is an optional per-system allow-list of logical ids
(``{"<system>": ["logicalId", ...]}``) that are *intentionally* shared by more
than one native object (legitimate N1 aliasing). Id collisions on an
allow-listed logical id are downgraded from a risk to informational; any other
collision indicates an alias/id error and must be surfaced.
"""

from __future__ import annotations

import json
from bisect import bisect_right
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from stonebranch_graph.core import normalize_name

_TOP_LEVEL_KEYS = frozenset({"version", "logical_ids", "plumbing", "merge"})


@dataclass
class AliasUsage:
    """Lookup accounting for alias diagnostics."""

    logical_hits: set[tuple[str, str]] = field(default_factory=set)
    logical_misses: set[tuple[str, str]] = field(default_factory=set)
    plumbing_hits: set[tuple[str, str]] = field(default_factory=set)
    plumbing_misses: set[tuple[str, str]] = field(default_factory=set)


@dataclass
class AliasTable:
    """Per-system native-name alias table used by skeleton builders."""

    logical_ids: dict[str, dict[str, str]] = field(default_factory=dict)
    plumbing_exact: dict[str, set[str]] = field(default_factory=dict)
    plumbing_glob_prefixes: dict[str, tuple[str, ...]] = field(default_factory=dict)
    plumbing_glob_lengths: dict[str, tuple[int, ...]] = field(default_factory=dict)
    native_names: dict[tuple[str, str], str] = field(default_factory=dict)
    merge_allow: dict[str, set[str]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    usage: AliasUsage = field(default_factory=AliasUsage)

    @classmethod
    def from_file(cls, path: Path | None) -> AliasTable:
        """Load an alias table from ``path`` or return an empty table."""

        if path is None:
            return cls()
        if not path.exists():
            return cls(warnings=[f"Alias table file does not exist: {path}"])

        text = path.read_text(encoding="utf-8")
        if not text.strip():
            return cls()

        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError(f"Alias table must be a JSON object: {path}")

        warnings = [
            f"Unknown alias table top-level key ignored: {key}"
            for key in sorted(set(data) - _TOP_LEVEL_KEYS)
        ]
        return cls._from_data(data, warnings=warnings)

    @classmethod
    def _from_data(cls, data: dict[str, Any], *, warnings: list[str] | None = None) -> AliasTable:
        logical_ids: dict[str, dict[str, str]] = {}
        native_names: dict[tuple[str, str], str] = {}
        for system, entries in _object_items(data.get("logical_ids", {})):
            system_key = _key(system)
            system_map: dict[str, str] = {}
            for native_name, logical_id in _object_items(entries):
                native_key = _key(native_name)
                system_map[native_key] = str(logical_id).strip("/")
                native_names[(system_key, native_key)] = str(native_name)
            logical_ids[system_key] = system_map

        plumbing_exact: dict[str, set[str]] = {}
        plumbing_glob_prefixes: dict[str, tuple[str, ...]] = {}
        plumbing_glob_lengths: dict[str, tuple[int, ...]] = {}
        for system, entries in _object_items(data.get("plumbing", {})):
            system_key = _key(system)
            exact: set[str] = set()
            prefixes: set[str] = set()
            if isinstance(entries, list):
                for item in entries:
                    native = _key(str(item))
                    if native.endswith("*"):
                        prefixes.add(native[:-1])
                    else:
                        exact.add(native)
            plumbing_exact[system_key] = exact
            plumbing_glob_prefixes[system_key] = tuple(sorted(prefixes))
            plumbing_glob_lengths[system_key] = tuple(sorted({len(prefix) for prefix in prefixes}))

        merge_allow: dict[str, set[str]] = {}
        for system, entries in _object_items(data.get("merge", {})):
            system_key = _key(system)
            if not isinstance(entries, list):
                continue
            merge_allow[system_key] = {_key(str(item)).strip("/") for item in entries}

        return cls(
            logical_ids=logical_ids,
            plumbing_exact=plumbing_exact,
            plumbing_glob_prefixes=plumbing_glob_prefixes,
            plumbing_glob_lengths=plumbing_glob_lengths,
            native_names=native_names,
            merge_allow=merge_allow,
            warnings=list(warnings or []),
        )

    def logical_id(self, system: str, native_name: str) -> str | None:
        """Return a configured logical id for ``native_name`` in ``system``."""

        system_key = _key(system)
        native_key = _key(native_name)
        logical = self.logical_ids.get(system_key, {}).get(native_key)
        lookup = (system_key, native_key)
        if logical is None:
            self.usage.logical_misses.add(lookup)
            return None
        self.usage.logical_hits.add(lookup)
        return logical

    def is_plumbing(self, system: str, native_name: str) -> bool:
        """Return whether ``native_name`` is configured as dependency plumbing."""

        system_key = _key(system)
        native_key = _key(native_name)
        lookup = (system_key, native_key)
        if native_key in self.plumbing_exact.get(system_key, set()) or self._matches_plumbing_glob(
            system_key, native_key
        ):
            self.usage.plumbing_hits.add(lookup)
            return True
        self.usage.plumbing_misses.add(lookup)
        return False

    def is_merge_allowed(self, system: str, logical_id: str) -> bool:
        """Return whether ``logical_id`` is allow-listed for intentional merges."""

        system_key = _key(system)
        id_key = _key(logical_id).strip("/")
        return id_key in self.merge_allow.get(system_key, set())

    def unused_entries(self) -> list[tuple[str, str]]:
        """Return configured logical-id aliases that were never used."""

        unused = []
        for system, entries in self.logical_ids.items():
            for native_key in entries:
                if (system, native_key) not in self.usage.logical_hits:
                    unused.append((system, self.native_names[(system, native_key)]))
        return sorted(unused)

    def _matches_plumbing_glob(self, system_key: str, native_key: str) -> bool:
        prefixes = self.plumbing_glob_prefixes.get(system_key, ())
        if not prefixes:
            return False

        for length in self.plumbing_glob_lengths.get(system_key, ()):
            if length > len(native_key):
                break
            candidate = native_key[:length]
            index = bisect_right(prefixes, candidate)
            if index and prefixes[index - 1] == candidate:
                return True
        return False


def _object_items(value: Any) -> list[tuple[str, Any]]:
    if not isinstance(value, dict):
        return []
    return [(str(key), item) for key, item in value.items()]


def _key(value: str) -> str:
    return normalize_name(str(value)).lower()
