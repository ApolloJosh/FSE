"""What happens to the ranking if 'simply working' is worth less?

Working points are currently 58% of all value in the market, because real
filmographies run to ~58 credits and the constants were fitted against
reference careers of 35. This re-ranks the whole roster at several values so
the trade-off can be seen rather than argued about.
"""
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fsx import constants as K            # noqa: E402
from fsx.engine import value_person       # noqa: E402
from fsx.store import load                # noqa: E402

people, _ = load(Path("data/people.json"))
TODAY = date.today()
WATCH = ["Tom Cruise", "Daniel Day-Lewis", "Kieran Culkin", "Spike Lee",
         "Meryl Streep", "Sean Baker", "Zoe Saldaña", "Olivia Colman"]

for w in (160, 120, 90, 60, 40):
    K.WORKING_POINTS = float(w)
    vals = sorted((value_person(p, TODAY) for p in people), key=lambda v: -v.price)
    rank = {v.person: i for i, v in enumerate(vals, 1)}
    prices = [v.price for v in vals]
    tiers = Counter(v.tier for v in vals)
    share = sum(abs(v.working_cp) for v in vals) / sum(
        abs(v.working_cp) + abs(v.reception_cp) + abs(v.box_office_cp) + abs(v.award_cp)
        for v in vals)
    print(f"\n--- WORKING_POINTS = {w} "
          f"(working is {share:.0%} of all value) ---")
    print(f"    median CR {median(prices):>6.2f}   under CR20 {sum(1 for p in prices if p < 20):>3}"
          f"   Legend {tiers.get('Legend',0)}  A-List {tiers.get('A-List',0)}"
          f"  Established {tiers.get('Established',0)}  Recognized {tiers.get('Recognized',0)}")
    print("    " + "  ".join(f"{n.split()[-1]}#{rank.get(n,'-')}" for n in WATCH))
