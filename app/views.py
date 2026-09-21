"""HTML rendering. Reuses the Phase 1 visual system so the public market and the
signed-in market are visibly the same product."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime

from fsx.history import Point
from fsx.site import (FONT_LINK, STYLE, THEME_BOOT, THEME_BUTTON, esc, key_block,
                      line_chart, money, pct, shell as static_shell, sparkline,
                      trend_class)

from . import db, images

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
.filter { display: flex; gap: 12px; align-items: center; flex-wrap: wrap;
  margin: 0 0 14px; }
.filter input, .filter select { font: inherit; font-size: .92rem; padding: 7px 10px;
  border: 1px solid var(--rule); background: var(--surface); color: var(--ink);
  border-radius: 2px; }
.filter input { width: 15rem; }
.filter .count { color: var(--muted); font-size: .88rem; margin-left: auto; }
tr.hidden { display: none; }
.boards-grid { display: grid; gap: 22px; margin: 26px 0 34px;
  grid-template-columns: repeat(auto-fit, minmax(255px, 1fr)); }
.board { border: 1px solid var(--rule); padding: 16px 18px; background: var(--raised); }
.board h3 { margin: 0 0 2px; font-size: 1rem; }
.board p { margin: 0 0 10px; font-size: .8rem; }
.board ol { margin: 0; padding: 0; list-style: none; counter-reset: rank; }
.board li { display: grid; grid-template-columns: 1fr auto auto; gap: 10px;
  align-items: baseline; padding: 5px 0; border-top: 1px solid var(--rule);
  font-size: .92rem; }
.board li:first-child { border-top: 0; }
.board li a { color: var(--ink); text-decoration: none; }
.board li a:hover { text-decoration: underline; }
.board .mono { font-family: var(--mono); color: var(--muted); font-size: .86rem; }
/* A game form is not the trade panel: it stacks, and its labels are not the
   little uppercase field captions the trade panel uses. Without these the
   options rendered as grey small-caps in a narrow column with the button
   floated beside them. */
.trade form.game { display: block; }
.trade form.game .choice { font-size: .95rem; text-transform: none;
  letter-spacing: 0; color: var(--ink); margin: 0; display: flex; }

/* Choices were stacked labels with a margin, which reads as a list of things
   rather than a set of options to pick between. */
.choices { display: grid; gap: 0; width: 100%; margin: 14px 0 18px;
  border: 1px solid var(--rule); border-radius: 2px; overflow: hidden; }
.choices.two { grid-template-columns: repeat(auto-fit, minmax(290px, 1fr)); }
.choice { display: flex; align-items: center; gap: 10px; padding: 9px 13px;
  border-top: 1px solid var(--rule); cursor: pointer; font-size: .95rem; }
.choices > .choice:first-child { border-top: 0; }
.choices.two > .choice:nth-child(-n+3) { border-top: 0; }
.choice:hover { background: var(--raised); }
.choice input { margin: 0; flex: none; }
.choice span:not(.price) { flex: 1; }
.choice .price { font-family: var(--mono); font-size: .85rem; color: var(--muted); }
.choice.spent { opacity: .38; cursor: not-allowed; }
.choice:has(input:checked) { background: var(--raised); font-weight: 600; }

.budget { display: flex; gap: 26px; padding: 12px 14px; background: var(--raised);
  border: 1px solid var(--rule); font-family: var(--mono); }
.budget small { display: block; font-family: var(--sans); font-size: .68rem;
  text-transform: uppercase; letter-spacing: .07em; color: var(--muted); }
.budget strong { font-size: 1.15rem; font-weight: 500; }

.rungs { margin: 0 0 16px; padding: 0; list-style: none; }
.rungs li { padding: 5px 0; border-top: 1px solid var(--rule); }
.rungs li:first-child { border-top: 0; }
.rungs .num { display: inline-block; width: 1.6rem; color: var(--muted);
  font-family: var(--mono); font-size: .85rem; }

.filmtitle { margin: 0 0 6px; font-size: 1.05rem; }
.billing { margin: 0 0 4px; padding: 0; list-style: none; display: flex;
  flex-wrap: wrap; gap: 6px 10px; }
.billing li { font-size: .92rem; color: var(--ink-2); }
.billing li + li::before { content: "· "; color: var(--muted); }
.billing .gap { color: var(--ink); font-weight: 600; border-bottom: 2px solid var(--ink);
  padding-bottom: 1px; }

.chain { margin: 0 0 18px; padding: 0; list-style: none; }
.chain .who { font-size: 1.02rem; padding: 3px 0; }
.chain .who.start, .chain .who.target { font-weight: 600; }
.chain .link { margin-left: .45rem; padding: 2px 0 2px 14px;
  border-left: 2px solid var(--rule); font-size: .86rem; color: var(--muted); }
.chain .link.pending { border-left-style: dashed; }
.chain .tick { color: var(--up); font-weight: 600; margin-right: 6px; }
.chain .link .tick { margin-left: -2px; }

.reveal { margin: 0 0 20px; }
.reveal .rank { width: 2rem; color: var(--muted); font-family: var(--mono); }
.reveal .total td { border-top: 2px solid var(--rule); font-weight: 600; }
.reset { display: flex; gap: 12px; align-items: center; margin: 26px 0 0;
  padding-top: 18px; border-top: 1px dashed var(--rule); }
/* ---------------------------------------------------------------- pictures
   The index covers 96% of credited films and all but two of the roster, so
   the missing ones are a designed state rather than a broken image: the same
   card, the same size, initials instead of a face and a blank frame instead
   of a poster. A page of them still lines up. */
.face { display: block; object-fit: cover; border: 1px solid var(--rule-hard);
  background: var(--raised); }
.face.none { display: flex; align-items: center; justify-content: center;
  font-family: var(--poster); letter-spacing: .06em; color: var(--ink-2);
  background: var(--raised); }
.poster { display: block; object-fit: cover; border: 1px solid var(--rule);
  background: var(--raised); }
.poster.none { display: block; border: 1px dashed var(--rule); }

.stockhead { display: flex; gap: 20px; align-items: flex-start;
  padding: 6px 0 4px; }
.stockhead .face { width: 120px; height: 180px; flex: none; }
.stockhead-text { min-width: 0; flex: 1; }

.sheet .face { width: 100%; height: 190px; margin: 6px 0 10px; }
.sheet .face.none { font-size: 1.6rem; }

.quote-card li a { display: flex; align-items: center; gap: 9px; }
.quote-card .face { width: 30px; height: 30px; border-radius: 50%;
  flex: none; font-size: .62rem; }

/* The flex belongs on a wrapper, not the cell: a td with display:flex leaves
   table layout and takes the row's borders with it. */
.reasons .filmcell { display: flex; align-items: center; gap: 10px; }
.reasons .poster, .reasons .poster.none { width: 32px; height: 48px; flex: none; }

.creditblock .tmdb { font-size: .72rem; color: var(--ink-2); }

@media (max-width: 620px) {
  .stockhead { gap: 14px; }
  .stockhead .face { width: 84px; height: 126px; }
  .sheet .face { height: 150px; }
  .reasons .poster, .reasons .poster.none { width: 26px; height: 39px; }
}

/* ------------------------------------------------------------- name picker */
.picker { position: relative; }
.picker input { width: min(22rem, 100%); }
.picker-list { position: absolute; z-index: 30; left: 0; right: 0;
  max-width: min(22rem, 100%); margin: 2px 0 0; padding: 0; list-style: none;
  max-height: 46vh; overflow-y: auto; background: var(--raised);
  border: 1px solid var(--rule-hard);
  box-shadow: 0 10px 24px rgba(0, 0, 0, .18); }
.picker-list li + li { border-top: 1px solid var(--rule); }
.picker-list button { display: block; width: 100%; min-height: 46px;
  padding: 11px 14px; text-align: left; font: inherit; font-size: 1rem;
  color: var(--ink); background: none; border: 0; cursor: pointer; }
.picker-list button:hover, .picker-list button:focus {
  background: var(--rule-hard); color: var(--surface); outline: none; }

/* -------------------------------------------------------------- the ladder
   Drawn as a ladder rather than a growing list. The top rung is the one film
   and the big payout; each step down hands you another film and takes money
   off. A list that grew downwards while the prize fell was the whole reason
   nobody could tell which way was up. */
.ladder { margin: 0 0 18px; padding: 0; list-style: none;
  border: 2px solid var(--rule-hard); background: var(--raised); }
.ladder .rung { display: flex; align-items: center; gap: 12px;
  padding: 10px 14px; border-bottom: 1px solid var(--rule); }
.ladder .rung:last-child { border-bottom: 0; }
.ladder .level { font-family: var(--poster); font-size: .95rem; width: 1.5rem;
  text-align: center; color: var(--muted); flex: none; }
.ladder .clue { flex: 1; min-width: 0; }
.ladder .pays { font-family: var(--mono); font-size: .85rem; color: var(--muted);
  flex: none; }
.ladder .rung.here { background: var(--rule-hard); color: var(--surface); }
.ladder .rung.here .level, .ladder .rung.here .pays,
.ladder .rung.here .muted { color: var(--surface); opacity: .85; }
.ladder .rung.ahead { opacity: .5; }
.ladder .rung.passed .clue { text-decoration: none; }
.choice.spent { opacity: .45; text-decoration: line-through; }
.trade fieldset { border: 0; margin: 0; padding: 0; }
.trade fieldset legend { font-family: var(--poster); font-size: .72rem;
  letter-spacing: .18em; text-transform: uppercase; color: var(--ink-2);
  padding: 0; margin: 0 0 6px; }

/* .trade input is 7rem wide for the shares box, which also made every radio
   and checkbox 7rem wide - a hundred pixels of nothing between the dot and
   the name it belongs to. */
.choice input[type="radio"], .choice input[type="checkbox"] { width: auto; }
"""


