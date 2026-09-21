"""Rendering for the daily games. Server-rendered forms: the answer stays on
the server, and every guess is a POST that the server grades."""

from __future__ import annotations

from datetime import date

from fsx.site import esc, money

from app import db
from app.views import chrome, flash, name_picker

from .puzzles import GAMES, TITLES, WEEKLY, Puzzle
from .scoring import DAILY_GAMES, PAYOUTS


def hub(summary: dict, unavailable: dict[str, str], user, on: date,
        streak: int, weekly_done: bool, msg: str = "", ok: bool = False,
        csrf: str = "") -> str:
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

    # No condition on this. It used to be hidden unless the local test player
    # was enabled, which is off in production - so the button existed, the
    # route allowed it, and nobody could see it.
    reset = f"""<form method="post" action="play/reset" class="reset">
  <input type="hidden" name="csrf" value="{esc(csrf)}">
  <button class="btn ghost">Play today's games again</button>
  <span class="muted">For practice. You keep what you earned, and a replay
  pays nothing.</span>
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


def _dollars(value) -> str:
    """One decimal, because two films rounding to the same "$634M" at ranks 1
    and 2 makes the order look arbitrary."""
    if not value:
        return "—"
    if value >= 1e9:
        return f"${value / 1e9:,.2f}B"
    return f"${value / 1e6:,.1f}M"


def reveal(state: dict) -> str:
    """What the answer actually was.

    "1 of 4 pairs in the right order" tells a player their score and nothing
    they wanted to know. The point of a daily game is finding out.
    """
    data = state.get("reveal") or {}
    kind = data.get("kind")

    if kind == "order":
        def row(entry):
            right = entry["yours"] == entry["truth"]
            mark = "✓" if right else "you said {}".format(entry["yours"])
            return ('<tr><td class="rank">{}</td><td>{}</td>'
                    '<td class="num">{}</td>'
                    '<td class="num {}">{}</td></tr>').format(
                        entry["truth"], esc(entry["title"]),
                        _dollars(entry["gross"]),
                        "up" if right else "down", mark)

        rows = "".join(row(r) for r in data["rows"])
        return f"""<h2>The real order</h2>
