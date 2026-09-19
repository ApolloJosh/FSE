"""Regression tests pinning the engine to the design doc.

These are the tests that tell you what a constant change cost. If one fails,
either the change was wrong or the doc needs updating - decide which, do not
just move the number.
"""

from datetime import date, timedelta

import pytest

from fsx import constants as K
from fsx.decay import price_from_cp
from fsx.engine import conviction_multiplier, held_value, value_person
from fsx.models import Award, Credit, Person
from fsx.reference import AS_OF, EXPECTED_PRICES, reference_careers

TOLERANCE = 0.02      # 2%: constants are fitted, not exact


def credit(years_ago, rw, rs, bop, scale):
    return Credit(title="c", release_date=AS_OF - timedelta(days=round(years_ago * 365.25)),
                  role_weight_override=rw, reception_override=rs, confidence_override=1.0,
                  bop_override=bop, scale_override=scale)


@pytest.mark.parametrize("person", reference_careers(), ids=lambda p: p.name)
def test_reference_career_prices_match_the_doc(person):
    price = value_person(person, AS_OF).price
    expected = EXPECTED_PRICES[person.name]
    assert price == pytest.approx(expected, rel=TOLERANCE)


def test_the_ladder_is_strictly_ordered():
    prices = [value_person(p, AS_OF).price for p in reference_careers()]
    debut, journeyman, recognized, alister, legend, megastar = prices
    assert debut < journeyman < recognized < alister < megastar < legend


def test_each_reference_career_lands_in_its_intended_tier():
    tiers = {p.name: value_person(p, AS_OF).tier for p in reference_careers()}
    assert tiers["ref: Debut"] == "Debut"
    assert tiers["ref: Journeyman"] == "Working"
    assert tiers["ref: Recognized"] == "Recognized"
    assert tiers["ref: A-List"] == "A-List"
    assert tiers["ref: Legend"] == "Legend"


# --------------------------------------------------- the core design property
@pytest.mark.parametrize("cp,expected_move", [
    (95, 1.715), (400, 0.669), (1500, 0.214),
    (4000, 0.085), (9000, 0.038), (14000, 0.025),
])
def test_one_oscar_nomination_moves_a_newcomer_far_more(cp, expected_move):
    """The chart in the design doc. If this flattens, the game stops being
    about scouting and becomes about who saved up the most Credits."""
    before, after = price_from_cp(cp), price_from_cp(cp + 400)
    assert after / before - 1 == pytest.approx(expected_move, abs=0.005)


# ------------------------------------------------------------ worked examples
def test_the_breakout():
    debut_credit = credit(2.0, 0.30, 67.5, 120, 0.92)
    breakout_credit = credit(0.0, 0.80, 74, 120, 0.94)
    K.AWARD_TABLE.setdefault("_sag_test", (130, 0))
    K.AWARD_TABLE.setdefault("_globe_test", (110, 0))
    precursors = [Award("_sag_test", 2025, AS_OF), Award("_globe_test", 2025, AS_OF)]

    listing = value_person(Person("b", credits=[credit(0.0, 0.30, 67.5, 120, 0.92)]), AS_OF)
    won = value_person(Person("b", credits=[debut_credit, breakout_credit],
                              awards=precursors +
                              [Award("oscar_supporting", 2025, AS_OF, won=True)]), AS_OF)

    assert listing.price == pytest.approx(5.03, rel=TOLERANCE)
    assert won.price == pytest.approx(43.12, rel=TOLERANCE)
    assert won.price / listing.price - 1 > 6.0       # a 600%+ move


def test_conviction_splits_the_same_move_between_two_players():
    entry, final = 5.03, 43.12
    early = held_value(entry, final, days_held_before=800)
    late = held_value(23.70, final, days_held_before=1)
    assert early == pytest.approx(54.55, rel=TOLERANCE)
    assert late == pytest.approx(31.47, rel=TOLERANCE)
    assert early > late


def test_conviction_ladder_rewards_holding():
    assert conviction_multiplier(1) == 0.40
    assert conviction_multiplier(10) == 0.70
    assert conviction_multiplier(60) == 1.00
    assert conviction_multiplier(200) == 1.15
    assert conviction_multiplier(400) == 1.30


def test_losses_are_always_realized_in_full():
    assert held_value(100.0, 80.0, days_held_before=1) == pytest.approx(80.0)
    assert held_value(100.0, 80.0, days_held_before=4000) == pytest.approx(80.0)


