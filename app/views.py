"""HTML rendering. Reuses the Phase 1 visual system so the public market and the
signed-in market are visibly the same product."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime

from fsx.history import Point
from fsx.site import (STYLE, esc, line_chart, money, pct, shell as static_shell,
                      sparkline, trend_class)

from . import db

APP_STYLE = STYLE + """
.authbar { display: flex; align-items: center; gap: 14px; font-size: .9rem; }
.authbar a { color: var(--ink-2); text-decoration: none; }
.authbar a:hover { color: var(--ink); }
.balance { font-family: var(--mono); color: var(--ink); }
.btn { font: inherit; font-size: .92rem; padding: 7px 14px; border: 1px solid var(--ink);
  background: var(--ink); color: var(--surface); cursor: pointer; border-radius: 2px; }
.btn.ghost { background: transparent; color: var(--ink); }
.btn:disabled { opacity: .45; cursor: not-allowed; }
.trade { border: 1px solid var(--rule); padding: 18px; background: var(--raised);
  margin: 8px 0 24px; }
.trade form { display: flex; gap: 10px; align-items: flex-end; flex-wrap: wrap; }
.trade label { font-size: .76rem; text-transform: uppercase; letter-spacing: .07em;
  color: var(--muted); display: block; margin-bottom: 4px; }
.trade input { font: inherit; font-family: var(--mono); padding: 6px 8px; width: 7rem;
  border: 1px solid var(--rule); background: var(--surface); color: var(--ink); }
.flash { padding: 10px 14px; border-left: 3px solid var(--down); background: var(--raised);
  margin: 12px 0; }
.flash.ok { border-left-color: var(--up); }
.holding { display: flex; gap: 22px; flex-wrap: wrap; font-family: var(--mono);
  font-size: .95rem; padding: 10px 0 0; }
.holding span small { font-family: var(--sans); color: var(--muted); display: block;
  font-size: .7rem; text-transform: uppercase; letter-spacing: .07em; }
.boards { display: flex; gap: 18px; margin: 0 0 18px; flex-wrap: wrap; }
.boards a { text-decoration: none; color: var(--muted); font-size: .92rem;
  padding-bottom: 3px; border-bottom: 2px solid transparent; }
.boards a.on { color: var(--ink); border-bottom-color: var(--ink); }
.signin { display: flex; gap: 12px; margin: 22px 0; }
.empty { color: var(--muted); padding: 28px 0; }
"""


def chrome(title: str, body: str, user: sqlite3.Row | None, depth: int = 0) -> str:
    """The shell, with an auth bar the static Phase 1 pages do not have."""
    up = "../" * depth
    if user:
        right = (f'<span class="balance">CR {money(db.credits(user["credits"]))}</span>'
                 f'<a href="{up}portfolio">Portfolio</a>'
                 f'<a href="{up}leaderboards">Leaderboards</a>'
                 f'<a href="{up}about">How prices work</a>'
                 f'<a href="{up}signout">Sign out</a>')
    else:
        right = (f'<a href="{up}leaderboards">Leaderboards</a>'
                 f'<a href="{up}about">How prices work</a>'
                 f'<a href="{up}signin">Sign in</a>')

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title><link rel="stylesheet" href="{up}static/style.css">
</head><body>
<header class="site">
  <a class="wordmark" href="{up}">Film Stock Exchange</a>
  <nav class="authbar">{right}</nav>
</header>
<main>{body}</main>
<footer>
  <p>Prices are fictional and move only on released work and juried awards.
     No real money, no cash-out, nothing to win but bragging rights.</p>
</footer>
<script src="{up}static/chart.js" defer></script>
</body></html>"""


def flash(message: str | None, ok: bool = False) -> str:
    if not message:
        return ""
    return f'<p class="flash{" ok" if ok else ""}">{esc(message)}</p>'


def points_from(rows: list[sqlite3.Row]) -> list[Point]:
    return [Point(datetime.strptime(r["on_date"], "%Y-%m-%d").date(),
                  db.credits(r["price"])) for r in rows]


def market_page(rows: list[dict], user: sqlite3.Row | None, note: str = "") -> str:
    body_rows = "".join(f"""<tr>
  <td class="rank">{i}</td>
  <td class="name"><a href="stock/{esc(r['slug'])}">{esc(r['name'])}</a>
      {'<span class="badge">dir</span>' if r['is_director'] else ''}</td>
  <td class="num price">{money(r['price'])}</td>
  <td class="num {trend_class(r['change'])}">{pct(r['change'])}</td>
  <td class="tier"><span class="pill">{esc(r['tier'])}</span></td>
  <td class="num">{'<strong>' + str(r['shares']) + '</strong>' if r['shares'] else '<span class="muted">—</span>'}</td>
  <td class="sparkcell">{r['spark']}</td>
</tr>""" for i, r in enumerate(rows, 1))

    return chrome("The market — Film Stock Exchange", f"""
<section class="hero">
  <h1>The market</h1>
  <p class="lede">Every price is derived from real results — awards, box office
  and critical reception — and nothing else. Buy in before the rest of the
  market notices.</p>
</section>
{note}
<table class="market">
  <thead><tr><th class="rank">#</th><th>Name</th><th class="num">Price</th>
  <th class="num">30 days</th><th>Tier</th><th class="num">Held</th>
  <th>History</th></tr></thead>
  <tbody>{body_rows}</tbody>
</table>""", user)


def trade_panel(slug: str, price: int, user: sqlite3.Row | None,
                pos: sqlite3.Row | None, csrf: str, settle_days: int | None) -> str:
    if user is None:
        return ('<div class="trade"><p class="muted">'
                '<a href="signin">Sign in</a> to trade. New players start with '
                'CR 50.00.</p></div>')

    affordable = int(db.credits(user["credits"]) / (db.credits(price) * 1.015)) if price else 0
    held = ""
    if pos:
        gain = pos["held_value"] / pos["entry_price"] - 1 if pos["entry_price"] else 0
        held = f"""<div class="holding">
  <span><small>Shares</small>{pos['shares']}</span>
  <span><small>Entry</small>{money(db.credits(pos['entry_price']))}</span>
  <span><small>Your value</small>{money(db.credits(pos['held_value']))}</span>
  <span class="{trend_class(gain)}"><small>Gain</small>{pct(gain)}</span>
</div>"""

    sell_note = ""
    can_sell = bool(pos)
    if pos and settle_days and settle_days > 0:
        can_sell = False
        sell_note = (f'<p class="muted">Settlement: {settle_days} more '
                     f'{"day" if settle_days == 1 else "days"} before this can be sold.</p>')

    return f"""<div class="trade">
<form method="post" action="trade">
  <input type="hidden" name="csrf" value="{esc(csrf)}">
  <input type="hidden" name="slug" value="{esc(slug)}">
  <div><label for="shares">Shares</label>
    <input id="shares" name="shares" type="number" min="1" step="1" value="1" required></div>
  <button class="btn" name="side" value="buy">Buy</button>
  <button class="btn ghost" name="side" value="sell" {'' if can_sell else 'disabled'}>Sell</button>
  <span class="muted">You can afford {affordable:,} at {money(db.credits(price))} plus the 1.5% fee.</span>
</form>
{held}{sell_note}
</div>"""
