# Film Stock Exchange

A price engine for a market in film talent, and the read-only site that
publishes it. Prices move on awards, box office and critical reception, and on
nothing else.

**Phase 0** answered one question: does a film-literate person read the ranked
list and find it defensible? **Phase 1** published the prices as a static site.
**Phase 2** added the game: accounts, Credits, portfolios, trading and
leaderboards. **Phase 3** is the daily habit: puzzles that pay the Credits the
market runs on.

## Run it

```bash
make setup      # pip install -r requirements.txt
make dev        # seeds the market if empty, serves on http://localhost:8000
```

Python 3.9 or newer — including the 3.9 Apple ships as `/usr/bin/python3`, which
CI tests on every push alongside 3.12.

Then open http://localhost:8000, click **Sign in**, and choose **Continue as a
test player**. That is a local account with no OAuth application behind it — it
starts with CR 500.00 so you can buy something, sell it and watch a leaderboard
move in one sitting, and it refuses to exist when `FSX_ENV=production`.

No API keys are needed to run it. The market is built from the committed
snapshot in `data/people.json`; keys are only for refreshing that snapshot.

```bash
make test       # 246 tests
make check      # tests, then crawl every page looking for a dead link
make seed       # rebuild two years of weekly price history from scratch
make clean      # throw away the local database and start over
```

There are two surfaces and it is worth knowing which is which:

| | what it is | how to run it |
| --- | --- | --- |
| **The app** | the game — market, trading, portfolios, leaderboards, daily puzzles | `make dev` |
| **`site/`** | a read-only static export of the market, for GitHub Pages | `make site` |

`site/` has no accounts and no games by design. If you open `site/index.html`
expecting the game, it will look like half a product, because it is the half
that can be served from a CDN with no server at all.

### With API keys

Copy `.env.example` to `.env` and fill in what you have:

```bash
make refresh          # refetch the roster from TMDB/OMDb, then rebuild prices
make refresh CREDITS=60   # ...shallower and faster
```

`CREDITS` counts **work** per person, not lines on a filmography. 100 reaches
the 90th percentile of real filmographies; 60 truncates about 90 people. Every
film already fetched is cached, so a run you stop resumes where it left off.

`SESSION_SECRET` is required in production and the app refuses to boot without
it, because a signed session cookie with a known key is a forgeable one. Google
and GitHub OAuth pairs are optional; the sign-in page offers only the buttons
that are configured.

## What can be hosted where

The game is a Python server with a SQLite database. **GitHub Pages cannot run
it** — Pages serves files. So:

| | where it goes |
| --- | --- |
| The game (`app/`) | Fly.io or Render — see `DEPLOY.md` |
| The static market (`site/`) | GitHub Pages, built nightly by `.github/workflows/rebuild.yml` |

A Pages deploy of this repo will always be the read-only half. That is not a
broken deploy; it is the only half a static host can serve.

## The site

`fsx.cli site` reads `data/people.json` and writes a static `site/` — no server,
no database. Fetching and rendering are deliberately split: a rebuild takes under
a second offline, and a bad render can never cost an API quota.

- **The market** — every stock ranked, with 1-year and 90-day moves and a
  5-year sparkline.
- **A stock page** — price history, and a *why it moved* panel listing the
  largest scoring events behind today's price. A market game whose prices cannot
  be interrogated is a black box.
- **How prices work** — the formula, in plain language.
- **`market.json`** — the whole market as data, for whatever comes next.

Price history is computed, not accumulated. The engine takes an as-of date, so
running it backwards produces the real series a career would have had — day one
ships with years of chart.

`.github/workflows/rebuild.yml` rebuilds nightly and deploys to GitHub Pages. If
the API keys are absent it still builds from the committed snapshot, so a data
outage serves yesterday's prices rather than taking the site down.

## How a price is made

One number, **Career Points**, run through one curve:

```
price = 2.50 + 0.05 × CP^0.88
```

CP is the decayed sum of every scoring event in a career. Four components, all
scaled by the person's role weight in that film:

| Component | At role weight 1.0 |
| --- | --- |
| Working points | +160 per credit |
| Reception | (RS − 50) × 5, so −250 to +250 |
| Box office | −540 to +1,980, then judged against the reviews |
| Awards | +60 to +1,350, role weight not applied |

Then two forces pull down: **age decay**, floored so an old Oscar never becomes
worthless, and an **idle multiplier** that bites while nothing is coming out and
stops the moment something does.

Because the curve compresses at the top, one Oscar nomination is +171% to a debut
stock and +2.5% to a legend. That is the whole design — scouting beats hoarding —
and it falls out of the math rather than needing a rule.

## Layout

```
fsx/
  constants.py    every tunable, in one place
  models.py       Credit, Award, Person, Valuation
  roles.py        billing position -> role weight
  reception.py    five review scales -> one 0-100 score
  boxoffice.py    multiple of budget -> points
  awards.py       the awards table, first-win bonus, snub clawback
  decay.py        age decay, idle multiplier, the price curve
  engine.py       puts it together, resolves the tier/CP circularity
  reference.py    the six careers the constants were fitted to
  sources/        TMDB and OMDb adapters behind one interface
  fixtures/       hand-entered careers for judging the engine without keys
scripts/
  doc_figures.py  regenerates every number the design doc quotes
```

