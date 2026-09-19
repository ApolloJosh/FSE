"""The puzzle corpus: the snapshot, inverted.

The engine's data is person -> credits. Every game here needs the opposite -
film -> cast - plus a popularity floor, because a puzzle nobody could solve is
worse than no puzzle. Built once and cached; it is derived data, never a
second source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from fsx.models import Credit, Person
from fsx.roles import role_weight
from fsx.site import slug as slugify
from fsx.store import load

MIN_VOTES = 20_000          # a film nobody has seen is not a fair puzzle
MIN_CAST = 2


@dataclass
class Film:
    key: str
    title: str
    year: int
    votes: int = 0
    budget: float | None = None
    gross: float | None = None
    rt_critics: float | None = None
    imdb: float | None = None
    metascore: float | None = None
    cast: list[tuple[str, float]] = field(default_factory=list)   # (person slug, RW)

    @property
    def multiple(self) -> float | None:
        if not self.budget or not self.gross:
            return None
        return self.gross / self.budget

    def billed(self) -> list[str]:
        return [slug for slug, _ in sorted(self.cast, key=lambda c: -c[1])]


@dataclass
class Corpus:
    films: dict[str, Film]
    people: dict[str, Person]
    names: dict[str, str]
    by_person: dict[str, list[str]] = field(default_factory=dict)

    def name(self, slug: str) -> str:
        return self.names.get(slug, slug)

    def films_with_money(self) -> list[Film]:
        return [f for f in self.films.values() if f.multiple is not None]

    def films_with_scores(self) -> list[Film]:
        return [f for f in self.films.values()
                if f.rt_critics is not None and f.imdb is not None]

    def neighbours(self, person_slug: str) -> set[str]:
        """Everyone who shared a film with this person."""
        out: set[str] = set()
        for film_key in self.by_person.get(person_slug, []):
            out.update(s for s, _ in self.films[film_key].cast)
        out.discard(person_slug)
        return out


def _film_key(credit: Credit) -> str:
    imdb_id = getattr(credit, "imdb_id", None)
    if imdb_id:
        return imdb_id
    return f"{credit.title.strip().lower()}::{credit.release_date.year}"


@lru_cache(maxsize=4)
def build(snapshot: str) -> Corpus:
    people_list, _ = load(Path(snapshot))
    films: dict[str, Film] = {}
    people: dict[str, Person] = {}
    names: dict[str, str] = {}
    by_person: dict[str, list[str]] = {}

    for person in people_list:
        person_slug = slugify(person.name)
        people[person_slug] = person
        names[person_slug] = person.name
        if person.is_director:
            continue                    # the games are about who is on screen

        for credit in person.credits:
            if credit.placeholder:
                continue        # a fixture stand-in, not a film anyone can name
            weight = role_weight(credit)
            if weight <= 0:
                continue
            key = _film_key(credit)
            film = films.get(key)
            if film is None:
                film = Film(key=key, title=credit.title,
                            year=credit.release_date.year,
                            votes=credit.imdb_votes or 0,
                            budget=credit.budget, gross=credit.worldwide_gross,
                            rt_critics=credit.rt_critics, imdb=credit.imdb,
                            metascore=credit.metascore)
                films[key] = film
            # Credits are per person, so the richest copy of a film wins.
            film.votes = max(film.votes, credit.imdb_votes or 0)
            film.budget = film.budget or credit.budget
            film.gross = film.gross or credit.worldwide_gross
            film.rt_critics = film.rt_critics if film.rt_critics is not None else credit.rt_critics
            film.imdb = film.imdb if film.imdb is not None else credit.imdb
            film.cast.append((person_slug, weight))
            by_person.setdefault(person_slug, []).append(key)

    # Drop the obscure, and anything with nobody to talk about.
    keep = {k: f for k, f in films.items() if f.votes >= MIN_VOTES}
    for key, film in list(keep.items()):
        film.cast = sorted(set(film.cast), key=lambda c: -c[1])
    by_person = {p: [k for k in keys if k in keep] for p, keys in by_person.items()}
    by_person = {p: keys for p, keys in by_person.items() if keys}

    return Corpus(films=keep, people=people, names=names, by_person=by_person)


def shared_films(corpus: Corpus, a: str, b: str) -> list[Film]:
    return [corpus.films[k] for k in corpus.by_person.get(a, [])
            if any(s == b for s, _ in corpus.films[k].cast)]
