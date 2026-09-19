"""On-disk JSON cache.

Scores are cached permanently on first fetch, so an OMDb outage degrades new
films only and never disturbs an existing price. That is the whole mitigation
for having three of the game's most important numbers behind one small service.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Optional

CACHE_DIR = Path(__file__).resolve().parents[2] / ".cache"


class Cache:
    def __init__(self, namespace: str, directory: Path | None = None):
        self.dir = (directory or CACHE_DIR) / namespace
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode()).hexdigest()[:24]
        return self.dir / f"{digest}.json"

    def get(self, key: str) -> Optional[Any]:
        path = self._path(key)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    def set(self, key: str, value: Any) -> None:
        try:
            self._path(key).write_text(json.dumps(value))
        except OSError:
            pass    # a cache miss is never fatal