def test_the_snub_fires_only_once_nominations_are_announced():
    credits = [credit(4.0, 0.60, 64, 120, 0.95), credit(0.0, 1.00, 72, 180, 0.97)]
    precursors = [Award("globe", 2025, AS_OF - timedelta(days=30)),
                  Award("sag_individual", 2025, AS_OF - timedelta(days=20)),
                  Award("bafta", 2025, AS_OF - timedelta(days=10))]
    person = Person("snub", credits=credits, awards=precursors)

    eve = value_person(person, date(2026, 1, 22))
    morning = value_person(person, date(2026, 1, 23))

    assert eve.price > morning.price
    assert morning.price / eve.price - 1 == pytest.approx(-0.135, abs=0.02)


def test_one_precursor_alone_is_not_a_snub():
    credits = [credit(0.0, 1.00, 72, 180, 0.97)]
    person = Person("p", credits=credits,
                    awards=[Award("globe", 2025, AS_OF - timedelta(days=30))])
    assert value_person(person, date(2026, 3, 1)).price > value_person(
        Person("q", credits=credits), date(2026, 3, 1)).price


def test_the_bomb_dents_a_major_career_without_ending_it():
    alist = [p for p in reference_careers() if p.name == "ref: A-List"][0]
    before = value_person(alist, AS_OF).price
    alist.credits.append(Credit(title="bomb", release_date=AS_OF, role_weight_override=1.0,
                                reception_override=28, confidence_override=1.0,
                                bop_override=-360, scale_override=1.0))
    after = value_person(alist, AS_OF).price
    assert -0.08 < after / before - 1 < -0.02


def test_no_single_event_can_wipe_out_a_career():
    from fsx.engine import apply_event
    assert apply_event(10_000, -50_000) == pytest.approx(10_000 * (1 - K.MAX_SINGLE_EVENT_LOSS))


# -------------------------------------------------------------- idle decay
@pytest.mark.parametrize("years,lo,hi", [(1, -0.20, -0.03), (3, -0.45, -0.15),
                                         (5, -0.60, -0.25)])
def test_going_quiet_costs_real_money(years, lo, hi):
    alist = [p for p in reference_careers() if p.name == "ref: A-List"][0]
    base = value_person(alist, AS_OF).price
    later = value_person(alist, AS_OF + timedelta(days=round(years * 365.25))).price
    assert lo < later / base - 1 < hi


def test_a_legend_fades_more_slowly_than_a_smaller_career():
    """Working and Recognized land within a point of each other at five years -
    a career whose value has already sunk to the retention floor stops decaying,
    so adjacent small tiers tie. The gap that matters is small versus large."""
    five_years = timedelta(days=round(5 * 365.25))
    people = {p.name: p for p in reference_careers()}
    drops = {}
    for name in ("ref: Journeyman", "ref: Recognized", "ref: A-List", "ref: Legend"):
        person = people[name]
        base = value_person(person, AS_OF).price
        drops[name] = value_person(person, AS_OF + five_years).price / base - 1

    small = max(drops["ref: Journeyman"], drops["ref: Recognized"])
    assert small < drops["ref: A-List"] < drops["ref: Legend"]
    assert drops["ref: Legend"] - small > 0.15      # a clear separation


# ------------------------------------------------- valuing a date in the past
def test_a_past_valuation_ignores_work_that_had_not_happened_yet():
    """Every historical price was too high and every chart sloped the wrong
    way, because future credits were counted at full weight."""
    from fsx.models import Person

    early = credit(0.0, 1.0, 75, 300, 1.0)                 # released at AS_OF
    later = Credit(title="future", release_date=AS_OF + timedelta(days=365),
                   role_weight_override=1.0, reception_override=90,
                   confidence_override=1.0, bop_override=660, scale_override=1.0)
    person = Person("p", credits=[early, later])

    now = value_person(person, AS_OF)
    after = value_person(person, AS_OF + timedelta(days=366))
    assert after.price > now.price
    assert now.credits_scored == 1
    assert after.credits_scored == 2


def test_a_future_award_does_not_pay_early():
    from fsx.models import Person
    person = Person("p", credits=[credit(1.0, 1.0, 70, 120, 1.0)],
                    awards=[Award("oscar_lead", 2027,
                                  AS_OF + timedelta(days=200), won=True)])
    assert value_person(person, AS_OF).award_cp == 0
    assert value_person(person, AS_OF + timedelta(days=201)).award_cp > 0


def test_a_price_chart_rises_through_a_breakout():
    """The direct consequence: a career that got better must chart upward."""
    from fsx.history import series
    from fsx.models import Person
    person = Person("riser", credits=[
        credit(4.0, 0.30, 62, 0, 0.9),
        credit(2.0, 0.80, 74, 120, 0.95),
        credit(0.5, 1.00, 82, 450, 1.0)])
    points = series(person, years=5, as_of=AS_OF)
    assert points[-1].price > points[0].price
    assert points[-1].price > points[len(points) // 2].price
