from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path


SETTINGS_FILE = Path(".stonebranch-tool-settings.json")


@dataclass
class TuiSettings:
    stonebranch_path: str = ""
    jil_path: str = ""
    stonebranch_graph_json: str = ""
    jil_graph_json: str = ""
    output_path: str = "out"
    stonebranch_pack_path: str = "out/stonebranch-pack"
    jil_pack_path: str = "out/jil-pack"
    compare_pack_path: str = "out/compare-pack"
    env: str = "PROD"
    mapping_path: str = ""
    include_raw_values: bool = False
    deep_scan: bool = False
    env_aware: bool = False


def load_tui_settings(settings_file: Path = SETTINGS_FILE) -> TuiSettings:
    if settings_file.exists():
        try:
            data = json.loads(settings_file.read_text(encoding="utf-8"))
            allowed_keys = set(asdict(TuiSettings()).keys())
            return TuiSettings(**{key: value for key, value in data.items() if key in allowed_keys})
        except Exception:
            return TuiSettings()
    return TuiSettings()


def save_tui_settings(settings: TuiSettings, settings_file: Path = SETTINGS_FILE) -> None:
    settings_file.write_text(json.dumps(asdict(settings), indent=2, ensure_ascii=False), encoding="utf-8")


def optional_path(value: str) -> Path | None:
    if not value:
        return None
    path = Path(value)
    return path if path.exists() else None


def path_exists(value: str) -> bool:
    return bool(value) and Path(value).exists()
