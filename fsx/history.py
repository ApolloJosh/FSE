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
