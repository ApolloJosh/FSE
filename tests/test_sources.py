"""Auth wiring for the data sources. No network: these test credential handling."""

import json

import pytest

from fsx.sources.base import HTTPSource, MissingKey
from fsx.sources.omdb import OMDb
from fsx.sources.tmdb import TMDB


def test_tmdb_prefers_the_bearer_token():
    source = TMDB(api_key="v3key", token="v4token")
    assert source.headers == {"Authorization": "Bearer v4token"}
    assert source.auth == {}          # the key is left out entirely


def test_tmdb_falls_back_to_the_v3_key():
    source = TMDB(api_key="v3key", token="")
    assert source.headers == {}
    assert source.auth == {"api_key": "v3key"}


def test_either_credential_counts_as_available():
    assert TMDB(api_key="", token="v4token").available
    assert TMDB(api_key="v3key", token="").available
    assert not TMDB(api_key="", token="").available


def test_an_explicit_empty_credential_is_not_the_environment(monkeypatch):
    monkeypatch.setenv("TMDB_READ_ACCESS_TOKEN", "from-env")
    assert TMDB(api_key="", token="").token == ""
    assert TMDB(api_key="").token == "from-env"


def test_a_missing_key_names_both_credentials():
    with pytest.raises(MissingKey, match="TMDB_READ_ACCESS_TOKEN"):
        TMDB(api_key="", token="").require_key()


def test_omdb_has_no_bearer_option():
    source = OMDb(api_key="k")
    assert source.headers == {}
    assert source.available


def test_omdb_reports_its_own_env_var():
    with pytest.raises(MissingKey, match="OMDB_API_KEY"):
        OMDb(api_key="").require_key()


def test_the_cache_survives_a_missing_key(tmp_path):
    """Scores are cached permanently so an outage degrades new films only."""
    from fsx.sources.cache import Cache
    cache = Cache("test", directory=tmp_path)
    cache.set("imdb:tt0111161", {"imdbRating": "9.3"})
    assert cache.get("imdb:tt0111161") == {"imdbRating": "9.3"}
    assert cache.get("imdb:nothing") is None


def test_a_source_reads_its_credential_from_the_environment(monkeypatch):
    monkeypatch.setenv("OMDB_API_KEY", "env-key")
    assert OMDb().api_key == "env-key"


# ------------------------------------------------------------------- cache age
def test_a_stamped_entry_expires(tmp_path):
    """A film's reviews settle; a filmography does not. Cached for good, a
    stock could never learn that its owner had released something."""
    import time
    from fsx.sources.cache import Cache

    cache = Cache("t", tmp_path)
    cache.set("credits:1", {"cast": []}, stamp=True)
    assert cache.get("credits:1", max_age_days=7) == {"cast": []}

    stale = cache._path("credits:1")
    data = json.loads(stale.read_text())
    data["_fetched"] = time.time() - 8 * 86400
    stale.write_text(json.dumps(data))
    assert cache.get("credits:1", max_age_days=7) is None
    assert cache.get("credits:1") == {"cast": []}   # still readable, just stale


def test_an_unstamped_entry_is_refetched_once_when_an_age_is_wanted(tmp_path):
    """Entries written before expiry existed have an unknown age, so they must
    not be trusted as fresh - and must still read as permanent ones."""
    from fsx.sources.cache import Cache

    cache = Cache("t", tmp_path)
    cache.set("credits:2", {"cast": ["old"]})
    assert cache.get("credits:2", max_age_days=7) is None
    assert cache.get("credits:2") == {"cast": ["old"]}


def test_a_permanent_entry_is_untouched(tmp_path):
    from fsx.sources.cache import Cache

    cache = Cache("t", tmp_path)
    cache.set("movie:9", {"budget": 1})
    assert cache.get("movie:9") == {"budget": 1}


# ------------------------------------------------------------- the fetch window
def test_the_credit_window_counts_work_not_filmography_lines():
    """The window used to take the most recent N of everything, and for a
    veteran most of those are documentaries about them - Harrison Ford's
    reached back only to 2010, so Raiders was never fetched."""
    from fsx.sources.tmdb import appearance_of

    cast = [
        {"title": "Doc About Him", "character": "Self", "release_date": "2024-01-01"},
        {"title": "Clips Of Him", "character": "Self (archive footage)",
         "release_date": "2023-01-01"},
        {"title": "Raiders", "character": "Indiana Jones", "release_date": "1981-06-12"},
        {"title": "A Documentary", "character": "Narrator (voice)",
         "release_date": "2022-01-01"},
    ]
    work = [e for e in cast
            if appearance_of(e.get("character")) in ("role", "narration")]
    assert [e["title"] for e in work] == ["Raiders", "A Documentary"]


def test_an_archivist_is_a_part_not_archive_footage():
    from fsx.sources.tmdb import appearance_of
    assert appearance_of("Archivist") == "role"
    assert appearance_of("Self (archive footage)") == "archive"
