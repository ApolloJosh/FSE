"""Re-rank from data/people.json, offline. Compares against a saved baseline."""
import sys, csv, collections
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fsx.store import load
from fsx.cli import rank, print_distribution

people, asof = load(Path("data/people.json"))
values = rank(people)
by_name = {v.person: v for v in values}

base = {}
p = Path(sys.argv[1]) if len(sys.argv) > 1 else None
if p and p.exists():
    for row in csv.DictReader(p.open()):
        base[row["person"]] = float(row["price"])

print(f"snapshot {asof}  people {len(values)}\n")
print("%-4s %-26s %9s %9s" % ("#", "name", "price", "delta"))
for i, v in enumerate(values[:25], 1):
    d = v.price - base[v.person] if v.person in base else None
    print("%-4d %-26s %9.2f %9s" % (i, v.person[:26], v.price,
                                    f"{d:+.2f}" if d is not None else "-"))
if base:
    moves = [(v.price - base[v.person], v.person, base[v.person], v.price)
             for v in values if v.person in base]
    moves.sort(reverse=True)
    print("\nbiggest risers:")
    for d, n, b, a in moves[:10]: print("  %-26s %7.2f -> %7.2f  %+.2f" % (n[:26], b, a, d))
    print("\nbiggest fallers:")
    for d, n, b, a in moves[-5:]: print("  %-26s %7.2f -> %7.2f  %+.2f" % (n[:26], b, a, d))
    print("\nmoved at all: %d of %d" % (sum(1 for m in moves if abs(m[0]) > 0.005), len(moves)))
print()
print_distribution(values)

from fsx.cli import write_csv, OUT_DIR
if "--write" in sys.argv:
    print("\nWrote", write_csv(values, OUT_DIR / "backfill_ranked.csv"))