def chrome(title: str, body: str, user: sqlite3.Row | None, depth: int = 0) -> str:
    """The shell, with an auth bar the static Phase 1 pages do not have."""
    up = "../" * depth
    # An empty href is the current page, not the site root, so on /market and
    # /play the wordmark was a link that reloaded whatever you were already
    # looking at. "./" resolves to the directory, which is home from any depth.
    home = up or "./"
    market = f'<a href="{up}market">Market</a>'
    if user:
        right = (f'<span class="balance">CR {money(db.credits(user["credits"]))}</span>'
                 f'{market}'
                 f'<a href="{up}play">Play</a>'
                 f'<a href="{up}portfolio">Portfolio</a>'
                 f'<a href="{up}leaderboards">Leaderboards</a>'
                 f'<a href="{up}about">How prices work</a>'
                 f'<a href="{up}signout">Sign out</a>'
                 f'{THEME_BUTTON}')
    else:
        right = (f'{market}'
                 f'<a href="{up}leaderboards">Leaderboards</a>'
                 f'<a href="{up}about">How prices work</a>'
                 f'<a href="{up}signin">Sign in</a>'
                 f'{THEME_BUTTON}')

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title><link rel="stylesheet" href="{up}static/style.css">
{FONT_LINK}{THEME_BOOT}
</head><body>
<header class="site">
  <a class="wordmark" href="{home}">Film Stock Exchange</a>
  <nav class="authbar">{right}</nav>
