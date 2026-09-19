"""Buying and selling. Every rule from the design doc lives here.

The one idea that makes this different from a normal market game: a position's
worth to its holder is not the market price. It is **held value**, which starts
at the entry price and moves by the market's gains scaled by how long they had
already held when the gain happened - and by the market's losses in full.

That asymmetry is the whole "buy in early" fantasy expressed as arithmetic, and
it is why a sell settles at held value rather than at the quote.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime

from fsx import constants as K

from . import db

FEE = K.TRADE_FEE
SETTLEMENT_DAYS = K.SETTLEMENT_DAYS
POSITION_CAP = K.POSITION_CAP_PCT
FREE_SLOTS = K.FREE_PORTFOLIO_SLOTS
SLOT_BASE = db.cents(20.00)          # slots 11-25
SLOT_STEP = db.cents(5.00)           # each slot past 25 costs this much more


class TradeError(Exception):
    """A rule said no. The message is shown to the player verbatim."""


@dataclass(frozen=True)
class Quote:
    shares: int
    price: int          # per share, centidollars
    gross: int
    fee: int
    total: int          # signed: negative is money leaving the account


def fee_on(amount: int) -> int:
    return int(round(amount * FEE))


def quote_buy(shares: int, price: int) -> Quote:
    gross = shares * price
    fee = fee_on(gross)
    return Quote(shares, price, gross, fee, -(gross + fee))


def quote_sell(shares: int, held_value: int) -> Quote:
    gross = shares * held_value
    fee = fee_on(gross)
    return Quote(shares, held_value, gross, fee, gross - fee)


def conviction(days_held_before_event: int) -> float:
    """How much of a gain a holder actually realizes. Late money still profits;
    early money profits far more."""
    for threshold, share in K.CONVICTION_LADDER:
        if days_held_before_event < threshold:
            return share
    return K.CONVICTION_LADDER[-1][1]


def slot_cost(current_slots: int) -> int | None:
    """Cost of the next slot, or None once the ladder is exhausted."""
    if current_slots < FREE_SLOTS:
        return 0
    if current_slots < 25:
        return SLOT_BASE
    return SLOT_BASE + SLOT_STEP * (current_slots - 24)


def days_between(earlier: str, later: date) -> int:
    return (later - datetime.strptime(earlier, "%Y-%m-%d").date()).days


# --------------------------------------------------------------------- buying
def buy(conn: sqlite3.Connection, user_id: int, slug: str, shares: int,
        on: date | None = None) -> Quote:
    on = on or date.today()
    if shares <= 0:
        raise TradeError("Enter a whole number of shares.")

    user = db.user(conn, user_id)
    if user is None:
        raise TradeError("Sign in to trade.")

    price = db.price_asof(conn, slug, on.isoformat())
    if price is None:
        raise TradeError("That stock is not listed.")

    q = quote_buy(shares, price)
    if user["credits"] + q.total < 0:
        short = db.credits(-(user["credits"] + q.total))
        raise TradeError(f"Short by CR {short:,.2f}. The fee is {FEE:.1%}.")

    existing = db.position(conn, user_id, slug)

    # The 5% cap forces diversification: one lucky pick must not decide a season.
    if POSITION_CAP:
        held_after = q.gross + (existing["shares"] * existing["held_value"]
                                if existing else 0)
        portfolio_after = db.portfolio_value(conn, user_id) - q.fee
        if portfolio_after > 0 and held_after > portfolio_after * POSITION_CAP:
            cap = db.credits(int(portfolio_after * POSITION_CAP))
            raise TradeError(
                f"That would put more than {POSITION_CAP:.0%} of your portfolio in "
                f"one stock. The most you can hold here right now is CR {cap:,.2f}.")

    if existing is None:
        open_positions = conn.execute(
            "SELECT COUNT(*) AS n FROM positions WHERE user_id = ?",
            (user_id,)).fetchone()["n"]
        if open_positions >= user["slots"]:
            raise TradeError(
                f"All {user['slots']} portfolio slots are full. Sell something, "
                f"or buy another slot.")

    today = on.isoformat()
    with db.tx(conn):
        if existing:
            total_shares = existing["shares"] + shares
            # Weighted averages, so adding to a winner does not reset the gains
            # already realized on the shares held longest.
            entry = round((existing["entry_price"] * existing["shares"]
                           + price * shares) / total_shares)
            held = round((existing["held_value"] * existing["shares"]
                          + price * shares) / total_shares)
            conn.execute(
                "UPDATE positions SET shares = ?, entry_price = ?, held_value = ?,"
                " last_buy_on = ? WHERE id = ?",
                (total_shares, entry, held, today, existing["id"]))
        else:
            conn.execute(
                "INSERT INTO positions (user_id, slug, shares, entry_price,"
                " held_value, opened_on, last_buy_on) VALUES (?,?,?,?,?,?,?)",
                (user_id, slug, shares, price, price, today, today))

        conn.execute("UPDATE users SET credits = credits + ? WHERE id = ?",
                     (q.total, user_id))
        conn.execute(
            "INSERT INTO trades (user_id, slug, side, shares, price, fee,"
            " cash_delta, at) VALUES (?,?,'buy',?,?,?,?,?)",
            (user_id, slug, shares, price, q.fee, q.total, db.now()))
        conn.execute(
            "INSERT INTO ledger (user_id, kind, amount, note, at) VALUES (?,?,?,?,?)",
            (user_id, "trade", q.total, f"Bought {shares} {slug}", db.now()))
    return q


# -------------------------------------------------------------------- selling
def sell(conn: sqlite3.Connection, user_id: int, slug: str, shares: int,
         on: date | None = None) -> Quote:
    on = on or date.today()
    if shares <= 0:
        raise TradeError("Enter a whole number of shares.")

    pos = db.position(conn, user_id, slug)
    if pos is None:
        raise TradeError("You do not hold that stock.")
    if shares > pos["shares"]:
        raise TradeError(f"You hold {pos['shares']} shares.")

    held_days = days_between(pos["last_buy_on"], on)
    if held_days < SETTLEMENT_DAYS:
        wait = SETTLEMENT_DAYS - held_days
        raise TradeError(
            f"Settlement is {SETTLEMENT_DAYS} days. {wait} to go on this position.")

    q = quote_sell(shares, pos["held_value"])
    with db.tx(conn):
        if shares == pos["shares"]:
            conn.execute("DELETE FROM positions WHERE id = ?", (pos["id"],))
        else:
            conn.execute("UPDATE positions SET shares = shares - ? WHERE id = ?",
                         (shares, pos["id"]))
        conn.execute("UPDATE users SET credits = credits + ? WHERE id = ?",
                     (q.total, user_id))
        conn.execute(
            "INSERT INTO trades (user_id, slug, side, shares, price, fee,"
            " cash_delta, at) VALUES (?,?,'sell',?,?,?,?,?)",
            (user_id, slug, shares, pos["held_value"], q.fee, q.total, db.now()))
        conn.execute(
            "INSERT INTO ledger (user_id, kind, amount, note, at) VALUES (?,?,?,?,?)",
            (user_id, "trade", q.total, f"Sold {shares} {slug}", db.now()))
    return q


def buy_slot(conn: sqlite3.Connection, user_id: int) -> int:
    user = db.user(conn, user_id)
    if user is None:
        raise TradeError("Sign in first.")
    cost = slot_cost(user["slots"])
    if cost is None:
        raise TradeError("No more slots available.")
    if user["credits"] < cost:
        raise TradeError(f"A slot costs CR {db.credits(cost):,.2f}.")
    with db.tx(conn):
        conn.execute("UPDATE users SET credits = credits - ?, slots = slots + 1"
                     " WHERE id = ?", (cost, user_id))
        conn.execute(
            "INSERT INTO ledger (user_id, kind, amount, note, at) VALUES (?,?,?,?,?)",
            (user_id, "slot", -cost, "Bought a portfolio slot", db.now()))
    return cost
