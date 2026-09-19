"""The Film Stock Exchange web app.

Phase 2: accounts, Credits, portfolios, trading and leaderboards. The market
itself is still read-only in the sense that matters - player money never moves
a price. Prices come from the engine and nothing else.
"""

from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from fsx.engine import explain
from fsx.site import esc, money, pct, sparkline, trend_class
from fsx.store import load

from . import auth, db, leaderboards, marking, views
from .trading import SETTLEMENT_DAYS, TradeError, buy, buy_slot, days_between, sell

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = Path(os.environ.get("FSX_SNAPSHOT", ROOT / "data" / "people.json"))
DB_PATH = Path(os.environ.get("FSX_DB", ROOT / "data" / "market.db"))

app = FastAPI(title="Film Stock Exchange", docs_url=None, redoc_url=None)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SESSION_SECRET", "dev-only-not-a-secret"),
    https_only=os.environ.get("FSX_ENV") == "production",
    same_site="lax",
)

PROVIDERS = auth.configure()
_conn = None


def conn():
    global _conn
    if _conn is None:
        _conn = db.connect(DB_PATH)
        db.migrate(_conn)
    return _conn


def current_user(request: Request):
    user_id = auth.current_user_id(request)
    return db.user(conn(), user_id) if user_id else None


def _static_dir() -> Path:
    directory = Path(__file__).with_name("static")
    directory.mkdir(exist_ok=True)
    (directory / "style.css").write_text(views.APP_STYLE)
    from fsx.site import CHART_JS
    (directory / "chart.js").write_text(CHART_JS)
    return directory


app.mount("/static", StaticFiles(directory=_static_dir()), name="static")

from .games.routes import router as games_router      # noqa: E402
app.include_router(games_router)


# --------------------------------------------------------------------- market
@app.get("/", response_class=HTMLResponse)
def market(request: Request, msg: str | None = None, ok: int = 0):
    user = current_user(request)
    prices = db.latest_prices(conn())
    held = {}
    if user:
        held = {p["slug"]: p["shares"] for p in db.positions(conn(), user["id"])}

    rows = []
    for slug, row in prices.items():
        history = db.price_history(conn(), slug, 120)
        points = views.points_from(history)
        earlier = [p for p in points if (points[-1].on - p.on).days >= 30]
        change = (points[-1].price / earlier[-1].price - 1) if earlier else None
        rows.append({
            "slug": slug, "name": row["name"], "is_director": row["is_director"],
            "price": db.credits(row["price"]), "tier": row["tier"], "change": change,
            "shares": held.get(slug, 0),
            "spark": sparkline(points) if len(points) > 1 else "",
        })
    rows.sort(key=lambda r: r["price"], reverse=True)
    return views.market_page(rows, user, views.flash(msg, bool(ok)))


@app.get("/stock/{slug}", response_class=HTMLResponse)
def stock(request: Request, slug: str, msg: str | None = None, ok: int = 0):
    user = current_user(request)
    prices = db.latest_prices(conn())
    row = prices.get(slug)
    if row is None:
        return HTMLResponse(views.chrome("Not listed", "<h1>Not listed</h1>"
                                         "<p>No such stock.</p>", user), status_code=404)

    points = views.points_from(db.price_history(conn(), slug, 400))
    pos = db.position(conn(), user["id"], slug) if user else None
    settle = None
    if pos:
        settle = SETTLEMENT_DAYS - days_between(pos["last_buy_on"], date.today())

    from fsx.site import line_chart
    chart = line_chart(points, row["name"]) if len(points) > 1 else (
        '<p class="muted">Price history starts once the market has run overnight.</p>')

    reasons = ""
    try:
        people, _ = load(SNAPSHOT)
        match = next((p for p in people if p.name == row["name"]), None)
        if match:
            items = [(c, v) for c, v in explain(match) if abs(v) >= 0.5][:12]
            reasons = "".join(
                f'<tr><td class="date">{c.event_date.isoformat()}</td>'
                f'<td>{esc(c.label)}</td>'
                f'<td class="num {"up" if v > 0 else "down"}">{v:+,.0f}</td></tr>'
                for c, v in items)
    except Exception:                                  # noqa: BLE001
        reasons = ""

    change = None
    if len(points) > 1:
        earlier = [p for p in points if (points[-1].on - p.on).days >= 30]
        if earlier:
            change = points[-1].price / earlier[-1].price - 1

    body = f"""
<nav class="crumb"><a href="../">← The market</a></nav>
<header class="stockhead">
  <h1>{esc(row['name'])}</h1>
  <div class="quote">
    <span class="big">{money(db.credits(row['price']))}</span><span class="unit">CR</span>
    <span class="chg {trend_class(change)}">{pct(change)} <small>30d</small></span>
    <span class="pill">{esc(row['tier'])}</span>
  </div>
</header>
{views.flash(msg, bool(ok))}
{views.trade_panel(slug, row['price'], user, pos, auth.csrf_token(request), settle)}
<h2>Price history</h2>
{chart}
<h2>Why it moved</h2>
<table class="reasons"><thead><tr><th>Date</th><th>Event</th>
<th class="num">CP</th></tr></thead><tbody>{reasons or
'<tr><td colspan="3" class="muted">No scoring events on file.</td></tr>'}</tbody></table>
"""
    return views.chrome(f"{row['name']} — Film Stock Exchange", body, user, depth=1)


