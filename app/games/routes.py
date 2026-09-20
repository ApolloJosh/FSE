"""Routes for the daily games."""

from __future__ import annotations

from datetime import date

from typing import Optional

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from fsx.site import slug as slugify

from app import auth, db

from . import play, scoring, views
from .corpus import build
from .puzzles import GAMES, NotEnoughData, WEEKLY, check_chain, generate

router = APIRouter()


def _ctx(request: Request):
    from app.main import SNAPSHOT, conn, current_user
    return conn(), current_user(request), str(SNAPSHOT)


@router.get("/play", response_class=HTMLResponse)
def hub(request: Request, msg: Optional[str] = None, ok: int = 0):
    conn, user, snapshot = _ctx(request)
    if user is None:
        return RedirectResponse("/signin", status_code=303)

    on = date.today()
    unavailable = {}
    for game in GAMES:
        try:
            generate(game, on, snapshot)
        except NotEnoughData as exc:
            unavailable[game] = str(exc)

    summary = play.today_summary(conn, user["id"], on)
    weekly_row = play.get(conn, user["id"], WEEKLY, _weekly_date(on))
    from app import auth as app_auth
    return views.hub(summary, unavailable, user, on,
                     scoring.streak_length(conn, user["id"], on),
                     bool(weekly_row and weekly_row["done"]), msg or "", bool(ok),
                     csrf=app_auth.csrf_token(request),
                     can_reset=app_auth.dev_login_allowed())


@router.post("/play/reset")
def reset_today(request: Request, csrf: str = Form(...)):
    """Open today's games up to be played again.

    Anyone can, because playing a puzzle a second time is practice and there is
    no reason to forbid it. What a replay cannot do is pay: the row keeps its
    payout and its paid flag, so the day is worth exactly one payout however
    many times it is played.
    """
    from app import auth as app_auth
    conn, user, _ = _ctx(request)
    app_auth.check_csrf(request, csrf)
    user_id = app_auth.require_user_id(request)
    play.clear_day(conn, user_id, date.today())
    play.clear_day(conn, user_id, _weekly_date(date.today()))
    return RedirectResponse(
        "/play?msg=Today's games are open again. A replay pays nothing.&ok=1",
        status_code=303)


def _remember(state: dict, corpus, chain: list, links: list, misses: int) -> None:
    """Keep the chain in the play state as names as well as slugs: the page
    that draws it has no corpus to look them up in."""
    state["chain"] = chain
    state["links"] = links
    state["misses"] = misses
    state["chain_names"] = [corpus.name(s) for s in chain]


def _weekly_date(on: date) -> date:
    """The weekly puzzle is keyed to the Friday of its week, so a weekend of
    play is one puzzle rather than three."""
    return on - __import__("datetime").timedelta(days=(on.weekday() - 4) % 7)


@router.get("/play/{game}", response_class=HTMLResponse)
def show(request: Request, game: str, msg: Optional[str] = None, ok: int = 0):
    conn, user, snapshot = _ctx(request)
    if user is None:
        return RedirectResponse("/signin", status_code=303)
    if game not in GAMES and game != WEEKLY:
        return RedirectResponse("/play", status_code=303)

    on = _weekly_date(date.today()) if game == WEEKLY else date.today()
    try:
        puzzle = generate(game, on, snapshot)
    except NotEnoughData as exc:
        return RedirectResponse(f"/play?msg={exc}&ok=0", status_code=303)

    row = play.start(conn, user["id"], game, on)
    return views.play_page(game, puzzle, row, play.state_of(row),
                           auth.csrf_token(request), user, msg or "", bool(ok))


