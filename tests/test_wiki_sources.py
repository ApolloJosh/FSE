"""Parser tests for the Wikipedia and Wikidata sources.

The HTTP paths are not exercised here - both hosts are unreachable from the
sandboxes this was built in. What is tested is the parsing, which is where the
real risk lives: these are free-text human-written fields, not an API contract.
"""

import pytest

from fsx.sources.wikidata import classify_award, parse_score
from fsx.sources.wikipedia import parse_billing, parse_infobox, parse_money

# ------------------------------------------------------------------- awards
@pytest.mark.parametrize("label,expected", [
    ("Academy Award for Best Actress", "oscar_lead"),
    ("Academy Award for Best Actor", "oscar_lead"),
    ("Academy Award for Best Supporting Actress", "oscar_supporting"),
    ("Academy Award for Best Director", "oscar_directing"),
    ("Academy Award for Best Picture", "oscar_picture"),
    ("Golden Globe Award for Best Actress in a Motion Picture - Drama", "globe"),
    ("BAFTA Award for Best Actress in a Leading Role", "bafta"),
    ("British Academy Film Award for Best Direction", "bafta"),
    ("Screen Actors Guild Award for Outstanding Performance by a Female Actor "
     "in a Leading Role", "sag_individual"),
    ("Screen Actors Guild Award for Outstanding Performance by a Cast in a "
     "Motion Picture", "sag_ensemble"),
    ("Primetime Emmy Award for Outstanding Supporting Actress in a Drama Series",
     "emmy_supporting"),
    ("Primetime Emmy Award for Outstanding Lead Actress in a Limited Series",
     "emmy_lead"),
    ("Critics' Choice Movie Award for Best Actress", "critics_choice"),
    ("Palme d'Or", "festival_top"),
    ("Volpi Cup for Best Actress", "festival_top"),
    ("Independent Spirit Award for Best Female Lead", "spirit_gotham"),
    ("New York Film Critics Circle Award for Best Actress", "critics_group"),
])
def test_award_labels_map_to_table_keys(label, expected):
    assert classify_award(label) == expected


def test_supporting_beats_the_generic_acting_pattern():
    """Order matters: 'Best Supporting Actress' also matches 'best actress'."""
    assert classify_award("Academy Award for Best Supporting Actor") == "oscar_supporting"


def test_unknown_awards_are_ignored_rather_than_guessed():
    assert classify_award("Saturn Award for Best Horror Film") is None
    assert classify_award("Honorary Doctorate") is None


def test_award_keys_all_exist_in_the_table():
    from fsx import constants as K
    from fsx.sources.wikidata import AWARD_PATTERNS
    for _, key in AWARD_PATTERNS:
        assert key in K.AWARD_TABLE, key


# ------------------------------------------------------- wikidata review scores
@pytest.mark.parametrize("raw,source,expected", [
    ("72%", "Rotten Tomatoes", 72.0),
    ("62/100", "Metacritic", 62.0),
    ("8.3/10", "IMDb", 8.3),
])
def test_review_scores_parse_off_their_own_scale(raw, source, expected):
    assert parse_score(raw, source) == pytest.approx(expected)


def test_the_rotten_tomatoes_average_is_not_the_tomatometer():
    """RT publishes both '72%' and '6.7/10'. Only the percentage is the
    Tomatometer the Reception Score is calibrated against."""
    assert parse_score("6.7/10", "Rotten Tomatoes") is None
    assert parse_score("72%", "Rotten Tomatoes") == 72.0


def test_an_unrecognised_source_is_dropped():
    assert parse_score("4/5", "Some Blog") is None


# --------------------------------------------------------------- infobox money
@pytest.mark.parametrize("raw,expected", [
    ("$100 million", 100e6),
    ("$976.1 million", 976_100_000),
    ("$1.446 billion", 1.446e9),
    ("$4.5 million", 4.5e6),
    ("$220,000", 220_000),
])
def test_money_parses(raw, expected):
    assert parse_money(raw) == pytest.approx(expected)


def test_a_range_takes_the_low_end():
    assert parse_money("$15-17 million") == pytest.approx(15e6)
    assert parse_money("$15–17 million") == pytest.approx(15e6)


def test_references_and_templates_are_stripped():
    raw = "$30 million<ref name=\"budget\">{{cite web|url=x}}</ref>"
    assert parse_money(raw) == pytest.approx(30e6)


def test_non_dollar_figures_are_converted():
    """Foreign films are the ones missing a budget most often, and when they
    have one it is rarely in dollars. Refusing to read it threw away 36 budgets
    on a 1,467-article sample."""
    assert parse_money("€12 million") == pytest.approx(13.2e6)
    assert parse_money("£2 million") == pytest.approx(2.56e6)
    assert parse_money("₹125 crore") == pytest.approx(125 * 1e7 * 0.012)


