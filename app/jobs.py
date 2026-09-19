"""The nightly job, as a command.

    python3 -m app.jobs mark              # reprice + mark positions
    python3 -m app.jobs mark --dividends  # also pay the quarterly dividend
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

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
    seed.add_argument("--months", type=int, default=24)
    seed.add_argument("--every", type=int, default=7,
                      help="days between seeded price points (default weekly)")
    seed.add_argument("--force", action="store_true",
                      help="re-seed a database that already has prices")

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
        if db.latest_date(conn) and not args.force:
            print("This database already has prices. Nothing to seed. "
                  "Pass --force to rebuild them (positions are kept).")
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
        for i in range(points, -1, -1):
            day = on - timedelta(days=step * i)
            count = marking.refresh_prices(conn, snapshot, day)
            if i % 10 == 0 or i == 0:
                print(f"  {day}  {count} stocks", flush=True)
        print(f"Seeded {points + 1} prices per stock, "
              f"every {step} days back to {on - timedelta(days=step * points)}.")
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
