"""On-disk JSON cache.

Scores are cached permanently on first fetch, so an OMDb outage degrades new
films only and never disturbs an existing price. That is the whole mitigation
for having three of the game's most important numbers behind one small service.

Not everything is permanent, though. A film's reviews and gross settle and stop
moving; a person's filmography does not, and caching it forever means a stock
can never learn that its owner released something. Those lookups pass
`max_age_days` and are stamped with a fetch time.
"""

from __future__ import annotations

import hashlib
import json
import time
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

    def get(self, key: str, max_age_days: Optional[float] = None) -> Optional[Any]:
        path = self._path(key)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return None

        stamped = isinstance(data, dict) and "_fetched" in data and "_value" in data
        if max_age_days is None:
            return data["_value"] if stamped else data
        if not stamped:
            # Written before this entry had an expiry, so its age is unknown.
            # Refetch once; it will be stamped from then on.
            return None
        if (time.time() - data["_fetched"]) / 86400 > max_age_days:
            return None
        return data["_value"]

    def set(self, key: str, value: Any, stamp: bool = False) -> None:
        payload = {"_fetched": time.time(), "_value": value} if stamp else value
        try:
            self._path(key).write_text(json.dumps(payload))
        except OSError:
            pass    # a cache miss is never fatal