def test_a_currency_template_is_read_before_templates_are_stripped():
    """{{KRW|15 billion}} was being stripped wholesale, so a documented budget
    read as no budget."""
    assert parse_money("{{KRW|15 billion}}") == pytest.approx(11.25e6)
    assert parse_money("{{USD|7,200,000}}") == pytest.approx(7.2e6)
    assert parse_money("{{cite web|url=x}}") is None


def test_a_longer_currency_marker_wins():
    """Read as a bare yen sign, a Chinese film prices at a twentieth of its
    budget; read as a bare dollar, an Australian one at half again too much."""
    assert parse_money("CN¥300 million") == pytest.approx(42e6)
    assert parse_money("A$20 million") == pytest.approx(13.2e6)
    assert parse_money("US$20 million") == pytest.approx(20e6)


def test_a_small_figure_is_judged_before_conversion():
    """¥100,000,000 is a real budget; it must not be discarded for being under
    the dollar cutoff after conversion."""
    assert parse_money("¥100,000,000") == pytest.approx(680_000)
    assert parse_money("¥500") is None


def test_junk_returns_none_rather_than_a_guess():
    assert parse_money(None) is None
    assert parse_money("N/A") is None
    assert parse_money("") is None
    assert parse_money("$100") is None      # too small to be a film budget


# ------------------------------------------------------------- infobox parsing
INFOBOX = """{{Infobox film
| director       = [[Christopher Nolan]]
| starring       = {{Plainlist|
* [[Cillian Murphy]]
* [[Emily Blunt]]
* [[Matt Damon]]
}}
| runtime        = 181 minutes
| budget         = $100 million
| gross          = $976.1 million
}}"""


def test_infobox_fields_are_flattened():
    fields = parse_infobox(INFOBOX)
    assert fields["budget"].startswith("$100 million")
    assert fields["runtime"].startswith("181 minutes")


def test_the_billing_block_keeps_its_order():
    fields = parse_infobox(INFOBOX)
    assert parse_billing(fields["starring"]) == ["Cillian Murphy", "Emily Blunt", "Matt Damon"]


def test_billing_handles_a_missing_field():
    assert parse_billing(None) == []
    assert parse_billing("") == []


def test_piped_wikilinks_resolve_to_the_display_name():
    assert parse_billing("* [[Robert Downey Jr.|Downey]]") == ["Downey"]


# ------------------------------------------------- OMDb, against a real payload
# Captured live from OMDb for tt3896198 (Guardians of the Galaxy Vol. 2).
OMDB_PAYLOAD = {
    "Title": "Guardians of the Galaxy: Vol. 2", "Year": "2017",
    "Ratings": [
        {"Source": "Internet Movie Database", "Value": "7.6/10"},
        {"Source": "Rotten Tomatoes", "Value": "85%"},
        {"Source": "Metacritic", "Value": "67/100"},
    ],
    "Metascore": "67", "imdbRating": "7.6", "imdbVotes": "828,114",
    "imdbID": "tt3896198", "BoxOffice": "$389,813,101", "Response": "True",
}


def _enriched(payload):
    from datetime import date as _d
    from fsx.models import Credit
    from fsx.sources.omdb import OMDb

    source = OMDb(api_key="k")
    source.by_imdb_id = lambda _id: payload            # no network
    credit = Credit(title="t", release_date=_d(2017, 5, 5))
    credit.imdb_id = "tt3896198"
    return source.enrich(credit)


def test_omdb_fills_the_three_launch_sources():
    credit = _enriched(OMDB_PAYLOAD)
    assert credit.imdb == pytest.approx(7.6)
    assert credit.metascore == pytest.approx(67)
    assert credit.rt_critics == pytest.approx(85)


def test_vote_counts_survive_their_commas():
    """The vote count drives the confidence factor, so a bad parse quietly
    halves every score on the film."""
    assert _enriched(OMDB_PAYLOAD).imdb_votes == 828_114


def test_the_payload_clears_the_three_source_minimum():
    from fsx.reception import reception_score
    result = reception_score(_enriched(OMDB_PAYLOAD))
    assert result is not None and result.sources_used == 3
    assert result.confidence == pytest.approx(1.0)


def test_omdb_box_office_is_never_used():
    """OMDb reports DOMESTIC gross - $389.8M on a film that took ~$863M
    worldwide. Scoring that against budget would call most hits flops."""
    credit = _enriched(OMDB_PAYLOAD)
    assert credit.worldwide_gross is None


def test_a_missing_film_is_left_untouched():
    credit = _enriched({"Response": "False", "Error": "Incorrect IMDb ID."})
    assert credit.imdb is None and credit.rt_critics is None


def test_na_values_do_not_become_zero():
    payload = dict(OMDB_PAYLOAD, imdbVotes="N/A", imdbRating="N/A")
    credit = _enriched(payload)
    assert credit.imdb_votes is None
    assert credit.imdb is None


