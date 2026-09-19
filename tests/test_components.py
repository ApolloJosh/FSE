"""Unit tests for each scoring component in isolation."""

from datetime import date

import pytest

from fsx import boxoffice, constants as K, reception, roles
from fsx.decay import age_factor, decay_rates, idle_factor, idle_years, price_from_cp
from fsx.models import Credit


def credit(**kw) -> Credit:
    base = dict(title="t", release_date=date(2024, 1, 1))
    base.update(kw)
    return Credit(**base)


# ------------------------------------------------------------------- roles
def test_top_billing_in_small_cast_is_a_lead():
    assert roles.classify(credit(billing_order=0, cast_size=4)) == "sole_lead"


def test_high_billing_in_a_deep_cast_is_promoted():
    """9th of 12 is a supporting part; 9th of 60 is more selective than that."""
    shallow = roles.classify(credit(billing_order=8, cast_size=12))
    deep = roles.classify(credit(billing_order=8, cast_size=60))
    assert K.ROLE_WEIGHTS[deep] > K.ROLE_WEIGHTS[shallow]


def test_billing_bands_follow_the_role_table():
    assert roles.classify(credit(billing_order=0, cast_size=20)) == "sole_lead"
    assert roles.classify(credit(billing_order=1, cast_size=20)) == "co_lead"
    assert roles.classify(credit(billing_order=4, cast_size=20)) == "major_supporting"
    assert roles.classify(credit(billing_order=9, cast_size=20)) == "supporting"
    assert roles.classify(credit(billing_order=20, cast_size=40)) == "minor"


def test_short_screen_time_caps_a_star_billed_part_at_cameo():
    c = credit(billing_order=0, cast_size=20, runtime_share=0.04)
    assert roles.classify(c) == "cameo"


def test_long_screen_time_floors_a_low_billed_part():
    c = credit(billing_order=15, cast_size=20, runtime_share=0.50)
    assert roles.classify(c) == "major_supporting"


def test_uncredited_scores_nothing():
    assert roles.role_weight(credit(is_uncredited=True)) == 0.0


def test_voice_work_takes_a_discount():
    plain = roles.role_weight(credit(billing_order=0, cast_size=4))
    voiced = roles.role_weight(credit(billing_order=0, cast_size=4, is_voice=True))
    assert voiced == pytest.approx(plain * K.VOICE_MULTIPLIER)


def test_ensemble_cap_scales_every_weight_down():
    c = credit(billing_order=0, cast_size=4, ensemble_weight_sum=6.0)
    assert roles.role_weight(c) == pytest.approx(1.0 * K.ENSEMBLE_WEIGHT_CAP / 6.0)


def test_small_ensemble_is_untouched():
    c = credit(billing_order=0, cast_size=4, ensemble_weight_sum=2.0)
    assert roles.role_weight(c) == pytest.approx(1.0)


# --------------------------------------------------------------- reception
def test_an_average_film_on_every_scale_scores_fifty():
    c = credit(rt_critics=60, metascore=56, rt_audience=63, imdb=6.3,
               letterboxd=3.15, imdb_votes=10_000)
    assert reception.reception_score(c).score == pytest.approx(50.0)


def test_normalization_stops_rotten_tomatoes_dominating():
    """A 60 Tomatometer is mediocre; a 60 Metascore is good. Both must normalize
    to something sane rather than averaging to 60."""
    assert reception.normalize("rt_critics", 60) == pytest.approx(50.0)
    assert reception.normalize("metascore", 60) > 50.0


def test_two_sources_is_not_enough():
    assert reception.reception_score(credit(imdb=8.0, metascore=80)) is None


def test_three_sources_is_enough_and_weights_renormalize():
    result = reception.reception_score(
        credit(imdb=8.0, metascore=80, rt_critics=90, imdb_votes=10_000))
    assert result is not None and result.sources_used == 3


def test_confidence_scales_with_vote_count():
    assert reception.confidence(10_000) == pytest.approx(1.0)
    assert reception.confidence(1_000) == pytest.approx(0.75)
    assert reception.confidence(100) == pytest.approx(0.50)


def test_a_masterpiece_lead_earns_the_documented_cp():
    c = credit(reception_override=85, confidence_override=1.0)
    cp, _ = reception.reception_cp(c, 1.0)
    assert cp == pytest.approx(175.0)


