"""Phase 0 backfill: run a roster through the engine and print a ranked list.

    python -m fsx.cli fixtures              # the hand-entered careers
    python -m fsx.cli backfill roster.txt   # real data, needs TMDB + OMDb keys
    python -m fsx.cli reference             # the six design-doc careers

The question Phase 0 answers is whether a film-literate person reads the ranked
list and finds it defensible. Everything here exists to produce that list.
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date
from pathlib import Path

from . import constants as K
from .engine import value_person
from .models import Person, Valuation

OUT_DIR = Path(__file__).resolve().parents[1] / "out"


def _load_env() -> None:
    env = Path(__file__).resolve().parents[1] / ".env"
    if not env.exists():
        return
    import os
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def rank(people: list[Person], as_of: date | None = None) -> list[Valuation]:
    values = [value_person(p, as_of) for p in people]
    return sorted(values, key=lambda v: v.price, reverse=True)


def write_csv(values: list[Valuation], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [v.as_row() for v in values]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        for i, row in enumerate(rows, 1):
            writer.writerow({**row, "person": row["person"]})
    return path


def print_table(values: list[Valuation], limit: int = 100) -> None:
    print(f"\n{'#':>3}  {'Person':<32} {'Price':>9}  {'Tier':<12} "
          f"{'CP':>9}  {'cred':>4}  {'work':>7} {'recep':>8} {'box':>8} {'award':>9}  idle")
    print("-" * 122)
    for i, v in enumerate(values[:limit], 1):
        print(f"{i:>3}  {v.person:<32} {v.price:>9,.2f}  {v.tier:<12} "
              f"{v.cp:>9,.0f}  {v.credits_scored:>4}  "
              f"{v.working_cp:>7,.0f} {v.reception_cp:>8,.0f} "
              f"{v.box_office_cp:>8,.0f} {v.award_cp:>9,.0f}  {v.idle_years:>4.1f}y")


def print_distribution(values: list[Valuation]) -> None:
    counts: dict[str, int] = {}
    for v in values:
        counts[v.tier] = counts.get(v.tier, 0) + 1
    total = len(values) or 1
    print(f"\nTier distribution ({total} listed)")
    print("-" * 46)
    for _, name, _, _ in K.DECAY_TIERS:
        n = counts.get(name, 0)
        bar = "#" * round(40 * n / total)
        print(f"  {name:<12} {n:>4}  {100 * n / total:>5.1f}%  {bar}")


# ------------------------------------------------------------------ commands
def cmd_fixtures(args) -> int:
    from .fixtures.careers import roster
    values = rank(roster())
    print_table(values, args.limit)
    print_distribution(values)
    out = write_csv(values, OUT_DIR / "fixtures_ranked.csv")
    print(f"\nWrote {out}")
    print("\nThese figures come from hand-entered approximations, not live data.")
    print("They test whether the engine orders people sensibly, nothing more.")
    return 0


def cmd_reference(args) -> int:
    from .reference import AS_OF, EXPECTED_PRICES, reference_careers
    values = rank(reference_careers(), as_of=AS_OF)
    print_table(values, args.limit)
    print("\n  Against the design doc:")
    for v in values:
        want = EXPECTED_PRICES.get(v.person)
        if want:
            drift = 100 * (v.price / want - 1)
            print(f"    {v.person:<20} {v.price:>8,.2f}  doc {want:>8,.2f}  {drift:+6.2f}%")
    return 0


def cmd_backfill(args) -> int:
    _load_env()
    from .sources.omdb import OMDb
    from .sources.tmdb import TMDB

    tmdb, omdb = TMDB(), OMDb()
    missing = [s.env_var for s in (tmdb, omdb) if not s.available]
    if missing:
        print(f"Missing API keys: {', '.join(missing)}", file=sys.stderr)
        print("Copy .env.example to .env and fill them in, then rerun.", file=sys.stderr)
        return 1

    names = [n.strip() for n in Path(args.roster).read_text().splitlines() if n.strip()]
    people: list[Person] = []

    for i, raw in enumerate(names, 1):
        as_director = raw.endswith("*")
        name = raw.rstrip("*").strip()
        print(f"[{i}/{len(names)}] {name}", file=sys.stderr)
        try:
            person = tmdb.build_person(name, as_director=as_director,
                                       max_credits=args.max_credits)
            if person is None:
                print(f"    not found on TMDB, skipped", file=sys.stderr)
                continue
            for credit in person.credits:
                omdb.enrich(credit)
            people.append(person)
        except Exception as exc:                      # noqa: BLE001
            print(f"    failed: {exc}", file=sys.stderr)

    if not people:
        print("Nothing to rank.", file=sys.stderr)
        return 1

    values = rank(people)
    print_table(values, args.limit)
    print_distribution(values)
    out = write_csv(values, OUT_DIR / "backfill_ranked.csv")
    print(f"\nWrote {out}")
    print("\nAwards are NOT fetched: no free API is good enough. Load them from "
          "Wikidata or enter them by hand before trusting these prices.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fsx", description=__doc__)
    parser.add_argument("--limit", type=int, default=100,
                        help="rows to print (default 100)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("fixtures", help="rank the hand-entered careers")
    sub.add_parser("reference", help="rank the six design-doc reference careers")

    backfill = sub.add_parser("backfill", help="rank real people from TMDB + OMDb")
    backfill.add_argument("roster", help="text file, one name per line, * for directors")
    backfill.add_argument("--max-credits", type=int, default=60)

    args = parser.parse_args(argv)
    return {"fixtures": cmd_fixtures, "reference": cmd_reference,
            "backfill": cmd_backfill}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
