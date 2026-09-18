"""The interface every data source implements.

The engine never imports a vendor client directly. Swapping OMDb for a licensed
replacement, or adding RT Audience and Letterboxd if either is ever licensed,
is a new class here plus a backfill - not a rewrite.
"""

from __future__ import annotations

import os
import time
from typing import Any, Optional

import requests

from .cache import Cache


class SourceError(RuntimeError):
    pass


class MissingKey(SourceError):
    pass


class HTTPSource:
    """Shared HTTP plumbing: an API key, a cache, and a rate limit."""

    name = "source"
    env_var = ""
    base_url = ""
    min_interval = 0.0     # seconds between requests

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get(self.env_var, "")
        self.cache = Cache(self.name)
        self._last_call = 0.0

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def require_key(self) -> None:
        if not self.available:
            raise MissingKey(
                f"{self.name} needs {self.env_var}. Copy .env.example to .env and add it."
            )

    def _throttle(self) -> None:
        if self.min_interval:
            wait = self.min_interval - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
        self._last_call = time.monotonic()

    def get(self, path: str, params: dict[str, Any], cache_key: str) -> Any:
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        self.require_key()
        self._throttle()
        response = requests.get(f"{self.base_url}{path}", params=params, timeout=20)
        if response.status_code == 429:
            time.sleep(2.0)
            response = requests.get(f"{self.base_url}{path}", params=params, timeout=20)
        response.raise_for_status()

        payload = response.json()
        self.cache.set(cache_key, payload)
        return payload
