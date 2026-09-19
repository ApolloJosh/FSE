"""The money logic. These matter most in the whole project: everything else
renders a number, this decides one."""

from datetime import date, timedelta

import pytest

from app import db, leaderboards, marking, trading
from app.trading import TradeError
from fsx import constants as K

TODAY = date(2026, 6, 1)
BASE = TODAY - timedelta(days=500)      # opening prices, so a move has a "before"


@pytest.fixture
def fresh():
    """A migrated database with no prices at all."""
    c = db.connect(":memory:")
    db.migrate(c)
    return c


@pytest.fixture
def conn(fresh):
    c = fresh
    db.record_prices(c, BASE, [
        {"slug": "cheap", "name": "Cheap Newcomer", "is_director": False,
         "price": db.cents(4.00), "cp": 50.0, "tier": "Debut"},
        {"slug": "mid", "name": "Mid Career", "is_director": False,
         "price": db.cents(20.00), "cp": 700.0, "tier": "Working"},
        {"slug": "legend", "name": "Big Legend", "is_director": False,
         "price": db.cents(200.00), "cp": 12000.0, "tier": "Legend"},
    ])
    return c


@pytest.fixture
def player(conn):
    return db.upsert_user(conn, "github", "1", "Josh", None, db.cents(50000.00))["id"]


def move_price(conn, slug, price, on):
    db.record_prices(conn, on, [{"slug": slug, "name": slug, "is_director": False,
                                 "price": db.cents(price), "cp": 1.0, "tier": "x"}])


# ------------------------------------------------------------------ the basics
def test_money_is_never_a_float():
    assert db.cents(4.00) == 400
    assert db.cents(0.07) == 7
    assert db.credits(1234) == 12.34


def test_buying_costs_the_price_plus_the_fee(conn, player):
    before = db.user(conn, player)["credits"]
    q = trading.buy(conn, player, "mid", 10, on=TODAY)
    assert q.gross == db.cents(200.00)
    assert q.fee == db.cents(3.00)
    assert db.user(conn, player)["credits"] == before - db.cents(203.00)


def test_a_position_starts_at_its_entry_price(conn, player):
    trading.buy(conn, player, "mid", 5, on=TODAY)
    pos = db.position(conn, player, "mid")
    assert pos["entry_price"] == pos["held_value"] == db.cents(20.00)


def test_you_cannot_spend_money_you_do_not_have(conn):
    poor = db.upsert_user(conn, "github", "broke", "Broke", None, db.cents(10.00))["id"]
    with pytest.raises(TradeError, match="Short by"):
        trading.buy(conn, poor, "mid", 1, on=TODAY)


def test_the_fee_is_what_makes_it_unaffordable(conn):
    user = db.upsert_user(conn, "github", "edge", "Edge", None, db.cents(20.00))["id"]
    with pytest.raises(TradeError, match="Short by"):
        trading.buy(conn, user, "mid", 1, on=TODAY)


def test_unlisted_stocks_cannot_be_bought(conn, player):
    with pytest.raises(TradeError, match="not listed"):
        trading.buy(conn, player, "nobody", 1, on=TODAY)


def test_zero_and_negative_orders_are_refused(conn, player):
    for bad in (0, -5):
        with pytest.raises(TradeError):
            trading.buy(conn, player, "mid", bad, on=TODAY)


# --------------------------------------------------------------- settlement
def test_you_cannot_sell_inside_the_settlement_window(conn, player):
    trading.buy(conn, player, "mid", 10, on=TODAY)
    with pytest.raises(TradeError, match="Settlement"):
        trading.sell(conn, player, "mid", 5, on=TODAY + timedelta(days=6))


def test_you_can_sell_the_day_settlement_ends(conn, player):
    trading.buy(conn, player, "mid", 10, on=TODAY)
    q = trading.sell(conn, player, "mid", 10,
                     on=TODAY + timedelta(days=K.SETTLEMENT_DAYS))
    assert q.total > 0
    assert db.position(conn, player, "mid") is None