</header>
<main>{body}
{key_block()}</main>
<footer>
  <p>Prices are fictional and move only on released work and juried awards.
     No real money, no cash-out, nothing to win but bragging rights.</p>
</footer>
<script src="{up}static/chart.js" defer></script>
<script src="{up}static/picker.js" defer></script>
</body></html>"""


def flash(message: str | None, ok: bool = False) -> str:
    if not message:
        return ""
    return f'<p class="flash{" ok" if ok else ""}">{esc(message)}</p>'


def points_from(rows: list[sqlite3.Row]) -> list[Point]:
    return [Point(datetime.strptime(r["on_date"], "%Y-%m-%d").date(),
                  db.credits(r["price"])) for r in rows]


def movers_panel(boards: list[tuple[str, str, list[dict]]]) -> str:
    """Three short lists above the table, set like the review quotes on a
    one-sheet. 312 rows sorted by price answers "who is expensive", which is
    the least interesting question the data can answer."""
    cards = ""
    for title, blurb, entries in boards:
        if not entries:
            continue
        items = "".join(f"""<li>
  <a href="stock/{esc(e['slug'])}">
    {headshot(e['name'], e.get('tmdb_id'))}{esc(e['name'])}</a>
  <span class="mono">{money(e['price'])}</span>
  <span class="{trend_class(e['change'])}">{pct(e['change'])}</span>
