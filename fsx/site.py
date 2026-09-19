"""Static site generator for the read-only market.

Phase 1 is a public price list with a chart and an explanation, and nothing
else - no accounts, no trading. That makes a static build the right shape: no
server, no database, free hosting, and a nightly job that regenerates the whole
thing from a snapshot in seconds.
"""

from __future__ import annotations

import html
import json
import re
from datetime import date
from pathlib import Path

from . import constants as K
from .engine import explain, value_person
from .history import Point, change, series
from .models import Person

CHART_W, CHART_H = 720, 250
PAD_L, PAD_R, PAD_T, PAD_B = 52, 18, 16, 28


def slug(name: str) -> str:
    out = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return out or "unknown"


def esc(text: object) -> str:
    return html.escape(str(text), quote=True)


def money(value: float) -> str:
    return f"{value:,.2f}"


def pct(value: float | None) -> str:
    return "—" if value is None else f"{value:+.1%}"


def trend_class(value: float | None) -> str:
    if value is None or abs(value) < 0.0005:
        return "flat"
    return "up" if value > 0 else "down"


# ----------------------------------------------------------------------- charts
def _scale(points: list[Point]):
    prices = [p.price for p in points]
    lo, hi = min(prices), max(prices)
    if hi - lo < 1e-9:
        lo, hi = lo * 0.95, hi * 1.05 or 1.0
    span = hi - lo
    lo, hi = lo - span * 0.08, hi + span * 0.08
    days = (points[-1].on - points[0].on).days or 1

    def x(p: Point) -> float:
        return PAD_L + (p.on - points[0].on).days / days * (CHART_W - PAD_L - PAD_R)

    def y(price: float) -> float:
        return PAD_T + (hi - price) / (hi - lo) * (CHART_H - PAD_T - PAD_B)

    return x, y, lo, hi


def line_chart(points: list[Point], label: str) -> str:
    """One series, so no legend: the heading names it. Recessive grid, 2px line,
    a marker and a direct label on the last point only."""
    if len(points) < 2:
        return '<p class="muted">Not enough history to chart.</p>'

    x, y, lo, hi = _scale(points)
    path = " ".join(f"{'M' if i == 0 else 'L'}{x(p):.1f},{y(p.price):.1f}"
                    for i, p in enumerate(points))

    ticks = [lo + (hi - lo) * i / 4 for i in range(5)]
    grid = "".join(
        f'<line class="grid" x1="{PAD_L}" x2="{CHART_W - PAD_R}" '
        f'y1="{y(t):.1f}" y2="{y(t):.1f}"/>'
        f'<text class="axis" x="{PAD_L - 8}" y="{y(t) + 4:.1f}" text-anchor="end">'
        f'{t:,.0f}</text>' for t in ticks)

    years, seen = [], set()
    for p in points:
        if p.on.year not in seen:
            seen.add(p.on.year)
            years.append(p)
    xlabels = "".join(
        f'<text class="axis" x="{x(p):.1f}" y="{CHART_H - 8}" text-anchor="middle">'
        f'{p.on.year}</text>' for p in years[1:])

    last = points[-1]
    data = json.dumps([[p.on.isoformat(), round(p.price, 2)] for p in points])

    return f"""<figure class="chart">
<svg viewBox="0 0 {CHART_W} {CHART_H}" role="img"
     aria-label="{esc(label)} price history, {points[0].on.year} to {last.on.year}"
     data-points='{esc(data)}' data-x0="{PAD_L}" data-x1="{CHART_W - PAD_R}">
  {grid}{xlabels}
  <path class="series" d="{path}"/>
  <circle class="dot" cx="{x(last):.1f}" cy="{y(last.price):.1f}" r="4.5"/>
  <text class="endlabel" x="{x(last) - 8:.1f}" y="{y(last.price) - 10:.1f}"
        text-anchor="end">{money(last.price)}</text>
  <line class="crosshair" y1="{PAD_T}" y2="{CHART_H - PAD_B}" style="display:none"/>
  <circle class="hoverdot" r="4.5" style="display:none"/>
</svg>
<div class="tip" hidden></div>
</figure>"""