def test_buying_more_restarts_the_settlement_clock(conn, player):
    trading.buy(conn, player, "mid", 5, on=TODAY)
    trading.buy(conn, player, "mid", 5, on=TODAY + timedelta(days=5))
    with pytest.raises(TradeError, match="Settlement"):
        trading.sell(conn, player, "mid", 5, on=TODAY + timedelta(days=8))


def test_you_cannot_sell_more_than_you_hold(conn, player):
    trading.buy(conn, player, "mid", 3, on=TODAY)
    with pytest.raises(TradeError, match="hold 3"):
        trading.sell(conn, player, "mid", 4, on=TODAY + timedelta(days=10))


def test_you_cannot_sell_what_you_never_bought(conn, player):
    with pytest.raises(TradeError, match="do not hold"):
        trading.sell(conn, player, "mid", 1, on=TODAY + timedelta(days=30))


# ------------------------------------------------------------------- the caps
def test_one_stock_cannot_take_over_a_portfolio(conn):
    user = db.upsert_user(conn, "github", "whale", "Whale", None,
                          db.cents(1000.00))["id"]
    with pytest.raises(TradeError, match="5%"):
        trading.buy(conn, user, "mid", 40, on=TODAY)


def test_a_position_inside_the_cap_is_allowed(conn):
    user = db.upsert_user(conn, "github", "ok", "OK", None, db.cents(1000.00))["id"]
    trading.buy(conn, user, "mid", 2, on=TODAY)
    assert db.position(conn, user, "mid")["shares"] == 2


def test_slots_run_out(conn):
    user = db.upsert_user(conn, "github", "many", "Many", None,
                          db.cents(100000.00))["id"]
    for i in range(K.FREE_PORTFOLIO_SLOTS):
        db.record_prices(conn, TODAY, [{"slug": f"s{i}", "name": f"S{i}",
                                        "is_director": False, "price": db.cents(10.00),
                                        "cp": 1.0, "tier": "Working"}])
        trading.buy(conn, user, f"s{i}", 1, on=TODAY)
    db.record_prices(conn, TODAY, [{"slug": "extra", "name": "Extra",
                                    "is_director": False, "price": db.cents(10.00),
                                    "cp": 1.0, "tier": "Working"}])
    with pytest.raises(TradeError, match="slots are full"):
        trading.buy(conn, user, "extra", 1, on=TODAY)


def test_buying_a_slot_costs_and_works(conn, player):
    before = db.user(conn, player)["credits"]
    cost = trading.buy_slot(conn, player)
    user = db.user(conn, player)
    assert user["slots"] == K.FREE_PORTFOLIO_SLOTS + 1
    assert user["credits"] == before - cost


def test_slots_get_more_expensive_past_twenty_five():
    assert trading.slot_cost(10) == trading.slot_cost(24)
    assert trading.slot_cost(25) > trading.slot_cost(24)
    assert trading.slot_cost(30) > trading.slot_cost(25)


# ------------------------------------------------------- conviction and marking
def test_the_conviction_ladder_matches_the_design_doc():
    assert trading.conviction(1) == 0.40
    assert trading.conviction(10) == 0.70
    assert trading.conviction(60) == 1.00
    assert trading.conviction(200) == 1.15
    assert trading.conviction(400) == 1.30


def test_an_early_holder_keeps_more_of_a_gain_than_a_late_one(conn):
    """The whole design in one test. Same stock, same night, different returns."""
    early = db.upsert_user(conn, "github", "early", "Early", None,
                           db.cents(50000.00))["id"]
    late = db.upsert_user(conn, "github", "late", "Late", None,
                          db.cents(50000.00))["id"]
    trading.buy(conn, early, "mid", 10, on=TODAY - timedelta(days=400))
    trading.buy(conn, late, "mid", 10, on=TODAY - timedelta(days=1))

    move_price(conn, "mid", 30.00, TODAY)
    marking.mark_positions(conn, TODAY)

    early_held = db.position(conn, early, "mid")["held_value"]
    late_held = db.position(conn, late, "mid")["held_value"]
    assert early_held == db.cents(20.00) + int(db.cents(10.00) * 1.30)
    assert late_held == db.cents(20.00) + int(db.cents(10.00) * 0.40)
    assert early_held > late_held