## What the data actually looks like

Measured, not assumed. Coverage figures come from sampling one actor's 75-film
filmography on Wikidata and 15 recent films on Wikipedia.

| Data | Source | Coverage | Cost |
| --- | --- | --- | --- |
| People, credits, **billing order** | TMDB | full | free / negotiated |
| Budget and worldwide gross | Wikipedia infobox | 87% / 93% | free |
| Budget and worldwide gross | TMDB | patchy under ~$10M | free |
| RT Tomatometer, Metacritic | Wikidata | ~85% have one, RT far more than MC | free |
| IMDb rating **and vote count** | OMDb | full | $1+/mo lifts the 1,000/day cap |
| Awards, dated and per-film | Wikidata | rich | free |
| RT Audience Score | — | none | — |
| Letterboxd | — | declined for this use case | — |

**TMDB is the one source with no substitute.** Wikidata carries billing order on
0% of cast statements, and Wikipedia's `starring` field is the poster billing
block — a median of 6 names. Neither can tell 13th billed from 20th, and role
weight is the backbone of every working actor's valuation.

**Wikidata replaces the manual awards entry** the design doc budgeted for. One
query returned 70 dated award statements for a single actor, linked to the film.
That was the weakest part of the pipeline and it is now automated.

**OMDb is now optional.** Without it you still get RT and Metacritic from
Wikidata, but you lose the IMDb rating and its vote count — and the vote count
is what drives the confidence factor, so every credit scores at reduced
confidence. You also lose the audience side of the Reception Score entirely:
RT Tomatometer and Metacritic are both critic measures, so the documented
40% critic / 40% audience / 20% cinephile split collapses to all-critic.
Run `--no-omdb` to try it; keep OMDb if you want the split the design assumes.

## Tuning

`fsx/constants.py` holds every number. Change one, then:

```bash
python3 -m pytest tests/ -q          # what did it cost?
python3 scripts/doc_figures.py       # reconcile the design doc
```

The tests pin six reference careers and four worked examples to the design doc.
If one fails, decide whether the change was wrong or the doc needs updating —
do not just move the number.

## Known gaps

- **Fixture figures are hand-entered approximations.** They test ordering, not
  price. Do not publish a number that came out of `fsx.cli fixtures`.
- **Screen-time data is not wired up.** The runtime-share override exists but no
  source fills it, so the classifier runs on billing position alone.
- **The ensemble weight cap needs the full scored cast** of a film, which the
  backfill does not yet assemble across people.
- **Television is modelled but not fetched.**
- **No re-rate job.** The two-year cult-classic reappraisal is specified in the
  design doc and not implemented here.


## Phase 2: the game

Sign-in is Google or GitHub, plus the local test player described under
**Run it**. **No password is ever collected, hashed, reset or breached**,
because none is ever asked for.

### Held value, the one idea worth understanding

A position is not worth the market price. It is worth its **held value**, which
starts at the entry price and then moves by each gain *scaled by how long you
had already held when the gain happened*, and by each loss in full.

| Held before the move | You realise |
| --- | --- |
| under 7 days | 40% |
| 7–29 days | 70% |
| 30–89 days | 100% |
| 90–364 days | 115% |
| 365+ days | 130% |

Two people holding the same stock on the same night can end the night worth
different amounts. Selling settles at held value, not at the quote — so a
long-held winner pays out *above* the market price, and buying the morning after
an Oscar pays well below it.

### The rest of the rules

1.5% fee both ways · 1-day settlement after every buy · no position cap, so
you can put everything into one name · 10 free slots, then CR 20.00 each,
escalating past 25 ·
quarterly dividends of 0.5% plus 0.25% per full year held, capped at 2%.

### The nightly job

`python -m app.jobs mark` reprices the market from the snapshot and marks every
position through the conviction ladder. It is **idempotent** — a day already
marked is never marked twice, however many times it runs, because paying a gain
twice is the one failure nobody would spot.

### Money

Credits are `INTEGER` centidollars everywhere. Nothing in this app puts money in
a float, and every mutation runs in a transaction. `tests/test_trading.py`
asserts that a user's balance always equals the sum of their ledger.

### Deploying

`Dockerfile` plus `render.yaml` (web service + nightly cron, both on a shared
persistent disk) or `fly.toml`. SQLite lives on the mounted disk, never in the
image — otherwise every deploy wipes every portfolio. OAuth callback URLs are
`https://YOUR-HOST/auth/google/callback` and `/auth/github/callback`.


## Phase 3: the daily games

Sign in, then visit `/play`. Four puzzles a day plus a weekend one, all generated from the same film data
that prices the market — so playing them teaches you to read it.

