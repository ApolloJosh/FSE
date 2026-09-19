"""Four boards, because one always collapses into "whoever started earliest".

The Scout board is the important one. It is the only board a new player can win
in their first season, and its winner has a story worth telling - which is the
whole point of a game about finding people early.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date

from . import db

SCOUT_MAX_ENTRY = db.cents(10.00)      # "bought under CR 10.00"
SEASON_START_MONTH = 9                 # a season runs Sep 1 - Mar 31


@dataclass
class Entry:
    rank: int
    user_id: int
    name: str
    value: float
    detail: str = ""


def season_id(on: date | None = None) -> str:
    on = on or date.today()
    start_year = on.year if on.month >= SEASON_START_MONTH else on.year - 1
    return f"{start_year}-{str(start_year + 1)[2:]}"


def ensure_season_baseline(conn: sqlite3.Connection, user_id: int,
                           on: date | None = None) -> None:
    """Freeze a player's portfolio value at their first sight of a new season,
    so season growth is measured from where they actually started."""
    current = season_id(on)
    row = db.user(conn, user_id)
    if row is None or row["season_id"] == current:
        return
    with db.tx(conn):
        conn.execute("UPDATE users SET season_id = ?, season_base = ? WHERE id = ?",
                     (current, db.portfolio_value(conn, user_id), user_id))


def _named(conn: sqlite3.Connection) -> dict[int, str]:
    return {r["id"]: r["display_name"]
            for r in conn.execute("SELECT id, display_name FROM users").fetchall()}


def all_time(conn: sqlite3.Connection, limit: int = 50) -> list[Entry]:
    names = _named(conn)
    rows = conn.execute(
        "SELECT u.id, u.credits + COALESCE(SUM(p.shares * p.held_value), 0) AS total"
        " FROM users u LEFT JOIN positions p ON p.user_id = u.id"
        " GROUP BY u.id ORDER BY total DESC LIMIT ?", (limit,)).fetchall()
    return [Entry(i, r["id"], names.get(r["id"], "?"), db.credits(r["total"]))
            for i, r in enumerate(rows, 1)]


def season(conn: sqlite3.Connection, limit: int = 50,
           on: date | None = None) -> list[Entry]:
    """Percentage growth, so a late starter is not out of it before they begin."""
    current = season_id(on)
    names = _named(conn)
    out = []
    for r in conn.execute(
        "SELECT u.id, u.season_base,"
        " u.credits + COALESCE(SUM(p.shares * p.held_value), 0) AS total"
        " FROM users u LEFT JOIN positions p ON p.user_id = u.id"
        " WHERE u.season_id = ? AND u.season_base > 0"
        " GROUP BY u.id", (current,)).fetchall():
        growth = r["total"] / r["season_base"] - 1
        out.append((growth, r["id"]))
    out.sort(reverse=True)
    return [Entry(i, uid, names.get(uid, "?"), growth)
            for i, (growth, uid) in enumerate(out[:limit], 1)]


def scout(conn: sqlite3.Connection, limit: int = 50) -> list[Entry]:
    """Best single gain on a position bought cheap. Open positions only - this
    board is about conviction you are still holding."""
    names = _named(conn)
    out = []
    for r in conn.execute(
        "SELECT p.user_id, p.slug, p.entry_price, p.held_value, s.name"
        " FROM positions p LEFT JOIN stocks s ON s.slug = p.slug"
        " WHERE p.entry_price > 0 AND p.entry_price <= ?",
        (SCOUT_MAX_ENTRY,)).fetchall():
        gain = r["held_value"] / r["entry_price"] - 1
        out.append((gain, r["user_id"], r["name"] or r["slug"]))
    out.sort(reverse=True)

    best_per_user, entries = set(), []
    for gain, user_id, stock in out:
        if user_id in best_per_user:
            continue
        best_per_user.add(user_id)
        entries.append(Entry(len(entries) + 1, user_id,
                             names.get(user_id, "?"), gain, stock))
        if len(entries) >= limit:
            break
    return entries


def minigames(conn: sqlite3.Connection, limit: int = 50) -> list[Entry]:
    """Cumulative minigame earnings this month. Resets monthly, so a newcomer
    is never permanently behind on the one board that rewards showing up."""
    from datetime import datetime
    month = (on_month := date.today().strftime("%Y-%m"))
    names = _named(conn)
    rows = conn.execute(
        "SELECT user_id, SUM(payout) AS total, COUNT(*) AS games FROM plays"
        " WHERE done = 1 AND on_date LIKE ? GROUP BY user_id"
        " ORDER BY total DESC LIMIT ?", (f"{month}%", limit)).fetchall()
    return [Entry(i, r["user_id"], names.get(r["user_id"], "?"),
                  db.credits(r["total"]), f"{r['games']} games")
            for i, r in enumerate(rows, 1)]


BOARDS = {
    "season": ("Season", "Percentage portfolio growth this season", season, "pct"),
    "all-time": ("All-time", "Total portfolio value", all_time, "credits"),
    "scout": ("Scout", "Best gain on a position bought under CR 10.00", scout, "pct"),
    "minigame": ("Minigame", "Credits earned from the daily games this month",
                 minigames, "credits"),
}
