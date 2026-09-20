"""Price history, computed rather than accumulated.

A market normally has to wait to have a chart. This one does not: the engine
takes an as-of date, so running it backwards over a career produces the real
price series it would have had - every award and release landing on the day it
actually landed. Day one of the site ships with years of history.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import NamedTuple

from .engine import value_person
from .models import Person

MONTH = timedelta(days=30.44 * 1)


class Point(NamedTuple):
    on: date
    price: float


def month_starts(years: int, as_of: date) -> list[date]:
    months = []
    year, month = as_of.year, as_of.month
    for _ in range(years * 12):
        months.append(date(year, month, 1))
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return list(reversed(months))


def series(person: Person, years: int = 5, as_of: date | None = None) -> list[Point]:
    """Monthly prices over the last `years`, ending today."""
    as_of = as_of or date.today()
    points = [Point(d, value_person(person, d).price) for d in month_starts(years, as_of)]
    points.append(Point(as_of, value_person(person, as_of).price))
    return points


def change(points: list[Point], days: int) -> float | None:
    """Percentage change over a trailing window, or None if history is too short."""
    if len(points) < 2:
        return None
    cutoff = points[-1].on - timedelta(days=days)
    earlier = [p for p in points if p.on <= cutoff]
    if not earlier or earlier[-1].price <= 0:
        return None
    return points[-1].price / earlier[-1].price - 1


def career_start(person: Person) -> date | None:
    """The day this career began, as the data has it.

    Earliest credit or earliest award, whichever came first. A person with
    neither has no career to draw.
    """
    dates = [c.release_date for c in person.credits if c.release_date]
    dates += [a.awarded_on for a in person.awards if a.awarded_on]
    return min(dates) if dates else None


def career_before(person: Person, edge: date, step: int = 91,
                  limit: int = 320) -> list[Point]:
    """The part of a career that happened before the market started recording.

    The seeded history only reaches back ten years, so "All" and "10 years"
    drew the same picture for everyone - and for someone who has been working
    since 1959 that is not all of it. Prices are a function of the date, so the
    missing decades can be computed rather than stored: quarterly, because
    nobody needs a fortnightly reading of 1974, and because the recent years
    the seed does hold are spliced on after this.
    """
    start = career_start(person)
    if start is None or start >= edge:
        return []
    span = (edge - start).days
    step = max(step, -(-span // limit))      # ceiling division
    days, cursor = [], start
    while cursor < edge:
        days.append(cursor)
        cursor += timedelta(days=step)
    return [Point(d, value_person(person, d).price) for d in days]
