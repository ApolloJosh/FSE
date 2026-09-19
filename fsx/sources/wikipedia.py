"""Wikipedia film infoboxes: budget and worldwide gross.

Free, no key, no meaningful rate limit. Measured on a 15-film sample, the
infobox carried a budget for 87% and a gross for 93% - against 24% and 28% on
Wikidata, and TMDB's community-entered figures, which thin out badly below
about $10M. So this is the better money source, and it is the one that makes
the box office engine usable for small films.

The catch is that these are free-text fields written by humans:

    | budget = $100 million
    | gross  = $976.1 million
    | budget = $15-17 million
    | gross  = $1.446 billion

so everything here is parsing, and every parse can fail. A failed parse returns
None and the credit scores on reception and awards alone, which is the same
path a missing budget already takes.

The infobox `starring` field is the poster billing block, not a cast list -
a median of 6 names. It is useful for confirming who the leads are, and useless
for telling 13th billed from 20th, which is why TMDB remains the source for
role weight.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from .base import HTTPSource

API_URL = "https://en.wikipedia.org/w/api.php"
USER_AGENT = "FilmStockExchange/0.1 (career scoring research)"

MULTIPLIERS = {"thousand": 1e3, "million": 1e6, "billion": 1e9, "crore": 1e7, "lakh": 1e5}

# Foreign films are the ones whose budgets are missing most often, and when they
# do have one it is rarely in dollars. Refusing to read it dropped 27 of the 54
# budgets that failed to parse on a 1,467-article sample - a British film with a
# documented £2M budget read as having no budget at all.
#
# These are rough long-run rates, not the rate on the film's release date. That
# is fine: the ladder buckets are wide enough that a 10% error in the conversion
# never moves a film between rungs. It would not be fine for anything narrower.
USD_PER = {
    "$": 1.0, "US$": 1.0, "USD": 1.0,
    "€": 1.10, "EUR": 1.10,
    "£": 1.28, "GBP": 1.28,
    "¥": 0.0068, "JPY": 0.0068,
    "₩": 0.00075, "KRW": 0.00075,
    "₹": 0.012, "INR": 0.012,
    "A$": 0.66, "AUD": 0.66,
    "C$": 0.73, "CAD": 0.73,
    "CN¥": 0.14, "CNY": 0.14, "RMB": 0.14,
    "R$": 0.19, "BRL": 0.19,
}
# Longest first, so "US$" and "A$" are not read as a bare "$", and "CN¥" is not
# read as yen - which would price a Chinese film at a twentieth of its budget.
CURRENCY_MARKERS = sorted(USD_PER, key=len, reverse=True)


def _currency_templates(text: str) -> str:
    """{{KRW|15 billion}} -> 'KRW 15 billion', before templates get stripped."""
    def sub(match):
        code = match.group(1).upper()
        return f" {code} {match.group(2)} " if code in USD_PER else " "
    return re.sub(r"\{\{\s*([A-Za-z]{3})\s*\|\s*([^{}|]+?)\s*(?:\|[^{}]*)?\}\}",
                  sub, text)


def parse_money(raw: Optional[str]) -> Optional[float]:
    """'$976.1 million' -> 976100000.0, '£2 million' -> 2560000.0.

    Ranges take the low end; anything that does not parse cleanly returns None
    rather than a guess.
    """
    if not raw:
        return None

    text = re.sub(r"<ref[\s\S]*?(/>|</ref>)", " ", raw)
    text = _currency_templates(text)
    text = re.sub(r"\{\{[^{}]*\}\}", " ", text)
    text = text.replace("&nbsp;", " ").replace("–", "-").replace("—", "-")
    text = re.sub(r"[\[\]']", "", text).strip()

    # A figure has to say what currency it is in. An unmarked number in an
    # infobox is usually a footnote marker or a stray year.
    marker = next((m for m in CURRENCY_MARKERS if m in text), None)
    if marker is None:
        return None
    rate = USD_PER[marker]
    text = text.split(marker, 1)[1]

    match = re.match(r"\s*([\d,]+(?:\.\d+)?)", text)
    if not match:
        return None
    amount = float(match.group(1).replace(",", ""))

    tail = text[match.end():match.end() + 24].lower()
    for word, factor in MULTIPLIERS.items():
        if word in tail:
            return amount * factor * rate
    # A bare "$100" is a footnote, not a budget - but the cutoff is on the
    # original figure, so ¥100,000,000 is not thrown away for being small.
    return amount * rate if amount > 1000 else None


def is_film_article(wikitext: str) -> bool:
    """Belt and braces on top of the sitelink: only read money off a film.

    A title match once landed on {{Infobox dance}} for an article about
    Indonesian folk theatre, and on several disambiguation pages.
    """
    return bool(re.search(r"\{\{\s*Infobox\s+film\b", wikitext, re.IGNORECASE))


def parse_infobox(wikitext: str) -> dict[str, str]:
    """Flatten an infobox into {field: raw value}, keeping multi-line lists."""
    fields: dict[str, str] = {}
    key = None
    for line in wikitext.split("\n"):
        match = re.match(r"^\|\s*([a-z_0-9]+)\s*=\s*(.*)$", line, re.IGNORECASE)
        if match:
            key = match.group(1).lower()
            fields[key] = match.group(2)
        elif key and line.startswith(("*", " ")):
            fields[key] += "\n" + line
    return fields


def parse_billing(starring_field: Optional[str]) -> list[str]:
    """The poster billing block, in order. Median 6 names; not a full cast."""
    if not starring_field:
        return []
    names = []
    for line in re.findall(r"^\*\s*(.+)$", starring_field, re.MULTILINE):
        cleaned = re.sub(r"<ref[\s\S]*?(/>|</ref>)", "", line)
        cleaned = re.sub(r"[\[\]']", "", cleaned).split("|")[-1].strip()
        if cleaned:
            names.append(cleaned)
    return names


class Wikipedia(HTTPSource):
    name = "wikipedia"
    env_var = ""            # no key required
    base_url = API_URL
    min_interval = 0.2

    @property
    def available(self) -> bool:
        return True

    def require_key(self) -> None:
        return None

    def lead_wikitext(self, title: str) -> Optional[str]:
        cache_key = f"lead:{title}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached or None

        import requests
        self._throttle()
        response = requests.get(API_URL, params={
            "action": "parse", "page": title, "prop": "wikitext",
            "section": 0, "format": "json", "redirects": 1,
        }, headers={"User-Agent": USER_AGENT}, timeout=30)
        response.raise_for_status()

        payload: dict[str, Any] = response.json()
        text = payload.get("parse", {}).get("wikitext", {}).get("*", "")
        self.cache.set(cache_key, text)
        return text or None

    def film_money(self, title: str) -> dict[str, Optional[float]]:
        """Budget and worldwide gross for one film, or an empty dict.

        `title` must be an exact article title resolved from the film's Wikidata
        sitelink, never a bare film name - see Wikidata.films_info for why.
        """
        wikitext = self.lead_wikitext(title)
        if not wikitext or not is_film_article(wikitext):
            return {}
        fields = parse_infobox(wikitext)
        out = {}
        budget = parse_money(fields.get("budget"))
        gross = parse_money(fields.get("gross"))
        if budget:
            out["budget"] = budget
        if gross:
            out["worldwide_gross"] = gross
        return out