# --------------------------------------------------------------------- trading
@app.post("/stock/trade")
def trade(request: Request, slug: str = Form(...), side: str = Form(...),
          shares: int = Form(...), csrf: str = Form(...)):
    auth.check_csrf(request, csrf)
    user_id = auth.require_user_id(request)
    leaderboards.ensure_season_baseline(conn(), user_id)

    try:
        if side == "buy":
            q = buy(conn(), user_id, slug, shares)
            note = (f"Bought {shares} at CR {money(db.credits(q.price))}, "
                    f"fee CR {money(db.credits(q.fee))}.")
        elif side == "sell":
            q = sell(conn(), user_id, slug, shares)
            note = (f"Sold {shares} at CR {money(db.credits(q.price))}, "
                    f"fee CR {money(db.credits(q.fee))}.")
        else:
            note, ok = "Unknown action.", 0
            return RedirectResponse(f"/stock/{slug}?msg={note}&ok=0", status_code=303)
        ok = 1
    except TradeError as exc:
        note, ok = str(exc), 0

    return RedirectResponse(f"/stock/{slug}?msg={note}&ok={ok}", status_code=303)


@app.post("/slots")
def slots(request: Request, csrf: str = Form(...)):
    auth.check_csrf(request, csrf)
    user_id = auth.require_user_id(request)
    try:
        cost = buy_slot(conn(), user_id)
        msg, ok = f"Slot added for CR {money(db.credits(cost))}.", 1
    except TradeError as exc:
        msg, ok = str(exc), 0
    return RedirectResponse(f"/portfolio?msg={msg}&ok={ok}", status_code=303)


# ------------------------------------------------------------------- portfolio
@app.get("/portfolio", response_class=HTMLResponse)
def portfolio(request: Request, msg: str | None = None, ok: int = 0):
    user = current_user(request)
    if user is None:
        return RedirectResponse("/signin", status_code=303)

    leaderboards.ensure_season_baseline(conn(), user["id"])
    user = db.user(conn(), user["id"])
    prices = db.latest_prices(conn())
    rows = ""
    for pos in db.positions(conn(), user["id"]):
        market_row = prices.get(pos["slug"])
        market_price = db.credits(market_row["price"]) if market_row else 0.0
        held = db.credits(pos["held_value"])
        gain = pos["held_value"] / pos["entry_price"] - 1 if pos["entry_price"] else 0
        rows += f"""<tr>
  <td class="name"><a href="/stock/{esc(pos['slug'])}">{esc(pos['name'] or pos['slug'])}</a></td>
  <td class="num">{pos['shares']}</td>
  <td class="num">{money(db.credits(pos['entry_price']))}</td>
  <td class="num">{money(market_price)}</td>
  <td class="num">{money(held)}</td>
  <td class="num {trend_class(gain)}">{pct(gain)}</td>
  <td class="num">{money(held * pos['shares'])}</td>
</tr>"""

    total = db.portfolio_value(conn(), user["id"])
    base = user["season_base"] or total
    season_growth = (total / base - 1) if base else 0.0
    open_positions = len(db.positions(conn(), user["id"]))

    history = "".join(
        f'<tr><td class="date">{esc(t["at"][:10])}</td>'
        f'<td>{esc(t["side"].title())} {t["shares"]} {esc(t["name"] or t["slug"])}</td>'
        f'<td class="num">{money(db.credits(t["price"]))}</td>'
        f'<td class="num {"up" if t["cash_delta"] > 0 else "down"}">'
        f'{money(db.credits(t["cash_delta"]))}</td></tr>'
        for t in db.trades(conn(), user["id"], 25))

    body = f"""
<section class="hero"><h1>{esc(user['display_name'])}</h1></section>
{views.flash(msg, bool(ok))}
<section class="stats">
  <div class="stat"><span class="stat-label">Cash</span>
    <span class="stat-value">{money(db.credits(user['credits']))}</span></div>
  <div class="stat"><span class="stat-label">Portfolio</span>
    <span class="stat-value">{money(db.credits(total))}</span></div>
  <div class="stat"><span class="stat-label">Season</span>
    <span class="stat-value {trend_class(season_growth)}">{pct(season_growth)}</span></div>
  <div class="stat"><span class="stat-label">Slots</span>
    <span class="stat-value">{open_positions}/{user['slots']}</span>
    <span class="stat-sub">
      <form method="post" action="/slots" style="display:inline">
        <input type="hidden" name="csrf" value="{esc(auth.csrf_token(request))}">
        <button class="btn ghost" style="padding:2px 8px;font-size:.78rem">Buy a slot</button>
      </form></span></div>
</section>
<h2>Holdings</h2>
<table><thead><tr><th>Stock</th><th class="num">Shares</th><th class="num">Entry</th>
<th class="num">Market</th><th class="num">Your value</th><th class="num">Gain</th>
<th class="num">Total</th></tr></thead>
<tbody>{rows or '<tr><td colspan="7" class="empty">Nothing held yet. '
'<a href="/">Find someone worth backing.</a></td></tr>'}</tbody></table>
<p class="muted">Your value differs from the market price because gains are
scaled by how long you had held when they happened. Selling settles at your
value, not the quote.</p>
<h2>Recent trades</h2>
<table><tbody>{history or '<tr><td class="empty">No trades yet.</td></tr>'}</tbody></table>
"""
    return views.chrome("Portfolio — Film Stock Exchange", body, user)


