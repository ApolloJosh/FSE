"""Two separate forces pull a price down.

Age decay is the slow erosion of a back catalogue: every past event loses value
with time, floored so a 1982 Oscar never becomes worthless. The idle multiplier
is what players actually feel: it bites while nothing is coming out, and it stops
the moment something does.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from . import constants as K


def tier_name(cp: float) -> str:
    """The label shown to players. Stepwise, by design: a stock is in one tier."""
    for threshold, name, _, _ in K.DECAY_TIERS:
        if cp <= threshold:
            return name
    return K.DECAY_TIERS[-1][1]


def decay_rates(cp: float) -> tuple[float, float]:
    """Return (annual age decay, annual idle rate), interpolated across tiers.

    Stepping these at the tier boundaries produced a cliff: a stock decaying out
    of A-List suddenly took the Established rate, so a five-year fade was worse
    than for a lower-tier stock that never moved. Rates are interpolated so a
    price slides smoothly while its displayed tier still steps.
    """
    anchors = [(0.0, K.DECAY_TIERS[0][2], K.DECAY_TIERS[0][3])]
    for threshold, _, age_rate, idle_rate in K.DECAY_TIERS:
        upper = 26000.0 if threshold == float("inf") else float(threshold)
        anchors.append((upper, age_rate, idle_rate))

    if cp <= anchors[0][0]:
        return anchors[0][1], anchors[0][2]
    for (lo, lo_age, lo_idle), (hi, hi_age, hi_idle) in zip(anchors, anchors[1:]):
        if cp <= hi:
            span = hi - lo
            t = 0.0 if span <= 0 else (cp - lo) / span
            return lo_age + t * (hi_age - lo_age), lo_idle + t * (hi_idle - lo_idle)
    return anchors[-1][1], anchors[-1][2]


def tier_for_cp(cp: float) -> tuple[str, float, float]:
    """Return (tier name, annual age decay, annual idle rate)."""
    age_rate, idle_rate = decay_rates(cp)
    return tier_name(cp), age_rate, idle_rate


def age_factor(age_years: float, rate: float) -> float:
    return max(K.DECAY_RETENTION, (1.0 - rate) ** age_years)


def idle_years(last_release: Optional[date], as_of: date,
               next_release: Optional[date] = None) -> float:
    """Years of idleness past the grace period. A dated project in production
    halves the clock, which rewards players for reading trade news."""
    if last_release is None:
        return 0.0
    elapsed = (as_of - last_release).days / 365.25
    idle = max(0.0, elapsed - K.GRACE_DAYS / 365.25)
    if next_release is not None and next_release > as_of:
        idle *= K.IN_PRODUCTION_IDLE_FACTOR
    return idle


def idle_factor(years: float, rate: float) -> float:
    return (1.0 - rate) ** years


def price_from_cp(cp: float) -> float:
    return K.PRICE_FLOOR + K.PRICE_COEF * (max(cp, 0.0) ** K.PRICE_EXP)
