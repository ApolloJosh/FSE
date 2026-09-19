"""Wikidata: awards, and review scores as an OMDb fallback.

Free, no key, CC0, and structured - which makes it the right answer for awards.
The design doc assumed roughly 400 hand-entered award rows a year; this replaces
most of that. A sample query for one actor returned 70 award statements, dated
and linked to the film they were for.

What it is NOT good for, measured rather than assumed:
  - budget:        ~24% of films carry P2130
  - box office:    ~28% carry P2142
  - billing order: 0%. Cast statements almost never carry a series ordinal,
                   which is why TMDB stays the spine of the pipeline.
  - review scores: ~85% of films carry at least one, but the mix is lopsided -
                   Rotten Tomatoes on most, Metacritic on about a third, IMDb
                   and Letterboxd on almost none.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Optional

from ..models import Award
from .base import HTTPSource

SPARQL_URL = "https://query.wikidata.org/sparql"
USER_AGENT = "FilmStockExchange/0.1 (career scoring research)"

# Wikidata award labels -> keys in constants.AWARD_TABLE. First match wins, so
# the more specific patterns come first.
AWARD_PATTERNS: list[tuple[str, str]] = [
    (r"academy award.*(best director|directing)", "oscar_directing"),
    (r"academy award.*best (motion )?picture", "oscar_picture"),
    (r"academy award.*(writing|screenplay)", "oscar_screenplay"),
    (r"academy award.*supporting", "oscar_supporting"),
    (r"academy award.*best (actor|actress)", "oscar_lead"),
    (r"(british academy|bafta)", "bafta"),
    (r"golden globe", "globe"),
    (r"screen actors guild.*(cast|ensemble)", "sag_ensemble"),
    (r"screen actors guild", "sag_individual"),
    (r"(primetime )?emmy.*supporting", "emmy_supporting"),
    (r"(primetime )?emmy", "emmy_lead"),
    (r"critics.? choice", "critics_choice"),
    (r"(palme d'or|golden lion|golden bear|volpi cup|prix d'interpr)", "festival_top"),
    (r"(independent spirit|gotham)", "spirit_gotham"),
    (r"(new york film critics|los angeles film critics|national society of film critics)",
     "critics_group"),
]


def classify_award(label: str) -> Optional[str]:
    """Map a Wikidata award label onto an AWARD_TABLE key, or None to ignore it."""
    lowered = label.lower()
    for pattern, key in AWARD_PATTERNS:
        if re.search(pattern, lowered):
            return key
    return None


def parse_score(raw: str, source: str) -> Optional[float]:
    """Wikidata review scores are free text: '72%', '62/100', '6.7/10'."""
    raw = raw.strip()
    source = source.lower()
    percent = re.match(r"^([\d.]+)\s*%$", raw)
    fraction = re.match(r"^([\d.]+)\s*/\s*([\d.]+)$", raw)

    if "rotten tomatoes" in source:
        if percent:
            return float(percent.group(1))          # the Tomatometer
        return None                                  # the /10 average is a different scale
    if "metacritic" in source:
        if fraction and float(fraction.group(2)) == 100:
            return float(fraction.group(1))
        if percent:
            return float(percent.group(1))
    if "imdb" in source and fraction and float(fraction.group(2)) == 10:
        return float(fraction.group(1))
    return None


class Wikidata(HTTPSource):
    name = "wikidata"
    env_var = ""            # no key required
    base_url = SPARQL_URL
    min_interval = 1.0      # be a good citizen on a donated endpoint

    @property
    def available(self) -> bool:
        return True

    def require_key(self) -> None:
        return None

    def query(self, sparql: str, cache_key: str) -> list[dict[str, Any]]:
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        import requests
        self._throttle()
        response = requests.get(
            SPARQL_URL, params={"format": "json", "query": sparql},
            headers={"Accept": "application/sparql-results+json", "User-Agent": USER_AGENT},
            timeout=60)
        response.raise_for_status()
        rows = response.json()["results"]["bindings"]
        self.cache.set(cache_key, rows)
        return rows

    # ------------------------------------------------------------------ people
    def qid_for_imdb(self, imdb_person_id: str) -> Optional[str]:
        """Resolve via IMDb id (P345), which TMDB gives us - far safer than a
        name search, which collides on common names."""
        rows = self.query(
            f'SELECT ?p WHERE {{ ?p wdt:P345 "{imdb_person_id}" }} LIMIT 1',
            f"qid_imdb:{imdb_person_id}")
        return rows[0]["p"]["value"].rsplit("/", 1)[-1] if rows else None

    def awards(self, qid: str) -> list[Award]:
        """Every award and nomination Wikidata holds for a person."""
        # The label service derives ?awardLabel from a variable named ?award.
        # Naming it ?a returns rows with no label at all, which is silent - the
        # query succeeds and every award is dropped. See test_label_variables.
        sparql = f"""