# ---------------------------------------------------------------- leaderboards
@app.get("/leaderboards", response_class=HTMLResponse)
def boards(request: Request, board: str = "season"):
    user = current_user(request)
    if board not in leaderboards.BOARDS:
        board = "season"
    title, blurb, fn, unit = leaderboards.BOARDS[board]
    entries = fn(conn())

    tabs = "".join(
        f'<a class="{"on" if key == board else ""}" href="?board={key}">{esc(name)}</a>'
        for key, (name, _, _, _) in leaderboards.BOARDS.items())

    def fmt(entry):
        if unit == "pct":
            return f'<span class="{trend_class(entry.value)}">{pct(entry.value)}</span>'
        if unit == "credits":
            return money(entry.value)
        return f"{entry.value:,.0f}"

    rows = "".join(
        f'<tr><td class="rank">{e.rank}</td><td>{esc(e.name)}</td>'
        f'<td class="muted">{esc(e.detail)}</td>'
        f'<td class="num">{fmt(e)}</td></tr>' for e in entries)

    body = f"""
<section class="hero"><h1>Leaderboards</h1><p class="lede">{esc(blurb)}</p></section>
<div class="boards">{tabs}</div>
<table><thead><tr><th class="rank">#</th><th>Player</th><th></th>
<th class="num">{esc(title)}</th></tr></thead>
<tbody>{rows or '<tr><td colspan="4" class="empty">Nobody on this board yet.</td></tr>'}
</tbody></table>"""
    return views.chrome(f"{title} leaderboard — Film Stock Exchange", body, user)


# ------------------------------------------------------------------------ auth
@app.get("/signin", response_class=HTMLResponse)
def signin(request: Request):
    if not PROVIDERS:
        body = ("<h1>Sign-in is not configured</h1><p class='muted'>Set "
                "GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET or GITHUB_CLIENT_ID / "
                "GITHUB_CLIENT_SECRET and restart.</p>")
        return views.chrome("Sign in", body, None)

    buttons = "".join(
        f'<a class="btn" href="/auth/{p}">Continue with {p.title()}</a>'
        for p in PROVIDERS)
    body = f"""
<section class="hero"><h1>Sign in</h1>
<p class="lede">New players start with CR 50.00. No passwords — we never ask for
one and never store one.</p></section>
<div class="signin">{buttons}</div>
<p class="muted">We keep a display name and an avatar. Nothing else.</p>"""
    return views.chrome("Sign in — Film Stock Exchange", body, None)


@app.get("/auth/{provider}")
async def authorize(request: Request, provider: str):
    if provider not in PROVIDERS:
        return RedirectResponse("/signin", status_code=303)
    client = getattr(auth.oauth, provider)
    return await client.authorize_redirect(
        request, str(request.url_for("callback", provider=provider)))


@app.get("/auth/{provider}/callback", name="callback")
async def callback(request: Request, provider: str):
    if provider not in PROVIDERS:
        return RedirectResponse("/signin", status_code=303)
    client = getattr(auth.oauth, provider)
    token = await client.authorize_access_token(request)
    provider_id, name, avatar = await auth.profile_from(provider, token, client)

    user = db.upsert_user(conn(), provider, provider_id, name, avatar,
                          auth.STARTING_CREDITS)
    auth.sign_in(request, user["id"])
    leaderboards.ensure_season_baseline(conn(), user["id"])
    return RedirectResponse("/", status_code=303)


@app.get("/signout")
def signout(request: Request):
    auth.sign_out(request)
    return RedirectResponse("/", status_code=303)


@app.get("/about", response_class=HTMLResponse)
def about(request: Request):
    from fsx.site import render_about
    inner = render_about(date.today().isoformat())
    start = inner.index("<article")
    end = inner.index("</article>") + len("</article>")
    return views.chrome("How prices work — Film Stock Exchange",
                        inner[start:end], current_user(request))


@app.get("/healthz")
def healthz():
    latest = db.latest_date(conn())
    return {"ok": True, "prices_as_of": latest}
