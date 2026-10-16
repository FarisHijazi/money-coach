"""Savings if the money rules had applied on NON-travel days (Feb 1 – Sep 30 2026). Run from the repo root."""
import csv, re, sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import P

TRIPS = P.TRIPS  # (first day, last day) of each trip
TOYS = P.TOY_SUBS  # subscriptions the "no toy subscriptions" rule would cut
on_trip = lambda d: any(a <= d <= b for a, b in TRIPS)

rows = [r for r in csv.DictReader(open("categorized.csv", encoding="utf-8-sig"))
        if "2026-02-01" <= r["datetime"][:10] <= "2026-09-30" and not on_trip(r["datetime"][:10])]
by_month = defaultdict(lambda: defaultdict(list))
for r in rows:
    by_month[r["datetime"][:7]][r["category"]].append(r)

saved = defaultdict(float); post = defaultdict(float)
def add(rule, m, amt):
    saved[rule] += amt
    if m >= "2026-06": post[rule] += amt  # Jun–Sep

for m, cats in by_month.items():
    deliv = sorted(cats["Food delivery"], key=lambda r: r["datetime"])
    add("Delivery: max 4 orders/month", m, sum(float(r["amount"]) for r in deliv[4:]))
    online = sorted(cats["Online shopping"], key=lambda r: -float(r["amount"]))
    add("Amazon/online: max 2 orders/month", m, sum(float(r["amount"]) for r in online[2:]))
    add("No new gadgets", m, sum(float(r["amount"]) for r in cats["Home lab / gadgets"]))
    add("No toy subscriptions", m, sum(float(r["amount"]) for r in cats["AI & software subs"] if TOYS.search(r["merchant"])))

for name, d in (("Feb–Sep, non-travel days", saved), ("Jun–Sep only", post)):
    print(f"== {name}")
    for k, v in d.items(): print(f"  {k:36}{v:9,.0f}")
    print(f"  {'TOTAL':36}{sum(d.values()):9,.0f}")
