"""Set each credit's appearance kind from the already-cached TMDB credits.

The classifier is new; the data it needs was fetched on the last backfill and
is on disk. So this re-derives it offline rather than spending an hour
refetching, exactly like scripts/refill_money.py.
"""
import collections
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fsx.sources.tmdb import appearance_of
from fsx.store import load, save

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache/tmdb"


def cached(key: str):
    path = CACHE / f"{hashlib.sha256(key.encode()).hexdigest()[:24]}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    return data["_value"] if isinstance(data, dict) and "_value" in data else data


def main() -> int:
    people, asof = load(ROOT / "data/people.json")
    tally = collections.Counter()
    missed = 0

    for person in people:
        if person.is_director:
            continue
        payload = cached(f"credits:{person.tmdb_id}")
        if not payload:
            missed += 1
            continue
        characters = {(e.get("title"), e.get("release_date")): e.get("character")
                      for e in payload.get("cast", [])}
        for credit in person.credits:
            key = (credit.title, credit.release_date.isoformat())
            if key not in characters:
                continue
            credit.appearance = appearance_of(characters[key])
            tally[credit.appearance] += 1

    total = sum(tally.values()) or 1
    print(f"classified {total:,} credits"
          + (f" ({missed} people had no cached credits)" if missed else ""))
    for kind, n in tally.most_common():
        print(f"  {kind:<10} {n:>5}  {100 * n / total:.1f}%")
    if "--write" in sys.argv:
        print("wrote", save(people, ROOT / "data/people.json"))
    else:
        print("(dry run - pass --write to save)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