def test_a_disaster_lead_loses_the_documented_cp():
    c = credit(reception_override=25, confidence_override=1.0)
    cp, _ = reception.reception_cp(c, 1.0)
    assert cp == pytest.approx(-125.0)


# -------------------------------------------------------------- box office
def test_box_office_is_a_multiple_not_a_gross():
    cheap = credit(budget=40e6, worldwide_gross=180e6)      # 4.5x, a triumph
    dear = credit(budget=250e6, worldwide_gross=180e6)      # 0.7x, a catastrophe
    assert boxoffice.evaluate(cheap).bop > 0
    assert boxoffice.evaluate(dear).bop < 0


def test_break_even_pays_nothing():
    assert boxoffice.evaluate(credit(budget=100e6, worldwide_gross=300e6)).bop == 0.0


def test_scale_keeps_a_blockbuster_ahead_of_a_lucky_cheapie():
    assert boxoffice.scale_factor(1e9) == pytest.approx(1.0)
    assert boxoffice.scale_factor(1e7) < boxoffice.scale_factor(1e9)


def test_no_budget_means_no_box_office_score_rather_than_a_guess():
    result = boxoffice.evaluate(credit(worldwide_gross=50e6))
    assert result.bop == 0.0 and result.basis == "none"


def test_streaming_falls_back_at_a_discount():
    result = boxoffice.evaluate(credit(streaming_viewers_28d=60_000_000))
    assert result.basis == "streaming" and result.bop > 0


# ------------------------------------------------------------------ decay
def test_an_old_award_never_becomes_worthless():
    assert age_factor(60, 0.22) == pytest.approx(K.DECAY_RETENTION)


def test_decay_rates_are_continuous_across_a_tier_boundary():
    """Stepping these produced a cliff: a stock decaying out of A-List suddenly
    took a harsher rate and fell faster than a lower-tier stock."""
    just_below = decay_rates(5_999)
    just_above = decay_rates(6_001)
    assert just_below[0] == pytest.approx(just_above[0], abs=1e-4)
    assert just_below[1] == pytest.approx(just_above[1], abs=1e-4)


def test_bigger_careers_decay_more_slowly():
    assert decay_rates(100)[0] > decay_rates(2_000)[0] > decay_rates(20_000)[0]


def test_the_grace_period_holds_idle_decay_off():
    last = date(2026, 1, 1)
    assert idle_years(last, date(2026, 6, 1)) == 0.0
    assert idle_years(last, date(2027, 6, 1)) > 0.0


def test_a_dated_project_in_production_halves_the_idle_clock():
    last, now = date(2024, 1, 1), date(2026, 1, 1)
    assert idle_years(last, now, next_release=date(2026, 9, 1)) == pytest.approx(
        idle_years(last, now) * K.IN_PRODUCTION_IDLE_FACTOR)


def test_the_price_floor_holds():
    assert price_from_cp(0) == pytest.approx(K.PRICE_FLOOR)
    assert price_from_cp(-500) == pytest.approx(K.PRICE_FLOOR)


# ------------------------------------------- box office judged against reviews
def scored(multiple_budget, gross, rs):
    """A credit with a known multiple and a known Reception Score."""
    return credit(budget=multiple_budget, worldwide_gross=gross,
                  reception_override=rs, confidence_override=1.0)


def test_a_well_reviewed_film_that_lost_money_is_barely_punished():
    """Crime 101: $90M budget, $73M gross, Reception 61. It cost Chris
    Hemsworth exactly what Red Dawn did, and Red Dawn scored 29."""
    art, _ = boxoffice.box_office_cp(scored(90e6, 73e6, 61), 1.0)
    flop, _ = boxoffice.box_office_cp(scored(65e6, 45e6, 29), 1.0)
    assert art < 0 and flop < 0
    assert abs(art) < abs(flop) * 0.3


def test_a_badly_reviewed_film_that_lost_money_is_punished_in_full():
    cp, result = boxoffice.box_office_cp(scored(70e6, 18e6, 30), 1.0)
    assert result.verdict == "flop"
    raw = boxoffice.evaluate(credit(budget=70e6, worldwide_gross=18e6))
    assert cp == pytest.approx(raw.bop * result.scale, rel=1e-6)


def test_a_badly_reviewed_film_that_made_money_earns_less():
    """The co-worker movie: it made the money, it is not a good film."""
    good, _ = boxoffice.box_office_cp(scored(20e6, 200e6, 70), 1.0)
    bad, _ = boxoffice.box_office_cp(scored(20e6, 200e6, 30), 1.0)
    assert good > bad > 0
    assert bad < good * 0.5