</li>""" for e in entries)
        cards += (f'<section class="quote-card"><h3>{esc(title)}</h3>'
                  f'<p class="note">{esc(blurb)}</p><ol>{items}</ol></section>')
    return f'<div class="quotes">{cards}</div>' if cards else ""




def name_picker(field: str, label: str, names: list[str],
                placeholder: str = "Type a few letters") -> str:
    """A text field with a list of names under it.

    This was a <datalist>, which is a dropdown on a desktop and very nearly
    nothing on a phone - so on a phone the game became "spell Mahershala Ali
    from memory". The list is plain elements at thumb size; with the script
    off, the input still takes a typed name, which is what the server checks.
    """
    import json as _json

    return f"""<div class="picker" data-picker>
  <label for="{esc(field)}">{label}</label>
  <input id="{esc(field)}" name="{esc(field)}" type="text" required
         autocomplete="off" autocapitalize="words" autocorrect="off"
         spellcheck="false" enterkeyhint="done"
         placeholder="{esc(placeholder)}" role="combobox"
         aria-autocomplete="list" aria-expanded="false"
         aria-controls="{esc(field)}-list">
  <ul class="picker-list" id="{esc(field)}-list" role="listbox" hidden></ul>
  <script type="application/json" class="picker-names">{_json.dumps(names)}</script>
</div>"""


def headshot(name: str, tmdb_id=None, size: str = "") -> str:
    """A face, or the space where one would be.

    Every image here is someone else's: the index is TMDB's, the pictures are
    served from TMDB, and neither is guaranteed to have one. So the absence is
    designed rather than patched - initials on the same warm card, at the same
    size, so a row with a face and a row without are the same shape.
    """
    initials = "".join(part[0] for part in name.split()[:2]).upper()
    src = images.face(name, tmdb_id, size or images.FACE_SIZE)
    if not src:
        return f'<span class="face none" aria-hidden="true">{esc(initials)}</span>'
    # The pictures are TMDB's and served from TMDB, so they can be missing,
    # moved or blocked on the player's network. On error the img becomes the
    # same initials card the index-miss case renders, rather than a broken
    # glyph in a frame.
    fallback = f'<span class="face none" aria-hidden="true">{esc(initials)}</span>'
    return (f'<img class="face" src="{esc(src)}" alt="" loading="lazy" '
            f'decoding="async" width="80" height="120" '
            f'data-fallback="{esc(fallback)}" '
            f'onerror="this.outerHTML=this.dataset.fallback">')


def poster_thumb(title: str, year, size: str = "") -> str:
    src = images.poster(title, year, size or images.POSTER_TINY)
    if not src:
        return '<span class="poster none" aria-hidden="true"></span>'
    fallback = '<span class="poster none" aria-hidden="true"></span>'
    return (f'<img class="poster" src="{esc(src)}" alt="" loading="lazy" '
            f'decoding="async" width="46" height="69" '
            f'data-fallback="{esc(fallback)}" '
            f'onerror="this.outerHTML=this.dataset.fallback">')


def masthead(listed: int, market_value: float, as_of: str) -> str:
    """The top of a one-sheet: over-line, title, rule, billing."""
    return f"""<section class="masthead">
  <p class="over">Prices derived from released work alone</p>
  <h1>The Film Stock Exchange</h1>
  <hr class="rule">
  <p class="billing">
    <span><b>{listed}</b> listed</span>
    <span><b>CR {money(market_value)}</b> on the board</span>
    <span>Trading as of <b>{esc(as_of)}</b></span>
  </p>
