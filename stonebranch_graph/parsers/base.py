from __future__ import annotations

from pathlib import Path
from typing import Protocol

from stonebranch_graph.core import Graph


class GraphParser(Protocol):
    def parse(self, input_path: Path) -> Graph:
        ...
