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


def test_non_dollar_figures_are_refused_rather_than_guessed():
    """We have no exchange rate, so a rupee or euro figure is not a number we
    can put on the multiple-of-budget ladder."""
    assert parse_money("₹125 crore") is None
    assert parse_money("€12 million") is None


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
