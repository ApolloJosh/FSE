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
    verdict: str = ""       # art | flop | hit | paycheque | break-even


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
    """Keeps a genuine blockbuster worth more than a lucky micro-budget hit.

    Ramps from $1M (0.0) to $1B (1.0). The previous version started at a 0.5
    floor, so a film that grossed $70,000 earned 77% of what a billion-dollar
    opening earned - which is how a $3,000 debut became a phenomenon.
    """
    if not gross or gross <= 1:
        return 0.0
    ramp = (math.log10(gross) - K.SCALE_LOG_FLOOR) / K.SCALE_LOG_SPAN
    return max(0.0, min(1.0, ramp))


def is_wide_release(credit: Credit) -> bool:
    """Was this a studio-scale bet? Only those can lose box office points."""
    return ((credit.budget or 0) >= K.WIDE_RELEASE_BUDGET
            or (credit.worldwide_gross or 0) >= K.WIDE_RELEASE_GROSS)


def is_streaming_release(credit: Credit) -> bool:
    """Did this film ever really play in cinemas?

    A limited-only or digital-only release was never selling tickets, so its
    multiple of budget is not a verdict on anything - The Irishman had a
    26-day limited run and reads as 0.01x. Where TMDB has no typed release,
    a theatrical-to-digital window under three weeks says the same thing.
    """
    if credit.release_kind in ("limited", "digital"):
        return True
    if credit.release_kind == "wide":
        return False
    window = credit.digital_window_days
    return window is not None and window < K.STREAMING_WINDOW_DAYS


def in_pandemic_window(credit: Credit) -> bool:
    ym = (credit.release_date.year, credit.release_date.month)
    return K.PANDEMIC_FROM <= ym <= K.PANDEMIC_TO


def evaluate(credit: Credit) -> BoxOfficeResult:
    # An explicit override beats every inference below it.
    if credit.bop_override is not None:
        return BoxOfficeResult(None, credit.bop_override,
                               credit.scale_override if credit.scale_override
                               is not None else 1.0, "override")

    # Neither of these is a box office result, so neither is scored as one.
    if is_streaming_release(credit):
        return BoxOfficeResult(multiple(credit), 0.0, 1.0, "none", "streaming")
    if in_pandemic_window(credit):
        return BoxOfficeResult(multiple(credit), 0.0, 1.0, "none", "pandemic")

    result = _evaluate_theatrical(credit)
    if result.bop == 0 and not result.verdict:
        why = "no budget" if multiple(credit) is None else "break-even"
        result = result._replace(verdict=why)
    return result


def _evaluate_theatrical(credit: Credit) -> BoxOfficeResult:
    mult = multiple(credit)
    if mult is not None:
        points = ladder_points(mult)
        if points < 0 and not is_wide_release(credit):
            points = 0.0
        # A multiple computed off a tiny gross is noise, not a result.
        if points > 0 and (credit.worldwide_gross or 0) < K.MIN_GROSS_FOR_POINTS:
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


def reception_modifier(points: float, rs: Optional[float]) -> tuple[float, str]:
    """How much of a box office result the reviews let stand.

    A film that lost money but was liked was probably not trying to make money.
    A film that made money and was disliked made it anyway. Ramped rather than
    stepped, so nothing hinges on a film scoring 39 instead of 41.
    """
    if rs is None:
        rs = K.RECEPTION_CENTER          # unknown: treat as average, judge neither way

    if points < 0:
        span = K.PENALTY_MIN_ABOVE_RS - K.PENALTY_FULL_BELOW_RS
        t = max(0.0, min(1.0, (rs - K.PENALTY_FULL_BELOW_RS) / span))
        factor = 1.0 - t * (1.0 - K.PENALTY_FLOOR)
        return factor, ("art" if t > 0.6 else "flop" if t < 0.2 else "misfire")

    if points > 0:
        span = K.REWARD_FULL_ABOVE_RS - K.REWARD_MIN_BELOW_RS
        t = max(0.0, min(1.0, (rs - K.REWARD_MIN_BELOW_RS) / span))
        factor = K.REWARD_FLOOR + t * (1.0 - K.REWARD_FLOOR)
        return factor, ("hit" if t > 0.6 else "paycheque" if t < 0.2 else "solid")

    return 1.0, "break-even"


def box_office_cp(credit: Credit, weight: float) -> tuple[float, BoxOfficeResult]:
    from .reception import reception_score

    result = evaluate(credit)
    if result.bop == 0:
        # Nothing to modify, and evaluate() already said why - streaming,
        # pandemic, no budget on file. Overwriting that with "break-even"
        # threw away the only useful thing the panel had to show.
        return 0.0, result

    scored = reception_score(credit)
    factor, verdict = reception_modifier(result.bop, scored.score if scored else None)
    result = result._replace(bop=result.bop * factor, verdict=verdict)
    return weight * result.bop * result.scale, result