<table class="reveal"><thead><tr><th class="rank">#</th><th>Film</th>
<th class="num">Worldwide</th><th class="num">You</th></tr></thead>
<tbody>{rows}</tbody></table>"""

    if kind == "chain":
        chain, links = data["chain"], data["links"]
        items = f'<li class="who start">{esc(chain[0])}</li>'
        for i, who in enumerate(chain[1:], start=1):
            films = links[i - 1] if i - 1 < len(links) else []
            items += (f'<li class="link"><span class="tick">✓</span>'
                      f'<span class="via">{esc(", ".join(films))}</span></li>'
                      f'<li class="who"><span class="tick">✓</span>{esc(who)}</li>')
        return f'<h2>Your chain</h2><ol class="chain">{items}</ol>'

    if kind == "slate":
        def table(entries, heading):
            rows = "".join(
                f'<tr><td>{esc(e["name"])}</td>'
                f'<td class="num">{e["price"]}</td>'
                f'<td class="num">{_dollars(e["gross"])}</td></tr>'
                for e in entries)
            total = sum(e["gross"] for e in entries)
            spend = sum(e["price"] for e in entries)
            return (f'<h2>{heading}</h2><table class="reveal"><thead><tr>'
                    f'<th>Name</th><th class="num">Cost</th>'
                    f'<th class="num">Gross</th></tr></thead><tbody>{rows}'
                    f'<tr class="total"><td>Total</td><td class="num">{spend}</td>'
                    f'<td class="num">{_dollars(total)}</td></tr>'
                    f'</tbody></table>')
        return table(data["yours"], "Your slate") + table(data["best"],
                                                          "The best slate")
    return ""


def _finished(grade_detail: str, payout: int, state: dict | None = None) -> str:
    return (f'<div class="trade"><p><strong>{esc(grade_detail)}</strong></p>'
            f'<p class="muted">Earned CR {money(db.credits(payout))}. '
            f'Back tomorrow for a new one.</p></div>'
            + reveal(state or {}))


def play_page(game: str, puzzle: Puzzle, row, state: dict, csrf: str,
              user, msg: str = "", ok: bool = False) -> str:
    title, blurb = TITLES[game]
    if row is not None and row["done"]:
        return _shell(title, _finished(state.get("detail", "Finished."),
                                       row["payout"], state), user, msg, ok)

    form_open = (f'<form class="game" method="post" action="../play/{game}">'
                 f'<input type="hidden" name="csrf" value="{esc(csrf)}">')
    body = f'<p class="lede">{esc(blurb)}</p><p class="muted">{esc(puzzle.note)}</p>'

    if game == "ladder":
        from .scoring import payout_for

        total = puzzle.max_guesses
        shown = int(state.get("rungs", 1))
        tried = list(state.get("wrong") or [])
        films = puzzle.public["rungs"]

        # A ladder read top-down was the whole confusion: the list grew
        # downwards while the payout fell, so "climbing" meant doing worse.
        # Drawn as a ladder - hardest and richest at the top, easiest and
        # cheapest at the bottom - a step down is obviously a step down.
        steps = ""
        for level in range(total, 0, -1):
            revealed = total - level + 1        # films you have at this rung
            pays = payout_for("ladder", (total - revealed + 1) / total)
            if revealed < shown:
                mark, film = "passed", films[revealed - 1]
                clue = f'{esc(film["title"])} <span class="muted">({film["year"]})</span>'
            elif revealed == shown:
                mark, film = "here", films[revealed - 1]
                clue = f'{esc(film["title"])} <span class="muted">({film["year"]})</span>'
            else:
                mark, clue = "ahead", '<span class="muted">one more film</span>'
            steps += (f'<li class="rung {mark}"><span class="level">{level}</span>'
                      f'<span class="clue">{clue}</span>'
                      f'<span class="pays">{money(db.credits(pays))}</span></li>')

        choices = "".join(
            f'<label class="choice{" spent" if o in tried else ""}">'
            f'<input type="radio" name="answer" value="{esc(o)}" required'
            f'{" disabled" if o in tried else ""}><span>{esc(o)}</span></label>'
            for o in puzzle.public["options"])

        left = total - shown
        step_down = (f'<button class="btn ghost" name="action" value="reveal">'
                     f'Step down for another film</button>' if left else '')
        where = (f"You are on rung {total - shown + 1} of {total}, "
                 f"worth {money(db.credits(payout_for('ladder', (total - shown + 1) / total)))}.")
        where += (" A wrong name costs you a rung." if left else
                  " Bottom rung: this is the last guess.")

        body = f"""<p class="lede">One person's filmography, most obscure film
first. Name them from as high up the ladder as you can — every extra film you
take drops you a rung and pays less.</p>
<div class="trade">
<ol class="ladder">{steps}</ol>
{form_open}
  <fieldset><legend>Whose filmography is this?</legend>
  <div class="choices">{choices}</div></fieldset>
  <button class="btn" name="action" value="guess">Lock it in</button>{step_down}
</form>
<p class="muted">{where}</p>
</div>"""

    elif game == "cast-gap":
        film = puzzle.public
        billed = "".join(f"<li>{esc(n)}</li>" for n in film["shown"])
        options = "".join(
            f'<label class="choice"><input type="radio" name="answer" '
            f'value="{esc(o)}" required><span>{esc(o)}</span></label>'
            for o in film["options"])
        tries = int(state.get("guesses", 0))
        body = f"""<p class="lede">One name is missing from the billing.</p>
<div class="trade">
<p class="filmtitle"><strong>{esc(film['title'])}</strong>
   <span class="muted">({film['year']})</span></p>