def sparkline(points: list[Point], w: int = 104, h: int = 26) -> str:
    if len(points) < 2:
        return ""
    prices = [p.price for p in points]
    lo, hi = min(prices), max(prices)
    span = (hi - lo) or 1.0
    step = w / (len(points) - 1)
    path = " ".join(
        f"{'M' if i == 0 else 'L'}{i * step:.1f},{h - 2 - (v - lo) / span * (h - 4):.1f}"
        for i, v in enumerate(prices))
    return (f'<svg class="spark" viewBox="0 0 {w} {h}" aria-hidden="true">'
            f'<path d="{path}"/></svg>')


# ------------------------------------------------------------------ page shell
def shell(title: str, body: str, built: str, depth: int = 0) -> str:
    up = "../" * depth
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<link rel="stylesheet" href="{up}style.css">
</head>
<body>
<header class="site">
  <a class="wordmark" href="{up}index.html">Film Stock Exchange</a>
  <nav><a href="{up}about.html">How prices work</a></nav>
</header>
<main>{body}</main>
<footer>
  <p>Prices are fictional and move only on released work and juried awards.
     No real money, no trading. Built {esc(built)}.</p>
  <p class="muted">Film and credit data from TMDB. Review scores from OMDb and
     Wikidata. Awards from Wikidata. Budgets and grosses from Wikipedia.</p>
</footer>
<script src="{up}chart.js" defer></script>
</body>
</html>"""


# ------------------------------------------------------------------- the market
def render_index(rows: list[dict], built: str) -> str:
    listed = len(rows)
    total = sum(r["price"] for r in rows)
    movers = [r for r in rows if r["change_1y"] is not None]
    best = max(movers, key=lambda r: r["change_1y"], default=None)
    worst = min(movers, key=lambda r: r["change_1y"], default=None)

    def card(label, value, sub=""):
        return (f'<div class="stat"><span class="stat-label">{esc(label)}</span>'
                f'<span class="stat-value">{value}</span>'
                f'<span class="stat-sub">{sub}</span></div>')

    stats = "".join([
        card("Listed", f"{listed:,}"),
        card("Market value", money(total)),
        card("Best year",
             f'<span class="{trend_class(best["change_1y"])}">'
             f'{pct(best["change_1y"])}</span>' if best else "—",
             esc(best["name"]) if best else ""),
        card("Worst year",
             f'<span class="{trend_class(worst["change_1y"])}">'
             f'{pct(worst["change_1y"])}</span>' if worst else "—",
             esc(worst["name"]) if worst else ""),
    ])

    body_rows = "".join(f"""<tr>
  <td class="rank">{i}</td>
  <td class="name"><a href="stock/{esc(r['slug'])}.html">{esc(r['name'])}</a>
      {'<span class="badge">dir</span>' if r['is_director'] else ''}</td>
  <td class="num price">{money(r['price'])}</td>
  <td class="num {trend_class(r['change_1y'])}">{pct(r['change_1y'])}</td>
  <td class="num {trend_class(r['change_90'])}">{pct(r['change_90'])}</td>
  <td class="tier"><span class="pill t{r['tier'].lower().replace('-', '')}">{esc(r['tier'])}</span></td>
  <td class="sparkcell">{r['spark']}</td>
</tr>""" for i, r in enumerate(rows, 1))

    return shell("Film Stock Exchange", f"""
<section class="hero">
  <h1>The market</h1>
  <p class="lede">Every price below is derived from real results — awards, box
  office, and critical reception — and nothing else. Open any name to see the
  arithmetic.</p>
</section>
<section class="stats">{stats}</section>
<section>
<table class="market">
  <thead><tr>
    <th class="rank">#</th><th>Name</th><th class="num">Price</th>
    <th class="num">1 year</th><th class="num">90 days</th>
    <th>Tier</th><th>5 years</th>
  </tr></thead>
  <tbody>{body_rows}</tbody>