def test_a_well_reviewed_hit_earns_everything():
    _, result = boxoffice.box_office_cp(scored(200e6, 1400e6, 70), 1.0)
    assert result.verdict == "hit"


def test_the_four_verdicts_are_reachable():
    cases = {
        "art": scored(90e6, 73e6, 68),
        "flop": scored(90e6, 40e6, 28),
        "hit": scored(50e6, 400e6, 70),
        "paycheque": scored(20e6, 300e6, 30),
    }
    for want, c in cases.items():
        assert boxoffice.box_office_cp(c, 1.0)[1].verdict == want


def test_an_unscored_film_is_judged_neither_way():
    """No reviews on file means no opinion, not a free pass and not a beating."""
    c = credit(budget=90e6, worldwide_gross=40e6)          # no reception at all
    cp, result = boxoffice.box_office_cp(c, 1.0)
    assert result.verdict in ("flop", "misfire")
    assert cp < 0


def test_the_modifier_ramps_rather_than_steps():
    """Nothing should hinge on a film scoring 39 instead of 41."""
    a, _ = boxoffice.reception_modifier(-100, 39.0)
    b, _ = boxoffice.reception_modifier(-100, 41.0)
    assert abs(a - b) < 0.12


# ----------------------------------------------- how a film actually released
def test_a_limited_only_release_is_not_scored_on_its_multiple():
    """The Irishman had a 26-day limited run and reads as 0.01x of budget.
    That is not a verdict on anything."""
    c = credit(budget=159e6, worldwide_gross=8e6, release_kind="limited",
               digital_window_days=26)
    result = boxoffice.evaluate(c)
    assert result.bop == 0.0 and result.verdict == "streaming"


def test_a_wide_release_that_flopped_is_still_scored():
    """Killers of the Flower Moon had a real theatrical run and a 46-day
    window. It underperformed, and that counts."""
    c = credit(budget=200e6, worldwide_gross=158e6, release_kind="wide",
               digital_window_days=46)
    assert boxoffice.evaluate(c).bop < 0


def test_a_short_window_stands_in_when_the_type_is_missing():
    assert boxoffice.is_streaming_release(credit(digital_window_days=14))
    assert not boxoffice.is_streaming_release(credit(digital_window_days=60))
    assert not boxoffice.is_streaming_release(credit())     # nothing known


def test_a_typed_wide_release_beats_a_short_window():
    """A studio dumping a wide release early is a flop, not a streaming title."""
    c = credit(release_kind="wide", digital_window_days=20)
    assert not boxoffice.is_streaming_release(c)


def test_the_pandemic_cohort_is_not_judged_on_box_office():
    from datetime import date as _d
    c = Credit(title="t", release_date=_d(2020, 7, 1), budget=100e6,
               worldwide_gross=20e6, release_kind="wide")
    assert boxoffice.evaluate(c).verdict == "pandemic"
    assert boxoffice.evaluate(c).bop == 0.0


def test_films_either_side_of_the_pandemic_are_judged_normally():
    from datetime import date as _d
    for when in (_d(2019, 7, 1), _d(2022, 7, 1)):
        c = Credit(title="t", release_date=when, budget=100e6,
                   worldwide_gross=20e6, release_kind="wide")
        assert boxoffice.evaluate(c).bop < 0


def test_an_explicit_override_beats_every_inference():
    c = credit(release_kind="limited", bop_override=500.0, scale_override=1.0)
    assert boxoffice.evaluate(c).bop == 500.0


def test_a_zero_score_still_says_why():
    """streaming, pandemic and no-budget were all being relabelled
    'break-even', which threw away the only useful thing to show."""
    from datetime import date as _d
    cases = {
        "streaming": credit(budget=159e6, worldwide_gross=8e6, release_kind="limited"),
        "no budget": credit(worldwide_gross=50e6, release_kind="wide"),
    }
    for want, c in cases.items():
        cp, result = boxoffice.box_office_cp(c, 1.0)
        assert cp == 0.0 and result.verdict == want
    pandemic = Credit(title="t", release_date=_d(2020, 7, 1), budget=100e6,
                      worldwide_gross=20e6, release_kind="wide")
    assert boxoffice.box_office_cp(pandemic, 1.0)[1].verdict == "pandemic"