def test_losses_land_in_full_however_long_you_held(conn):
    early = db.upsert_user(conn, "github", "e2", "E", None, db.cents(50000.00))["id"]
    late = db.upsert_user(conn, "github", "l2", "L", None, db.cents(50000.00))["id"]
    trading.buy(conn, early, "mid", 10, on=TODAY - timedelta(days=400))
    trading.buy(conn, late, "mid", 10, on=TODAY - timedelta(days=1))

    move_price(conn, "mid", 15.00, TODAY)
    marking.mark_positions(conn, TODAY)
    assert db.position(conn, early, "mid")["held_value"] == db.cents(15.00)
    assert db.position(conn, late, "mid")["held_value"] == db.cents(15.00)


def test_marking_twice_does_not_pay_twice(conn, player):
    trading.buy(conn, player, "mid", 10, on=TODAY - timedelta(days=400))
    move_price(conn, "mid", 30.00, TODAY)
    first = marking.mark_positions(conn, TODAY)
    held = db.position(conn, player, "mid")["held_value"]

    second = marking.mark_positions(conn, TODAY)
    assert second.skipped
    assert db.position(conn, player, "mid")["held_value"] == held
    assert first.positions == 1


def test_held_value_never_falls_below_the_price_floor(conn, player):
    trading.buy(conn, player, "cheap", 10, on=TODAY)
    move_price(conn, "cheap", 0.01, TODAY + timedelta(days=1))
    marking.mark_positions(conn, TODAY + timedelta(days=1))
    assert db.position(conn, player, "cheap")["held_value"] >= db.cents(K.PRICE_FLOOR)


def test_a_sell_settles_at_held_value_not_the_quote(conn, player):
    trading.buy(conn, player, "mid", 10, on=TODAY - timedelta(days=400))
    move_price(conn, "mid", 30.00, TODAY)
    marking.mark_positions(conn, TODAY)

    held = db.position(conn, player, "mid")["held_value"]
    assert held > db.cents(30.00)
    q = trading.sell(conn, player, "mid", 10, on=TODAY)
    assert q.price == held


def test_a_stock_with_no_price_today_is_left_alone(conn, player):
    trading.buy(conn, player, "mid", 10, on=TODAY)
    move_price(conn, "cheap", 9.00, TODAY + timedelta(days=1))   # only cheap moves
    marking.mark_positions(conn, TODAY + timedelta(days=1))
    assert db.position(conn, player, "mid")["held_value"] == db.cents(20.00)


# ---------------------------------------------------------------- the full loop
def test_the_breakout_returns_what_the_design_doc_promises(fresh):
    conn = fresh
    scout_player = db.upsert_user(conn, "github", "s", "Scout", None,
                                  db.cents(50000.00))["id"]
    start = TODAY - timedelta(days=730)
    db.record_prices(conn, start, [{"slug": "cheap", "name": "Cheap",
                                    "is_director": False, "price": db.cents(5.56),
                                    "cp": 107.0, "tier": "Debut"}])
    trading.buy(conn, scout_player, "cheap", 100, on=start)

    on = start
    for price in (11.87, 16.94, 23.70, 44.38):
        on += timedelta(days=180)
        move_price(conn, "cheap", price, on)
        marking.mark_positions(conn, on)

    held = db.credits(db.position(conn, scout_player, "cheap")["held_value"])
    assert held > 44.38                     # conviction paid above the market
    assert held / 5.56 - 1 > 7.0            # better than a 700% return


def test_cash_and_the_ledger_always_reconcile(conn, player):
    """No path may create or destroy Credits without a ledger row."""
    trading.buy(conn, player, "mid", 10, on=TODAY)
    trading.buy(conn, player, "cheap", 20, on=TODAY)
    trading.sell(conn, player, "mid", 4, on=TODAY + timedelta(days=10))
    trading.buy_slot(conn, player)
    marking.pay_dividends(conn, TODAY)

    total = conn.execute("SELECT SUM(amount) AS t FROM ledger WHERE user_id = ?",
                         (player,)).fetchone()["t"]
    assert db.user(conn, player)["credits"] == total


