"""The six reference careers the engine's constants were fitted against.

These are synthetic career shapes, not real people. They exist so a change to
any constant immediately shows what it did to the price ladder - see
tests/test_reference_careers.py, which pins each one to the design doc.

Inputs are given as exact Reception Scores and Box Office Points (already in CP,
as the ladder in constants.py expresses them) rather than review scores and grosses, so the fit is reproducible and the derivation layers
are tested separately.
"""

from __future__ import annotations

from datetime import date, timedelta

from .models import Award, Credit, Person

AS_OF = date(2026, 1, 1)


def _credit(years_ago: float, rw: float, rs: float, bop: float, scale: float) -> Credit:
    return Credit(
        title=f"ref-{years_ago:.1f}",
        release_date=AS_OF - timedelta(days=round(years_ago * 365.25)),
        role_weight_override=rw,
        reception_override=rs,
        confidence_override=1.0,
        bop_override=bop,
        scale_override=scale,
    )


def _award(years_ago: float, raw_cp: float) -> Award:
    """A synthetic award worth an exact CP amount, via a one-off table entry."""
    from . import constants as K
    key = f"_ref_{raw_cp:g}"
    K.AWARD_TABLE.setdefault(key, (raw_cp, 0))
    return Award(key=key, year=AS_OF.year - int(years_ago),
                 awarded_on=AS_OF - timedelta(days=round(years_ago * 365.25)))


def debut() -> Person:
    return Person("ref: Debut", credits=[_credit(0.5, 0.30, 67.5, 120, 0.92)])


def journeyman() -> Person:
    return Person("ref: Journeyman", credits=[
        _credit(0.5 + i * 0.8, 0.35, 57, 48, 0.93) for i in range(15)])


def recognized() -> Person:
    return Person("ref: Recognized",
                  credits=[_credit(0.5 + i * 0.6, 0.45, 62, 90, 0.94) for i in range(25)],
                  awards=[_award(3, 340), _award(3, 130), _award(3, 110)])


def alister() -> Person:
    awards = []
    for years_ago in (22, 18, 14, 11, 8, 5, 2):
        awards.append(_award(years_ago, 400))
        for value in (140, 110, 130, 70):
            awards.append(_award(years_ago, value))
    awards.append(_award(5, 1350))      # a win, with the first-win 1.5x applied
    return Person("ref: A-List",
                  credits=[_credit(0.5 + i * 0.8, 0.75, 68, 210, 0.97) for i in range(35)],
                  awards=awards)


def legend() -> Person:
    awards = []
    for i in range(21):
        years_ago = 2 + i * 2.3
        awards.append(_award(years_ago, 380))
        awards.append(_award(years_ago, 110))
        awards.append(_award(years_ago, 140))
    awards.append(_award(44, 1350))
    awards.append(_award(30, 900))
    awards.append(_award(14, 900))
    return Person("ref: Legend",
                  credits=[_credit(0.5 + i * 0.82, 0.70, 66, 120, 0.95) for i in range(60)],
                  awards=awards)


def megastar() -> Person:
    awards = []
    for years_ago in (35, 32, 26, 9):
        awards.append(_award(years_ago, 400))
        awards.append(_award(years_ago, 110))
        awards.append(_award(years_ago, 130))
    return Person("ref: Megastar",
                  credits=[_credit(0.5 + i * 0.93, 0.90, 63, 360, 1.00) for i in range(45)],
                  awards=awards)


def reference_careers() -> list[Person]:
    return [debut(), journeyman(), recognized(), alister(), legend(), megastar()]


# The prices the design doc quotes, in Credits.
# Re-derived 2026-09-19 after the constants were refitted against the real
# 256-person roster. These are no longer targets the constants were fitted to -
# the real roster is the anchor now. They exist to catch accidental drift: if
# one moves, something changed and you should know why.
EXPECTED_PRICES = {
    "ref: Debut": 4.77,
    "ref: Journeyman": 12.88,
    "ref: Recognized": 35.84,
    "ref: A-List": 150.92,
    "ref: Legend": 209.4,
    "ref: Megastar": 181.05,
}
