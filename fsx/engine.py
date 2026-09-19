"""The price engine.

Listing a new person and repricing an existing one are the same operation: run
every event in their career through this, decayed by age, and read off a price.
That is what lets the whole roster be backfilled and re-validated from one script.
"""

from __future__ import annotations

from datetime import date

from . import awards as awards_mod
from . import boxoffice, constants as K, decay, roles
from .models import Contribution, Person, Valuation

_FIXED_POINT_ITERATIONS = 40
_FIXED_POINT_TOLERANCE = 1e-6


def credit_contributions(person: Person) -> list[Contribution]:
    """Working, reception and box office points for every scored credit."""
    out: list[Contribution] = []
    scale = K.DIRECTOR_SCALE if person.is_director else 1.0

    for credit in person.credits:
        weight = roles.role_weight(credit)
        if weight <= 0:
            continue

        part = roles.role_name(credit)
        out.append(Contribution("working", f"{credit.title} (credit)",
                                weight * K.WORKING_POINTS, credit.release_date,
                                title=credit.title, role=part, kind="Credit"))

        from .reception import reception_cp
        rec_cp, _ = reception_cp(credit, weight)
        box_cp, _ = boxoffice.box_office_cp(credit, weight * scale)
        rec_cp *= scale

        # A genuine disaster - lost money AND was hated - compounds.
        if rec_cp < 0 and box_cp < 0:
            combined = (rec_cp + box_cp) * K.BOMB_COMPOUND
            out.append(Contribution("bomb", f"{credit.title} (bomb)", combined,
                                    credit.release_date, title=credit.title,
                                    role=part, kind="Bomb"))
        else:
            if rec_cp:
                out.append(Contribution("reception", f"{credit.title} (reception)",
                                        rec_cp, credit.release_date,
                                        title=credit.title, role=part,
                                        kind="Reception"))
            if box_cp:
                out.append(Contribution("box_office", f"{credit.title} (box office)",
                                        box_cp, credit.release_date,
                                        title=credit.title, role=part,
                                        kind="Box office"))
    return out


def all_contributions(person: Person, as_of: date | None = None) -> list[Contribution]:
    return (credit_contributions(person)
            + awards_mod.award_contributions(person, as_of))


def _sum_decayed(contributions, as_of: date, age_rate: float) -> dict[str, float]:
    """Decay every contribution by its age and bucket it by source.

    Events dated after `as_of` are skipped. Without that guard a valuation of a
    past date silently counts work that had not happened yet - which made every
    historical price too high and every price chart slope the wrong way.
    """
    buckets = {"working": 0.0, "reception": 0.0, "box_office": 0.0, "award": 0.0}
    for c in contributions:
        if c.event_date > as_of:
            continue
        age = max(0.0, (as_of - c.event_date).days / 365.25)
        value = c.raw_cp * decay.age_factor(age, age_rate)
        if c.source in ("award", "snub"):
            buckets["award"] += value
        elif c.source == "bomb":
            # a compounded disaster is reception and box office, already merged
            buckets["reception"] += value * 0.5
            buckets["box_office"] += value * 0.5
        else:
            buckets[c.source] += value
    return buckets


def value_person(person: Person, as_of: date | None = None) -> Valuation:
    """Price a person as of a date.

    The decay rate depends on tier, and tier depends on CP, which depends on the
    decay rate. That circle is resolved by iterating to a fixed point - it
    converges in a handful of passes for every career shape tested.
    """
    as_of = as_of or date.today()
    contributions = all_contributions(person, as_of)

    released = [c.release_date for c in person.credits if c.release_date <= as_of]
    years_idle = decay.idle_years(max(released) if released else None, as_of,
                                  person.next_release)

    cp = 1000.0
    buckets: dict[str, float] = {}
    idle_mult = 1.0
    for _ in range(_FIXED_POINT_ITERATIONS):
        _, age_rate, idle_rate = decay.tier_for_cp(cp)
        buckets = _sum_decayed(contributions, as_of, age_rate)
        idle_mult = decay.idle_factor(years_idle, idle_rate)
        new_cp = max(0.0, sum(buckets.values()) * idle_mult)
        if abs(new_cp - cp) < _FIXED_POINT_TOLERANCE:
            cp = new_cp
            break
        cp = new_cp

    tier, _, _ = decay.tier_for_cp(cp)
    scored = sum(1 for c in person.credits
                 if roles.role_weight(c) > 0 and c.release_date <= as_of)

    return Valuation(
        person=person.name,
        cp=cp,
        price=decay.price_from_cp(cp),
        tier=tier,
        working_cp=buckets.get("working", 0.0) * idle_mult,
        reception_cp=buckets.get("reception", 0.0) * idle_mult,
        box_office_cp=buckets.get("box_office", 0.0) * idle_mult,
        award_cp=buckets.get("award", 0.0) * idle_mult,
        idle_years=years_idle,
        idle_factor=idle_mult,
        credits_scored=scored,
        contributions=contributions,
    )


def explain(person: Person, as_of: date | None = None
            ) -> list[tuple[Contribution, float]]:
    """Every scoring event with its decayed value, biggest effect first.

    This is what powers the "why did this move?" panel. A market game whose
    prices cannot be interrogated is a black box, and nobody trusts a black box
    holding their portfolio.
    """
    as_of = as_of or date.today()
    valuation = value_person(person, as_of)
    _, age_rate, _ = decay.tier_for_cp(valuation.cp)

    out = []
    for c in all_contributions(person, as_of):
        if c.event_date > as_of:
            continue
        age = max(0.0, (as_of - c.event_date).days / 365.25)
        out.append((c, c.raw_cp * decay.age_factor(age, age_rate) * valuation.idle_factor))
    return sorted(out, key=lambda pair: abs(pair[1]), reverse=True)


def apply_event(current_cp: float, delta_cp: float) -> float:
    """Apply one event with the single-event loss cap, then the floor."""
    if delta_cp < 0:
        delta_cp = max(delta_cp, -current_cp * K.MAX_SINGLE_EVENT_LOSS)
    return max(0.0, current_cp + delta_cp)


def conviction_multiplier(days_held_before_event: int) -> float:
    for threshold, share in K.CONVICTION_LADDER:
        if days_held_before_event < threshold:
            return share
    return K.CONVICTION_LADDER[-1][1]


def held_value(entry_price: float, market_price: float, days_held_before: int) -> float:
    """What a position is actually worth to its holder. Gains are scaled by
    conviction; losses always land in full."""
    delta = market_price - entry_price
    if delta > 0:
        delta *= conviction_multiplier(days_held_before)
    return entry_price + delta