def test_metacritic_falls_back_to_the_ratings_array():
    """OMDb reports Metacritic twice - a top-level Metascore and an entry in
    Ratings. When the first is N/A the second still carries the number."""
    credit = _enriched(dict(OMDB_PAYLOAD, Metascore="N/A"))
    assert credit.metascore == pytest.approx(67)


def test_metascore_is_none_when_neither_place_has_it():
    payload = dict(OMDB_PAYLOAD, Metascore="N/A",
                   Ratings=[{"Source": "Rotten Tomatoes", "Value": "85%"}])
    assert _enriched(payload).metascore is None


def test_a_film_with_only_rt_falls_below_the_source_minimum():
    """Two sources is not enough, so the credit stays provisional rather than
    scoring off a single critic measure."""
    from fsx.reception import reception_score
    payload = dict(OMDB_PAYLOAD, Metascore="N/A",
                   Ratings=[{"Source": "Rotten Tomatoes", "Value": "85%"}])
    assert reception_score(_enriched(payload)) is None


# ------------------------------------------------- SPARQL / label-service wiring
def _sparql_of(method, *args):
    """Capture the query a method builds, without any network."""
    from fsx.sources.wikidata import Wikidata
    source = Wikidata()
    captured = {}

    def fake_query(sparql, cache_key, **kw):
        captured["sparql"] = sparql
        return []

    source.query = fake_query
    getattr(source, method)(*args)
    return captured.get("sparql", "")


def test_label_variables_have_a_matching_subject():
    """wikibase:label derives ?xLabel from a variable named ?x. Selecting
    ?awardLabel while binding ?a returns rows with no label at all - the query
    succeeds, and every award is silently dropped. That shipped once."""
    import re
    for query in (_sparql_of("awards", "Q123"), _sparql_of("films_info", ["tt1"])):
        for label_var in set(re.findall(r"\?(\w+)Label\b", query)):
            assert re.search(rf"\?{label_var}\b(?!Label)", query), (
                f"?{label_var}Label is selected but ?{label_var} is never bound")


def test_the_awards_query_asks_for_both_wins_and_nominations():
    query = _sparql_of("awards", "Q873")
    assert "P166" in query and "P1411" in query
    assert '"won"' in query and '"nom"' in query


def test_films_info_batches_ids_into_one_query():
    query = _sparql_of("films_info", ["tt1", "tt2", "tt3"])
    assert query.count("VALUES") == 1
    for i in ("tt1", "tt2", "tt3"):
        assert f'"{i}"' in query


def test_an_award_row_with_no_label_is_skipped_not_crashed():
    from fsx.sources.wikidata import Wikidata
    source = Wikidata()
    source.query = lambda *_, **__: [
        {"kind": {"value": "won"}, "date": {"value": "2020-01-01T00:00:00Z"}},
    ]
    assert source.awards("Q1") == []


def test_awards_map_and_date_correctly():
    from fsx.sources.wikidata import Wikidata
    source = Wikidata()
    source.query = lambda *_, **__: [
        {"kind": {"value": "won"},
         "awardLabel": {"value": "Academy Award for Best Director"},
         "date": {"value": "2024-01-01T00:00:00Z"}},
        {"kind": {"value": "nom"},
         "awardLabel": {"value": "Golden Globe Award for Best Director"},
         "date": {"value": "2024-01-01T00:00:00Z"}},
    ]
    awards = source.awards("Q25191")
    assert {a.key for a in awards} == {"oscar_directing", "globe"}
    assert [a.won for a in awards] == [True, False]
    assert awards[0].year == 2023        # a 2024 ceremony honours 2023 films


def test_awards_reach_the_engine_as_career_points():
    """The end of the chain that broke: awards fetched, mapped, and actually
    moving a price."""
    from datetime import date
    from fsx.engine import value_person
    from fsx.models import Person
    from fsx.sources.wikidata import Wikidata

    source = Wikidata()
    source.query = lambda *_, **__: [
        {"kind": {"value": "won"},
         "awardLabel": {"value": "Academy Award for Best Actress"},
         "date": {"value": "2023-01-01T00:00:00Z"}},
    ]
    person = Person("test", awards=source.awards("Q1"))
    assert value_person(person, date(2023, 6, 1)).award_cp > 0


def test_screenplay_awards_are_not_dropped():
    """A live query for a director returned several 'Academy Award for Best
    Writing, Adapted Screenplay' rows that mapped to nothing and vanished."""
    assert classify_award("Academy Award for Best Writing, Adapted Screenplay") \
        == "oscar_screenplay"
    assert classify_award("Academy Award for Best Writing, Original Screenplay") \
        == "oscar_screenplay"


def test_screenplay_does_not_outrank_directing():
    from fsx import constants as K
    assert K.AWARD_TABLE["oscar_screenplay"] < K.AWARD_TABLE["oscar_directing"]