<ul class="billing">{billed}<li class="gap">the missing name</li></ul>
{form_open}<div class="choices">{options}</div>
<button class="btn" name="action" value="guess">Answer</button></form>
<p class="muted">{2 - tries} {'guess' if 2 - tries == 1 else 'guesses'} left.</p>
</div>"""

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
        chain = state.get("chain") or []
        links = state.get("links") or []
        names = state.get("chain_names") or []
        misses = int(state.get("misses", 0))

        steps = f'<li class="who start">{esc(pub["from"])}</li>'
        for i, who in enumerate(names[1:], start=1):
            films = links[i - 1] if i - 1 < len(links) else []
            steps += (f'<li class="link"><span class="tick">✓</span>'
                      f'<span class="via">{esc(", ".join(films))}</span></li>'
                      f'<li class="who"><span class="tick">✓</span>{esc(who)}</li>')
        steps += ('<li class="link pending"><span class="via muted">?</span></li>'
                  f'<li class="who target">{esc(pub["to"])}</li>')

        undo = ('<button class="btn ghost" name="action" value="undo">Undo</button>'
                if len(names) > 1 else '')
        picker = name_picker(
            "answer",
            f'Who links {esc(names[-1] if names else pub["from"])} onward?',
            list(pub["roster"]))
        body = f"""<p class="lede">Connect the two through people they have
actually shared a film with — one name at a time.</p>
<div class="trade">
<ol class="chain">{steps}</ol>
{form_open}
  {picker}
  <button class="btn" name="action" value="link">Lock it in</button>{undo}
  <button class="btn ghost" name="action" value="giveup">Give up</button>
</form>
<p class="muted">Par is {pub['par']} hop{'' if pub['par'] == 1 else 's'}.
{f"{misses} wrong so far." if misses else "A wrong name costs you."}</p>
</div>"""

    elif game == WEEKLY:
        pub = puzzle.public
        picks = "".join(
            f'<label class="choice"><input type="checkbox" name="pick" '
            f'value="{esc(p["slug"])}" data-price="{p["price"]}">'
            f'<span>{esc(p["name"])}</span>'
            f'<span class="price">{p["price"]}</span></label>'
            for p in pub["pool"])
        body = f"""<p class="lede">Pick five. The highest combined worldwide
gross inside the budget wins, so the dear names have to earn their price.</p>
<div class="trade">
<div class="budget">
  <span><small>Budget</small><strong id="budget">{pub['budget']}</strong></span>
  <span><small>Spent</small><strong id="spent">0</strong></span>
  <span><small>Picked</small><strong id="picked">0</strong>/5</span>
</div>
{form_open}<div class="choices two">{picks}</div>
<button class="btn" id="lock" name="action" value="guess" disabled>
  Lock in the slate</button></form>
<p class="muted" id="slatehint">Pick five names inside the budget.</p>
</div>
<script>
// A budget you can only discover by submitting is not a budget.
(function () {{
  var boxes = [].slice.call(document.querySelectorAll('input[name="pick"]'));
  var budget = {pub['budget']};
  var spent = document.getElementById('spent');
  var picked = document.getElementById('picked');
  var lock = document.getElementById('lock');
  var hint = document.getElementById('slatehint');
  function tally() {{
    var chosen = boxes.filter(function (b) {{ return b.checked; }});
    var cost = chosen.reduce(function (t, b) {{
      return t + parseInt(b.dataset.price, 10);
    }}, 0);
    spent.textContent = cost;
    picked.textContent = chosen.length;
    spent.className = cost > budget ? 'down' : '';
    // Grey out what you can no longer afford, and what would be a sixth pick.
    boxes.forEach(function (b) {{
      if (b.checked) {{ b.disabled = false; return; }}
      var price = parseInt(b.dataset.price, 10);
      b.disabled = chosen.length >= 5 || cost + price > budget;
      b.parentNode.classList.toggle('spent', b.disabled);
    }});
    var ready = chosen.length === 5 && cost <= budget;
    lock.disabled = !ready;
    hint.textContent = ready
      ? 'Five picked, ' + (budget - cost) + ' left over.'
      : chosen.length < 5
        ? (5 - chosen.length) + ' more to pick, ' + (budget - cost) + ' left.'
        : 'Over budget by ' + (cost - budget) + '.';
  }}
  boxes.forEach(function (b) {{ b.addEventListener('change', tally); }});
  tally();
}})();
</script>"""

    return _shell(title, body, user, msg, ok)
