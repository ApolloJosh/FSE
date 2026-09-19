"""Rendering for the daily games. Server-rendered forms: the answer stays on
the server, and every guess is a POST that the server grades."""

from __future__ import annotations

from datetime import date

from fsx.site import esc, money

from app import db
from app.views import chrome, flash

from .puzzles import GAMES, TITLES, WEEKLY, Puzzle
from .scoring import DAILY_GAMES, PAYOUTS


def hub(summary: dict, unavailable: dict[str, str], user, on: date,
        streak: int, weekly_done: bool, msg: str = "", ok: bool = False,
        csrf: str = "", can_reset: bool = False) -> str:
    cards = ""
    for game in GAMES:
        title, blurb = TITLES[game]
        row = summary["rows"].get(game)
        floor, ceiling = PAYOUTS[game]
        if game in unavailable:
            state = f'<span class="muted">{esc(unavailable[game])}</span>'
            action = ""
        elif row and row["done"]:
            state = (f'<span class="up">Done · earned CR '
                     f'{money(db.credits(row["payout"]))}</span>')
            action = f'<a class="btn ghost" href="play/{game}">Review</a>'
        else:
            state = (f'<span class="muted">CR {money(db.credits(floor))}–'
                     f'{money(db.credits(ceiling))}</span>')
            action = f'<a class="btn" href="play/{game}">Play</a>'
        cards += f"""<tr>
  <td><strong>{esc(title)}</strong><br><span class="muted">{esc(blurb)}</span></td>
  <td>{state}</td><td class="num">{action}</td></tr>"""

    reset = ""
    if can_reset:
        reset = f"""<form method="post" action="play/reset" class="reset">
  <input type="hidden" name="csrf" value="{esc(csrf)}">
  <button class="btn ghost">Play today's games again</button>
  <span class="muted">Local only. Credits already earned are kept.</span>
</form>"""

    wt, wb = TITLES[WEEKLY]
    weekly_state = ('<span class="up">Done</span>' if weekly_done
                    else f'<a class="btn" href="play/{WEEKLY}">Play</a>')

    return chrome("Daily games — Film Stock Exchange", f"""
<section class="hero"><h1>Today's games</h1>
<p class="lede">Four puzzles, each under ninety seconds, all generated from the
same film data that prices the market. Playing them is how you learn to read
it.</p></section>
{flash(msg, ok)}
<section class="stats">
  <div class="stat"><span class="stat-label">Earned today</span>
    <span class="stat-value">{money(db.credits(summary['earned']))}</span></div>
  <div class="stat"><span class="stat-label">Completed</span>
    <span class="stat-value">{len(summary['done'])}/{len(DAILY_GAMES)}</span></div>
  <div class="stat"><span class="stat-label">Streak</span>
    <span class="stat-value">{streak}</span>
    <span class="stat-sub">+CR 0.50 a day, capped at 5.00</span></div>
  <div class="stat"><span class="stat-label">Date</span>
    <span class="stat-value">{on.isoformat()}</span></div>
</section>
<table><tbody>{cards}</tbody></table>
<h2>This weekend</h2>
<table><tbody><tr>
  <td><strong>{esc(wt)}</strong><br><span class="muted">{esc(wb)}</span></td>
  <td>{weekly_state}</td></tr></tbody></table>
<p class="muted">A fifth daily game, Critics vs Crowd, is on hold until an
audience score is licensable.</p>
{reset}""", user)


def _shell(title: str, inner: str, user, msg: str, ok: bool) -> str:
    return chrome(f"{title} — Film Stock Exchange", f"""
<nav class="crumb"><a href="../play">← Today's games</a></nav>
<section class="hero"><h1>{esc(title)}</h1></section>
{flash(msg, ok)}{inner}""", user, depth=1)


def _finished(grade_detail: str, payout: int) -> str:
    return (f'<div class="trade"><p><strong>{esc(grade_detail)}</strong></p>'
            f'<p class="muted">Earned CR {money(db.credits(payout))}. '
            f'Back tomorrow for a new one.</p></div>')