# ----------------------------------------------------------------- dividends
def test_dividends_pay_once_a_quarter(conn, player):
    trading.buy(conn, player, "mid", 10, on=TODAY)
    before = db.user(conn, player)["credits"]
    assert marking.pay_dividends(conn, TODAY) == 1
    after = db.user(conn, player)["credits"]
    assert after > before
    assert marking.pay_dividends(conn, TODAY) == 0
    assert db.user(conn, player)["credits"] == after


def test_a_longer_hold_pays_a_bigger_dividend(conn):
    new = db.upsert_user(conn, "github", "n", "New", None, db.cents(50000.00))["id"]
    old = db.upsert_user(conn, "github", "o", "Old", None, db.cents(50000.00))["id"]
    trading.buy(conn, new, "mid", 10, on=TODAY)
    trading.buy(conn, old, "mid", 10, on=BASE)      # listed since BASE, ~16 months
    marking.pay_dividends(conn, TODAY)
    paid = {r["user_id"]: r["amount"]
            for r in conn.execute("SELECT * FROM dividends").fetchall()}
    assert paid[old] > paid[new]


# --------------------------------------------------------------- leaderboards
def test_the_scout_board_only_counts_cheap_entries(conn):
    a = db.upsert_user(conn, "github", "a", "Scout A", None, db.cents(50000.00))["id"]
    b = db.upsert_user(conn, "github", "b", "Whale B", None, db.cents(500000.00))["id"]
    trading.buy(conn, a, "cheap", 50, on=TODAY)
    trading.buy(conn, b, "legend", 10, on=TODAY)

    later = TODAY + timedelta(days=1)
    move_price(conn, "cheap", 12.00, later)
    move_price(conn, "legend", 600.00, later)
    marking.mark_positions(conn, later)

    assert [e.user_id for e in leaderboards.scout(conn)] == [a]


def test_the_season_board_ranks_by_growth_not_size(conn):
    small = db.upsert_user(conn, "github", "sm", "Small", None, db.cents(1000.00))["id"]
    big = db.upsert_user(conn, "github", "bg", "Big", None, db.cents(100000.00))["id"]
    for uid in (small, big):
        leaderboards.ensure_season_baseline(conn, uid, TODAY)
    conn.execute("UPDATE users SET credits = credits * 2 WHERE id = ?", (small,))

    board = leaderboards.season(conn, on=TODAY)
    assert board[0].user_id == small
    assert board[0].value == pytest.approx(1.0)


def test_all_time_counts_cash_plus_held_value(conn, player):
    trading.buy(conn, player, "mid", 10, on=TODAY)
    board = leaderboards.all_time(conn)
    assert board[0].user_id == player
    assert board[0].value == pytest.approx(db.credits(db.portfolio_value(conn, player)))


def test_a_season_baseline_is_frozen_once(conn, player):
    leaderboards.ensure_season_baseline(conn, player, TODAY)
    base = db.user(conn, player)["season_base"]
    trading.buy(conn, player, "mid", 10, on=TODAY)
    leaderboards.ensure_season_baseline(conn, player, TODAY)
    assert db.user(conn, player)["season_base"] == base


def test_a_trade_prices_off_the_market_as_it_stood_that_day(conn, player):
    """Not off the newest row in the table. Identical in production; the whole
    correctness of a replay or a backfill otherwise."""
    later = TODAY + timedelta(days=10)
    move_price(conn, "mid", 99.00, later)             # a future quote exists
    trading.buy(conn, player, "mid", 1, on=TODAY)     # but we trade at TODAY
    assert db.position(conn, player, "mid")["entry_price"] == db.cents(20.00)


def test_a_stock_not_yet_listed_on_that_date_cannot_be_traded(conn, player):
    with pytest.raises(TradeError, match="not listed"):
        trading.buy(conn, player, "mid", 1, on=BASE - timedelta(days=1))
