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


def test_one_unreachable_film_does_not_cost_the_whole_person():
    """A single failed call used to raise out of build_person, the caller
    logged "no TMDB record", and the person left the market with everything
    already fetched for them thrown away."""
    from datetime import date

    from fsx.sources.tmdb import TMDB

    source = TMDB(api_key="k")
    cast = [{"id": 1, "title": "Good", "character": "Lead", "order": 0,
             "release_date": "2020-01-01"},
            {"id": 2, "title": "Broken", "character": "Lead", "order": 0,
             "release_date": "2019-01-01"},
            {"id": 3, "title": "Also good", "character": "Lead", "order": 0,
             "release_date": "2018-01-01"}]

    source.search_person = lambda name: {"id": 7, "name": name}
    source.person_credits = lambda pid, age=None: {"cast": cast}
    source.release_shape = lambda mid: ("wide", None)
    source.movie_cast_size = lambda mid: 10

    def movie(mid):
        if mid == 2:
            raise RuntimeError("timeout")
        return {"runtime": 100, "budget": 1, "revenue": 2, "imdb_id": "tt1"}
    source.movie = movie

    skipped = []
    person = source.build_person("Someone", on_skip=lambda t, e: skipped.append(t))
    assert person is not None
    assert [c.title for c in person.credits] == ["Good", "Also good"]
    assert skipped == ["Broken"]


def test_a_missing_cast_size_is_not_fatal_either():
    from fsx.sources.tmdb import TMDB

    source = TMDB(api_key="k")
    source.search_person = lambda name: {"id": 7, "name": name}
    source.person_credits = lambda pid, age=None: {"cast": [
        {"id": 1, "title": "Film", "character": "Lead", "order": 0,
         "release_date": "2020-01-01"}]}
    source.movie = lambda mid: {"runtime": 100, "imdb_id": "tt1"}
    source.release_shape = lambda mid: ("wide", None)

    def boom(mid):
        raise RuntimeError("500")
    source.movie_cast_size = boom

    skipped = []
    person = source.build_person("Someone", on_skip=lambda t, e: skipped.append(t))
    assert len(person.credits) == 1 and person.credits[0].cast_size is None
    assert skipped == ["Film (cast size)"]


# ------------------------------------------------------------ nightly refresh
def _entry(title, released, character="Lead"):
    return {"id": abs(hash(title)) % 10000, "title": title,
            "character": character, "order": 0, "release_date": released}


def test_new_means_released_since_we_looked_not_absent_from_the_snapshot():
    """A filmography is capped, so everything below the cut is absent by
    design. Without a cutoff the nightly job reads Kramer vs. Kramer as
    tonight's news and spends weeks dragging in a back catalogue."""
    from fsx.cli import select_new

    payload = {"cast": [_entry("Kramer vs. Kramer", "1979-12-07"),
                        _entry("Out Last Night", "2026-09-18")]}
    fresh = select_new(payload, known=set(), cutoff="2026-05-22",
                       today="2026-09-19", max_new=6, is_director=False)
    assert [e["title"] for e in fresh] == ["Out Last Night"]


def test_a_film_already_in_the_snapshot_is_not_new():
    from fsx.cli import select_new

    payload = {"cast": [_entry("Already Have It", "2026-09-01")]}
    known = {("Already Have It", "2026-09-01")}
    assert select_new(payload, known, "2026-05-22", "2026-09-19", 6, False) == []


def test_an_unreleased_film_is_not_new_yet():
    from fsx.cli import select_new

    payload = {"cast": [_entry("Next Year", "2027-06-01")]}
    assert select_new(payload, set(), "2026-05-22", "2026-09-19", 6, False) == []


def test_documentary_appearances_are_not_new_work():
    from fsx.cli import select_new

    payload = {"cast": [_entry("A Doc About Them", "2026-09-01", "Self"),
                        _entry("Old Clips", "2026-09-02", "Self (archive footage)"),
                        _entry("A Real Part", "2026-09-03", "Lead")]}
    fresh = select_new(payload, set(), "2026-05-22", "2026-09-19", 6, False)
    assert [e["title"] for e in fresh] == ["A Real Part"]


def test_a_burst_of_new_entries_is_capped():
    """Forty new entries is a data change, not forty premieres."""
    from fsx.cli import select_new

    payload = {"cast": [_entry(f"Film {i}", f"2026-08-{i:02d}") for i in range(1, 21)]}
    assert len(select_new(payload, set(), "2026-05-22", "2026-09-19", 6, False)) == 6
