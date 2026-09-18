"""The Reception Score: five review scales collapsed onto one 0-100 number.

The scales have very different centers - 60 on Rotten Tomatoes is mediocre, a 60
Metascore is good - so each is z-scored against its own distribution before any
averaging happens. A naive mean would let the bimodal Tomatometer dominate.
"""

from __future__ import annotations

import math
from typing import NamedTuple, Optional

from . import constants as K
from .models import Credit


class ReceptionResult(NamedTuple):
    score: float          # 0-100, 50 is average
    confidence: float     # 0-1, from vote count
    sources_used: int


def normalize(source: str, value: float) -> float:
    mu, sigma, _ = K.RECEPTION_SOURCES[source]
    z = (value - mu) / sigma
    return max(0.0, min(100.0, K.RECEPTION_CENTER + K.RECEPTION_SPREAD * z))


def confidence(votes: Optional[int]) -> float:
    if not votes or votes <= 1:
        return 0.0
    return min(1.0, math.log10(votes) / K.CONFIDENCE_VOTE_EXP)


def reception_score(credit: Credit) -> Optional[ReceptionResult]:
    """None when fewer than MIN_RECEPTION_SOURCES are available: the credit is
    provisional and contributes nothing until a third source appears."""
    if credit.reception_override is not None:
        return ReceptionResult(
            credit.reception_override,
            1.0 if credit.confidence_override is None else credit.confidence_override,
            len(K.RECEPTION_SOURCES),
        )

    weighted, total_weight, used = 0.0, 0.0, 0

    for source, (_, _, weight) in K.RECEPTION_SOURCES.items():
        value = getattr(credit, source, None)
        if value is None:
            continue
        weighted += normalize(source, value) * weight
        total_weight += weight
        used += 1

    if used < K.MIN_RECEPTION_SOURCES:
        return None

    return ReceptionResult(weighted / total_weight, confidence(credit.imdb_votes), used)


def reception_cp(credit: Credit, weight: float) -> tuple[float, Optional[ReceptionResult]]:
    result = reception_score(credit)
    if result is None:
        return 0.0, None
    cp = weight * result.confidence * (result.score - K.RECEPTION_CENTER) * K.RECEPTION_COEF
    return cp, result