</table>
</section>""", built)


# --------------------------------------------------------------- a single stock
def render_stock(person: Person, points: list[Point], built: str) -> str:
    valuation = value_person(person)
    c1y, c90 = change(points, 365), change(points, 90)

    reasons = [(c, v) for c, v in explain(person) if abs(v) >= 0.5][:14]
    reason_rows = "".join(f"""<tr>
  <td class="date">{c.event_date.isoformat()}</td>
  <td>{esc(c.label)}</td>
  <td class="src">{esc(c.source.replace('_', ' '))}</td>
  <td class="num {'up' if v > 0 else 'down'}">{v:+,.0f}</td>
</tr>""" for c, v in reasons)

    parts = [("Working", valuation.working_cp), ("Reception", valuation.reception_cp),
             ("Box office", valuation.box_office_cp), ("Awards", valuation.award_cp)]
    part_rows = "".join(
        f'<tr><td>{esc(n)}</td><td class="num">{v:+,.0f}</td>'
        f'<td class="num muted">{(v / valuation.cp * 100) if valuation.cp else 0:.0f}%</td></tr>'
        for n, v in parts)

    idle = ""
    if valuation.idle_years > 0.05:
        idle = (f'<p class="warn">No release for {valuation.idle_years:.1f} years past '
                f'the grace period — idle decay is holding this price down by '
                f'{(1 - valuation.idle_factor) * 100:.0f}%.</p>')

    credits = sorted(person.credits, key=lambda c: c.release_date, reverse=True)[:12]
    credit_rows = "".join(
        f'<tr><td class="date">{c.release_date.year}</td><td>{esc(c.title)}</td></tr>'
        for c in credits)

    return shell(f"{person.name} — Film Stock Exchange", f"""
<article>
<nav class="crumb"><a href="../index.html">← The market</a></nav>
<header class="stockhead">
  <h1>{esc(person.name)}{' <span class="badge">director</span>' if person.is_director else ''}</h1>
  <div class="quote">
    <span class="big">{money(valuation.price)}</span>
    <span class="unit">CR</span>
    <span class="chg {trend_class(c1y)}">{pct(c1y)} <small>1y</small></span>
    <span class="chg {trend_class(c90)}">{pct(c90)} <small>90d</small></span>
    <span class="pill t{valuation.tier.lower().replace('-', '')}">{esc(valuation.tier)}</span>
  </div>
</header>
{idle}
<h2>Price history</h2>
{line_chart(points, person.name)}

<div class="cols">
<section>
  <h2>Why it moved</h2>
  <p class="muted">The largest scoring events behind today's price, after age
  decay. Everything here traces to a dated, public result.</p>
  <table class="reasons">
    <thead><tr><th>Date</th><th>Event</th><th>Kind</th><th class="num">CP</th></tr></thead>
    <tbody>{reason_rows or '<tr><td colspan="4" class="muted">Nothing scored yet.</td></tr>'}</tbody>
  </table>
</section>

<aside>
  <h2>Where the value is</h2>
  <table class="parts">
    <tbody>{part_rows}</tbody>
    <tfoot><tr><td>Career Points</td><td class="num">{valuation.cp:,.0f}</td><td></td></tr></tfoot>
  </table>
  <h2>Recent credits</h2>
  <table class="credits"><tbody>{credit_rows}</tbody></table>
  <p class="muted">{valuation.credits_scored} scored credits, {len(person.awards)} awards.</p>
</aside>
</div>
</article>""", built, depth=1)


def render_about(built: str) -> str:
    return shell("How prices work — Film Stock Exchange", f"""
<article class="prose">
<h1>How prices work</h1>
<p class="lede">Every price comes from one number, Career Points, run through
one curve. Nothing here is a guess, and nothing moves on rumour.</p>

<pre class="formula">price = {K.PRICE_FLOOR} + {K.PRICE_COEF} × CP<sup>{K.PRICE_EXP}</sup></pre>

<h2>What earns Career Points</h2>
<table class="parts">
<thead><tr><th>Component</th><th class="num">At a leading role</th></tr></thead>
<tbody>
<tr><td>Simply working — one released credit</td><td class="num">+{K.WORKING_POINTS:,.0f}</td></tr>
<tr><td>Critical reception, best to worst</td>
    <td class="num">−250 to +250</td></tr>
