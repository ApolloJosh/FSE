"""The Film Stock Exchange web app.

Phase 2: accounts, Credits, portfolios, trading and leaderboards. The market
itself is still read-only in the sense that matters - player money never moves
a price. Prices come from the engine and nothing else.
"""

from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path

from typing import Optional

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from fsx.engine import explain
from fsx.site import esc, money, pct, sparkline, trend_class
from fsx.store import load

from . import auth, db, leaderboards, marking, views
from .trading import SETTLEMENT_DAYS, TradeError, buy, buy_slot, days_between, sell

ROOT = Path(__file__).resolve().parents[1]
BUNDLED_SNAPSHOT = ROOT / "data" / "people.json"
# The snapshot is data, not code, and it changes when a film comes out - which
# is nightly, not per release. Baked into the image it could only change on a
# redeploy, so the deployed market could never learn that anyone had worked.
# On a host with a volume it lives there, seeded from the image on first boot.
SNAPSHOT = Path(os.environ.get("FSX_SNAPSHOT", BUNDLED_SNAPSHOT))
DB_PATH = Path(os.environ.get("FSX_DB", ROOT / "data" / "market.db"))


def _seed_snapshot() -> None:
    if SNAPSHOT == BUNDLED_SNAPSHOT or SNAPSHOT.exists():
        return
    try:
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT.write_bytes(BUNDLED_SNAPSHOT.read_bytes())
    except OSError:
        pass        # fall back to whatever is in the image


_seed_snapshot()

IS_PRODUCTION = os.environ.get("FSX_ENV") == "production"
# "Up and comers" needs a ceiling, and it should be one a new player can reach.
SCOUT_CEILING = 30.0


def _session_secret() -> str:
    """A signed session cookie is only as good as its key.

    With a known fallback in production, anyone could mint a cookie and sign in
    as any player - so production refuses to boot without a real one rather
    than quietly running forgeable.
    """
    secret = os.environ.get("SESSION_SECRET", "")
    if secret:
        return secret
    if IS_PRODUCTION:
        raise RuntimeError(
            "SESSION_SECRET is not set. Sessions would be forgeable. "
            "Set it (fly secrets set SESSION_SECRET=$(openssl rand -hex 32)) "
            "and redeploy.")
    return "dev-only-not-a-secret"


