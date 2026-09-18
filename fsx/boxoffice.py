"""Box office scored as a multiple of budget, never as raw gross.

A $40M horror film that grosses $180M is a triumph. A $250M tentpole that grosses
the same number ends careers. Raw gross prices those identically.
"""

from __future__ import annotations

import math
from typing import NamedTuple, Optional

from . import constants as K
from .models import Credit


class BoxOfficeResult(NamedTuple):
    multiple: Optional[float]
    bop: float
    scale: float
    basis: str      # theatrical | streaming | none


def multiple(credit: Credit) -> Optional[float]:
    if not credit.budget or not credit.worldwide_gross or credit.budget <= 0:
        return None
    return credit.worldwide_gross / credit.budget


def ladder_points(mult: float) -> float:
    for upper, points in K.BOX_OFFICE_LADDER:
        if mult < upper:
            return points
    return K.BOX_OFFICE_LADDER[-1][1]


def scale_factor(gross: Optional[float]) -> float:
    """Keeps a genuine blockbuster worth more than a lucky micro-budget hit,
    without erasing the cheapie's win. Deliberately a narrow range."""
    if not gross or gross <= 1:
        return K.SCALE_BASE
    return K.SCALE_BASE + K.SCALE_BASE * min(1.0, math.log10(gross) / K.SCALE_LOG_DIVISOR)


def is_wide_release(credit: Credit) -> bool:
    """Was this a studio-scale bet? Only those can lose box office points."""
    return ((credit.budget or 0) >= K.WIDE_RELEASE_BUDGET
            or (credit.worldwide_gross or 0) >= K.WIDE_RELEASE_GROSS)


def evaluate(credit: Credit) -> BoxOfficeResult:
    if credit.bop_override is not None:
        return BoxOfficeResult(None, credit.bop_override,
                               credit.scale_override if credit.scale_override
                               is not None else 1.0, "override")

    mult = multiple(credit)
    if mult is not None:
        points = ladder_points(mult)
        if points < 0 and not is_wide_release(credit):
            points = 0.0
        return BoxOfficeResult(mult, points, scale_factor(credit.worldwide_gross),
                               "theatrical")

    # Fallback 1: a streaming original with published viewership.
    if credit.streaming_viewers_28d:
        synthetic = credit.streaming_viewers_28d / K.STREAMING_BREAKEVEN_VIEWERS
        synthetic *= K.BREAKEVEN_MULTIPLE     # map "break-even viewers" onto the ladder
        points = ladder_points(synthetic) * K.STREAMING_DISCOUNT
        return BoxOfficeResult(synthetic, points, 1.0, "streaming")

    # Fallback 2: limited release with no reliable budget. Reception carries it.
    return BoxOfficeResult(None, 0.0, 1.0, "none")


def box_office_cp(credit: Credit, weight: float) -> tuple[float, BoxOfficeResult]:
    result = evaluate(credit)
    return weight * result.bop * result.scale, result