<tr><td>Box office, as a multiple of budget</td><td class="num">−360 to +660</td></tr>
<tr><td>An Academy Award nomination</td><td class="num">+{K.AWARD_TABLE['oscar_lead'][0]}</td></tr>
<tr><td>Winning it</td><td class="num">+{K.AWARD_TABLE['oscar_lead'][1]}</td></tr>
</tbody></table>
<p>A supporting part earns a fraction of a film's result; a cameo earns very
little. Awards are the exception — they are given to the person, so they pay in
full.</p>

<h2>Why prices fall</h2>
<p>Two forces. Every past result slowly loses weight with age, floored so that
an old Academy Award never becomes worthless. And a career with nothing coming
out decays faster the smaller it is — a newcomer who disappears for three years
loses around a third of their value, while a legend loses about an eighth.</p>

<h2>What deliberately does not count</h2>
<p>Personal conduct, scandals, arrests, feuds, casting rumours and follower
counts move nothing. Prices respond to released work and juried awards only.</p>

<h2>Where the numbers come from</h2>
<p>Credits and billing order from TMDB. Review scores from OMDb and Wikidata,
blended across Rotten Tomatoes, Metacritic and IMDb after each is normalised
against its own distribution — a 60 on Rotten Tomatoes is mediocre where a 60
Metascore is good, and averaging them raw would be wrong. Awards from Wikidata.
Budgets and grosses from Wikipedia.</p>
<p class="muted">Built {esc(built)}.</p>
</article>""", built)


STYLE = """
:root {
  color-scheme: light;
  --surface: #fcfcfb;
  --raised: #ffffff;
  --ink: #0b0b0b;
  --ink-2: #52514e;
  --muted: #8a8880;
  --rule: #e6e4de;
  --series: #2a78d6;
  --up: #008300;
  --down: #c5302f;
  --serif: "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif;
  --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  --mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --surface: #17171a; --raised: #1e1e21; --ink: #f4f3ef; --ink-2: #c3c2b7;
    --muted: #8d8c86; --rule: #2e2e32; --series: #3987e5;
    --up: #4caf50; --down: #e66767;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--surface); color: var(--ink);
  font-family: var(--sans); font-size: 16px; line-height: 1.55;
  -webkit-font-smoothing: antialiased;
}
main { max-width: 1040px; margin: 0 auto; padding: 0 24px 72px; }
a { color: inherit; }
h1, h2, h3 { font-family: var(--serif); font-weight: 600; letter-spacing: -0.01em; }
h1 { font-size: 2.6rem; line-height: 1.1; margin: 0 0 .4rem; }
h2 { font-size: 1.3rem; margin: 2.4rem 0 .6rem; }
.muted { color: var(--muted); }
.lede { font-size: 1.15rem; color: var(--ink-2); max-width: 62ch; margin: 0; }

header.site {
  display: flex; justify-content: space-between; align-items: baseline;
  max-width: 1040px; margin: 0 auto; padding: 28px 24px 20px;
  border-bottom: 1px solid var(--rule);
}
.wordmark { font-family: var(--serif); font-size: 1.15rem; text-decoration: none; }
header.site nav a { color: var(--ink-2); text-decoration: none; font-size: .92rem; }
header.site nav a:hover { color: var(--ink); }
.hero { padding: 48px 0 8px; }
.crumb { padding: 22px 0 6px; font-size: .9rem; }
.crumb a { color: var(--ink-2); text-decoration: none; }

.stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1px;
  background: var(--rule); border: 1px solid var(--rule); margin: 32px 0 8px; }
.stat { background: var(--surface); padding: 14px 16px; display: flex; flex-direction: column; }
.stat-label { font-size: .74rem; text-transform: uppercase; letter-spacing: .07em;
  color: var(--muted); }
.stat-value { font-family: var(--mono); font-size: 1.35rem; margin-top: 2px; }
.stat-sub { font-size: .82rem; color: var(--muted); }