SELECT ?kind ?awardLabel ?date WHERE {{
  {{ wd:{qid} p:P166 ?s . BIND("won" AS ?kind) ?s ps:P166 ?award .
     OPTIONAL {{ ?s pq:P585 ?date }} }}
  UNION
  {{ wd:{qid} p:P1411 ?s . BIND("nom" AS ?kind) ?s ps:P1411 ?award .
     OPTIONAL {{ ?s pq:P585 ?date }} }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}}"""
        out: list[Award] = []
        for row in self.query(sparql, f"awards:{qid}"):
            label = row.get("awardLabel", {}).get("value")
            if not label:
                continue        # no label, nothing to classify
            key = classify_award(label)
            if key is None:
                continue
            awarded = _parse_date(row.get("date", {}).get("value"))
            if awarded is None:
                continue        # undated awards cannot be decayed, so they are dropped
            out.append(Award(key=key, year=awarded.year - 1, awarded_on=awarded,
                             won=row["kind"]["value"] == "won", category=label))
        return _dedupe(out)

    # ------------------------------------------------------------------- films
    def films_info(self, imdb_ids: list[str]) -> dict[str, dict[str, Any]]:
        """Review scores AND the exact English Wikipedia article, for many films
        in one query.

        The article title matters more than it looks. Matching a film to
        Wikipedia by its bare title is badly wrong - a first attempt resolved
        1 of 10 correctly and pulled money figures off disambiguation pages, a
        TV special and an article about Indonesian folk theatre. The sitelink
        from the film's own Wikidata entity is exact.
        """
        ids = [i for i in dict.fromkeys(imdb_ids) if i]
        if not ids:
            return {}

        out: dict[str, dict[str, Any]] = {}
        for chunk in _chunks(ids, 60):
            values = " ".join(f'"{i}"' for i in chunk)
            sparql = f"""
SELECT ?imdb ?article ?score ?byLabel WHERE {{
  VALUES ?imdb {{ {values} }}
  ?f wdt:P345 ?imdb .
  OPTIONAL {{ ?article schema:about ?f ; schema:isPartOf <https://en.wikipedia.org/> }}
  OPTIONAL {{ ?f p:P444 ?s . ?s ps:P444 ?score . OPTIONAL {{ ?s pq:P447 ?by }} }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}}"""
            key = "films:" + ",".join(sorted(chunk))
            for row in self.query(sparql, key):
                imdb_id = row["imdb"]["value"]
                entry = out.setdefault(imdb_id, {"article": None, "scores": {}})

                if row.get("article") and not entry["article"]:
                    entry["article"] = _article_title(row["article"]["value"])

                if row.get("score"):
                    source = row.get("byLabel", {}).get("value", "")
                    value = parse_score(row["score"]["value"], source)
                    if value is None:
                        continue
                    lowered = source.lower()
                    if "rotten tomatoes" in lowered:
                        entry["scores"].setdefault("rt_critics", value)
                    elif "metacritic" in lowered:
                        entry["scores"].setdefault("metascore", value)
                    elif "imdb" in lowered:
                        entry["scores"].setdefault("imdb", value)
        return out


def _chunks(items: list[str], size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _article_title(url: str) -> str:
    from urllib.parse import unquote
    return unquote(url.split("/wiki/", 1)[-1]).replace("_", " ")


def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _dedupe(awards: list[Award]) -> list[Award]:
    """Wikidata often carries the same award twice with different qualifiers."""
    seen, out = set(), []
    for award in awards:
        token = (award.key, award.awarded_on, award.won)
        if token in seen:
            continue
        seen.add(token)
        out.append(award)
    return out