| Game | What it asks | Pays |
| --- | --- | --- |
| Six Degrees | Connect two actors through films they shared | CR 0.60–1.80 |
| The Ladder | Six films, obscurest first — name the actor | CR 0.60–1.80 |
| Box Office Blind | Rank five films by worldwide gross | CR 0.40–1.20 |
| Cast Gap | One name is missing from the billing | CR 0.40–1.20 |
| The Slate *(weekend)* | Highest-grossing cast inside a budget | CR 4.00–12.00 |

Plus a CR 2.50 perfect-day bonus and CR 0.50 per streak day, capped at 5.00. A
perfect day with the weekend puzzle tops out around CR 16.00.

**A fifth game, Critics vs Crowd, is deliberately absent.** It needs the Rotten
Tomatoes audience score, which is not licensable — see the data table above. The
slot stays empty rather than being filled with a proxy.

### Two rules the generators obey

**Deterministic per day.** The seed is a hash of the game name and the date, so
everyone gets the same puzzle and nothing has to be stored. A daily game people
cannot compare notes on is just a quiz.

**The answer never leaves the server.** A puzzle has a public half that goes to
the browser and a private half that does not. Every guess is a POST the server
grades.

### Fairness

Films below 20,000 IMDb votes never appear — a puzzle nobody could solve is
worse than no puzzle. Solve rates are recorded per puzzle in `puzzle_stats`, so
a generator producing something under 15% or over 95% can be spotted and tuned.
When the corpus cannot make a fair puzzle, the generator raises `NotEnoughData`
and the hub says so, rather than shipping something broken.

Every game has a **floor**: bombing all four still pays CR 2.00. Being bad at
film trivia should not exclude you from the market — the market is the game and
the puzzles are the way in.

`UNIQUE(user_id, game, on_date)` is the anti-replay mechanism: a day's puzzle
pays exactly once, whatever anyone does with the form.

### On fixture data

Six Degrees reports itself unavailable, and it is right to. The 25 fixture
careers give a cast web whose largest connected group is four people. It needs
the real backfill; its generator is proved against a synthetic dense corpus in
`tests/test_games.py`.


## Box office is judged against the reviews

Money and reviews are not independent signals. Four quadrants:

| | well reviewed | badly reviewed |
| --- | --- | --- |
| **made money** | a hit — full credit | a paycheque — 40% of it |
| **lost money** | art — 15% of the penalty | a flop — the full penalty |

Without this, *Crime 101* ($90M budget, $73M gross, Reception 61) cost Chris
Hemsworth exactly what *Red Dawn* did, and *Red Dawn* scored 29. *Killers of
the Flower Moon* and *The Irishman* were being punished like failures. Some
films are not trying to make money, and the engine now knows the difference.

The modifier ramps rather than steps, so nothing hinges on a film scoring 39
instead of 41, and a film with no reviews on file is judged neither way.


## Not every credit is a performance

A fifth of the corpus is not: documentary interviews, making-of featurettes,
awards-show appearances, and old clips spliced into someone else's film. TMDB
says which in the character field.

| character | what it is | cap |
| --- | --- | --- |
| `Ethan Hunt` | a part | 1.00 |
| `Narrator (voice)` | real work, but not carrying a film | 0.40 |
| `Self` | you turned up | 0.10 |
| `Self (archive footage)` | you were not there | 0.00 |

Scored as parts, these made a documentary *about* Tom Cruise read as a film he
led, and gave him a 47-minute IMAX documentary he narrated as his second
biggest career event. Archive footage also counted as "having something out",
which held off idle decay for people who had not worked in years.

The same distinction fixes something larger. `--max-credits` counts work now,
not lines on a filmography — it used to take the most recent N of everything,
and for a veteran most of those are documentaries about them. Harrison Ford's
window reached back only to 2010, so *Raiders*, *Witness* and *Air Force One*
were never fetched at all. Across the roster that dropped **4,803 real films**,
including 100 of De Niro's 123.

## Streaming and limited releases

TMDB's `/movie/{id}/release_dates` tags every release by type — premiere,
limited theatrical, theatrical, digital, physical, TV. A film that never had a
**wide** run was not selling tickets, so its multiple of budget is not a
verdict on anything:

```
The Irishman         limited 2019-11-01  digital 2019-11-27   26d  -> streaming
The Two Popes        limited 2019-11-27  digital 2019-12-20   23d  -> streaming
Killers of the Moon  wide    2023-10-20  digital 2023-12-05   46d  -> judged
Crime 101            wide    2026-02-13  digital 2026-04-01   47d  -> judged
Oppenheimer          wide    2023-07-21  digital 2023-11-21  123d  -> judged
```

Release type is the signal. The theatrical-to-digital window is the fallback
where TMDB has no typed release: under 21 days and the theatrical run was not
the point. A typed **wide** release beats a short window, because a studio
dumping a film early is a flop, not a streaming title.

Films released March 2020 – December 2021 are exempt. Judging that cohort on
box office says more about the pandemic than about anyone's career.

Both cases score zero rather than a penalty, and carry the verdict `streaming`
or `pandemic` so the why-it-moved panel can say so. Reception and awards carry
those credits, which is what was always meant to happen.
