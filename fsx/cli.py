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
import re
import sys
from datetime import date
from pathlib import Path

from . import constants as K
from .engine import value_person
from .models import Person, Valuation

OUT_DIR = Path(__file__).resolve().parents[1] / "out"
DATA_DIR = Path(__file__).resolve().parents[1] / "data"


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


def cmd_snapshot(args) -> int:
    """Write the hand-entered fixtures out as a snapshot, so the site can be
    built and looked at before a real backfill exists."""
    from .fixtures.careers import roster
    from .store import save
    path = save(roster(), DATA_DIR / "people.json")
    print(f"Wrote {path} from the fixture careers.")
    print("These are hand-entered approximations - fine for seeing the site, "
          "not for publishing a price.")
    return 0


def cmd_site(args) -> int:
    """Render the read-only market from a snapshot. No network, no keys."""
    from .site import build
    snapshot = Path(args.snapshot)
    if not snapshot.exists():
        print(f"No snapshot at {snapshot}.", file=sys.stderr)
        print("Run 'fsx snapshot' for the fixtures, or 'fsx backfill' for real "
              "data, then try again.", file=sys.stderr)
        return 1

    result = build(snapshot, Path(args.out), years=args.years)
    print(f"Built {result['people']} stock pages into {result['out']}")
    print(f"Data snapshot fetched {result['fetched'] or 'unknown'}")
    print(f"\nOpen it:  python3 -m http.server -d {args.out} 8000")
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


def enrich_credits(credits, omdb, wikidata, wikipedia, stats, attempt,
                   use_omdb: bool = True) -> None:
    """Layer review scores and money onto a batch of credits, in place.

    The backfill does this for a whole filmography and the nightly refresh does
    it for the two films that appeared yesterday. Sharing it is what stops a
    new credit being scored differently from an old one.
    """
    info = {}
    if wikidata:
        ids = [getattr(c, "imdb_id", None) for c in credits]
        info = attempt("wikidata.films_info", wikidata.films_info, ids) or {}

    for credit in credits:
        imdb_id = getattr(credit, "imdb_id", None)

        if omdb is not None and omdb.available and use_omdb and not omdb.exhausted:
            attempt(f"omdb:{credit.title}", omdb.enrich, credit)
            if omdb.exhausted:
                print("    OMDb daily limit reached - continuing on Wikidata "
                      "scores. Rerun tomorrow to fill the gaps; everything "
                      "already fetched is cached.", file=sys.stderr)
            if credit.imdb is not None:
                stats["omdb"] += 1

        entry = info.get(imdb_id or "", {})
        for field, value in (entry.get("scores") or {}).items():
            if getattr(credit, field, None) is None:
                setattr(credit, field, value)
                stats["wikidata_scores"] += 1

        # TMDB's money thins out badly below ~$10M; Wikipedia's infobox
        # carried a budget for 87% of a sample and a gross for 93%.
        article = entry.get("article")
        if wikipedia and article and (credit.budget is None
                                      or credit.worldwide_gross is None):
            money = attempt(f"wikipedia:{article}",
                            wikipedia.film_money, article) or {}
            for field, value in money.items():
                if getattr(credit, field, None) is None:
                    setattr(credit, field, value)
                    stats["wikipedia_money"] += 1


def select_new(payload: dict, known: set, cutoff: str, today: str,
               max_new: int, is_director: bool) -> list[dict]:
    """Which entries in a TMDB credit list count as work released since we last
    looked.

    "New" means released since the snapshot - NOT merely absent from it. A
    filmography is capped at --max-credits, so everything below the cut is
    absent by design: without the cutoff, Meryl Streep's Kramer vs. Kramer
    reads as tonight's news and the job spends weeks dragging in a back
    catalogue nobody asked for.
    """
    from .sources.tmdb import appearance_of

    entries = payload.get("crew" if is_director else "cast") or []
    if is_director:
        entries = [e for e in entries if e.get("job") == "Director"]
    else:
        entries = [e for e in entries
                   if appearance_of(e.get("character")) in ("role", "narration")]

    fresh = []
    for entry in entries:
        released = entry.get("release_date")
        if not released or released > today or released < cutoff:
            continue
        if (entry.get("title"), released) in known:
            continue
        fresh.append(entry)

    # Newest first, and capped: a filmography that suddenly gains forty entries
    # is a data change, not forty premieres.
    fresh.sort(key=lambda e: e["release_date"], reverse=True)
    return fresh[:max_new]


