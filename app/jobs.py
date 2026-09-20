"""The nightly job, as a command.

    python3 -m app.jobs mark              # reprice + mark positions
    python3 -m app.jobs mark --dividends  # also pay the quarterly dividend
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

from fsx.store import load

from . import db, marking
from .main import DB_PATH, SNAPSHOT


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.jobs")
    sub = parser.add_subparsers(dest="command", required=True)
    mark = sub.add_parser("mark", help="reprice the market and mark positions")
    mark.add_argument("--snapshot", default=str(SNAPSHOT))
    mark.add_argument("--db", default=str(DB_PATH))
    mark.add_argument("--on", default=None, help="YYYY-MM-DD, for backfills")
    mark.add_argument("--dividends", action="store_true")

    seed = sub.add_parser(
        "seed", help="fill price history on a fresh database (run once after deploy)")
    seed.add_argument("--snapshot", default=str(SNAPSHOT))
    seed.add_argument("--db", default=str(DB_PATH))
    seed.add_argument("--months", type=int, default=120)
    seed.add_argument("--every", type=int, default=14,
                      help="days between seeded price points (default fortnightly)")
    seed.add_argument("--force", action="store_true",
                      help="re-seed a database that already has prices")
    seed.add_argument("--resume", action="store_true",
                      help="keep the days already priced and fill in the rest;"
                           " safe to re-run after an interrupted seed")

    args = parser.parse_args(argv)
    on = datetime.strptime(getattr(args, "on", None), "%Y-%m-%d").date() \
        if getattr(args, "on", None) else date.today()

    snapshot = Path(args.snapshot)
    if not snapshot.exists():
        print(f"No snapshot at {snapshot}. Run 'fsx snapshot' or 'fsx backfill'.",
              file=sys.stderr)
        return 1

    conn = db.connect(args.db)
    db.migrate(conn)

    if args.command == "seed":
        # Prices are computed from a date, so a brand new database can be given
        # a real history immediately instead of waiting months to grow one.
        if db.latest_date(conn) and not (args.force or args.resume):
            print("This database already has prices. Nothing to seed. "
                  "Pass --resume to fill in the days it is missing, or "
                  "--force to rebuild them all (positions are kept).")
            return 0
        if args.force:
            # Only the derived market: users, positions and trades survive, so
            # a stale dev database can be rebuilt without losing a test account.
            with conn:
                conn.execute("DELETE FROM prices")
                conn.execute("DELETE FROM stocks")
            print("Cleared the old prices.")
        from datetime import timedelta
        # Weekly rather than monthly: a chart drawn from 25 points looks like a
        # staircase, and the 30-day change on the market table was being read
        # off whichever monthly point happened to be nearest.
        step = max(1, args.every)
        points = max(1, (args.months * 30) // step)
        # Newest first. A seed that dies partway then leaves a market that is
        # short of history rather than one whose latest price is from 2022 -
        # which is what happened on the deployed volume, and every page read
        # that four-year-old price as today's.
        have = {r["on_date"] for r in conn.execute(
            "SELECT DISTINCT on_date FROM prices")} if args.resume else set()
        people, _ = load(snapshot)
        done = 0
        for i in range(0, points + 1):
            day = on - timedelta(days=step * i)
            if day.isoformat() in have:
                continue
            count = marking.refresh_prices(conn, snapshot, day, people=people)
            done += 1
            if done % 10 == 1 or i == points:
                print(f"  {day}  {count} stocks", flush=True)
        print(f"Seeded {done} of {points + 1} days per stock, "
              f"every {step} days back to {on - timedelta(days=step * points)}.")
        print(f"Newest price on file: {db.latest_date(conn)}.")
        return 0

    report = marking.run(conn, snapshot, on, with_dividends=args.dividends)

    if report.skipped:
        print(f"{on} was already marked. Nothing to do.")
    else:
        print(f"{on}: {report.stocks} stocks repriced, {report.positions} positions "
              f"marked ({report.gains} up, {report.losses} down).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
