"""Persist fetched people to JSON.

Fetching is slow and rate-limited; rendering is fast. Splitting them means the
site rebuilds offline in seconds from a snapshot, the nightly job re-fetches
only when it wants to, and a bad render can never cost an API quota.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .models import Award, Credit, Person

SCHEMA = 1
CREDIT_FIELDS = [
    "title", "medium", "billing_order", "cast_size", "runtime_share",
    "series_role", "is_voice", "is_uncredited", "is_director", "placeholder", "release_kind", "digital_window_days",
    "role_weight_override", "ensemble_weight_sum",
    "rt_critics", "rt_audience", "imdb", "imdb_votes", "metascore", "letterboxd",
    "budget", "worldwide_gross", "streaming_viewers_28d",
    "reception_override", "confidence_override", "bop_override", "scale_override",
]


def _d(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _p(value: str | None) -> date | None:
    return datetime.strptime(value, "%Y-%m-%d").date() if value else None


def credit_to_dict(credit: Credit) -> dict[str, Any]:
    out = {f: getattr(credit, f) for f in CREDIT_FIELDS}
    out["release_date"] = _d(credit.release_date)
    out["imdb_id"] = getattr(credit, "imdb_id", None)
    return {k: v for k, v in out.items() if v is not None}


def credit_from_dict(raw: dict[str, Any]) -> Credit:
    kwargs = {f: raw.get(f) for f in CREDIT_FIELDS if f in raw}
    kwargs.setdefault("title", "?")
    credit = Credit(release_date=_p(raw["release_date"]), **kwargs)
    if raw.get("imdb_id"):
        credit.imdb_id = raw["imdb_id"]              # type: ignore[attr-defined]
    return credit


def person_to_dict(person: Person) -> dict[str, Any]:
    return {
        "name": person.name,
        "tmdb_id": person.tmdb_id,
        "is_director": person.is_director,
        "next_release": _d(person.next_release),
        "credits": [credit_to_dict(c) for c in person.credits],
        "awards": [{"key": a.key, "year": a.year, "awarded_on": _d(a.awarded_on),
                    "won": a.won, "category": a.category} for a in person.awards],
    }


def person_from_dict(raw: dict[str, Any]) -> Person:
    return Person(
        name=raw["name"],
        tmdb_id=raw.get("tmdb_id"),
        is_director=raw.get("is_director", False),
        next_release=_p(raw.get("next_release")),
        credits=[credit_from_dict(c) for c in raw.get("credits", [])],
        awards=[Award(key=a["key"], year=a["year"], awarded_on=_p(a["awarded_on"]),
                      won=a.get("won", False), category=a.get("category", ""))
                for a in raw.get("awards", [])],
    )


def save(people: list[Person], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema": SCHEMA,
        "fetched_on": date.today().isoformat(),
        "people": [person_to_dict(p) for p in people],
    }, indent=1))
    return path


def load(path: Path) -> tuple[list[Person], str]:
    payload = json.loads(path.read_text())
    if payload.get("schema") != SCHEMA:
        raise ValueError(f"{path} is schema {payload.get('schema')}, expected {SCHEMA}")
    return [person_from_dict(p) for p in payload["people"]], payload.get("fetched_on", "")
