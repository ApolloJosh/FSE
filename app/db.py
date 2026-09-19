"""SQLite access. Plain sqlite3 on purpose - the money logic should be readable
without knowing an ORM, and every write here names its own transaction.

All currency is INTEGER CENTIDOLLARS. 1 CR = 100. Nothing in this app ever puts
money in a float.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA = Path(__file__).with_name("schema.sql")
DEFAULT_DB = Path(__file__).resolve().parents[1] / "data" / "market.db"


def cents(credits: float) -> int:
    return int(round(credits * 100))


def credits(cents_value: int) -> float:
    return cents_value / 100.0


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: Path | str = DEFAULT_DB) -> sqlite3.Connection:
    path = Path(path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA.read_text())


@contextmanager
def tx(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """One trade, one transaction. A partial trade is worse than a failed one."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


# ------------------------------------------------------------------- users
def upsert_user(conn: sqlite3.Connection, provider: str, provider_id: str,
                display_name: str, avatar_url: str | None,
                starting_credits: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM users WHERE provider = ? AND provider_id = ?",
        (provider, provider_id)).fetchone()
    if row:
        return row
    with tx(conn):
        cur = conn.execute(
            "INSERT INTO users (provider, provider_id, display_name, avatar_url,"
            " credits, created_at) VALUES (?,?,?,?,?,?)",
            (provider, provider_id, display_name, avatar_url, starting_credits, now()))
        conn.execute(
            "INSERT INTO ledger (user_id, kind, amount, note, at) VALUES (?,?,?,?,?)",
            (cur.lastrowid, "signup", starting_credits, "Starting bankroll", now()))
    return conn.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()


def user(conn: sqlite3.Connection, user_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


# ------------------------------------------------------------------ prices
def latest_date(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT MAX(on_date) AS d FROM prices").fetchone()
    return row["d"] if row and row["d"] else None


def price_asof(conn: sqlite3.Connection, slug: str, on: str) -> int | None:
    """The market price as of a date: the most recent quote on or before it.

    A trade must price off the market as it stood when the trade happened, not
    off whatever row is newest in the table. Identical in production, where
    today's row is always the newest - but the difference is the whole
    correctness of a backfill or a replay.
    """
    row = conn.execute(
        "SELECT price FROM prices WHERE slug = ? AND on_date <= ?"
        " ORDER BY on_date DESC LIMIT 1", (slug, on)).fetchone()
    return row["price"] if row else None


def price_on(conn: sqlite3.Connection, slug: str, on: str) -> int | None:
    row = conn.execute("SELECT price FROM prices WHERE slug = ? AND on_date = ?",
                       (slug, on)).fetchone()
    return row["price"] if row else None


def latest_prices(conn: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    on = latest_date(conn)
    if not on:
        return {}
    rows = conn.execute(
        "SELECT p.*, s.name, s.is_director FROM prices p"
        " JOIN stocks s ON s.slug = p.slug WHERE p.on_date = ?", (on,)).fetchall()
    return {r["slug"]: r for r in rows}


def price_history(conn: sqlite3.Connection, slug: str, limit: int = 400) -> list[sqlite3.Row]:
    return list(reversed(conn.execute(
        "SELECT on_date, price FROM prices WHERE slug = ?"
        " ORDER BY on_date DESC LIMIT ?", (slug, limit)).fetchall()))


def movers(conn: sqlite3.Connection, days: int = 365) -> list[sqlite3.Row]:
    """Every stock's move over the last `days`, as one query rather than 247.

    The reference point is the newest quote on or before the target date, so a
    fortnightly seed and a nightly mark both work without special-casing.
    """
    on = latest_date(conn)
    if not on:
        return []
    ref = conn.execute(
        "SELECT MAX(on_date) AS d FROM prices WHERE on_date <= date(?, ?)",
        (on, f"-{int(days)} days")).fetchone()
    if not ref or not ref["d"] or ref["d"] == on:
        return []
    return conn.execute(
        "SELECT n.slug, s.name, s.is_director, n.price, n.tier, o.price AS was,"
        "       (n.price * 1.0 / o.price) - 1 AS change"
        "  FROM prices n"
        "  JOIN prices o ON o.slug = n.slug AND o.on_date = ?"
        "  JOIN stocks s ON s.slug = n.slug"
        " WHERE n.on_date = ? AND o.price > 0"
        " ORDER BY change DESC", (ref["d"], on)).fetchall()


def all_history(conn: sqlite3.Connection, days: int = 365
                ) -> dict[str, list[sqlite3.Row]]:
    """Every stock's recent points in one query, for the market table's
    sparklines. 247 separate queries worked and was silly."""
    on = latest_date(conn)
    if not on:
        return {}
    rows = conn.execute(
        "SELECT slug, on_date, price FROM prices WHERE on_date >= date(?, ?)"
        " ORDER BY slug, on_date", (on, f"-{int(days)} days")).fetchall()
    out: dict[str, list[sqlite3.Row]] = {}
    for r in rows:
        out.setdefault(r["slug"], []).append(r)
    return out


def record_prices(conn: sqlite3.Connection, on: date,
                  rows: list[dict[str, Any]]) -> int:
    """Upsert one day of prices, and the stock list alongside."""
    with tx(conn):
        for r in rows:
            conn.execute(
                "INSERT INTO stocks (slug, name, is_director) VALUES (?,?,?)"
                " ON CONFLICT(slug) DO UPDATE SET name = excluded.name,"
                " is_director = excluded.is_director",
                (r["slug"], r["name"], int(r["is_director"])))
            conn.execute(
                "INSERT INTO prices (slug, on_date, price, cp, tier) VALUES (?,?,?,?,?)"
                " ON CONFLICT(slug, on_date) DO UPDATE SET price = excluded.price,"
                " cp = excluded.cp, tier = excluded.tier",
                (r["slug"], on.isoformat(), r["price"], r["cp"], r["tier"]))
    return len(rows)


# --------------------------------------------------------------- positions
def positions(conn: sqlite3.Connection, user_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT p.*, s.name FROM positions p LEFT JOIN stocks s ON s.slug = p.slug"
        " WHERE p.user_id = ? ORDER BY p.shares * p.held_value DESC",
        (user_id,)).fetchall()


def position(conn: sqlite3.Connection, user_id: int, slug: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM positions WHERE user_id = ? AND slug = ?",
                        (user_id, slug)).fetchone()


def portfolio_value(conn: sqlite3.Connection, user_id: int) -> int:
    """Cash plus held value. Held value, not market price - what a sell pays."""
    row = conn.execute("SELECT credits FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        return 0
    held = conn.execute(
        "SELECT COALESCE(SUM(shares * held_value), 0) AS v FROM positions"
        " WHERE user_id = ?", (user_id,)).fetchone()["v"]
    return row["credits"] + held


def ledger(conn: sqlite3.Connection, user_id: int, limit: int = 40) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM ledger WHERE user_id = ? ORDER BY at DESC, id DESC LIMIT ?",
        (user_id, limit)).fetchall()


def trades(conn: sqlite3.Connection, user_id: int, limit: int = 40) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT t.*, s.name FROM trades t LEFT JOIN stocks s ON s.slug = t.slug"
        " WHERE t.user_id = ? ORDER BY t.at DESC, t.id DESC LIMIT ?",
        (user_id, limit)).fetchall()
