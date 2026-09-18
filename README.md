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

| Data | Source | Status |
| --- | --- | --- |
| People, credits, billing, budget, gross | TMDB | Free for non-commercial; commercial negotiated |
| IMDb rating and votes, Metascore, RT Tomatometer | OMDb | $1+/month Patreon lifts the 1,000/day cap |
| RT Audience Score | — | Not obtainable |
| Letterboxd | — | Declined for this use case |
| Awards | Wikidata + manual | No free API is good enough |

The Reception Score is built to run on three of five sources, so launching on
IMDb, Metascore and RT Tomatometer is the intended configuration, not a degraded
one. RT Audience and Letterboxd are config changes plus a backfill if either is
ever licensed.

Awards are **not** fetched by the backfill. Roughly 400 rows a year across the
ceremonies that matter, entered the morning after each announcement, is the
honest answer — and it is the one part of the pipeline that must never be wrong.

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
