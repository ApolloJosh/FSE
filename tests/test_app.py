"""Route-level tests: auth gates, CSRF, and that a trade actually moves money."""

import os
from datetime import date, timedelta

import pytest

os.environ.setdefault("SESSION_SECRET", "test-secret")

from fastapi.testclient import TestClient      # noqa: E402

from app import db, main                        # noqa: E402

TODAY = date.today()


@pytest.fixture
def client(tmp_path, monkeypatch):
    conn = db.connect(":memory:")
    db.migrate(conn)
    db.record_prices(conn, TODAY - timedelta(days=2), [
        {"slug": "mid", "name": "Mid Career", "is_director": False,
         "price": db.cents(20.00), "cp": 700.0, "tier": "Working"},
        {"slug": "cheap", "name": "Cheap One", "is_director": False,
         "price": db.cents(4.00), "cp": 50.0, "tier": "Debut"},
    ])
    monkeypatch.setattr(main, "_conn", conn)
    monkeypatch.setattr(main, "conn", lambda: conn)
    return TestClient(main.app), conn


def sign_in(client, conn, name="Josh", credits=db.cents(50.00)):
    """Mint the same signed cookie SessionMiddleware would, so the tests go
    through the real session and CSRF path rather than around it."""
    import base64
    import json

    from itsdangerous import TimestampSigner

    user = db.upsert_user(conn, "github", name, name, None, credits)
    payload = base64.b64encode(
        json.dumps({"uid": user["id"], "csrf": "test-csrf"}).encode())
    signed = TimestampSigner(os.environ["SESSION_SECRET"]).sign(payload).decode()
    client.cookies.set("session", signed)
    return user["id"]


# ------------------------------------------------------------------- public
def test_the_market_is_public(client):
    c, _ = client
    r = c.get("/")
    assert r.status_code == 200
    assert "Mid Career" in r.text


def test_a_stock_page_is_public(client):
    c, _ = client
    r = c.get("/stock/mid")
    assert r.status_code == 200
    assert "Sign in</a> to trade" in r.text


def test_an_unknown_stock_is_a_404(client):
    c, _ = client
    assert c.get("/stock/nobody").status_code == 404


def test_health_reports_the_price_date(client):
    c, _ = client
    body = c.get("/healthz").json()
    assert body["ok"] is True
    assert body["prices_as_of"] == (TODAY - timedelta(days=2)).isoformat()


def test_the_leaderboards_are_public(client):
    c, _ = client
    assert c.get("/leaderboards").status_code == 200
    assert c.get("/leaderboards?board=scout").status_code == 200


def test_an_unknown_board_falls_back_rather_than_erroring(client):
    c, _ = client
    r = c.get("/leaderboards?board=../../etc/passwd")
    assert r.status_code == 200