table { width: 100%; border-collapse: collapse; }
th { text-align: left; font-size: .74rem; text-transform: uppercase;
  letter-spacing: .07em; color: var(--muted); font-weight: 600;
  padding: 10px 10px; border-bottom: 1px solid var(--rule); }
td { padding: 9px 10px; border-bottom: 1px solid var(--rule); vertical-align: middle; }
tbody tr:hover { background: var(--raised); }
.num { text-align: right; font-family: var(--mono); font-variant-numeric: tabular-nums; }
.market .rank { color: var(--muted); font-family: var(--mono); width: 3rem; }
.market .name a { text-decoration: none; }
.market .name a:hover { text-decoration: underline; }
.market .price { font-size: 1.02rem; }
.sparkcell { width: 120px; }
.spark { width: 104px; height: 26px; }
.spark path { fill: none; stroke: var(--series); stroke-width: 1.5;
  stroke-linejoin: round; stroke-linecap: round; opacity: .85; }
.up { color: var(--up); }
.down { color: var(--down); }
.flat { color: var(--muted); }
.badge { font-size: .64rem; text-transform: uppercase; letter-spacing: .08em;
  border: 1px solid var(--rule); padding: 1px 5px; color: var(--muted);
  vertical-align: middle; }
.pill { font-size: .74rem; padding: 2px 9px; border: 1px solid var(--rule);
  border-radius: 999px; color: var(--ink-2); white-space: nowrap; }
.pill.tlegend, .pill.talist { border-color: currentColor; color: var(--ink); }

.stockhead { padding: 6px 0 4px; }
.quote { display: flex; align-items: baseline; gap: 16px; flex-wrap: wrap;
  margin-top: 8px; }
.big { font-family: var(--mono); font-size: 2.6rem; font-variant-numeric: tabular-nums; }
.unit { color: var(--muted); margin-left: -12px; }
.chg { font-family: var(--mono); font-size: 1rem; }
.chg small { color: var(--muted); font-size: .72rem; margin-left: 2px; }
.warn { background: var(--raised); border-left: 3px solid var(--rule);
  padding: 10px 14px; color: var(--ink-2); font-size: .94rem; }

.chart { margin: 8px 0 0; position: relative; }
.chart svg { width: 100%; height: auto; display: block; overflow: visible; }
.grid { stroke: var(--rule); stroke-width: 1; }
.axis { fill: var(--muted); font-size: 11px; font-family: var(--mono); }
.series { fill: none; stroke: var(--series); stroke-width: 2;
  stroke-linejoin: round; stroke-linecap: round; }
.dot, .hoverdot { fill: var(--series); stroke: var(--surface); stroke-width: 2; }
.endlabel { fill: var(--ink); font-family: var(--mono); font-size: 12px; }
.crosshair { stroke: var(--muted); stroke-width: 1; stroke-dasharray: 3 3; }
.tip { position: absolute; pointer-events: none; background: var(--raised);
  border: 1px solid var(--rule); padding: 5px 9px; font-family: var(--mono);
  font-size: .8rem; white-space: nowrap; transform: translate(-50%, -140%); }
.tip[hidden] { display: none; }

.cols { display: grid; grid-template-columns: 1.55fr 1fr; gap: 40px; align-items: start; }
.reasons .date, .credits .date { font-family: var(--mono); color: var(--muted);
  font-size: .86rem; white-space: nowrap; }
.reasons .src { color: var(--muted); font-size: .86rem; }
.parts tfoot td { font-weight: 600; border-bottom: none; }
.prose { max-width: 68ch; padding-top: 40px; }
.prose p { color: var(--ink-2); }
.formula { font-family: var(--mono); background: var(--raised);
  border: 1px solid var(--rule); padding: 14px 16px; font-size: 1rem;
  overflow-x: auto; }
footer { border-top: 1px solid var(--rule); max-width: 1040px; margin: 0 auto;
  padding: 22px 24px 60px; color: var(--ink-2); font-size: .88rem; }
footer p { margin: 0 0 6px; }

