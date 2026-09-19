"""Role weight: how much of a film's value a person's part earns them."""

from __future__ import annotations

from . import constants as K
from .models import Credit


def classify(credit: Credit) -> str:
    """Return a role tier name from billed position and, where known, runtime."""
    if credit.is_uncredited:
        return "uncredited"
    if credit.billing_order is None:
        return "supporting"          # unknown billing: assume the middle

    position = credit.billing_order + 1
    cast_size = credit.cast_size or 20
    order = [name for _, name in K.BILLING_BANDS]

    tier = order[-1]
    for highest, name in K.BILLING_BANDS:
        if position <= highest:
            tier = name
            break

    # Deep casts: high billing among many credited players is more selective.
    if cast_size >= K.DEEP_CAST_SIZE and position / cast_size <= K.DEEP_CAST_FRACTION:
        index = order.index(tier)
        if index > 0:
            tier = order[index - 1]

    share = credit.runtime_share
    if share is not None:
        if share < K.CAMEO_RUNTIME_SHARE:
            tier = "cameo"
        elif share > K.MAJOR_RUNTIME_SHARE:
            # floor at major_supporting: never demote a big part below it
            if order.index(tier) > order.index("major_supporting"):
                tier = "major_supporting"
    return tier


def role_weight(credit: Credit) -> float:
    """Final role weight for a credit, after TV, voice and ensemble adjustments."""
    if credit.role_weight_override is not None:
        base = credit.role_weight_override
    elif credit.is_director:
        base = 1.0
    elif credit.medium == "series_season":
        base = K.TV_ROLE_WEIGHTS.get(credit.series_role or "regular", 0.0)
    else:
        base = K.ROLE_WEIGHTS[classify(credit)]

    if base == 0.0:
        return 0.0
    if credit.is_voice:
        base *= K.VOICE_MULTIPLIER
    return base * ensemble_scale(credit)


def ensemble_scale(credit: Credit) -> float:
    """Scale every weight in a film down when the cast soaks up more than the cap."""
    total = credit.ensemble_weight_sum
    if not total or total <= K.ENSEMBLE_WEIGHT_CAP:
        return 1.0
    return K.ENSEMBLE_WEIGHT_CAP / total