app = FastAPI(title="Film Stock Exchange", docs_url=None, redoc_url=None)
app.add_middleware(
    SessionMiddleware,
    secret_key=_session_secret(),
    https_only=IS_PRODUCTION,
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
# FastAPI evaluates a route signature at import time, so `str | None` here is
# not deferred by `from __future__ import annotations` the way every other
# annotation in this file is - and on Python 3.9 it raises. Apple ships 3.9 as
# /usr/bin/python3, so this is the difference between the app starting on a Mac
# and not. Optional[] costs nothing and works everywhere.
@app.get("/", response_class=HTMLResponse)
def market(request: Request, msg: Optional[str] = None, ok: int = 0):
    user = current_user(request)
    prices = db.latest_prices(conn())
    held = {}
    if user:
        held = {p["slug"]: p["shares"] for p in db.positions(conn(), user["id"])}

    history = db.all_history(conn(), 365)
    rows = []
    for slug, row in prices.items():
        points = views.points_from(history.get(slug, []))
        earlier = [p for p in points if (points[-1].on - p.on).days >= 30] if points else []
        change = (points[-1].price / earlier[-1].price - 1) if earlier else None
        rows.append({
            "slug": slug, "name": row["name"], "is_director": row["is_director"],
            "price": db.credits(row["price"]), "tier": row["tier"], "change": change,
            "shares": held.get(slug, 0),
            "spark": sparkline(points) if len(points) > 1 else "",
        })
    rows.sort(key=lambda r: r["price"], reverse=True)
    return views.market_page(rows, user, views.flash(msg, bool(ok)),
                             movers=_movers_panel())


def _movers_panel() -> str:
    """Risers, fallers, and the ones still cheap enough to get in front of."""
    year = db.movers(conn(), 365)
    if not year:
        return ""

    def shape(row):
        return {"slug": row["slug"], "name": row["name"],
                "price": db.credits(row["price"]), "change": row["change"]}

    risers = [shape(r) for r in year[:5]]
    fallers = [shape(r) for r in reversed(year[-5:])]
    # Cheap and climbing. The whole design says scouting beats hoarding, and
    # this is the only place on the site that says where to scout - so it must
    # not just repeat the risers, which is what it did when it did not exclude
    # them: three of the five were already in the list above.
    shown = {r["slug"] for r in risers}
    coming = [shape(r) for r in year
              if r["slug"] not in shown
              and db.credits(r["price"]) <= SCOUT_CEILING and r["change"] > 0][:5]

    return views.movers_panel([
        ("This year's risers", "Biggest gain over twelve months", risers),
        ("Up and comers", f"Climbing, still under CR {SCOUT_CEILING:.0f}", coming),
        ("Off the boil", "Twelve months of decay or a bad year", fallers),
    ])


@app.get("/stock/{slug}", response_class=HTMLResponse)
def stock(request: Request, slug: str, msg: Optional[str] = None, ok: int = 0):
    user = current_user(request)
    prices = db.latest_prices(conn())
    row = prices.get(slug)
    if row is None:
        body = ('<h1>Not listed</h1><p class="muted">No stock with that name. '
                '<a href="../">Back to the market</a>.</p>')
        return HTMLResponse(views.chrome("Not listed — Film Stock Exchange",
                                         body, user, depth=1), status_code=404)

    # Everything the database has, not a 400-day window: the chart is the
    # career, and a career is the only thing that explains a price.
    points = views.points_from(db.price_history(conn(), slug, 4000))
    pos = db.position(conn(), user["id"], slug) if user else None
    settle = None
    if pos:
        settle = SETTLEMENT_DAYS - days_between(pos["last_buy_on"], date.today())

    events = []
    try:
        people, _ = load(SNAPSHOT)
        match = next((p for p in people if p.name == row["name"]), None)
        if match:
            scored = [(c, v) for c, v in explain(match) if abs(v) >= 0.5]
            events = [(f"e{i}", c, v) for i, (c, v) in enumerate(scored[:60])]
    except Exception:                                  # noqa: BLE001
        events = []

    from fsx.site import line_chart
    marks = [(ident, c.event_date, f"{c.title} — {c.kind} {v:+,.0f}")
             for ident, c, v in events]
    chart = line_chart(points, row["name"], marks) if len(points) > 1 else (
        '<p class="muted">Price history starts once the market has run overnight.</p>')

    reasons = "".join(
        f'<tr data-event="{ident}" data-date="{c.event_date.isoformat()}"'
        f' data-cp="{v:.1f}" tabindex="0">'
        f'<td class="date">{c.event_date.isoformat()}</td>'
        f'<td>{esc(c.title)}</td>'
        f'<td class="muted">{esc(c.role)}</td>'
        f'<td class="src">{esc(c.kind)}</td>'
        f'<td class="num {"up" if v > 0 else "down"}">{v:+,.0f}</td></tr>'
        for ident, c, v in events)

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
<p class="muted" id="reasons-help">Every scoring event behind today's price,
after decay. Click a row to find it on the chart; click a heading to sort.</p>
<table class="reasons" id="reasons"><thead><tr>
  <th class="date sortable" data-sort="date">Date</th>
  <th>Film or award</th><th>Role</th><th>Event</th>
  <th class="num sortable" data-sort="cp">CP</th>
</tr></thead><tbody>{reasons or
'<tr><td colspan="5" class="muted">No scoring events on file.</td></tr>'}</tbody></table>
<script>
// Two small things the panel was missing: which row is which mark on the
// chart, and any order other than the one the engine happened to return.
(function () {{
  var table = document.getElementById('reasons');
  if (!table) return;
  var svg = document.querySelector('.chart svg');
  var body = table.tBodies[0];

  function select(row) {{
    var on = !row.classList.contains('on');
    [].forEach.call(body.rows, function (r) {{ r.classList.remove('on'); }});
    if (svg) [].forEach.call(svg.querySelectorAll('.evt'), function (g) {{
      g.classList.remove('on');
    }});
    if (!on) return;
    row.classList.add('on');
    var mark = svg && svg.querySelector('.evt[data-event="' + row.dataset.event + '"]');
    if (mark) mark.classList.add('on');
  }}
  body.addEventListener('click', function (e) {{
    var row = e.target.closest('tr');
    if (row && row.dataset.event) select(row);
  }});
  body.addEventListener('keydown', function (e) {{
    if (e.key !== 'Enter' && e.key !== ' ') return;
    var row = e.target.closest('tr');
    if (row && row.dataset.event) {{ e.preventDefault(); select(row); }}
  }});

  var descending = {{}};
  [].forEach.call(table.querySelectorAll('.sortable'), function (th) {{
    th.addEventListener('click', function () {{
      var key = th.dataset.sort;
      // Default to the useful direction: newest first, biggest first.
      descending[key] = key in descending ? !descending[key] : true;
      var dir = descending[key] ? -1 : 1;
      var rows = [].slice.call(body.rows).filter(function (r) {{
        return r.dataset.event;
      }});
      rows.sort(function (a, b) {{
        var x = a.dataset[key], y = b.dataset[key];
        if (key === 'cp') {{ x = parseFloat(x); y = parseFloat(y); }}
        return x < y ? -dir : x > y ? dir : 0;
      }});
      rows.forEach(function (r) {{ body.appendChild(r); }});
      [].forEach.call(table.querySelectorAll('.sortable'), function (o) {{
        o.removeAttribute('aria-sort');
      }});
      th.setAttribute('aria-sort', descending[key] ? 'descending' : 'ascending');
    }});
  }});
}})();
</script>
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
def portfolio(request: Request, msg: Optional[str] = None, ok: int = 0):
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
    buttons = "".join(
        f'<a class="btn" href="/auth/{p}">Continue with {p.title()}</a>'
        for p in PROVIDERS)
    if auth.dev_login_allowed():
        buttons += ('<a class="btn ghost" href="/auth/dev">'
                    'Continue as a test player</a>')

    if not buttons:
        body = ("<h1>Sign-in is not configured</h1><p class='muted'>Set "
                "GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET or GITHUB_CLIENT_ID / "
                "GITHUB_CLIENT_SECRET and restart.</p>")
        return views.chrome("Sign in — Film Stock Exchange", body, None)

    note = ('<p class="muted">The test player is a local account with no OAuth '
            'app behind it. It is refused when FSX_ENV=production.</p>'
            if auth.dev_login_allowed() else
            '<p class="muted">We keep a display name and an avatar. '
            'Nothing else.</p>')
    body = f"""
<section class="hero"><h1>Sign in</h1>
<p class="lede">New players start with CR 50.00. No passwords — we never ask for
one and never store one.</p></section>
<div class="signin">{buttons}</div>
{note}"""
    return views.chrome("Sign in — Film Stock Exchange", body, None)


@app.get("/auth/dev")
def dev_signin(request: Request):
    """Sign in as a local test player. Off in production - see dev_login_allowed."""
    if not auth.dev_login_allowed():
        return RedirectResponse("/signin", status_code=303)
    user = db.upsert_user(conn(), "dev", "local", "Test Player", None,
                          auth.DEV_STARTING_CREDITS)
    auth.sign_in(request, user["id"])
    leaderboards.ensure_season_baseline(conn(), user["id"])
    return RedirectResponse("/", status_code=303)


def callback_url(request: Request, provider: str) -> str:
    """The redirect_uri handed to the provider, which must match what is
    registered there exactly - scheme included.

    Behind a TLS-terminating proxy the app is reached over plain HTTP, so
    url_for builds http://... and the provider refuses it: "The redirect_uri is
    not associated with this application". The Dockerfile tells uvicorn to
    trust the proxy's X-Forwarded-Proto, which fixes it properly; this is the
    belt to that pair of braces, because the failure is invisible until someone
    tries to sign in and the message does not say what is wrong.
    """
    url = request.url_for("callback", provider=provider)
    if IS_PRODUCTION and url.scheme != "https":
        url = url.replace(scheme="https")
    return str(url)


@app.get("/auth/{provider}")
async def authorize(request: Request, provider: str):
    if provider not in PROVIDERS:
        return RedirectResponse("/signin", status_code=303)
    client = getattr(auth.oauth, provider)
    return await client.authorize_redirect(request, callback_url(request, provider))


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


# ------------------------------------------------------------------- the job
# The nightly reprice has to be triggered from outside. A scheduled machine
# cannot do it: SQLite lives on a volume, a Fly volume attaches to one machine
# at a time, and the web app is holding it. And an in-process timer cannot do
# it either, because the machine suspends when nobody is browsing.
#
# So the web app runs the job itself, woken by an HTTP request - which is what
# auto_start_machines is for. Marking is already idempotent, so a retry, a
# double fire or a nervous second click all do nothing.
JOB_TOKEN = os.environ.get("FSX_JOB_TOKEN", "")


@app.post("/jobs/mark")
def run_mark(request: Request, dividends: int = 0):
    import secrets as _secrets

    if not JOB_TOKEN:
        raise HTTPException(status_code=404, detail="No job token configured.")
    header = request.headers.get("authorization", "")
    offered = header[7:] if header.lower().startswith("bearer ") else ""
    if not _secrets.compare_digest(offered, JOB_TOKEN):
        raise HTTPException(status_code=403, detail="Bad job token.")

    from . import marking
    report = marking.run(conn(), SNAPSHOT, date.today(), with_dividends=bool(dividends))
    return {"ok": True, "on": date.today().isoformat(), "skipped": report.skipped,
            "stocks": report.stocks, "positions": report.positions,
            "gains": report.gains, "losses": report.losses}


@app.post("/jobs/snapshot")
async def put_snapshot(request: Request):
    """Replace the snapshot the market prices from.

    The nightly refresh runs where the API keys and the fetch cache are, and
    posts the result here. Written to a temporary file and renamed, so a
    connection that drops halfway cannot leave the market reading half a file.
    """
    import json
    import secrets as _secrets
    import tempfile

    if not JOB_TOKEN:
        raise HTTPException(status_code=404, detail="No job token configured.")
    header = request.headers.get("authorization", "")
    offered = header[7:] if header.lower().startswith("bearer ") else ""
    if not _secrets.compare_digest(offered, JOB_TOKEN):
        raise HTTPException(status_code=403, detail="Bad job token.")

    body = await request.body()
    try:
        payload = json.loads(body)
        people = payload["people"]
        if not isinstance(people, list) or not people:
            raise ValueError("no people")
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400,
                            detail=f"Not a snapshot: {exc}") from exc

    # A snapshot that has lost most of the roster is a failed fetch, not news.
    current = 0
    try:
        current = len(json.loads(SNAPSHOT.read_text())["people"])
    except Exception:                                  # noqa: BLE001
        pass
    if current and len(people) < current * 0.9:
        raise HTTPException(
            status_code=409,
            detail=f"Refused: {len(people)} people replacing {current}. "
                   "That is a failed fetch, not a smaller roster.")

    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "wb", dir=SNAPSHOT.parent, delete=False, suffix=".tmp")
    try:
        handle.write(body)
        handle.close()
        os.replace(handle.name, SNAPSHOT)
    except OSError as exc:
        os.unlink(handle.name)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {"ok": True, "people": len(people), "was": current}