@router.post("/play/{game}")
async def submit(request: Request, game: str, csrf: str = Form(...),
                 action: str = Form("guess")):
    conn, user, snapshot = _ctx(request)
    auth.check_csrf(request, csrf)
    user_id = auth.require_user_id(request)
    if game not in GAMES and game != WEEKLY:
        return RedirectResponse("/play", status_code=303)

    on = _weekly_date(date.today()) if game == WEEKLY else date.today()
    try:
        puzzle = generate(game, on, snapshot)
    except NotEnoughData as exc:
        return RedirectResponse(f"/play?msg={exc}&ok=0", status_code=303)

    row = play.start(conn, user_id, game, on)
    if row["done"]:
        return RedirectResponse(f"/play/{game}", status_code=303)

    form = await request.form()
    state = play.state_of(row)

    # ----- reveal another rung, no grading yet
    if game == "ladder" and action == "reveal":
        state["rungs"] = min(puzzle.max_guesses, int(state.get("rungs", 1)) + 1)
        play.save_state(conn, user_id, game, on, state)
        return RedirectResponse(f"/play/{game}", status_code=303)

    corpus = build(snapshot)
    grade = None

    if game == "ladder":
        rungs = int(state.get("rungs", 1))
        correct = (form.get("answer") or "").strip() == puzzle.answer["name"]
        grade = scoring.grade_ladder(puzzle, rungs, correct)

    elif game == "cast-gap":
        guesses = int(state.get("guesses", 0)) + 1
        correct = (form.get("answer") or "").strip() == puzzle.answer["name"]
        if not correct and guesses < 2:
            state["guesses"] = guesses
            play.save_state(conn, user_id, game, on, state)
            return RedirectResponse(
                f"/play/{game}?msg=Not that one. One guess left.&ok=0", status_code=303)
        grade = scoring.grade_cast_gap(puzzle, guesses, correct)

    elif game == "box-office":
        ranked = []
        for film in puzzle.public["films"]:
            raw = form.get(f"rank_{film['key']}")
            try:
                ranked.append((int(raw), film["key"]))
            except (TypeError, ValueError):
                ranked.append((99, film["key"]))
        submitted = [key for _, key in sorted(ranked)]
        grade = scoring.grade_box_office(puzzle, submitted)
        titles = {f["key"]: f"{f['title']} ({f['year']})"
                  for f in puzzle.public["films"]}
        placed = {key: i + 1 for i, key in enumerate(submitted)}
        state["reveal"] = {
            "kind": "order",
            "rows": [{"title": titles.get(key, key),
                      "gross": puzzle.answer["gross"].get(key),
                      "truth": i + 1, "yours": placed.get(key)}
                     for i, key in enumerate(puzzle.answer["order"])]}

    elif game == "six-degrees":
        # One link at a time. Four blanks submitted blind told a player
        # nothing about which of them was wrong, and there is no game in that.
        from .corpus import shared_films

        start, target = puzzle.answer["from"], puzzle.answer["to"]
        chain = state.get("chain") or [start]
        links = state.get("links") or []
        misses = int(state.get("misses", 0))

        if action == "undo" and len(chain) > 1:
            chain.pop()
            links.pop()
            _remember(state, corpus, chain, links, misses)
            play.save_state(conn, user_id, game, on, state)
            return RedirectResponse(f"/play/{game}", status_code=303)

        if action == "giveup":
            grade = scoring.grade_six_degrees(puzzle, 0, misses, gave_up=True)
        else:
            by_name = {corpus.name(s).lower(): s for s in corpus.by_person}
            typed = (form.get("answer") or "").strip()
            picked = by_name.get(typed.lower())

            problem = None
            if not typed:
                problem = "Name somebody."
            elif picked is None:
                problem = f"{typed} is not on the roster."
            elif picked == target:
                problem = (f"{corpus.name(target)} is where you are heading - "
                           "name somebody in between.")
            elif picked in chain:
                problem = f"{corpus.name(picked)} is already in the chain."
            if problem:
                return RedirectResponse(f"/play/{game}?msg={problem}&ok=0",
                                        status_code=303)

            bridge = shared_films(corpus, chain[-1], picked)
            if not bridge:
                misses += 1
                _remember(state, corpus, chain, links, misses)
                play.save_state(conn, user_id, game, on, state)
                return RedirectResponse(
                    f"/play/{game}?msg=No film links {corpus.name(chain[-1])} "
                    f"and {corpus.name(picked)}.&ok=0", status_code=303)

            chain.append(picked)
            links.append([f.title for f in bridge[:3]])

            home = shared_films(corpus, picked, target)
            if not home:
                _remember(state, corpus, chain, links, misses)
                play.save_state(conn, user_id, game, on, state)
                return RedirectResponse(
                    f"/play/{game}?msg={corpus.name(picked)} is in. "
                    f"Keep going.&ok=1", status_code=303)

            links.append([f.title for f in home[:3]])
            chain.append(target)
            _remember(state, corpus, chain, links, misses)
            grade = scoring.grade_six_degrees(puzzle, len(chain) - 1, misses)

        _remember(state, corpus, chain, links, misses)
        state["reveal"] = {"kind": "chain",
                           "chain": [corpus.name(s) for s in chain],
                           "links": links}

    elif game == WEEKLY:
        picked = [str(v) for v in form.getlist("pick")]
        if len(set(picked)) != 5:
            # An unfinished form is not a wrong answer. Grading it spent the
            # week's puzzle on a submission the player had not made yet.
            return RedirectResponse(
                f"/play/{game}?msg=Pick exactly five, then lock it in.&ok=0",
                status_code=303)
        grade = scoring.grade_slate(puzzle, picked)
        names = {e["slug"]: e["name"] for e in puzzle.public["pool"]}
        prices = puzzle.answer["prices"]
        state["reveal"] = {
            "kind": "slate",
            "yours": [{"name": names.get(s, s), "price": prices.get(s, 0),
                       "gross": puzzle.answer["totals"].get(s, 0)}
                      for s in picked],
            "best": [{"name": names.get(s, s), "price": prices.get(s, 0),
                      "gross": puzzle.answer["totals"].get(s, 0)}
                     for s in puzzle.answer["best"]],
            "best_total": puzzle.answer["best_total"],
            "best_spend": puzzle.answer["best_spend"]}

    state["detail"] = grade.detail
    payout = play.finish(conn, user_id, game, on, grade, state)
    bonus = scoring.finish_day(conn, user_id, date.today())

    msg = f"{grade.detail} Earned CR {db.credits(payout):,.2f}."
    if bonus:
        msg += f" Plus CR {db.credits(bonus[0]):,.2f} — {bonus[1].split(': ')[-1]}."
    return RedirectResponse(f"/play/{game}?msg={msg}&ok={1 if grade.correct else 0}",
                            status_code=303)
