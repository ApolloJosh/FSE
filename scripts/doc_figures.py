"""Regenerate every number the design doc quotes, straight from the engine.

The engine is the source of truth. Run this after changing any constant and
reconcile the design doc against the output.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fsx import constants as K                      # noqa: E402
from fsx.decay import price_from_cp, tier_for_cp    # noqa: E402
from fsx.engine import conviction_multiplier, value_person  # noqa: E402
from fsx.models import Award, Credit, Person        # noqa: E402
from fsx.reference import AS_OF, reference_careers  # noqa: E402

LINE = "-" * 78


def h(title: str) -> None:
    print(f"\n{title}\n{LINE}")


def credit(years_ago: float, rw: float, rs: float, bop: float, scale: float) -> Credit:
    return Credit(title="c", release_date=AS_OF - timedelta(days=round(years_ago * 365.25)),
                  role_weight_override=rw, reception_override=rs, confidence_override=1.0,
                  bop_override=bop, scale_override=scale)


h("REFERENCE CAREERS")
for v in sorted((value_person(p, AS_OF) for p in reference_careers()),
                key=lambda v: -v.price):
    print(f"  {v.person:<18} CP {v.cp:>9,.0f}   price {v.price:>8,.2f}   {v.tier}")

h("TIER BANDS")
prev = 0.0
for threshold, name, _, _ in K.DECAY_TIERS:
    top = 26000 if threshold == float("inf") else threshold
    print(f"  {name:<12} CP {prev:>7,.0f}-{top:<7,.0f}  "
          f"CR {price_from_cp(prev):>7,.2f} - {price_from_cp(top):>7,.2f}")
    prev = threshold

h("ONE OSCAR LEAD NOMINATION (+400 CP), BY TIER")
for name, cp in [("Debut", 95), ("Working", 400), ("Recognized", 1500),
                 ("Established", 4000), ("A-List", 9000), ("Legend", 14000)]:
    p0, p1 = price_from_cp(cp), price_from_cp(cp + 400)
    print(f"  {name:<12} {p0:>8,.2f} -> {p1:>8,.2f}   {100 * (p1 / p0 - 1):+7.1f}%")

h("EVENT VALUES AT ROLE WEIGHT 1.0")
print(f"  one credit (working points)        {K.WORKING_POINTS:>+8,.0f} CP")
print(f"  reception RS 85                    {(85 - 50) * K.RECEPTION_COEF:>+8,.0f} CP")
print(f"  reception RS 25                    {(25 - 50) * K.RECEPTION_COEF:>+8,.0f} CP")
for upper, bop in K.BOX_OFFICE_LADDER:
    label = f"box office under {upper}x" if upper != float("inf") else "box office 15x+"
    print(f"  {label:<34} {bop:>+8,.0f} CP")

h("IDLE DECAY BY TIER")
profiles = {
    "Debut": ([credit(0.0, 0.30, 67.5, 120, 0.92)], []),
    "Working": ([credit(0.5 + i * 0.8, 0.35, 57, 48, 0.93) for i in range(15)], []),
    "Recognized": ([credit(0.5 + i * 0.6, 0.45, 62, 90, 0.94) for i in range(25)],
                   [(3, 340), (3, 130), (3, 110)]),
    "Established": ([credit(0.5 + i * 0.7, 0.55, 64, 150, 0.95) for i in range(28)],
                    [(4, 400), (4, 140), (4, 130), (9, 340)]),
    "A-List": ([credit(0.5 + i * 0.8, 0.75, 68, 210, 0.97) for i in range(35)],
               [(a, v) for age in (22, 18, 14, 11, 8, 5, 2)
                for a, v in ((age, 400), (age, 140), (age, 110), (age, 130), (age, 70))]
               + [(5, 1350)]),
    "Legend": ([credit(0.5 + i * 0.82, 0.70, 66, 120, 0.95) for i in range(60)],
               [(a, v) for i in range(21)
                for a, v in ((2 + i * 2.3, 380), (2 + i * 2.3, 110), (2 + i * 2.3, 140))]
               + [(44, 1350), (30, 900), (14, 900)]),
}


def synth(name, credits, awards, shift=0.0):
    person = Person(name)
    for c in credits:
        person.credits.append(
            Credit(title="c", release_date=c.release_date - timedelta(days=round(shift * 365.25)),
                   role_weight_override=c.role_weight_override,
                   reception_override=c.reception_override, confidence_override=1.0,
                   bop_override=c.bop_override, scale_override=c.scale_override))
    for years_ago, raw in awards:
        key = f"_doc_{raw:g}"
        K.AWARD_TABLE.setdefault(key, (raw, 0))
        person.awards.append(Award(key=key, year=2020, awarded_on=AS_OF - timedelta(
            days=round((years_ago + shift) * 365.25))))
    return person


print(f"  {'Tier':<12} {'now':>9} {'+1y':>9} {'+3y':>9} {'+5y':>9}   "
      f"{'1y':>7} {'3y':>7} {'5y':>7}")
for name, (credits, awards) in profiles.items():
    base = value_person(synth(name, credits, awards), AS_OF).price
    out = [value_person(synth(name, credits, awards, s), AS_OF).price for s in (1, 3, 5)]
    print(f"  {name:<12} {base:>9,.2f} {out[0]:>9,.2f} {out[1]:>9,.2f} {out[2]:>9,.2f}   "
          f"{100 * (out[0] / base - 1):>6.1f}% {100 * (out[1] / base - 1):>6.1f}% "
          f"{100 * (out[2] / base - 1):>6.1f}%")

h("WORKED EXAMPLE: THE BREAKOUT")
K.AWARD_TABLE.setdefault("_sagglobe", (130, 0))
K.AWARD_TABLE.setdefault("_globe2", (110, 0))
stages = []
c1 = credit(2.0, 0.30, 67.5, 120, 0.92)
c2 = credit(0.0, 0.80, 74, 120, 0.94)
p = Person("breakout", credits=[credit(0.0, 0.30, 67.5, 120, 0.92)])
stages.append(("Year 0  debut supporting", value_person(p, AS_OF)))
p = Person("breakout", credits=[c1, c2])
stages.append(("Year 2  co-lead", value_person(p, AS_OF)))
aw = [Award("_sagglobe", 2025, AS_OF), Award("_globe2", 2025, AS_OF)]
p = Person("breakout", credits=[c1, c2], awards=list(aw))
stages.append(("Year 2  + SAG and Globe noms", value_person(p, AS_OF)))
aw2 = aw + [Award("oscar_supporting", 2025, AS_OF)]
p = Person("breakout", credits=[c1, c2], awards=list(aw2))
stages.append(("Year 2  + Oscar nomination", value_person(p, AS_OF)))
aw3 = aw + [Award("oscar_supporting", 2025, AS_OF, won=True)]
p = Person("breakout", credits=[c1, c2], awards=list(aw3))
stages.append(("Year 2  + WINS (first-win 1.5x)", value_person(p, AS_OF)))

prev = None
for label, v in stages:
    move = "" if prev is None else f"   {100 * (v.price / prev - 1):+6.1f}%"
    print(f"  {label:<34} CP {v.cp:>8,.0f}   CR {v.price:>8,.2f}{move}")
    prev = v.price

entry, final_price = stages[0][1].price, stages[-1][1].price
nom_price = stages[3][1].price
print(f"\n  early buyer held value  CR "
      f"{entry + (final_price - entry) * conviction_multiplier(800):>8,.2f}")
print(f"  nom-morning buyer       CR "
      f"{nom_price + (final_price - nom_price) * conviction_multiplier(1):>8,.2f}")

h("WORKED EXAMPLE: THE SNUB")
from datetime import date as _date                                    # noqa: E402
base_credits = [credit(4.0, 0.60, 64, 120, 0.95), credit(0.0, 1.00, 72, 180, 0.97)]
precursors = [Award("globe", 2025, AS_OF - timedelta(days=30)),
              Award("sag_individual", 2025, AS_OF - timedelta(days=20)),
              Award("bafta", 2025, AS_OF - timedelta(days=10))]
snubbed = Person("snub", credits=base_credits, awards=precursors)
# the day before nominations, and the morning they land
eve = _date(2026, 1, 22)
morning = _date(2026, 1, 23)
before = value_person(snubbed, eve)
after = value_person(snubbed, morning)
print(f"  precursor noms, nominations pending   CP {before.cp:>8,.0f}   CR {before.price:>8,.2f}")
print(f"  Oscar morning, snubbed                CP {after.cp:>8,.0f}   CR {after.price:>8,.2f}"
      f"   {100 * (after.price / before.price - 1):+.1f}%")

h("WORKED EXAMPLE: THE BOMB")
alist = [p for p in reference_careers() if p.name == "ref: A-List"][0]
v0 = value_person(alist, AS_OF)
disaster = Credit(title="bomb", release_date=AS_OF, role_weight_override=1.0,
                  reception_override=28, confidence_override=1.0,
                  bop_override=-360, scale_override=1.0)
alist.credits.append(disaster)
v1 = value_person(alist, AS_OF)
print(f"  before   CP {v0.cp:>9,.0f}   CR {v0.price:>8,.2f}")
print(f"  after    CP {v1.cp:>9,.0f}   CR {v1.price:>8,.2f}   "
      f"{100 * (v1.price / v0.price - 1):+.1f}%")
