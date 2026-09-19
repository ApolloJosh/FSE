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
        if db.latest_date(conn):
            print("This database already has prices. Nothing to seed.")
            return 0
        from datetime import timedelta
        months = args.months
        for i in range(months, -1, -1):
            day = on - timedelta(days=30 * i)
            count = marking.refresh_prices(conn, snapshot, day)
            print(f"  {day}  {count} stocks", flush=True)
        print(f"Seeded {months + 1} months of prices.")
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
