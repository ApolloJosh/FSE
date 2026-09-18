"""OMDb: IMDb rating and vote count, Metascore, and the RT Tomatometer.

Three of the game's most important numbers arrive through one community-run
service that relays scores it does not own. Everything fetched here is cached
permanently for exactly that reason.

RT Audience and Letterboxd are deliberately absent. Letterboxd declines
data-analysis and visualization projects outright, and no free or licensable
source carries the RT Audience score. The Reception Score is built to run on
three of five sources, so this is the launch configuration, not a degraded one.
"""

from __future__ import annotations

from typing import Optional

from ..models import Credit
from .base import HTTPSource


def _num(value: Optional[str]) -> Optional[float]:
    if not value or value in ("N/A", ""):
        return None
    try:
        return float(value.rstrip("%").replace(",", ""))
    except ValueError:
        return None


class OMDb(HTTPSource):
    name = "omdb"
    env_var = "OMDB_API_KEY"
    base_url = "http://www.omdbapi.com/"
    min_interval = 0.1

    def by_imdb_id(self, imdb_id: str) -> dict:
        return self.get("", {"apikey": self.api_key, "i": imdb_id},
                        f"imdb:{imdb_id}")

    def enrich(self, credit: Credit) -> Credit:
        """Layer review scores onto a credit TMDB already built."""
        imdb_id = getattr(credit, "imdb_id", None)
        if not imdb_id:
            return credit

        data = self.by_imdb_id(imdb_id)
        if data.get("Response") == "False":
            return credit

        credit.imdb = _num(data.get("imdbRating"))
        credit.imdb_votes = int(_num(data.get("imdbVotes")) or 0) or None
        credit.metascore = _num(data.get("Metascore"))

        for rating in data.get("Ratings") or []:
            if rating.get("Source") == "Rotten Tomatoes":
                credit.rt_critics = _num(rating.get("Value"))
            elif rating.get("Source") == "Metacritic" and credit.metascore is None:
                value = rating.get("Value", "")
                credit.metascore = _num(value.split("/")[0])

        if credit.runtime_share is None:
            runtime = getattr(credit, "runtime_minutes", 0) or 0
            if runtime:
                credit.runtime_share = None   # needs per-role screen time, not runtime
        return credit
