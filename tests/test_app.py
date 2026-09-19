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
