"""Re-read budget and gross out of already-cached Wikipedia articles.

The parser improves faster than the cache goes stale, so when it learns to read
a figure it could not read before, the answer is already on disk. This re-runs
the money extraction over the cached wikitext and updates data/people.json in
place, with no network and no risk of dropping anyone the way a failed backfill
can.
"""
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fsx.sources.cache import Cache
from fsx.sources.wikidata import _article_title
from fsx.sources.wikipedia import is_film_article, parse_infobox, parse_money
from fsx.store import load, save

ROOT = Path(__file__).resolve().parents[1]


def article_map() -> dict[str, str]:
    """imdb id -> exact English Wikipedia title, from the Wikidata cache."""
    out: dict[str, str] = {}
    for path in glob.glob(str(ROOT / ".cache/wikidata/*.json")):
        rows = json.loads(Path(path).read_text())
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, dict) and row.get("imdb") and row.get("article"):
                out.setdefault(row["imdb"]["value"],
                               _article_title(row["article"]["value"]))
    return out


def main() -> int:
    people, asof = load(ROOT / "data/people.json")
    articles = article_map()
    cache = Cache("wikipedia")
    filled = {"budget": 0, "worldwide_gross": 0}
    seen, hits = set(), 0

    for person in people:
        for credit in person.credits:
            if credit.budget and credit.worldwide_gross:
                continue
            title = articles.get(getattr(credit, "imdb_id", None) or "")
            if not title:
                continue
            wikitext = cache.get(f"lead:{title}")
            seen.add(title)
            if not wikitext or not is_film_article(wikitext):
                continue
            hits += 1
            fields = parse_infobox(wikitext)
            for field, raw in (("budget", fields.get("budget")),
                               ("worldwide_gross", fields.get("gross"))):
                if getattr(credit, field, None) is None:
                    value = parse_money(raw)
                    if value:
                        setattr(credit, field, value)
                        filled[field] += 1

    print(f"{len(articles):,} articles known, {len(seen):,} looked up, "
          f"{hits:,} cached film pages read")
    print(f"filled {filled['budget']:,} budgets and "
          f"{filled['worldwide_gross']:,} grosses")
    if "--write" in sys.argv:
        print("wrote", save(people, ROOT / "data/people.json"))
    else:
        print("(dry run - pass --write to save)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
