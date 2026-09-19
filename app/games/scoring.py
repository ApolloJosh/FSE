"""Grading and payouts.

Every game pays on a curve rather than pass/fail, and every game has a floor.
A player who bombs all four still walks away with CR 2.00, because the
punishment for being bad at film trivia should not be exclusion from the
market - the market is the game, the puzzles are the way in.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from app import db

# game -> (floor, ceiling) in centidollars
PAYOUTS = {
    "six-degrees": (60, 180),
    "ladder": (60, 180),
    "box-office": (40, 120),
    "cast-gap": (40, 120),
    "slate": (400, 1200),
}
PERFECT_DAY_BONUS = 250
STREAK_STEP = 50
STREAK_CAP = 500
DAILY_GAMES = ("six-degrees", "ladder", "box-office", "cast-gap")


@dataclass
class Grade:
    fraction: float             # 0..1
    payout: int                 # centidollars
    detail: str = ""
    correct: bool = False


def payout_for(game: str, fraction: float) -> int:
    floor, ceiling = PAYOUTS[game]
    fraction = max(0.0, min(1.0, fraction))
    return int(round(floor + (ceiling - floor) * fraction))


# ------------------------------------------------------------------- grading
def grade_six_degrees(puzzle, chain_ok: bool, hops: int) -> Grade:
    if not chain_ok:
        return Grade(0.0, payout_for("six-degrees", 0.0), "That chain does not connect.")
    par = puzzle.answer["par"]
    over = hops - par
    fraction = {0: 1.0}.get(over, 0.6 if over == 1 else 0.3 if over == 2 else 0.15)
    if over < 0:
        fraction = 1.0
    detail = ("Par." if over <= 0 else
              f"{over} over par." if over > 0 else "")
    return Grade(fraction, payout_for("six-degrees", fraction), detail, True)


def grade_ladder(puzzle, rungs_used: int, correct: bool) -> Grade:
    total = puzzle.max_guesses
    if not correct:
        return Grade(0.0, payout_for("ladder", 0.0),
                     f"It was {puzzle.answer['name']}.")
    fraction = (total - rungs_used + 1) / total
    return Grade(fraction, payout_for("ladder", fraction),
                 f"Named on rung {rungs_used} of {total}.", True)


def grade_box_office(puzzle, submitted: list[str]) -> Grade:
    order = puzzle.answer["order"]
    if sorted(submitted) != sorted(order):
        return Grade(0.0, payout_for("box-office", 0.0), "Incomplete ranking.")
    # Credit for every adjacent pair the player got the right way round.
    pairs = len(order) - 1
    right = sum(1 for a, b in zip(submitted, submitted[1:])
                if order.index(a) < order.index(b))
    fraction = right / pairs
    return Grade(fraction, payout_for("box-office", fraction),
                 f"{right} of {pairs} pairs in the right order.", right == pairs)


def grade_cast_gap(puzzle, guesses: int, correct: bool) -> Grade:
    if not correct:
        return Grade(0.0, payout_for("cast-gap", 0.0),
                     f"It was {puzzle.answer['name']}.")
    fraction = 1.0 if guesses <= 1 else 0.5
    return Grade(fraction, payout_for("cast-gap", fraction),
                 "First guess." if guesses <= 1 else "Second guess.", True)


def grade_slate(puzzle, picked: list[str]) -> Grade:
    answer = puzzle.answer
    if len(set(picked)) != 5:
        return Grade(0.0, payout_for("slate", 0.0), "Pick exactly five.")
    spend = sum(answer["prices"].get(p, 10**9) for p in picked)
    if spend > answer["budget"]:
        return Grade(0.0, payout_for("slate", 0.0),
                     f"Over budget by {spend - answer['budget']}.")
    total = sum(answer["totals"].get(p, 0) for p in picked)
    best = answer["best_total"] or 1
    fraction = max(0.0, min(1.0, total / best))
    return Grade(fraction, payout_for("slate", fraction),
                 f"{fraction:.0%} of the best possible slate.", fraction >= 0.999)


# -------------------------------------------------------------- daily bonuses
def streak_length(conn, user_id: int, on: date) -> int:
    """Consecutive days on which the player finished at least one game."""
    rows = conn.execute(
        "SELECT DISTINCT on_date FROM plays WHERE user_id = ? AND done = 1"
        " AND on_date <= ? ORDER BY on_date DESC LIMIT 400",
        (user_id, on.isoformat())).fetchall()
    days = [r["on_date"] for r in rows]
    streak, cursor = 0, on
    for day in days:
        if day == cursor.isoformat():
            streak += 1
            cursor -= timedelta(days=1)
        elif day < cursor.isoformat():
            break
    return streak


def streak_bonus(streak: int) -> int:
    return min(STREAK_CAP, max(0, streak - 1) * STREAK_STEP)


def finish_day(conn, user_id: int, on: date) -> tuple[int, str] | None:
    """Pay the perfect-day and streak bonuses, once, when the set is complete."""
    rows = conn.execute(
        "SELECT game, fraction FROM plays WHERE user_id = ? AND on_date = ? AND done = 1",
        (user_id, on.isoformat())).fetchall()
    finished = {r["game"]: r["fraction"] for r in rows}
    if not all(g in finished for g in DAILY_GAMES):
        return None
    if conn.execute("SELECT 1 FROM ledger WHERE user_id = ? AND kind = 'bonus'"
                    " AND note LIKE ?", (user_id, f"%{on.isoformat()}%")).fetchone():
        return None

    bonus, parts = 0, []
    if all(finished[g] >= 0.999 for g in DAILY_GAMES):
        bonus += PERFECT_DAY_BONUS
        parts.append("perfect day")
    streak = streak_length(conn, user_id, on)
    extra = streak_bonus(streak)
    if extra:
        bonus += extra
        parts.append(f"{streak}-day streak")
    if bonus <= 0:
        return None

    note = f"Daily bonus {on.isoformat()}: " + " + ".join(parts)
    with db.tx(conn):
        conn.execute("UPDATE users SET credits = credits + ? WHERE id = ?",
                     (bonus, user_id))
        conn.execute("INSERT INTO ledger (user_id, kind, amount, note, at)"
                     " VALUES (?,?,?,?,?)", (user_id, "bonus", bonus, note, db.now()))
    return bonus, note
