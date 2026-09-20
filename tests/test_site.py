"""The site build: it must never emit a broken or half-rendered page."""

from datetime import date, timedelta
from pathlib import Path

import pytest

from fsx import site, store
from fsx.fixtures.careers import roster
from fsx.history import change, month_starts, series
from fsx.models import Person


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("site")
    snapshot = out / "people.json"
    store.save(roster()[:6], snapshot)
    result = site.build(snapshot, out / "www", years=3)
    return out / "www", result


# ------------------------------------------------------------------ the store
def test_a_person_survives_a_round_trip():
    original = roster()[0]
    restored = store.person_from_dict(store.person_to_dict(original))
    assert restored.name == original.name
    assert len(restored.credits) == len(original.credits)
    assert len(restored.awards) == len(original.awards)
    assert restored.credits[0].release_date == original.credits[0].release_date


def test_prices_are_identical_after_a_round_trip():
    """The snapshot is what the site renders from, so it has to be lossless."""
    from fsx.engine import value_person
    as_of = date(2026, 1, 1)
    for original in roster()[:5]:
        restored = store.person_from_dict(store.person_to_dict(original))
        assert value_person(restored, as_of).price == pytest.approx(
            value_person(original, as_of).price)


def test_a_future_schema_is_refused_rather_than_misread(tmp_path):
    path = tmp_path / "p.json"
    store.save(roster()[:1], path)
    path.write_text(path.read_text().replace('"schema": 1', '"schema": 99'))
    with pytest.raises(ValueError, match="schema"):
        store.load(path)


# ---------------------------------------------------------------- the history
def test_history_runs_forward_in_time():
    months = month_starts(2, date(2026, 9, 18))
    assert len(months) == 24
    assert months == sorted(months)
    assert months[-1] < date(2026, 10, 1)


def test_a_career_with_no_credits_does_not_crash_the_chart():
    points = series(Person("nobody"), years=2)
    assert len(points) > 1
    assert all(p.price == pytest.approx(2.50) for p in points)


def test_change_is_none_when_history_is_too_short():
    points = series(roster()[0], years=1)
    assert change(points, days=3650) is None


# ------------------------------------------------------------------- the build
def test_every_page_is_written(built):
    www, result = built
    assert (www / "index.html").exists()
    assert (www / "about.html").exists()
    assert (www / "style.css").exists()
    assert (www / "market.json").exists()
    assert (www / ".nojekyll").exists()       # or Pages hides the assets
    assert len(list((www / "stock").glob("*.html"))) == result["people"]


def test_the_index_links_to_every_stock_page(built):
    www, _ = built
    index = (www / "index.html").read_text()
    for page in (www / "stock").glob("*.html"):
        assert f"stock/{page.name}" in index


def test_names_are_escaped_not_injected(built):
    """A name is data. It arrives from TMDB, so it is never trusted markup."""
    person = Person("<script>alert(1)</script>")
    html = site.render_stock(person, series(person, years=1), "today")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_slugs_are_safe_and_stable():
    assert site.slug("Timothée Chalamet") == "timoth-e-chalamet"
    assert site.slug("Robert Downey Jr.") == "robert-downey-jr"
    assert site.slug("../../etc/passwd") == "etc-passwd"
    assert site.slug("???") == "unknown"


def test_gains_and_losses_are_never_coloured_by_hand(built):
    """A negative 'best year' rendered green once, because the card hardcoded
    the class instead of deriving it from the sign."""
    import re
    index = (www_index := (built[0] / "index.html").read_text())
    for label in ("Best year", "Worst year"):
        match = re.search(
            re.escape(label) + r'</span><span class="stat-value"><span class="(\w+)">'
            r'(-?[\d.]+)', index)
        if match:
            css, value = match.group(1), float(match.group(2))
            assert css == ("up" if value > 0 else "down")
    assert www_index


def test_trend_class_follows_the_sign():
    assert site.trend_class(0.1) == "up"
    assert site.trend_class(-0.1) == "down"
    assert site.trend_class(None) == "flat"
    assert site.trend_class(0.0) == "flat"


def test_the_chart_stays_inside_its_viewbox(built):
    """The validator checks colour, not layout. This checks layout."""
    import re
    www, _ = built
    for page in (www / "stock").glob("*.html"):
        html = page.read_text()
        match = re.search(r'<path class="series" d="([^"]+)"', html)
        if not match:
            continue
        points = [tuple(map(float, s.split(",")))
                  for s in re.split(r"[ML]", match.group(1)) if s.strip()]
        xs = [p[0] for p in points]
        assert xs == sorted(xs), f"{page.name}: x axis is not monotonic"
        for x, y in points:
            assert 51.5 <= x <= site.CHART_W - 17.5, f"{page.name}: x overflow"
            assert 15.5 <= y <= site.CHART_H - 27.5, f"{page.name}: y overflow"


def test_the_api_payload_matches_the_pages(built):
    import json
    www, result = built
    payload = json.loads((www / "market.json").read_text())
    assert len(payload["stocks"]) == result["people"]
    for stock in payload["stocks"]:
        assert (www / "stock" / f"{stock['slug']}.html").exists()
        assert stock["price"] >= 2.50
        assert len(stock["history"]) > 1


def test_every_credit_field_survives_a_round_trip(tmp_path):
    """A field added to Credit and not to CREDIT_FIELDS is dropped on save,
    silently, and the engine then scores a snapshot that is missing it. That
    happened to `appearance`, and nothing failed until the ranking did not
    move."""
    import dataclasses
    from datetime import date

    from fsx.models import Credit, Person
    from fsx.store import CREDIT_FIELDS, load, save

    ignore = {"release_date"}       # handled separately, not a plain field
    declared = {f.name for f in dataclasses.fields(Credit)} - ignore
    assert declared == set(CREDIT_FIELDS), (
        "Credit fields not persisted: " + ", ".join(sorted(declared - set(CREDIT_FIELDS))))

    credit = Credit(title="T", release_date=date(2024, 1, 1), appearance="narration",
                    billing_order=0, cast_size=9, is_voice=True, budget=1e6)
    path = tmp_path / "people.json"
    save([Person(name="X", credits=[credit])], path)
    back = load(path)[0][0].credits[0]
    assert back.appearance == "narration" and back.is_voice and back.budget == 1e6


def test_the_operating_system_does_not_pick_the_theme():
    """A prefers-color-scheme block meant anyone whose Mac was in dark mode got
    a theme nobody had designed, and never saw the one we had."""
    from fsx.site import STYLE

    css = STYLE.split("*/")[-1]      # past the comment that explains this
    assert "prefers-color-scheme" not in css
    assert ':root[data-theme="dark"]' in STYLE


def test_the_theme_is_applied_before_the_page_paints():
    """Applied after first paint it is a white flash on every navigation for
    anyone who chose dark."""
    from fsx.site import THEME_BOOT, shell

    page = shell("T", "<p>body</p>", "2026-01-01")
    head = page[:page.index("</head>")]
    assert THEME_BOOT in head
    assert "fsx-theme" in head
