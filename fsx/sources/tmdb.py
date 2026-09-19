"""TMDB: people, credits, billing order, runtime, budget and revenue.

Free for non-commercial use at 40 requests per 10 seconds; commercial terms are
negotiated directly. Budget and revenue are community-entered and unreliable
below roughly $10M, so a missing budget means "no box office score" rather than
a guess - reception and awards carry those credits instead.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from ..models import Credit, Person
from .base import HTTPSource

PRINCIPAL_CAST = 20      # how deep a billed cast we treat as "principal"


def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


class TMDB(HTTPSource):
    name = "tmdb"
    env_var = "TMDB_API_KEY"
    token_env_var = "TMDB_READ_ACCESS_TOKEN"
    base_url = "https://api.themoviedb.org/3"
    min_interval = 0.26          # ~40 requests / 10s with headroom

    @property
    def auth(self) -> dict[str, str]:
        """v4 bearer auth is what TMDB prefers; the v3 key still works as a
        query parameter. When a token is present the key is left out entirely."""
        return {} if self.token else {"api_key": self.api_key}

    def search_person(self, name: str) -> Optional[dict[str, Any]]:
        data = self.get("/search/person", {**self.auth, "query": name},
                        f"search:{name.lower()}")
        results = data.get("results") or []
        return results[0] if results else None

    def person_imdb_id(self, person_id: int) -> Optional[str]:
        """Needed to resolve the person on Wikidata. Matching on name collides."""
        data = self.get(f"/person/{person_id}/external_ids", dict(self.auth),
                        f"ext:{person_id}")
        return data.get("imdb_id")

    def person_credits(self, person_id: int) -> dict[str, Any]:
        return self.get(f"/person/{person_id}/movie_credits",
                        dict(self.auth), f"credits:{person_id}")

    def movie(self, movie_id: int) -> dict[str, Any]:
        return self.get(f"/movie/{movie_id}", dict(self.auth), f"movie:{movie_id}")

    def movie_cast_size(self, movie_id: int) -> int:
        data = self.get(f"/movie/{movie_id}/credits", dict(self.auth),
                        f"cast:{movie_id}")
        return min(len(data.get("cast") or []), PRINCIPAL_CAST) or PRINCIPAL_CAST

    # ------------------------------------------------------------------ build
    def build_person(self, name: str, as_director: bool = False,
                     max_credits: int = 60) -> Optional[Person]:
        """Assemble a Person with everything TMDB knows. Review scores are layered
        on afterwards by the OMDb source, keyed on imdb_id."""
        found = self.search_person(name)
        if not found:
            return None

        person = Person(name=found.get("name", name), tmdb_id=found["id"],
                        is_director=as_director)
        credits_payload = self.person_credits(found["id"])
        entries = credits_payload.get("crew" if as_director else "cast") or []
        if as_director:
            entries = [e for e in entries if e.get("job") == "Director"]

        entries = [e for e in entries if _parse_date(e.get("release_date"))]
        entries.sort(key=lambda e: e["release_date"], reverse=True)

        for entry in entries[:max_credits]:
            released = _parse_date(entry.get("release_date"))
            if not released or released > date.today():
                continue

            detail = self.movie(entry["id"])
            runtime = detail.get("runtime") or 0

            credit = Credit(
                title=entry.get("title", "?"),
                release_date=released,
                is_director=as_director,
                billing_order=None if as_director else entry.get("order"),
                cast_size=None if as_director else self.movie_cast_size(entry["id"]),
                budget=detail.get("budget") or None,
                worldwide_gross=detail.get("revenue") or None,
            )
            credit.tmdb_id = entry["id"]                      # type: ignore[attr-defined]
            credit.imdb_id = detail.get("imdb_id")            # type: ignore[attr-defined]
            credit.runtime_minutes = runtime                  # type: ignore[attr-defined]
            person.credits.append(credit)

        return person
