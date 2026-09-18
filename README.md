# Film Stock Exchange — Phase 0

The price engine, and a script that prints a ranked list. No UI, no accounts.

Phase 0 answers one question: **does a film-literate person read the ranked list
and find it defensible?** If the list never looks right, the design is wrong and
nothing else matters. Everything here exists to produce that list.

## Run it

```bash
pip install -r requirements.txt

python3 -m fsx.cli fixtures     # 25 hand-entered careers, no API key needed
python3 -m fsx.cli reference    # the six careers the constants were fitted to
python3 -m pytest tests/ -q     # 53 tests pinning the engine to the design doc
```

With API keys in `.env` (copy `.env.example`):

```bash
python3 -m fsx.cli backfill roster.example.txt
```

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