@media (max-width: 860px) {
  .cols { grid-template-columns: 1fr; gap: 8px; }
  .stats { grid-template-columns: repeat(2, 1fr); }
  h1 { font-size: 2rem; }
  .big { font-size: 2rem; }
  .sparkcell, .market th:nth-child(5), .market td:nth-child(5) { display: none; }
}
"""

CHART_JS = """
// Crosshair + tooltip on the price chart. An HTML chart is interactive by
// default; a line you cannot read a value off is a picture, not a chart.
document.querySelectorAll('.chart').forEach(function (fig) {
  var svg = fig.querySelector('svg');
  var tip = fig.querySelector('.tip');
  if (!svg || !tip) return;
  var pts;
  try { pts = JSON.parse(svg.dataset.points); } catch (e) { return; }
  if (!pts || pts.length < 2) return;

  var cross = svg.querySelector('.crosshair');
  var dot = svg.querySelector('.hoverdot');
  var series = svg.querySelector('.series');
  var d = series.getAttribute('d').split(/[ML]/).filter(Boolean).map(function (s) {
    var xy = s.split(','); return { x: parseFloat(xy[0]), y: parseFloat(xy[1]) };
  });

  function show(evt) {
    var box = svg.getBoundingClientRect();
    var vb = svg.viewBox.baseVal;
    var x = (evt.clientX - box.left) / box.width * vb.width;
    var best = 0;
    for (var i = 1; i < d.length; i++) {
      if (Math.abs(d[i].x - x) < Math.abs(d[best].x - x)) best = i;
    }
    var p = d[best], row = pts[best];
    if (!p || !row) return;
    cross.setAttribute('x1', p.x); cross.setAttribute('x2', p.x);
    cross.style.display = ''; dot.style.display = '';
    dot.setAttribute('cx', p.x); dot.setAttribute('cy', p.y);
    var when = new Date(row[0] + 'T00:00:00').toLocaleDateString(undefined,
      { year: 'numeric', month: 'short' });
    tip.textContent = when + '  ·  ' + row[1].toFixed(2) + ' CR';
    tip.hidden = false;
    tip.style.left = (p.x / vb.width * box.width) + 'px';
    tip.style.top = (p.y / vb.height * box.height) + 'px';
  }
  function hide() {
    cross.style.display = 'none'; dot.style.display = 'none'; tip.hidden = true;
  }
  svg.addEventListener('mousemove', show);
  svg.addEventListener('mouseleave', hide);
  svg.addEventListener('touchmove', function (e) {
    if (e.touches[0]) show(e.touches[0]);
  }, { passive: true });
  svg.addEventListener('touchend', hide);
});
"""


def build(snapshot: Path, out_dir: Path, years: int = 5) -> dict:
    """Render the whole market. Pure: reads a snapshot, writes files, no network."""
    from .store import load

    people, fetched = load(snapshot)
    built = date.today().isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "stock").mkdir(exist_ok=True)
    (out_dir / "style.css").write_text(STYLE)
    (out_dir / "chart.js").write_text(CHART_JS)

    rows, api = [], []
    for person in people:
        points = series(person, years=years)
        valuation = value_person(person)
        person_slug = slug(person.name)

        (out_dir / "stock" / f"{person_slug}.html").write_text(
            render_stock(person, points, built))

        rows.append({
            "name": person.name, "slug": person_slug, "price": valuation.price,
            "tier": valuation.tier, "is_director": person.is_director,
            "change_1y": change(points, 365), "change_90": change(points, 90),
            "spark": sparkline(points),
        })
        api.append({
            "name": person.name, "slug": person_slug,
            "price": round(valuation.price, 2), "cp": round(valuation.cp, 1),
            "tier": valuation.tier, "is_director": person.is_director,
            "history": [[p.on.isoformat(), round(p.price, 2)] for p in points],
        })

    rows.sort(key=lambda r: r["price"], reverse=True)
    (out_dir / "index.html").write_text(render_index(rows, built))
    (out_dir / "about.html").write_text(render_about(built))
    (out_dir / "market.json").write_text(json.dumps(
        {"built": built, "fetched": fetched, "stocks": api}, indent=1))
    (out_dir / ".nojekyll").write_text("")

    return {"people": len(people), "out": out_dir, "fetched": fetched}