</section>"""


def billboard(rows: list[dict]) -> str:
    """Top billing. The most expensive names are the one thing a poster would
    set largest, so they are set largest."""
    cards = ""
    for slot, row in zip(("Starring", "And", "With"), rows):
        cards += f"""<a class="sheet" href="stock/{esc(row['slug'])}">
  <span class="slot">{slot}</span>
  {headshot(row['name'], row.get('tmdb_id'))}
  <div class="who">{esc(row['name'])}</div>
  <div class="figure"><b>{money(row['price'])}</b>
    <span class="{trend_class(row['change'])}">{pct(row['change'])}</span>
    <span class="pill">{esc(row['tier'])}</span></div>
  {row['spark']}
</a>"""
    return ('<section class="starring"><p class="over">Top billing</p>'
            f'<div class="billboard">{cards}</div></section>')


def landing_page(top: list[dict], movers: str, games: dict, user,
                 listed: int, market_value: float, as_of: str) -> str:
    """The front door. The board is 312 rows of detail, which is the wrong
    thing to meet first - this says what the place is, shows today's games, and
    shows enough of the market to make you want the rest of it."""
    steps = [
        ("Earn", "Play the day's puzzles. They pay Credits, and they are built "
                 "from the same film data that prices the market."),
        ("Back somebody", "Buy shares in an actor or a director. Prices come "
                          "from released work — awards, box office, reviews — "
                          "and nothing else. No hype, no votes."),
        ("Hold", "A gain counts for more the longer you were holding when it "
                 "happened. Get there before the rest of the board and the "
                 "same Oscar is worth more to you."),
    ]
    how = "".join(f"""<li><span class="step">{i}</span>
  <div><h3>{esc(title)}</h3><p>{esc(text)}</p></div></li>"""
                  for i, (title, text) in enumerate(steps, 1))

    cards = ""
    for game, (title, blurb) in games["titles"].items():
        row = games["rows"].get(game)
        state = ('<span class="up">Played</span>' if row and row["done"]
                 else '<span class="muted">Open</span>' if user
                 else '<span class="muted">Sign in to play</span>')
        cards += (f'<li><a href="play/{esc(game)}"><b>{esc(title)}</b>'
                  f'<span class="muted">{esc(blurb)}</span></a>{state}</li>')

    earned = (f'<p class="muted">Earned today: <b>CR '
              f'{money(db.credits(games["earned"]))}</b>.</p>' if user else "")

    return chrome("Film Stock Exchange",
                  masthead(listed, market_value, as_of) + f"""
<section class="intro">
  <p class="lede">A market in the people who make films. Every price is derived
  from work that has actually come out — awards, box office and how the reviews
  landed — run through one formula, and it moves when the work does.</p>
  <ol class="how">{how}</ol>
</section>

<h2>Today's games</h2>
{earned}
<ul class="gamelist">{cards}</ul>
<p class="more"><a href="play">All of today's games →</a></p>

<h2>The market today</h2>
""" + billboard(top) + movers + """
<p class="more"><a href="market">See the whole board →</a></p>
""", user)


def credit_block(rows: list[dict], tiers: dict[str, int]) -> str:
    """The dense little type at the foot of a poster, which is where a poster
    puts what is true but not the point."""
    order = ["Legend", "A-List", "Established", "Recognized", "Working", "Debut"]
    listed = " · ".join(f"<b>{tiers[t]}</b> {esc(t.lower())}"
                        for t in order if tiers.get(t))
    directors = sum(1 for r in rows if r["is_director"])
    return f"""<section class="creditblock">
  <div>{listed}</div>
  <div><b>{len(rows) - directors}</b> in front of the camera ·
       <b>{directors}</b> behind it</div>
  <div>Film and credit data TMDB · Reviews OMDb and Wikidata ·
       Awards Wikidata · Budgets and grosses Wikipedia</div>
  <div class="tmdb">Posters and photographs supplied by TMDB. This product uses
       the TMDB API but is not endorsed or certified by TMDB.</div>