def _match_key(name: str) -> str:
    """Compare names the way a person means them, not the way they are typed.

    The roster is hand-written ASCII; the snapshot holds what TMDB returned.
    Without this, "Zoe Saldana" never finds "Zoe Saldaña"."""
    import unicodedata
    folded = unicodedata.normalize("NFKD", name)
    folded = folded.encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", folded.lower())


def cmd_refresh(args) -> int:
    """Look for work that has come out since the snapshot, and only fetch that.

    A full backfill is hours, because it refetches a whole filmography per
    person. What actually changes overnight is small: a film opened, an awards
    ceremony happened. So this asks TMDB for each person's credit list - one
    call each, roughly two minutes for the whole roster - diffs it against the
    snapshot, and fetches details only for what is genuinely new.

    That is what makes "the market moves when something comes out" true without
    anyone running anything by hand.
    """
    _load_env()
    from datetime import date as _date, timedelta

    from .sources.omdb import OMDb
    from .sources.tmdb import TMDB, appearance_of
    from .sources.wikidata import Wikidata
    from .sources.wikipedia import Wikipedia
    from .store import load, save

    snapshot_path = Path(args.snapshot)
    if not snapshot_path.exists():
        print(f"No snapshot at {snapshot_path}. Run a backfill first.",
              file=sys.stderr)
        return 1

    tmdb = TMDB()
    if not tmdb.available:
        print("TMDB needs TMDB_READ_ACCESS_TOKEN or TMDB_API_KEY.", file=sys.stderr)
        return 1
    omdb = OMDb()
    wikipedia = None if args.no_wiki else Wikipedia()
    wikidata = None if args.no_wiki else Wikidata()

    people, was = load(snapshot_path)
    try:
        looked = _date.fromisoformat(was)
    except (TypeError, ValueError):
        looked = _date.today()
    cutoff = (looked - timedelta(days=args.since_days)).isoformat()
    # The roster is typed by a person and the snapshot stores what TMDB
    # returned, so "Penelope Cruz" has to find "Penélope Cruz" or the refresh
    # lists her a second time. Eleven of the roster were about to be
    # duplicated, which on a market means two stocks in the same career.
    by_name = {_match_key(p.name): p for p in people}
    today = _date.today()

    failures: list[str] = []

    def attempt(label: str, fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except Exception as exc:                      # noqa: BLE001
            failures.append(f"{label}: {type(exc).__name__}")
            return None

    stats = {"omdb": 0, "wikidata_scores": 0, "wikipedia_money": 0, "awards": 0,
             "dropped_credits": 0}
    added: list[tuple[str, str]] = []
    new_people: list[str] = []
    award_changes: list[tuple[str, int]] = []

    # Anyone on the roster who is not in the snapshot yet gets a full build.
    roster = [n.strip() for n in Path(args.roster).read_text().splitlines()
              if n.strip() and not n.startswith("#")] if args.roster else []
    for raw in roster:
        name = raw.rstrip("*").strip()
        if _match_key(name) in by_name:
            continue
        person = attempt("tmdb.build_person", tmdb.build_person, name,
                         as_director=raw.endswith("*"),
                         max_credits=args.max_credits)
        if person is None:
            continue
        enrich_credits(person.credits, omdb, wikidata, wikipedia, stats, attempt,
                       use_omdb=not args.no_omdb)
        people.append(person)
        by_name[_match_key(person.name)] = person
        new_people.append(person.name)

    for i, person in enumerate(people, 1):
        if person.name in new_people or not person.tmdb_id:
            continue
        if args.limit and i > args.limit:
            break

        payload = attempt(f"credits:{person.name}", tmdb.person_credits,
                          person.tmdb_id, args.credits_max_age_days)
        if not payload:
            continue

        known = {(c.title, c.release_date.isoformat()) for c in person.credits}
        fresh = select_new(payload, known, cutoff, today.isoformat(),
                           args.max_new, person.is_director)

        built = []
        for entry in fresh:
            credit = attempt(f"credit:{entry.get('title')}",
                             tmdb.build_credit, entry, person.is_director)
            if credit is None:
                stats["dropped_credits"] += 1
                continue
            built.append(credit)
            added.append((person.name, f"{credit.title} ({credit.release_date})"))

        if built:
            enrich_credits(built, omdb, wikidata, wikipedia, stats, attempt,
                           use_omdb=not args.no_omdb)
            person.credits.extend(built)

        # Awards, on a slower clock. They arrive in bursts around ceremonies,
        # and the query is the expensive one, so the cache age spreads the
        # roster over roughly a week rather than doing all of it every night.
        if wikidata and not args.no_awards:
            person_imdb = attempt("tmdb.person_imdb_id", tmdb.person_imdb_id,
                                  person.tmdb_id)
            qid = attempt("wikidata.qid", wikidata.qid_for_imdb,
                          person_imdb) if person_imdb else None
            if qid:
                awards = attempt("wikidata.awards", wikidata.awards, qid,
                                 args.awards_max_age_days)
                if awards is not None and len(awards) != len(person.awards):
                    award_changes.append((person.name,
                                          len(awards) - len(person.awards)))
                    person.awards = awards
                    stats["awards"] += len(awards)

    print(f"snapshot was {was}; checked {len(people)} people "
          f"for anything released since {cutoff}")
    if new_people:
        print(f"newly listed: {', '.join(new_people)}")
    if added:
        print(f"{len(added)} new credits:")
        for who, what in added[:20]:
            print(f"   {who} - {what}")
        if len(added) > 20:
            print(f"   and {len(added) - 20} more")
    if award_changes:
        print(f"{len(award_changes)} award histories changed: "
              + ", ".join(f"{n} {d:+d}" for n, d in award_changes[:10]))
    if not (added or new_people or award_changes):
        print("nothing new.")

    if failures:
        from collections import Counter
        tally = Counter(f.split(":")[0] for f in failures)
        print(f"{len(failures)} calls failed and were skipped: "
              + ", ".join(f"{k} x{v}" for k, v in tally.most_common()),
              file=sys.stderr)

    # Belt and braces on the name matching above: a market with the same
    # career listed twice is worse than a market missing someone.
    seen: dict[str, int] = {}
    for person in people:
        seen[_match_key(person.name)] = seen.get(_match_key(person.name), 0) + 1
    dupes = [n for n, count in seen.items() if count > 1]
    if dupes:
        print(f"refusing to write: {len(dupes)} duplicated names ({dupes[:5]})",
              file=sys.stderr)
        return 1

    if args.dry_run:
        print("(dry run - nothing written)")
        return 0
    out = save(people, snapshot_path)
    print(f"wrote {out}")
    return 0


def cmd_backfill(args) -> int:
    _load_env()
    from .sources.omdb import OMDb
    from .sources.tmdb import TMDB
    from .sources.wikidata import Wikidata
    from .sources.wikipedia import Wikipedia

    tmdb = TMDB()
    if not tmdb.available:
        print("TMDB needs TMDB_READ_ACCESS_TOKEN or TMDB_API_KEY.", file=sys.stderr)
        print("Copy .env.example to .env and fill one in, then rerun.", file=sys.stderr)
        return 1

    omdb = OMDb()
    if not omdb.available and not args.no_omdb:
        print("No OMDB_API_KEY: falling back to Wikidata for review scores.",
              file=sys.stderr)
        print("That loses the IMDb rating and its vote count, so every credit "
              "scores at reduced confidence.", file=sys.stderr)

    wikipedia = None if args.no_wiki else Wikipedia()
    wikidata = None if args.no_wiki else Wikidata()

    names = [n.strip() for n in Path(args.roster).read_text().splitlines()
             if n.strip() and not n.startswith("#")]
    if args.skip:
        names = names[args.skip:]
    if args.limit:
        names = names[:args.limit]

    if args.dry_run:
        calls = len(names) * args.max_credits
        print(f"{len(names)} people x up to {args.max_credits} credits")
        print(f"  ~{len(names) * 3 + calls:,} TMDB calls (cached forever after the first run)")
        print(f"  ~{calls:,} OMDb calls -> {max(1, -(-calls // 1000))} days on the free "
              f"tier, or one sitting on the $1 tier")
        print(f"  ~{len(names) * 2:,} Wikidata queries, ~{calls // 4:,} Wikipedia pages")
        print(f"  rough wall time: {(len(names) * args.max_credits * 0.45) / 60:.0f} minutes")
        return 0
    people: list[Person] = []
    stats = {"omdb": 0, "wikidata_scores": 0, "wikipedia_money": 0, "awards": 0,
             "dropped_credits": 0}

    def attempt(label: str, fn, *a, **kw):
        """Every external call is individually survivable.

        The first run lost all three people because one bad Wikipedia lookup
        raised inside the credit loop and aborted the whole person - awards
        never ran, nothing was ranked, no CSV was written. A person missing one
        film's box office is worth far more than no person at all.
        """
        try:
            return fn(*a, **kw)
        except Exception as exc:                      # noqa: BLE001
            failures.append(f"{label}: {type(exc).__name__}")
            return None

    failures: list[str] = []

    import time
    started = time.monotonic()

    for i, raw in enumerate(names, 1):
        as_director = raw.endswith("*")
        name = raw.rstrip("*").strip()
        elapsed = time.monotonic() - started
        eta = ""
        if i > 1:
            remaining = (elapsed / (i - 1)) * (len(names) - i + 1)
            eta = f"  eta {remaining / 60:.0f}m"
        print(f"[{i}/{len(names)}] {name}{eta}", file=sys.stderr)

        dropped: list[str] = []
        person = attempt("tmdb.build_person", tmdb.build_person, name,
                         as_director=as_director, max_credits=args.max_credits,
                         on_skip=lambda title, exc: dropped.append(title))
        if person is None:
            # Either TMDB has nobody by that name, or the build itself failed.
            # Those need different answers from whoever reads this, so they no
            # longer share a message.
            print("    not built - TMDB has no such person, or the search "
                  "call failed. Not listed.", file=sys.stderr)
            continue
        if dropped:
            stats["dropped_credits"] += len(dropped)
            print(f"    {len(dropped)} credits incomplete: "
                  + ", ".join(dropped[:3])
                  + (f" and {len(dropped) - 3} more" if len(dropped) > 3 else ""),
                  file=sys.stderr)

        # Awards first: they are the single most valuable input, and they used
        # to sit after the credit loop where a credit failure starved them.
        if wikidata and person.tmdb_id:
            person_imdb = attempt("tmdb.person_imdb_id", tmdb.person_imdb_id,
                                  person.tmdb_id)
            qid = attempt("wikidata.qid", wikidata.qid_for_imdb,
                          person_imdb) if person_imdb else None
            if qid:
                awards = attempt("wikidata.awards", wikidata.awards, qid) or []
                person.awards = awards
                stats["awards"] += len(awards)

        enrich_credits(person.credits, omdb, wikidata, wikipedia, stats, attempt,
                       use_omdb=not args.no_omdb)

        people.append(person)

    if not people:
        print("Nothing to rank.", file=sys.stderr)
        return 1

    from .store import save
    snapshot = save(people, DATA_DIR / "people.json")

    values = rank(people)
    print_table(values, args.limit)
    print_distribution(values)
    out = write_csv(values, OUT_DIR / "backfill_ranked.csv")
    print(f"\nWrote {out}")
    print(f"Wrote {snapshot} - the site builds from this, offline.")
    print(f"\nFilled: {stats['omdb']} credits from OMDb, "
          f"{stats['wikidata_scores']} scores from Wikidata, "
          f"{stats['wikipedia_money']} money fields from Wikipedia, "
          f"{stats['awards']} awards from Wikidata.")
    if stats["dropped_credits"]:
        print(f"{stats['dropped_credits']} credits were skipped on a failed "
              f"call. Rerun to fill them - everything else is cached.",
              file=sys.stderr)

    if failures:
        from collections import Counter
        tally = Counter(f.split(":")[0] for f in failures)
        print(f"\n{len(failures)} calls failed and were skipped: "
              + ", ".join(f"{k} x{v}" for k, v in tally.most_common()))

    # A person with no awards is usually a failed lookup, not a career without
    # awards - and it silently underprices them, so say so loudly.
    awardless = [p.name for p in people if not p.awards]
    if awardless:
        share = 100 * len(awardless) / len(people)
        print(f"\n!! {len(awardless)} of {len(people)} people ({share:.0f}%) have no "
              f"awards on file.")
        print("   Some genuinely have none. But a failed Wikidata lookup looks "
              "identical and\n   underprices them, so rerun to retry: failures are "
              "never cached, so a rerun\n   only repeats what did not work.")
        print("   e.g. " + ", ".join(awardless[:6]))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fsx", description=__doc__)
    parser.add_argument("--limit", type=int, default=100,
                        help="rows to print (default 100)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("fixtures", help="rank the hand-entered careers")
    sub.add_parser("reference", help="rank the six design-doc reference careers")
    sub.add_parser("snapshot", help="write the fixture careers to data/people.json")

    site = sub.add_parser("site", help="build the read-only market site")
    site.add_argument("--snapshot", default="data/people.json")
    site.add_argument("--out", default="site")
    site.add_argument("--years", type=int, default=5,
                      help="years of price history to chart (default 5)")

    backfill = sub.add_parser("backfill", help="rank real people from TMDB + OMDb")
    backfill.add_argument("roster", help="text file, one name per line, * for directors")
    backfill.add_argument("--max-credits", type=int, default=60)
    backfill.add_argument("--no-omdb", action="store_true",
                          help="skip OMDb; use Wikidata for review scores instead")
    backfill.add_argument("--no-wiki", action="store_true",
                          help="skip Wikipedia and Wikidata entirely")
    backfill.add_argument("--limit", dest="limit", type=int, default=0,
                          help="only the first N names, for chunking a big roster")
    backfill.add_argument("--skip", type=int, default=0,
                          help="skip the first N names, to resume a chunked run")
    backfill.add_argument("--dry-run", action="store_true",
                          help="estimate the call budget and stop")

    refresh = sub.add_parser(
        "refresh", help="fetch only what has come out since the snapshot")
    refresh.add_argument("--snapshot", default="data/people.json")
    refresh.add_argument("--roster", default="roster.txt",
                         help="anyone here and not in the snapshot is built in full")
    refresh.add_argument("--max-credits", type=int, default=100,
                         help="window for a person being listed for the first time")
    refresh.add_argument("--since-days", type=int, default=120,
                         help="how far before the snapshot date to look for "
                              "releases (default 120, to catch a festival film "
                              "that gets a real date later)")
    refresh.add_argument("--max-new", type=int, default=6,
                         help="most new credits to accept per person in one run; a "
                              "filmography that gains forty is a data change, not "
                              "forty premieres")
    refresh.add_argument("--credits-max-age-days", type=float, default=1.0,
                         help="how stale a cached credit list may be (default 1 day)")
    refresh.add_argument("--awards-max-age-days", type=float, default=7.0,
                         help="how stale a cached award history may be (default 7 "
                              "days, which spreads the roster over a week)")
    refresh.add_argument("--no-awards", action="store_true")
    refresh.add_argument("--no-omdb", action="store_true")
    refresh.add_argument("--no-wiki", action="store_true")
    refresh.add_argument("--limit", dest="limit", type=int, default=0)
    refresh.add_argument("--dry-run", action="store_true",
                         help="report what changed and write nothing")

    args = parser.parse_args(argv)
    return {"fixtures": cmd_fixtures, "reference": cmd_reference,
            "snapshot": cmd_snapshot, "site": cmd_site,
            "backfill": cmd_backfill, "refresh": cmd_refresh}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
