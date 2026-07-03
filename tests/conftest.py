"""Shared pytest fixtures and helpers for the stonebranch_graph test suite."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stonebranch_graph.alias import AliasTable
from stonebranch_graph.config import AnalyzerConfig
from stonebranch_graph.parsers.autosys_jil import AutosysJilParser
from stonebranch_graph.parsers.stonebranch_json import StonebranchJsonParser
from stonebranch_graph.skeleton import Skeleton
from stonebranch_graph.skeleton_autosys import build_autosys_skeleton
from stonebranch_graph.skeleton_normalize import erase_plumbing
from stonebranch_graph.skeleton_stonebranch import build_stonebranch_skeleton

FIXTURES_DIR = Path(__file__).parent / "fixtures"
GOLDEN_DIR = FIXTURES_DIR / "golden"


@pytest.fixture()
def config() -> AnalyzerConfig:
    return AnalyzerConfig.default()


def build_jil_skeleton(
    jil_path: Path, *, config: AnalyzerConfig, alias: AliasTable | None = None, erase: bool = True
) -> Skeleton:
    """Parse a JIL fixture and build (optionally erasing plumbing) its skeleton."""

    jobs = AutosysJilParser(config).parse_raw(jil_path)
    skeleton = build_autosys_skeleton(jobs, alias=alias)
    return erase_plumbing(skeleton) if erase else skeleton


def build_sb_skeleton(
    sb_path: Path, *, config: AnalyzerConfig, alias: AliasTable | None = None, erase: bool = True
) -> Skeleton:
    """Parse a Stonebranch folder fixture and build (optionally erasing plumbing) its skeleton."""

    raw = StonebranchJsonParser(config).parse_raw(sb_path)
    skeleton = build_stonebranch_skeleton(raw, alias=alias, config=config)
    return erase_plumbing(skeleton) if erase else skeleton


@pytest.fixture()
def golden_alias() -> AliasTable:
    return AliasTable.from_file(GOLDEN_DIR / "alias.json")


@pytest.fixture()
def golden_jil_skeleton(config: AnalyzerConfig, golden_alias: AliasTable) -> Skeleton:
    return build_jil_skeleton(GOLDEN_DIR / "jil" / "PROD", config=config, alias=golden_alias)


@pytest.fixture()
def golden_sb_skeleton(config: AnalyzerConfig, golden_alias: AliasTable) -> Skeleton:
    return build_sb_skeleton(GOLDEN_DIR / "stonebranch" / "PROD", config=config, alias=golden_alias)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