</section>"""


def market_page(rows: list[dict], user: sqlite3.Row | None, note: str = "",
                movers: str = "", as_of: str = "") -> str:
    body_rows = "".join(f"""<tr data-name="{esc(r['name'].lower())}" data-tier="{esc(r['tier'])}">
  <td class="rank">{i}</td>
  <td class="name"><a href="stock/{esc(r['slug'])}">{esc(r['name'])}</a>
      {'<span class="badge">dir</span>' if r['is_director'] else ''}</td>
  <td class="num price">{money(r['price'])}</td>
  <td class="num {trend_class(r['change'])}">{pct(r['change'])}</td>
  <td class="tier"><span class="pill">{esc(r['tier'])}</span></td>
  <td class="num">{'<strong>' + str(r['shares']) + '</strong>' if r['shares'] else '<span class="muted">—</span>'}</td>
  <td class="sparkcell">{r['spark']}</td>
</tr>""" for i, r in enumerate(rows, 1))

    tiers: dict[str, int] = {}
    for r in rows:
        tiers[r["tier"]] = tiers.get(r["tier"], 0) + 1
    options = "".join(f'<option value="{esc(t)}">{esc(t)}</option>' for t in tiers)

    board = f"""
<h2>The whole board</h2>
<div class="filter">
  <input id="q" type="search" placeholder="Find a name" autocomplete="off"
         aria-label="Filter by name">
  <select id="tier" aria-label="Filter by tier">
    <option value="">Every tier</option>{options}
  </select>
  <span class="count" id="count">{len(rows)} listed</span>
</div>
<div class="tablewrap"><table class="market">
  <thead><tr><th class="rank">#</th><th>Name</th><th class="num">Price</th>
  <th class="num">30 days</th><th>Tier</th><th class="num">Held</th>
  <th>History</th></tr></thead>
  <tbody id="rows">{body_rows}</tbody>
</table></div>
<p class="empty" id="none" hidden>Nobody by that name is listed.</p>"""

    script = """
<script>
// 312 rows and no way through them is a list, not a market. Filtering client
// side keeps it instant and keeps the page cacheable.
(function () {
  var q = document.getElementById('q'), tier = document.getElementById('tier');
  var rows = [].slice.call(document.querySelectorAll('#rows tr'));
  var count = document.getElementById('count'), none = document.getElementById('none');
  function apply() {
    var needle = q.value.trim().toLowerCase(), want = tier.value, shown = 0;
    rows.forEach(function (row) {
      var name = row.getAttribute('data-name') || '';
      var ok = (!needle || name.indexOf(needle) > -1)
            && (!want || row.getAttribute('data-tier') === want);
      row.classList.toggle('hidden', !ok);
      if (ok) shown++;
    });
    count.textContent = shown + ' listed';
    none.hidden = shown > 0;
  }
  q.addEventListener('input', apply);
  tier.addEventListener('change', apply);
})();
</script>"""

    return chrome("The market — Film Stock Exchange",
                  masthead(len(rows), sum(r["price"] for r in rows), as_of)
                  + note + billboard(rows[:3]) + movers + board
                  + credit_block(rows, tiers) + script, user)


def trade_panel(slug: str, price: int, user: sqlite3.Row | None,
                pos: sqlite3.Row | None, csrf: str, settle_days: int | None) -> str:
    if user is None:
        # Absolute: this panel renders on /stock/<slug>, where a relative
        # "signin" resolves to /stock/signin. That was the 404 on the one page
        # a signed-out visitor is most likely to click from.
        return ('<div class="trade"><p class="muted">'
                '<a href="/signin">Sign in</a> to trade. New players start with '
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
</div>
"""
