"""Daily puzzle generation.

Two rules shape all of this:

**Deterministic per day.** Everyone gets the same puzzle, because a daily game
people cannot compare notes on is just a quiz. The seed is a hash of the game
name and the date, so the same day always regenerates the same puzzle without
storing it.

**The answer never leaves the server.** A puzzle has a public half, which goes
to the browser, and a private half, which does not. Scoring happens here.
"""

from __future__ import annotations

import hashlib
import random
from collections import deque
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .corpus import Corpus, Film, build, shared_films

GAMES = ("six-degrees", "ladder", "box-office", "cast-gap")
WEEKLY = "slate"


@dataclass
class Puzzle:
    game: str
    on: date
    public: dict[str, Any]          # safe to send to a browser
    answer: Any                     # never sent
    max_guesses: int = 1
    note: str = ""


class NotEnoughData(Exception):
    """The corpus cannot make a fair puzzle today. Better than a broken one."""


def rng_for(game: str, on: date, salt: str = "") -> random.Random:
    digest = hashlib.sha256(f"{game}:{on.isoformat()}:{salt}".encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


# ------------------------------------------------------------------ six degrees
def shortest_path(corpus: Corpus, start: str, goal: str, cap: int = 5) -> list[str] | None:
    if start == goal:
        return [start]
    seen, queue = {start}, deque([[start]])
    while queue:
        path = queue.popleft()
        if len(path) > cap:
            return None
        for nxt in corpus.neighbours(path[-1]):
            if nxt == goal:
                return path + [nxt]
            if nxt not in seen:
                seen.add(nxt)
                queue.append(path + [nxt])
    return None


def six_degrees(corpus: Corpus, on: date) -> Puzzle:
    rng = rng_for("six-degrees", on)
    people = sorted(p for p in corpus.by_person if len(corpus.by_person[p]) >= 1)
    pairs = []
    for _ in range(400):
        a, b = rng.sample(people, 2) if len(people) >= 2 else (None, None)
        if a is None:
            break
        path = shortest_path(corpus, a, b)
        if path and 3 <= len(path) <= 5:      # two to four hops: solvable, not trivial
            pairs.append((a, b, path))
            if len(pairs) >= 8:
                break
    if not pairs:
        raise NotEnoughData("No two actors are connected closely enough today.")

    a, b, path = pairs[rng.randrange(len(pairs))]
    par = len(path) - 1
    return Puzzle(
        game="six-degrees", on=on,
        public={"from": corpus.name(a), "to": corpus.name(b),
                "from_slug": a, "to_slug": b, "par": par,
                "roster": sorted(corpus.name(p) for p in corpus.by_person)},
        answer={"from": a, "to": b, "par": par},
        max_guesses=3,
        note=f"Par is {par} {'hop' if par == 1 else 'hops'}.")


def check_chain(corpus: Corpus, chain: list[str]) -> tuple[bool, list[str]]:
    """Validate a chain of person slugs, returning the films that link them."""
    links = []
    for first, second in zip(chain, chain[1:]):
        shared = shared_films(corpus, first, second)
        if not shared:
            return False, links
        links.append(shared[0].title)
    return True, links


# ----------------------------------------------------------------------- ladder
def ladder(corpus: Corpus, on: date) -> Puzzle:
    rng = rng_for("ladder", on)
    candidates = [p for p, films in corpus.by_person.items() if len(films) >= 4]
    if not candidates:
        raise NotEnoughData("Nobody has enough credits for a ladder today.")

    who = candidates[rng.randrange(len(candidates))]
    films = [corpus.films[k] for k in corpus.by_person[who]]
    # Obscure first: the fun is in how few rungs you need.
    films.sort(key=lambda f: f.votes)
    rungs = films[:6]

    decoys = rng.sample([corpus.name(p) for p in corpus.by_person if p != who],
                        min(7, len(corpus.by_person) - 1))
    options = sorted(decoys + [corpus.name(who)])

    return Puzzle(
        game="ladder", on=on,
        public={"rungs": [{"title": f.title, "year": f.year} for f in rungs],
                "options": options},
        answer={"who": who, "name": corpus.name(who)},
        max_guesses=len(rungs),
        note="Top rung pays most. A wrong name costs a rung, same as asking for another film.")


# ------------------------------------------------------------------ box office
def box_office(corpus: Corpus, on: date) -> Puzzle:
    rng = rng_for("box-office", on)
    pool = [f for f in corpus.films_with_money() if f.gross and f.gross > 1_000_000]
    if len(pool) < 5:
        raise NotEnoughData("Not enough films with box office on file.")

    picked = rng.sample(pool, 5)
    ordered = sorted(picked, key=lambda f: -(f.gross or 0))
    shown = picked[:]
    rng.shuffle(shown)

    return Puzzle(
        game="box-office", on=on,
        public={"films": [{"title": f.title, "year": f.year, "key": f.key}
                          for f in shown]},
        answer={"order": [f.key for f in ordered],
                "gross": {f.key: f.gross for f in ordered}},
        note="Highest worldwide gross first.")


# -------------------------------------------------------------------- cast gap
def cast_gap(corpus: Corpus, on: date) -> Puzzle:
    rng = rng_for("cast-gap", on)
    pool = [f for f in corpus.films.values() if len(f.cast) >= 2]
    if not pool:
        raise NotEnoughData("No film on file has enough listed cast.")

    film = pool[rng.randrange(len(pool))]
    billed = film.billed()
    hidden = billed[rng.randrange(len(billed))]
    others = [s for s in billed if s != hidden]

    decoy_pool = [p for p in corpus.by_person if p not in billed]
    decoys = rng.sample(decoy_pool, min(3, len(decoy_pool)))
    options = sorted({corpus.name(hidden), *(corpus.name(d) for d in decoys)})

    return Puzzle(
        game="cast-gap", on=on,
        public={"title": film.title, "year": film.year,
                "shown": [corpus.name(s) for s in others], "options": options},
        answer={"who": hidden, "name": corpus.name(hidden)},
        max_guesses=2,
        note="One name is missing from the billing.")


# --------------------------------------------------------------- weekly: slate
def slate(corpus: Corpus, on: date) -> Puzzle:
    """Pick five names inside a budget whose films grossed the most.

    The weekend puzzle is an optimisation rather than a recall test, which is
    why it can carry a whole weekend.
    """
    rng = rng_for("slate", on)
    totals: dict[str, float] = {}
    for person_slug, keys in corpus.by_person.items():
        total = sum(corpus.films[k].gross or 0 for k in keys)
        if total > 0:
            totals[person_slug] = total
    if len(totals) < 8:
        raise NotEnoughData("Not enough people with box office on file.")

    pool = rng.sample(sorted(totals), min(12, len(totals)))

    # Price has to correlate with takings or there is no trade-off, but not
    # perfectly, or the puzzle is arithmetic rather than judgement. The square
    # root compresses a range that otherwise runs 1 to 65 - at which point the
    # dear names are decoration nobody can afford - and a seeded wobble makes
    # some of them genuine bargains and some of them traps.
    prices = {}
    for person_slug in pool:
        wobble = 0.75 + rng_for("slate-price", on, person_slug).random() * 0.55
        scaled = (totals[person_slug] / 1e8) ** 0.5 * 3 * wobble
        prices[person_slug] = max(1, round(scaled))

    ranked = sorted(prices.values())
    cheapest, dearest = sum(ranked[:5]), sum(ranked[-5:])
    # Enough to reach past the bargain bin, not enough to buy the top of it.
    budget = int(cheapest + (dearest - cheapest) * 0.45)
    # And never so tight that a name on the board cannot be bought at all:
    # four others at the floor price still have to fit beside the dearest.
    budget = max(budget, max(prices.values()) + 4)

    best, best_total = _best_slate(pool, prices, totals, budget)
    return Puzzle(
        game="slate", on=on,
        public={"budget": budget,
                "pool": [{"slug": p, "name": corpus.name(p), "price": prices[p]}
                         for p in sorted(pool, key=lambda p: -prices[p])]},
        answer={"prices": prices, "totals": totals, "budget": budget,
                "best": best, "best_total": best_total,
                "best_spend": sum(prices[p] for p in best)},
        note="Pick five. The highest combined worldwide gross inside the "
             "budget wins - so the dear names have to earn their price.")


def _best_slate(pool, prices, totals, budget, pick=5):
    """Brute force is fine at twelve choose five."""
    from itertools import combinations
    best, best_total = [], 0.0
    for combo in combinations(pool, pick):
        if sum(prices[p] for p in combo) > budget:
            continue
        total = sum(totals[p] for p in combo)
        if total > best_total:
            best, best_total = list(combo), total
    return best, best_total


GENERATORS = {
    "six-degrees": six_degrees,
    "ladder": ladder,
    "box-office": box_office,
    "cast-gap": cast_gap,
    "slate": slate,
}

TITLES = {
    "six-degrees": ("Six Degrees", "Connect two actors through films they shared."),
    "ladder": ("The Ladder", "Start at the top with one obscure film. Every extra film drops you a rung."),
    "box-office": ("Box Office Blind", "Rank five films by worldwide gross."),
    "cast-gap": ("Cast Gap", "One name is missing from the billing."),
    "slate": ("The Slate", "Build the highest-grossing cast inside a budget."),
}


def generate(game: str, on: date, snapshot: str) -> Puzzle:
    if game not in GENERATORS:
        raise KeyError(game)
    return GENERATORS[game](build(snapshot), on)
