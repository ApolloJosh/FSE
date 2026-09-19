"""The nightly job: reprice the market, mark every position, pay dividends.

Marking is where the conviction rule actually bites. When a stock moves from
yesterday's price to today's, each holder takes a different share of that move
depending on how long they had held before it happened - gains scaled, losses
in full. Two people holding the same stock on the same night can end the night
worth different amounts, and that is the design working.

The job is idempotent. It records the days it has marked and refuses to mark one
twice, because running it twice must never pay a gain twice.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from fsx import constants as K
from fsx.engine import value_person
from fsx.site import slug as slugify
from fsx.store import load

from . import db
from .trading import conviction, days_between

DIVIDEND_BASE = 0.005        # per quarter, on held value
DIVIDEND_PER_YEAR = 0.0025
DIVIDEND_CAP = 0.02


@dataclass
class MarkReport:
    on: date
    stocks: int = 0
    positions: int = 0
    gains: int = 0
    losses: int = 0
    skipped: bool = False


def refresh_prices(conn: sqlite3.Connection, snapshot: Path,
                   on: date | None = None) -> int:
    """Run the engine over the snapshot and store today's prices."""
    on = on or date.today()
    people, _ = load(snapshot)
    rows = []
    for person in people:
        valuation = value_person(person, on)
        rows.append({
            "slug": slugify(person.name), "name": person.name,
            "is_director": person.is_director,
            "price": db.cents(valuation.price), "cp": valuation.cp,
            "tier": valuation.tier,
        })
    return db.record_prices(conn, on, rows)


def mark_positions(conn: sqlite3.Connection, on: date | None = None) -> MarkReport:
    """Move every position's held value by today's price change."""
    on = on or date.today()
    today = on.isoformat()
    report = MarkReport(on)

    if conn.execute("SELECT 1 FROM marks WHERE on_date = ?", (today,)).fetchone():
        report.skipped = True
        return report

    previous = conn.execute(
        "SELECT MAX(on_date) AS d FROM prices WHERE on_date < ?", (today,)).fetchone()["d"]
    if previous is None:
        # First ever run: nothing to compare against, so nothing has moved.
        with db.tx(conn):
            conn.execute("INSERT INTO marks (on_date, positions, ran_at)"
                         " VALUES (?,?,?)", (today, 0, db.now()))
        return report

    moves = {
        r["slug"]: (r["was"], r["now_price"])
        for r in conn.execute(
            "SELECT a.slug, b.price AS was, a.price AS now_price"
            " FROM prices a JOIN prices b ON b.slug = a.slug AND b.on_date = ?"
            " WHERE a.on_date = ?", (previous, today)).fetchall()
    }
    report.stocks = len(moves)

    with db.tx(conn):
        for pos in conn.execute("SELECT * FROM positions").fetchall():
            move = moves.get(pos["slug"])
            if not move:
                continue
            was, now_price = move
            delta = now_price - was
            if delta == 0:
                continue

            if delta > 0:
                held_before = days_between(pos["opened_on"], on)
                realized = int(round(delta * conviction(held_before)))
                report.gains += 1
            else:
                realized = delta               # losses always land in full
                report.losses += 1

            # The floor holds for holders too: a position never prices below it.
            new_held = max(db.cents(K.PRICE_FLOOR), pos["held_value"] + realized)
            conn.execute("UPDATE positions SET held_value = ? WHERE id = ?",
                         (new_held, pos["id"]))
            report.positions += 1

        conn.execute("INSERT INTO marks (on_date, positions, ran_at) VALUES (?,?,?)",
                     (today, report.positions, db.now()))
    return report


def quarter_of(on: date) -> str:
    return f"{on.year}Q{(on.month - 1) // 3 + 1}"


def pay_dividends(conn: sqlite3.Connection, on: date | None = None) -> int:
    """0.5% of held value a quarter, plus 0.25% per full year held, capped at 2%.

    Small on purpose: it is the one faucet that scales with portfolio size, so
    it gives a reason to hold a steady veteran without letting the rich compound
    away from everyone else.
    """
    on = on or date.today()
    quarter = quarter_of(on)
    paid = 0

    for user_row in conn.execute("SELECT id FROM users").fetchall():
        user_id = user_row["id"]
        if conn.execute("SELECT 1 FROM dividends WHERE quarter = ? AND user_id = ?",
                        (quarter, user_id)).fetchone():
            continue

        amount = 0
        for pos in conn.execute("SELECT * FROM positions WHERE user_id = ?",
                                (user_id,)).fetchall():
            years = days_between(pos["opened_on"], on) / 365.25
            rate = min(DIVIDEND_CAP, DIVIDEND_BASE + DIVIDEND_PER_YEAR * int(years))
            amount += int(round(pos["shares"] * pos["held_value"] * rate))

        if amount <= 0:
            continue
        with db.tx(conn):
            conn.execute("UPDATE users SET credits = credits + ? WHERE id = ?",
                         (amount, user_id))
            conn.execute("INSERT INTO dividends (quarter, user_id, amount)"
                         " VALUES (?,?,?)", (quarter, user_id, amount))
            conn.execute(
                "INSERT INTO ledger (user_id, kind, amount, note, at)"
                " VALUES (?,?,?,?,?)",
                (user_id, "dividend", amount, f"{quarter} dividend", db.now()))
        paid += 1
    return paid


def run(conn: sqlite3.Connection, snapshot: Path, on: date | None = None,
        with_dividends: bool = False) -> MarkReport:
    on = on or date.today()
    refresh_prices(conn, snapshot, on)
    report = mark_positions(conn, on)
    if with_dividends:
        pay_dividends(conn, on)
    return report
