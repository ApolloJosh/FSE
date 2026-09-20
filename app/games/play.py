"""Play state: one row per player per game per day.

The UNIQUE(user_id, game, on_date) constraint is the anti-replay mechanism.
A day's puzzle pays exactly once, whatever a player does with the form.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date

from app import db

from . import scoring
from .puzzles import GAMES, WEEKLY


def get(conn: sqlite3.Connection, user_id: int, game: str,
        on: date) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM plays WHERE user_id = ? AND game = ? AND on_date = ?",
        (user_id, game, on.isoformat())).fetchone()


def state_of(row: sqlite3.Row | None) -> dict:
    if not row:
        return {}
    try:
        return json.loads(row["state"])
    except (TypeError, ValueError):
        return {}


def start(conn: sqlite3.Connection, user_id: int, game: str, on: date) -> sqlite3.Row:
    row = get(conn, user_id, game, on)
    if row:
        return row
    with db.tx(conn):
        conn.execute(
            "INSERT INTO plays (user_id, game, on_date, state, at) VALUES (?,?,?,?,?)",
            (user_id, game, on.isoformat(), "{}", db.now()))
        conn.execute(
            "INSERT INTO puzzle_stats (game, on_date, attempts, solves)"
            " VALUES (?,?,1,0) ON CONFLICT(game, on_date)"
            " DO UPDATE SET attempts = attempts + 1",
            (game, on.isoformat()))
    return get(conn, user_id, game, on)


def save_state(conn: sqlite3.Connection, user_id: int, game: str, on: date,
               state: dict) -> None:
    with db.tx(conn):
        conn.execute("UPDATE plays SET state = ? WHERE user_id = ? AND game = ?"
                     " AND on_date = ?",
                     (json.dumps(state), user_id, game, on.isoformat()))


def finish(conn: sqlite3.Connection, user_id: int, game: str, on: date,
           grade: scoring.Grade, state: dict) -> int:
    """Record the result and pay. Returns the payout, or 0 if already finished.

    A replay is a finish on a day that has already paid. It records the new
    attempt so the page can show it, and pays nothing - the day is worth
    exactly one payout however many times it is played.
    """
    row = get(conn, user_id, game, on)
    if row is None:
        row = start(conn, user_id, game, on)
    if row["done"]:
        return 0

    if row["paid"]:
        with db.tx(conn):
            conn.execute(
                "UPDATE plays SET state = ?, done = 1, at = ? WHERE id = ?",
                (json.dumps({**state, "replay": True}), db.now(), row["id"]))
        return 0

    with db.tx(conn):
        conn.execute(
            "UPDATE plays SET state = ?, fraction = ?, payout = ?, done = 1,"
            " paid = 1, at = ? WHERE id = ?",
            (json.dumps(state), grade.fraction, grade.payout, db.now(), row["id"]))
        conn.execute("UPDATE users SET credits = credits + ? WHERE id = ?",
                     (grade.payout, user_id))
        conn.execute(
            "INSERT INTO ledger (user_id, kind, amount, note, at) VALUES (?,?,?,?,?)",
            (user_id, "minigame", grade.payout, f"{game} {on.isoformat()}", db.now()))
        if grade.correct:
            conn.execute(
                "INSERT INTO puzzle_stats (game, on_date, attempts, solves)"
                " VALUES (?,?,0,1) ON CONFLICT(game, on_date)"
                " DO UPDATE SET solves = solves + 1", (game, on.isoformat()))
    return grade.payout


def today_summary(conn: sqlite3.Connection, user_id: int, on: date) -> dict:
    rows = {r["game"]: r for r in conn.execute(
        "SELECT * FROM plays WHERE user_id = ? AND on_date = ?",
        (user_id, on.isoformat())).fetchall()}
    earned = sum(r["payout"] for r in rows.values())
    done = [g for g in GAMES if g in rows and rows[g]["done"]]
    return {"rows": rows, "earned": earned, "done": done,
            "remaining": [g for g in GAMES if g not in done]}


def solve_rate(conn: sqlite3.Connection, game: str, on: date) -> float | None:
    """Used to pull unfair puzzles: under 15% or over 95% and the generator is
    producing something nobody enjoys."""
    row = conn.execute(
        "SELECT attempts, solves FROM puzzle_stats WHERE game = ? AND on_date = ?",
        (game, on.isoformat())).fetchone()
    if not row or not row["attempts"]:
        return None
    return row["solves"] / row["attempts"]


def clear_day(conn, user_id: int, on: date) -> int:
    """Open a day's games up to be played again.

    The row survives with its payout, its fraction and its paid flag intact -
    what is cleared is the progress. So the leaderboard, the streak and the
    day's earnings all stay where they were, and the replay pays nothing.
    """
    with db.tx(conn):
        cur = conn.execute(
            "UPDATE plays SET done = 0, state = '{}' WHERE user_id = ? AND on_date = ?",
            (user_id, on.isoformat()))
    return cur.rowcount
