"""The daily games: generation, grading, payouts and anti-replay."""

import json
from datetime import date, timedelta

import pytest

from app import db
from app.games import play, puzzles, scoring
from app.games.corpus import Corpus, Film, build
from app.games.puzzles import NotEnoughData, check_chain

SNAPSHOT = "data/people.json"
DAY = date(2026, 9, 21)


@pytest.fixture
def conn():
    c = db.connect(":memory:")
    db.migrate(c)
    return c


@pytest.fixture
def player(conn):
    return db.upsert_user(conn, "github", "p", "Player", None, db.cents(50.00))["id"]


def dense_corpus() -> Corpus:
    """A synthetic six-film cast web. The fixture set is too sparse for Six
    Degrees, so its generator is proved here instead of hoped about."""
    names = [f"actor-{i}" for i in range(8)]
    films, by_person = {}, {n: [] for n in names}
    chain = [("a", 0, 1), ("b", 1, 2), ("c", 2, 3), ("d", 3, 4), ("e", 4, 5),
             ("f", 5, 6), ("g", 6, 7)]
    for key, i, j in chain:
        film = Film(key=key, title=f"Film {key.upper()}", year=2020, votes=99_999,
                    budget=1e7, gross=5e7, rt_critics=80, imdb=7.5,
                    cast=[(names[i], 1.0), (names[j], 0.8)])
        films[key] = film
        by_person[names[i]].append(key)
        by_person[names[j]].append(key)
    return Corpus(films=films, people={}, names={n: n.title() for n in names},
                  by_person=by_person)


# ---------------------------------------------------------------- generation
@pytest.mark.parametrize("game", ["ladder", "box-office", "cast-gap", "slate"])
def test_a_puzzle_generates_from_the_fixture_data(game):
    assert puzzles.generate(game, DAY, SNAPSHOT).public


def test_the_same_day_always_makes_the_same_puzzle():
    """A daily game people cannot compare notes on is just a quiz."""
    a = puzzles.generate("ladder", DAY, SNAPSHOT)
    b = puzzles.generate("ladder", DAY, SNAPSHOT)
    assert a.answer == b.answer and a.public == b.public


def test_a_different_day_makes_a_different_puzzle():
    a = puzzles.generate("box-office", DAY, SNAPSHOT)
    b = puzzles.generate("box-office", DAY + timedelta(days=1), SNAPSHOT)
    assert a.public != b.public


def test_the_answer_is_never_in_the_public_half():
    for game in ("ladder", "cast-gap"):
        p = puzzles.generate(game, DAY, SNAPSHOT)
        assert p.answer["name"] not in json.dumps(p.public.get("rungs", p.public.get("shown", [])))


def test_placeholder_credits_never_reach_a_puzzle():
    """Fixture filler scores like a credit but is not a film anyone can name."""
    corpus = build(SNAPSHOT)
    assert not any("filler" in f.title.lower() for f in corpus.films.values())


def sparse_corpus() -> Corpus:
    """Two disconnected pairs - nobody is reachable from anybody far enough."""
    films = {"a": Film(key="a", title="A", year=2020, votes=99_999,
                       cast=[("x", 1.0), ("y", 0.8)]),
             "b": Film(key="b", title="B", year=2021, votes=99_999,
                       cast=[("p", 1.0), ("q", 0.8)])}
    return Corpus(films=films, people={}, names={n: n for n in "xypq"},
                  by_person={"x": ["a"], "y": ["a"], "p": ["b"], "q": ["b"]})


def test_six_degrees_declines_rather_than_shipping_a_broken_puzzle():
    """A sparse cast web must produce no puzzle rather than a broken one."""
    with pytest.raises(NotEnoughData):
        puzzles.six_degrees(sparse_corpus(), DAY)


def test_six_degrees_works_once_the_cast_web_is_dense():
    corpus = dense_corpus()
    puzzle = puzzles.six_degrees(corpus, DAY)
    assert puzzle.public["par"] >= 2
    path = puzzles.shortest_path(corpus, puzzle.answer["from"], puzzle.answer["to"])
    assert path and len(path) - 1 == puzzle.answer["par"]


