"""TMDB: people, credits, billing order, runtime, budget and revenue.

Free for non-commercial use at 40 requests per 10 seconds; commercial terms are
negotiated directly. Budget and revenue are community-entered and unreliable
below roughly $10M, so a missing budget means "no box office score" rather than
a guess - reception and awards carry those credits instead.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Optional

from ..models import Credit, Person
from .base import HTTPSource

PRINCIPAL_CAST = 20      # how deep a billed cast we treat as "principal"


def appearance_of(character: Optional[str]) -> str:
    """What kind of appearance TMDB is describing, from the character field.

    "Self - Narrator (voice)", "Self (archive footage)", "Self", "Ethan Hunt".
    A fifth of the corpus is one of the first three, and scoring those as parts
    is how a documentary about someone reads as a film they led.
    """
    text = (character or "").lower()
    if "archive" in text:
        return "archive"
    if "narrat" in text:
        return "narration"
    if re.match(r"^\s*(self|himself|herself|themself|themselves)\b", text):
        return "self"
    return "role"


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

    # A filmography is the one thing here that is never finished. Cached for
    # good, a stock could never learn that its owner had released something -
    # which is most of what the game is supposed to price.
    CREDITS_MAX_AGE_DAYS = 7

    def person_credits(self, person_id: int) -> dict[str, Any]:
        return self.get(f"/person/{person_id}/movie_credits",
                        dict(self.auth), f"credits:{person_id}",
                        max_age_days=self.CREDITS_MAX_AGE_DAYS)

    def movie(self, movie_id: int) -> dict[str, Any]:
        return self.get(f"/movie/{movie_id}", dict(self.auth), f"movie:{movie_id}")

    # TMDB release types: 1 premiere, 2 limited theatrical, 3 theatrical,
    # 4 digital, 5 physical, 6 TV.
    def release_shape(self, movie_id: int, country: str = "US"
                      ) -> tuple[Optional[str], Optional[int]]:
        """Return (release_kind, theatrical-to-digital window in days)."""
        data = self.get(f"/movie/{movie_id}/release_dates", dict(self.auth),
                        f"releases:{movie_id}")
        block = next((r for r in data.get("results", [])
                      if r.get("iso_3166_1") == country), None)
        if block is None:
            return None, None

        first: dict[int, str] = {}
        for entry in block.get("release_dates", []):
            kind, when = entry.get("type"), (entry.get("release_date") or "")[:10]
            if kind and when and when < first.get(kind, "9999"):
                first[kind] = when

        wide, limited, digital = first.get(3), first.get(2), first.get(4)
        theatrical = wide or limited
        window = None
        if theatrical and digital:
            window = (_parse_date(digital) - _parse_date(theatrical)).days

        if wide:
            release_kind = "wide"
        elif limited:
            release_kind = "limited"
        elif digital:
            release_kind = "digital"
        else:
            release_kind = None
        return release_kind, window

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

        # max_credits counts WORK, not lines on a filmography. It used to take
        # the most recent N of everything, and for a veteran most of those are
        # documentaries about them: Harrison Ford's window reached back only to
        # 2010, so Raiders, Witness and Air Force One were never fetched at
        # all, and he priced below people half his career. Across the roster
        # that dropped 4,803 real films - 100 of De Niro's 123.
        if not as_director:
            entries = [e for e in entries
                       if appearance_of(e.get("character")) in ("role", "narration")]
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
                appearance=("role" if as_director
                            else appearance_of(entry.get("character"))),
            )
            credit.release_kind, credit.digital_window_days = \
                self.release_shape(entry["id"])
            credit.tmdb_id = entry["id"]                      # type: ignore[attr-defined]
            credit.imdb_id = detail.get("imdb_id")            # type: ignore[attr-defined]
            credit.runtime_minutes = runtime                  # type: ignore[attr-defined]
            person.credits.append(credit)

        return person