# --------------------------------------------------------------------- gates
def test_the_portfolio_redirects_when_signed_out(client):
    c, _ = client
    r = c.get("/portfolio", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/signin"


def test_trading_signed_out_is_refused(client):
    c, conn = client
    r = c.post("/stock/trade", data={"slug": "mid", "side": "buy", "shares": "1",
                                     "csrf": "anything"})
    assert r.status_code in (401, 403)
    assert conn.execute("SELECT COUNT(*) AS n FROM trades").fetchone()["n"] == 0


def test_a_trade_without_a_csrf_token_is_refused(client):
    """Without this, any page on the internet could spend a player's Credits."""
    c, conn = client
    sign_in(c, conn)
    r = c.post("/stock/trade", data={"slug": "mid", "side": "buy", "shares": "1",
                                     "csrf": "forged"})
    assert r.status_code == 403
    assert conn.execute("SELECT COUNT(*) AS n FROM trades").fetchone()["n"] == 0


def _csrf(c, path="/stock/mid"):
    import re
    html = c.get(path).text
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


# -------------------------------------------------------------------- trading
def test_a_signed_in_player_can_buy(client):
    c, conn = client
    user_id = sign_in(c, conn, credits=db.cents(5000.00))
    token = _csrf(c)
    r = c.post("/stock/trade", data={"slug": "mid", "side": "buy", "shares": "2",
                                     "csrf": token}, follow_redirects=False)
    assert r.status_code == 303
    pos = db.position(conn, user_id, "mid")
    assert pos["shares"] == 2
    assert db.user(conn, user_id)["credits"] == db.cents(5000.00) - db.cents(40.60)


def test_a_refused_trade_reports_why_and_changes_nothing(client):
    c, conn = client
    user_id = sign_in(c, conn, credits=db.cents(5.00))
    token = _csrf(c)
    r = c.post("/stock/trade", data={"slug": "mid", "side": "buy", "shares": "99",
                                     "csrf": token}, follow_redirects=False)
    assert r.status_code == 303
    assert "ok=0" in r.headers["location"]
    assert db.position(conn, user_id, "mid") is None
    assert db.user(conn, user_id)["credits"] == db.cents(5.00)


def test_the_portfolio_shows_a_holding(client):
    c, conn = client
    user_id = sign_in(c, conn, credits=db.cents(5000.00))
    c.post("/stock/trade", data={"slug": "mid", "side": "buy", "shares": "2",
                                 "csrf": _csrf(c)})
    html = c.get("/portfolio").text
    assert "Mid Career" in html
    assert "Your value" in html


def test_signing_out_clears_the_session(client):
    c, conn = client
    sign_in(c, conn)
    r = c.get("/signout", follow_redirects=False)
    assert r.status_code == 303
    # The response must tell the browser to drop the session cookie.
    assert "session=" in r.headers.get("set-cookie", "")

    c.cookies.clear()
    assert c.get("/portfolio", follow_redirects=False).status_code == 303


def test_the_position_cap_is_enforced_through_the_route(client):
    """2 shares at CR 20 is 8% of a CR 500 portfolio, over the 5% cap."""
    c, conn = client
    user_id = sign_in(c, conn, credits=db.cents(500.00))
    r = c.post("/stock/trade", data={"slug": "mid", "side": "buy", "shares": "2",
                                     "csrf": _csrf(c)}, follow_redirects=False)
    assert "ok=0" in r.headers["location"]
    assert db.position(conn, user_id, "mid") is None


def test_a_player_name_is_escaped_on_the_leaderboard(client):
    c, conn = client
    db.upsert_user(conn, "github", "x", "<script>alert(1)</script>", None,
                   db.cents(50.00))
    html = c.get("/leaderboards?board=all-time").text
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


# --------------------------------------------------------------- daily games
def test_the_games_hub_needs_an_account(client):
    c, _ = client
    r = c.get("/play", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/signin"


def test_the_hub_lists_today_for_a_signed_in_player(client):
    c, conn = client
    sign_in(c, conn)
    html = c.get("/play").text
    assert "Today's games" in html
    assert "The Ladder" in html and "Box Office Blind" in html


def test_a_game_page_renders_and_starts_a_play(client):
    c, conn = client
    user_id = sign_in(c, conn)
    assert c.get("/play/ladder").status_code == 200
    row = conn.execute("SELECT * FROM plays WHERE user_id = ? AND game = 'ladder'",
                       (user_id,)).fetchone()
    assert row is not None and row["done"] == 0


def test_submitting_a_game_without_csrf_is_refused(client):
    c, conn = client
    user_id = sign_in(c, conn)
    c.get("/play/cast-gap")
    r = c.post("/play/cast-gap", data={"csrf": "forged", "answer": "x"})
    assert r.status_code == 403
    row = conn.execute("SELECT done FROM plays WHERE user_id = ? AND game = 'cast-gap'",
                       (user_id,)).fetchone()
    assert row["done"] == 0


def test_playing_a_game_pays_credits(client):
    c, conn = client
    user_id = sign_in(c, conn)
    before = db.user(conn, user_id)["credits"]
    token = _csrf(c, "/play/cast-gap")
    r = c.post("/play/cast-gap", data={"csrf": token, "answer": "definitely wrong",
                                       "action": "guess"}, follow_redirects=False)
    assert r.status_code == 303
    # a wrong first guess leaves one more, so play it out
    c.post("/play/cast-gap", data={"csrf": token, "answer": "still wrong",
                                   "action": "guess"})
    row = conn.execute("SELECT * FROM plays WHERE user_id = ? AND game = 'cast-gap'",
                       (user_id,)).fetchone()
    assert row["done"] == 1
    assert db.user(conn, user_id)["credits"] == before + row["payout"]


def test_a_finished_game_cannot_be_replayed_for_more_credits(client):
    c, conn = client
    user_id = sign_in(c, conn)
    token = _csrf(c, "/play/box-office")
    data = {"csrf": token, "action": "guess"}
    import re
    html = c.get("/play/box-office").text
    keys = re.findall(r'name="rank_([^"]+)"', html)
    for i, key in enumerate(keys, 1):
        data[f"rank_{key}"] = str(i)
    c.post("/play/box-office", data=data)
    after_first = db.user(conn, user_id)["credits"]
    c.post("/play/box-office", data=data)
    assert db.user(conn, user_id)["credits"] == after_first


def test_an_unavailable_game_sends_you_back_with_a_reason(client, monkeypatch):
    """When the corpus cannot make a fair puzzle, the player is told, not shown
    something broken."""
    from app.games import routes
    from app.games.puzzles import NotEnoughData

    def refuse(game, on, snapshot):
        raise NotEnoughData("Nothing fair to ask today.")

    monkeypatch.setattr(routes, "generate", refuse)
    c, conn = client
    sign_in(c, conn)
    r = c.get("/play/ladder", follow_redirects=False)
    assert r.status_code == 303 and "/play?msg=" in r.headers["location"]


def test_an_unknown_game_is_not_a_crash(client):
    c, conn = client
    sign_in(c, conn)
    r = c.get("/play/../../etc/passwd", follow_redirects=False)
    assert r.status_code in (303, 404)


# ------------------------------------------------------------------- linkage
def _broken_links(c):
    """Follow every href on every reachable page and report the dead ones.

    Relative hrefs are the recurring bug here: the same nav renders at the top
    level and a directory down, and one that forgets renders /stock/signin.
    """
    import re
    from urllib.parse import urljoin

    seen, queue, bad = set(), ["/"], []
    while queue:
        url = queue.pop(0)
        if url in seen or url.startswith("/signout"):
            continue
        seen.add(url)
        r = c.get(url, follow_redirects=True)
        url = r.url.path
        seen.add(url)
        if r.status_code >= 400:
            bad.append((url, r.status_code))
            continue
        if "html" not in r.headers.get("content-type", ""):
            continue
        for href in re.findall(r'href="([^"]*)"', r.text):
            if href and not href.startswith(("http", "mailto:", "#")):
                queue.append(urljoin(url, href))
    return bad


def test_no_page_links_to_a_dead_one_signed_out(client):
    c, _ = client
    assert _broken_links(c) == []


def test_no_page_links_to_a_dead_one_signed_in(client):
    c, conn = client
    sign_in(c, conn)
    assert _broken_links(c) == []
