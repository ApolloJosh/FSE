# Film Stock Exchange

A price engine for a market in film talent, and the read-only site that
publishes it. Prices move on awards, box office and critical reception, and on
nothing else.

**Phase 0** answered one question: does a film-literate person read the ranked
list and find it defensible? **Phase 1** is this site — public prices, charts,
and an explanation of every move. No accounts, no trading.

## Run it

```bash
pip install -r requirements.txt
python3 -m pytest tests/ -q      # 131 tests

python3 -m fsx.cli snapshot      # fixture careers -> data/people.json, no keys
python3 -m fsx.cli site          # build the market into site/
python3 -m http.server -d site 8000
```

With API keys in `.env` (copy `.env.example`):

```bash
python3 -m fsx.cli backfill roster.txt --max-credits 60   # fetch + snapshot
python3 -m fsx.cli site                                   # render
```

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
| Box office | −360 to +660 |
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
