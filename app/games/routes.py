"""Routes for the daily games."""

from __future__ import annotations

from datetime import date

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
def hub(request: Request, msg: str | None = None, ok: int = 0):
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
    return views.hub(summary, unavailable, user, on,
                     scoring.streak_length(conn, user["id"], on),
                     bool(weekly_row and weekly_row["done"]), msg or "", bool(ok))


def _weekly_date(on: date) -> date:
    """The weekly puzzle is keyed to the Friday of its week, so a weekend of
    play is one puzzle rather than three."""
    return on - __import__("datetime").timedelta(days=(on.weekday() - 4) % 7)


@router.get("/play/{game}", response_class=HTMLResponse)
def show(request: Request, game: str, msg: str | None = None, ok: int = 0):
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

    elif game == "six-degrees":
        names = [(form.get(f"step_{i}") or "").strip() for i in range(1, 5)]
        by_name = {corpus.name(s): s for s in corpus.by_person}
        middle = [by_name[n] for n in names if n in by_name]
        chain = [puzzle.answer["from"], *middle, puzzle.answer["to"]]
        valid, _ = check_chain(corpus, chain)
        grade = scoring.grade_six_degrees(puzzle, valid, len(chain) - 1)

    elif game == WEEKLY:
        picked = [str(v) for v in form.getlist("pick")]
        if len(set(picked)) != 5:
            # An unfinished form is not a wrong answer. Grading it spent the
            # week's puzzle on a submission the player had not made yet.
            return RedirectResponse(
                f"/play/{game}?msg=Pick exactly five, then lock it in.&ok=0",
                status_code=303)
        grade = scoring.grade_slate(puzzle, picked)

    state["detail"] = grade.detail
    payout = play.finish(conn, user_id, game, on, grade, state)
    bonus = scoring.finish_day(conn, user_id, date.today())

    msg = f"{grade.detail} Earned CR {db.credits(payout):,.2f}."
    if bonus:
        msg += f" Plus CR {db.credits(bonus[0]):,.2f} — {bonus[1].split(': ')[-1]}."
    return RedirectResponse(f"/play/{game}?msg={msg}&ok={1 if grade.correct else 0}",
                            status_code=303)