def test_a_chain_is_only_valid_if_every_link_shared_a_film():
    corpus = dense_corpus()
    good = ["actor-0", "actor-1", "actor-2"]
    bad = ["actor-0", "actor-5", "actor-2"]
    assert check_chain(corpus, good)[0] is True
    assert check_chain(corpus, bad)[0] is False


def test_the_ladder_puts_the_obscure_film_first():
    p = puzzles.generate("ladder", DAY, SNAPSHOT)
    assert p.answer["name"] in p.public["options"]
    assert len(p.public["rungs"]) >= 4


def test_box_office_ranks_five_distinct_films():
    p = puzzles.generate("box-office", DAY, SNAPSHOT)
    keys = [f["key"] for f in p.public["films"]]
    assert len(set(keys)) == 5 and sorted(keys) == sorted(p.answer["order"])


def test_the_slate_budget_is_reachable_but_not_free():
    p = puzzles.generate("slate", DAY, SNAPSHOT)
    prices = sorted(x["price"] for x in p.public["pool"])
    assert sum(prices[:5]) <= p.public["budget"] < sum(prices[-5:])
    assert len(p.answer["best"]) == 5


# ------------------------------------------------------------------- grading
def test_the_ladder_pays_more_for_fewer_rungs():
    p = puzzles.generate("ladder", DAY, SNAPSHOT)
    early = scoring.grade_ladder(p, 1, True)
    late = scoring.grade_ladder(p, p.max_guesses, True)
    assert early.payout > late.payout
    assert scoring.grade_ladder(p, 1, False).payout == scoring.PAYOUTS["ladder"][0]


def test_a_perfect_ranking_beats_a_partial_one():
    p = puzzles.generate("box-office", DAY, SNAPSHOT)
    right = scoring.grade_box_office(p, p.answer["order"])
    backwards = scoring.grade_box_office(p, list(reversed(p.answer["order"])))
    assert right.fraction == 1.0 and right.correct
    assert backwards.fraction == 0.0 and not backwards.correct


def test_an_incomplete_ranking_scores_zero_not_an_error():
    p = puzzles.generate("box-office", DAY, SNAPSHOT)
    assert scoring.grade_box_office(p, p.answer["order"][:3]).fraction == 0.0


def test_cast_gap_rewards_the_first_guess():
    p = puzzles.generate("cast-gap", DAY, SNAPSHOT)
    assert scoring.grade_cast_gap(p, 1, True).payout > \
        scoring.grade_cast_gap(p, 2, True).payout


def test_going_over_budget_on_the_slate_scores_zero():
    p = puzzles.generate("slate", DAY, SNAPSHOT)
    dearest = [x["slug"] for x in sorted(p.public["pool"],
                                         key=lambda x: -x["price"])[:5]]
    grade = scoring.grade_slate(p, dearest)
    if sum(p.answer["prices"][s] for s in dearest) > p.answer["budget"]:
        assert grade.fraction == 0.0 and "budget" in grade.detail.lower()


def test_the_best_possible_slate_scores_full_marks():
    p = puzzles.generate("slate", DAY, SNAPSHOT)
    assert scoring.grade_slate(p, p.answer["best"]).fraction == pytest.approx(1.0)


def test_every_game_has_a_floor_so_failing_still_pays():
    """Being bad at film trivia must not exclude you from the market."""
    for game, (floor, ceiling) in scoring.PAYOUTS.items():
        assert scoring.payout_for(game, 0.0) == floor > 0
        assert scoring.payout_for(game, 1.0) == ceiling


def test_bombing_every_daily_game_still_pays_two_credits():
    total = sum(scoring.payout_for(g, 0.0) for g in scoring.DAILY_GAMES)
    assert total == db.cents(2.00)


# -------------------------------------------------------- playing and paying
def test_finishing_a_game_pays_once(conn, player):
    p = puzzles.generate("ladder", DAY, SNAPSHOT)
    grade = scoring.grade_ladder(p, 1, True)
    before = db.user(conn, player)["credits"]

    first = play.finish(conn, player, "ladder", DAY, grade, {})
    assert first == grade.payout
    assert db.user(conn, player)["credits"] == before + grade.payout

    again = play.finish(conn, player, "ladder", DAY, grade, {})
    assert again == 0
    assert db.user(conn, player)["credits"] == before + grade.payout