def play_page(game: str, puzzle: Puzzle, row, state: dict, csrf: str,
              user, msg: str = "", ok: bool = False) -> str:
    title, blurb = TITLES[game]
    if row is not None and row["done"]:
        return _shell(title, _finished(state.get("detail", "Finished."),
                                       row["payout"]), user, msg, ok)

    form_open = (f'<form method="post" action="../play/{game}">'
                 f'<input type="hidden" name="csrf" value="{esc(csrf)}">')
    body = f'<p class="lede">{esc(blurb)}</p><p class="muted">{esc(puzzle.note)}</p>'

    if game == "ladder":
        shown = int(state.get("rungs", 1))
        rungs = puzzle.public["rungs"][:shown]
        listed = "".join(f"<li>{esc(r['title'])} <span class='muted'>({r['year']})</span></li>"
                         for r in rungs)
        options = "".join(f'<option value="{esc(o)}">{esc(o)}</option>'
                          for o in puzzle.public["options"])
        more = ('<button class="btn ghost" name="action" value="reveal">'
                'Reveal another</button>' if shown < puzzle.max_guesses else '')
        body += f"""<div class="trade"><ol>{listed}</ol>
{form_open}
  <div><label for="answer">Who is it?</label>
    <select id="answer" name="answer" style="width:16rem">{options}</select></div>
  <button class="btn" name="action" value="guess">Lock it in</button>{more}
</form>
<p class="muted">Rung {shown} of {puzzle.max_guesses}. Fewer rungs, more Credits.</p>
</div>"""

    elif game == "cast-gap":
        film = puzzle.public
        shown = ", ".join(film["shown"])
        options = "".join(
            f'<label style="display:block;margin:4px 0"><input type="radio" '
            f'name="answer" value="{esc(o)}" required> {esc(o)}</label>'
            for o in film["options"])
        tries = int(state.get("guesses", 0))
        body += f"""<div class="trade">
<p><strong>{esc(film['title'])}</strong> <span class="muted">({film['year']})</span></p>
<p>Billed: {esc(shown)}, and one more.</p>
{form_open}{options}
<button class="btn" name="action" value="guess">Answer</button></form>
<p class="muted">{2 - tries} {'guess' if 2 - tries == 1 else 'guesses'} left.</p></div>"""

    elif game == "box-office":
        rows = "".join(
            f'<tr><td>{esc(f["title"])} <span class="muted">({f["year"]})</span></td>'
            f'<td class="num"><input name="rank_{esc(f["key"])}" type="number" min="1" '
            f'max="5" required style="width:4rem"></td></tr>'
            for f in puzzle.public["films"])
        body += f"""<div class="trade">{form_open}
<table><thead><tr><th>Film</th><th class="num">Rank</th></tr></thead>
<tbody>{rows}</tbody></table>
<button class="btn" name="action" value="guess">Submit ranking</button></form>
<p class="muted">1 is the highest worldwide gross.</p></div>"""

    elif game == "six-degrees":
        pub = puzzle.public
        options = "".join(f'<option value="{esc(n)}">' for n in pub["roster"])
        steps = "".join(
            f'<div><label for="s{i}">Step {i}</label>'
            f'<input id="s{i}" name="step_{i}" list="roster" style="width:13rem"></div>'
            for i in range(1, 5))
        body += f"""<div class="trade">
<p><strong>{esc(pub['from'])}</strong> → <strong>{esc(pub['to'])}</strong></p>
<datalist id="roster">{options}</datalist>
{form_open}{steps}
<button class="btn" name="action" value="guess">Submit chain</button></form>
<p class="muted">Name the people in between. Leave later steps blank if you need
fewer. Par is {pub['par']}.</p></div>"""

    elif game == WEEKLY:
        pub = puzzle.public
        picks = "".join(
            f'<label style="display:block;margin:3px 0">'
            f'<input type="checkbox" name="pick" value="{esc(p["slug"])}"> '
            f'{esc(p["name"])} <span class="muted">— {p["price"]}</span></label>'
            for p in pub["pool"])
        body += f"""<div class="trade">
<p>Budget: <strong>{pub['budget']}</strong>. Pick exactly five.</p>
{form_open}{picks}
<button class="btn" name="action" value="guess">Lock in the slate</button></form></div>"""

    return _shell(title, body, user, msg, ok)
