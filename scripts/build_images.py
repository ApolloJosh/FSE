#!/usr/bin/env python3
"""Build the image index from the fetch cache, without calling TMDB.

Every poster and headshot the site needs has already been downloaded: the
backfill reads whole film payloads (which carry `poster_path`) and whole cast
and crew lists (which carry `profile_path` for everyone in them). None of that
was kept, because the engine only wanted numbers. So this re-reads the cache -
about half a gigabyte of JSON, no network, no API budget - and writes the two
small maps the pages actually need.

    python3 scripts/build_images.py

Films are keyed by title and year, because a Credit does not carry a TMDB id;
where two films share both, the one with more votes wins, which is the one a
player means. People are keyed by TMDB id first and by name second, since the
roster has ids and the cast lists have both.

Only films that appear in the snapshot are kept. The whole cache is 12,000
titles and the roster has touched a fraction of them.
"""

from __future__ import annotations

import json
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache" / "tmdb"
SNAPSHOT = ROOT / "data" / "people.json"
OUT = ROOT / "data" / "images.json"


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(text.lower().split())


def film_key(title: str, year) -> str:
    return f"{norm(title)}|{year}"


def main() -> int:
    if not CACHE.is_dir():
        print(f"No fetch cache at {CACHE}. Nothing to build from.", file=sys.stderr)
        return 1
    if not SNAPSHOT.exists():
        print(f"No snapshot at {SNAPSHOT}.", file=sys.stderr)
        return 1

    snap = json.loads(SNAPSHOT.read_text())
    wanted, roster_ids, roster_names = set(), set(), {}
    for person in snap["people"]:
        if person.get("tmdb_id"):
            roster_ids.add(int(person["tmdb_id"]))
        roster_names[norm(person["name"])] = person["name"]
        for credit in person.get("credits", []):
            if credit.get("placeholder"):
                continue
            year = (credit.get("release_date") or "")[:4]
            wanted.add(film_key(credit["title"], year))

    people: dict[str, str] = {}
    by_name: dict[str, str] = {}
    films: dict[str, tuple[int, str]] = {}
    seen = 0

    for path in CACHE.glob("*.json"):
        seen += 1
        if seen % 5000 == 0:
            print(f"  {seen} files, {len(films)} posters, {len(people)} faces",
                  flush=True)
        try:
            payload = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue

        poster = payload.get("poster_path")
        if poster and payload.get("title"):
            key = film_key(payload["title"], (payload.get("release_date") or "")[:4])
            if key in wanted:
                votes = int(payload.get("vote_count") or 0)
                if key not in films or films[key][0] < votes:
                    films[key] = (votes, poster)

        for entry in (payload.get("cast") or []) + (payload.get("crew") or []):
            face = entry.get("profile_path")
            if not face:
                continue
            ident = entry.get("id")
            if ident in roster_ids:
                people.setdefault(str(ident), face)
            name = norm(entry.get("name") or "")
            if name in roster_names:
                by_name.setdefault(name, face)

    OUT.write_text(json.dumps({
        "schema": 1,
        "base": "https://image.tmdb.org/t/p/",
        "people": people,
        "people_by_name": by_name,
        "films": {k: v[1] for k, v in films.items()},
    }, ensure_ascii=False, sort_keys=True))

    missing = [p["name"] for p in snap["people"]
               if str(p.get("tmdb_id")) not in people
               and norm(p["name"]) not in by_name]
    covered = len(snap["people"]) - len(missing)
    print(f"Read {seen} cached payloads.")
    print(f"Posters: {len(films)} of {len(wanted)} credited films "
          f"({len(films) * 100 // max(1, len(wanted))}%).")
    print(f"Faces:   {covered} of {len(snap['people'])} on the roster.")
    if missing:
        print(f"No face for: {', '.join(sorted(missing)[:20])}"
              + (" ..." if len(missing) > 20 else ""))
    print(f"Wrote {OUT} ({OUT.stat().st_size // 1024} KB).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
