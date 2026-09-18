"""Data shapes the engine consumes. Sources produce these; the engine reads them."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class Credit:
    """One scored appearance: a film, or one season of a series."""

    title: str
    release_date: date

    # --- role -------------------------------------------------------------
    medium: str = "film"                     # film | series_season | limited
    billing_order: Optional[int] = None      # 0-indexed, as TMDB gives it
    cast_size: Optional[int] = None          # credited principal cast
    runtime_share: Optional[float] = None    # 0-1, when known
    series_role: Optional[str] = None        # regular | recurring | guest
    is_voice: bool = False
    is_uncredited: bool = False
    is_director: bool = False
    role_weight_override: Optional[float] = None
    ensemble_weight_sum: Optional[float] = None  # all scored RW in this film

    # --- reception --------------------------------------------------------
    rt_critics: Optional[float] = None
    rt_audience: Optional[float] = None
    imdb: Optional[float] = None
    imdb_votes: Optional[int] = None
    metascore: Optional[float] = None
    letterboxd: Optional[float] = None

    # --- box office -------------------------------------------------------
    budget: Optional[float] = None
    worldwide_gross: Optional[float] = None
    streaming_viewers_28d: Optional[float] = None

    # --- manual overrides -------------------------------------------------
    # The role classifier will be wrong often enough to matter, and the
    # reference careers need exact inputs. These bypass the derivation.
    reception_override: Optional[float] = None    # an RS on the 0-100 scale
    confidence_override: Optional[float] = None
    bop_override: Optional[float] = None          # Box Office Points, in CP
    scale_override: Optional[float] = None

    def age_years(self, as_of: date) -> float:
        return max(0.0, (as_of - self.release_date).days / 365.25)


@dataclass
class Award:
    """A nomination or a win. `key` indexes constants.AWARD_TABLE."""

    key: str
    year: int
    awarded_on: date
    won: bool = False
    category: str = ""

    def age_years(self, as_of: date) -> float:
        return max(0.0, (as_of - self.awarded_on).days / 365.25)


@dataclass
class Person:
    name: str
    tmdb_id: Optional[int] = None
    is_director: bool = False
    credits: list[Credit] = field(default_factory=list)
    awards: list[Award] = field(default_factory=list)
    next_release: Optional[date] = None   # announced, dated project in production

    def last_release(self) -> Optional[date]:
        dates = [c.release_date for c in self.credits]
        return max(dates) if dates else None


@dataclass
class Contribution:
    """One scoring event, before decay. Kept for the 'why did this move?' panel."""

    source: str        # working | reception | box_office | award | snub
    label: str
    raw_cp: float
    event_date: date
    is_award: bool = False


@dataclass
class Valuation:
    person: str
    cp: float
    price: float
    tier: str
    working_cp: float = 0.0
    reception_cp: float = 0.0
    box_office_cp: float = 0.0
    award_cp: float = 0.0
    idle_years: float = 0.0
    idle_factor: float = 1.0
    credits_scored: int = 0
    contributions: list[Contribution] = field(default_factory=list)

    def as_row(self) -> dict:
        return {
            "person": self.person,
            "price": round(self.price, 2),
            "cp": round(self.cp, 1),
            "tier": self.tier,
            "credits": self.credits_scored,
            "working_cp": round(self.working_cp, 1),
            "reception_cp": round(self.reception_cp, 1),
            "box_office_cp": round(self.box_office_cp, 1),
            "award_cp": round(self.award_cp, 1),
            "idle_years": round(self.idle_years, 2),
            "idle_factor": round(self.idle_factor, 3),
        }
