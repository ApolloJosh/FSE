"""Awards: the most valuable events in the game, and the only predictable ones.

Role weight does not apply here. An award is given to the person, not to their
share of the film, so it pays in full.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from . import constants as K
from .models import Award, Contribution, Person


def award_name(key: str) -> str:
    return K.AWARD_NAMES.get(key, key.replace("_", " ").title())


def _first_oscar_win(person: Person) -> Award | None:
    wins = [a for a in person.awards if a.won and a.key in K.OSCAR_KEYS]
    return min(wins, key=lambda a: a.awarded_on) if wins else None


def award_contributions(person: Person, as_of: date | None = None) -> list[Contribution]:
    """One Contribution per nomination and per win, plus any snub clawbacks."""
    out: list[Contribution] = []
    first_win = _first_oscar_win(person)
    critics_group_total = 0.0

    for award in person.awards:
        if award.key not in K.AWARD_TABLE:
            continue
        nom_cp, win_cp = K.AWARD_TABLE[award.key]

        if award.key == "critics_group":
            room = K.CRITICS_GROUP_CAP - critics_group_total
            if room <= 0:
                continue
            value = min(float(win_cp), room)
            critics_group_total += value
            out.append(Contribution("award",
                                    f"{award_name(award.key)} ({award.year})", value,
                                    award.awarded_on, is_award=True))
            continue

        if nom_cp:
            out.append(Contribution(
                "award", f"{award_name(award.key)} nomination ({award.year})",
                float(nom_cp), award.awarded_on, is_award=True))
        if award.won:
            value = float(win_cp)
            if first_win is not None and award is first_win:
                value *= K.FIRST_OSCAR_WIN_MULTIPLIER
            out.append(Contribution(
                "award", f"{award_name(award.key)} win ({award.year})", value,
                award.awarded_on, is_award=True))

    out.extend(snub_contributions(person, as_of))
    return out


def snub_contributions(person: Person, as_of: date | None = None) -> list[Contribution]:
    """Heavily precursed, then missed by the Academy: claw back 40% of the
    precursor nominations that set up the expectation."""
    by_year: dict[int, list[Award]] = defaultdict(list)
    for award in person.awards:
        by_year[award.year].append(award)

    as_of = as_of or date.today()
    month, day = K.OSCAR_NOMINATION_MONTH_DAY

    out: list[Contribution] = []
    for year, awards in by_year.items():
        announced = date(year + 1, month, day)
        if as_of < announced:
            continue     # nominations are not out yet; nothing has happened
        precursors = [a for a in awards if a.key in K.PRECURSOR_KEYS]
        if len(precursors) < K.SNUB_MIN_PRECURSORS:
            continue
        if any(a.key in K.OSCAR_KEYS for a in awards):
            continue

        paid = sum(K.AWARD_TABLE[a.key][0] for a in precursors)
        out.append(Contribution(
            "snub", f"Oscar snub {year}", -paid * K.SNUB_CLAWBACK,
            announced, is_award=True))
    return out
