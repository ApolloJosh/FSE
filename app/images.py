"""Headshots and posters, from an index built out of the fetch cache.

The engine only ever wanted numbers, so the backfill threw away every image
path it downloaded. `scripts/build_images.py` reads them back out of the cache
and writes `data/images.json`; this reads that, and answers two questions:
what does this person look like, and what did this film's poster look like.

Both answers are optional. A missing face or poster is a layout the page has
to handle anyway - the index is 96% of credited films, not all of them - so
every accessor returns None rather than a placeholder URL, and the templates
decide what an absence looks like.
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path

INDEX = Path(__file__).resolve().parent.parent / "data" / "images.json"

# Small enough to be sharp on a retina thumbnail, small enough that a page with
# forty of them is not a megabyte of pictures.
FACE_SIZE = "w185"
POSTER_SIZE = "w154"
POSTER_TINY = "w92"
POSTER_LARGE = "w342"

_CACHE: dict = {}


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(text.lower().split())


def _index() -> dict:
    """Parsed once per version of the file, like the snapshot."""
    try:
        stat = INDEX.stat()
    except OSError:
        return {}
    stamp = (stat.st_mtime_ns, stat.st_size)
    if _CACHE.get("stamp") != stamp:
        try:
            data = json.loads(INDEX.read_text())
        except (OSError, ValueError):
            data = {}
        _CACHE.clear()
        _CACHE["stamp"] = stamp
        _CACHE["data"] = data
    return _CACHE.get("data") or {}


def _url(path: str | None, size: str) -> str | None:
    if not path:
        return None
    base = _index().get("base") or "https://image.tmdb.org/t/p/"
    return f"{base}{size}{path}"


def face(name: str, tmdb_id=None, size: str = FACE_SIZE) -> str | None:
    """A person's headshot. The id is tried first: two working actors can
    share a name, and the roster carries the id that tells them apart."""
    data = _index()
    path = None
    if tmdb_id:
        path = (data.get("people") or {}).get(str(tmdb_id))
    if not path:
        path = (data.get("people_by_name") or {}).get(_norm(name))
    return _url(path, size)


def poster(title: str, year, size: str = POSTER_SIZE) -> str | None:
    """A film's poster. Credits carry a title and a date, not an id, so the
    key is both - and where two films share them, the index already kept the
    one with more votes, which is the one a player means."""
    if not title:
        return None
    year = str(year or "")[:4]
    path = (_index().get("films") or {}).get(f"{_norm(title)}|{year}")
    return _url(path, size)


def have_any() -> bool:
    return bool(_index().get("people") or _index().get("films"))