def test_a_payout_lands_in_the_ledger(conn, player):
    p = puzzles.generate("cast-gap", DAY, SNAPSHOT)
    play.finish(conn, player, "cast-gap", DAY, scoring.grade_cast_gap(p, 1, True), {})
    total = conn.execute("SELECT SUM(amount) AS t FROM ledger WHERE user_id = ?",
                         (player,)).fetchone()["t"]
    assert db.user(conn, player)["credits"] == total


def _finish_all(conn, player, day, fraction=1.0):
    for game in scoring.DAILY_GAMES:
        grade = scoring.Grade(fraction, scoring.payout_for(game, fraction), "", True)
        play.finish(conn, player, game, day, grade, {})


def test_the_perfect_day_bonus_pays_once(conn, player):
    _finish_all(conn, player, DAY)
    first = scoring.finish_day(conn, player, DAY)
    assert first and first[0] >= scoring.PERFECT_DAY_BONUS
    assert scoring.finish_day(conn, player, DAY) is None


def test_no_bonus_until_the_set_is_complete(conn, player):
    grade = scoring.Grade(1.0, 100, "", True)
    play.finish(conn, player, "ladder", DAY, grade, {})
    assert scoring.finish_day(conn, player, DAY) is None


def test_a_streak_builds_and_is_capped(conn, player):
    for i in range(6):
        _finish_all(conn, player, DAY - timedelta(days=i))
    assert scoring.streak_length(conn, player, DAY) == 6
    assert scoring.streak_bonus(1) == 0
    assert scoring.streak_bonus(3) == 100
    assert scoring.streak_bonus(99) == scoring.STREAK_CAP


def test_a_missed_day_breaks_the_streak(conn, player):
    _finish_all(conn, player, DAY)
    _finish_all(conn, player, DAY - timedelta(days=2))
    assert scoring.streak_length(conn, player, DAY) == 1


def test_solve_rate_is_tracked_for_pulling_unfair_puzzles(conn, player):
    play.start(conn, player, "ladder", DAY)
    assert play.solve_rate(conn, "ladder", DAY) == 0.0
    p = puzzles.generate("ladder", DAY, SNAPSHOT)
    play.finish(conn, player, "ladder", DAY, scoring.grade_ladder(p, 1, True), {})
    assert play.solve_rate(conn, "ladder", DAY) == 1.0


def test_the_minigame_leaderboard_ranks_this_month(conn):
    from app import leaderboards
    a = db.upsert_user(conn, "github", "a", "A", None, 0)["id"]
    b = db.upsert_user(conn, "github", "b", "B", None, 0)["id"]
    today = date.today()
    play.finish(conn, a, "ladder", today, scoring.Grade(1.0, 180, "", True), {})
    play.finish(conn, b, "ladder", today, scoring.Grade(0.2, 80, "", False), {})
    board = leaderboards.minigames(conn)
    assert [e.user_id for e in board] == [a, b]


# ------------------------------------------------------------------ the slate
def test_every_name_on_the_slate_can_actually_be_bought():
    """The budget was 1.6x the five cheapest, so names cost more than the whole
    budget on their own and were decoration nobody could pick."""
    from app.games.puzzles import generate

    for day in range(7):
        puzzle = generate("slate", DAY + timedelta(days=7 * day), SNAPSHOT)
        budget = puzzle.public["budget"]
        prices = [p["price"] for p in puzzle.public["pool"]]
        # the dearest name, plus four others at the floor, has to fit
        assert max(prices) + 4 <= budget, (
            f"{max(prices)} cannot be bought inside {budget}")


def test_the_slate_budget_does_not_buy_the_whole_board():
    """It has to be a choice: enough to reach past the bargain bin, not enough
    to take the top five."""
    from app.games.puzzles import generate

    for day in range(7):
        puzzle = generate("slate", DAY + timedelta(days=7 * day), SNAPSHOT)
        prices = sorted(p["price"] for p in puzzle.public["pool"])
        assert puzzle.public["budget"] < sum(prices[-5:])


def test_the_slate_reveals_the_best_slate_it_was_measured_against():
    from app.games.puzzles import generate

    answer = generate("slate", DAY, SNAPSHOT).answer
    assert len(answer["best"]) == 5
    assert answer["best_spend"] <= answer["budget"]
