"""Weekly accountability line: grade the last 7 days (Sun-Sat) of ledger.csv.

Run: python3 weekly_check.py   (after pipeline.py; the server runs it on every SMS push)
"""
import csv
from collections import Counter
from datetime import date, datetime, timedelta

from categorize import CARD_SUBS, NONCARD, category, merchant
from config import DATA, P

WEEKLY_BUDGET = P.WEEKLY_BUDGET  # discretionary only (excludes EXCLUDE)
EXCLUDE = {"Loans", "Rent", P.SPOUSE_LABEL}
PERSONAL_BUDGET = P.PERSONAL_BUDGET  # personal spending per month (the PERSONAL categories)
PERSONAL = {"Restaurants & cafés", "Food delivery", "Online shopping", "Home lab / gadgets",
            "AI & software subs", "Clothes & beauty", "Fun & events"}


def main():
    today = date.today()
    end = today - timedelta(days=(today.weekday() + 1) % 7)  # most recent Sunday (exclusive end)
    start = end - timedelta(days=7)
    rows, month_personal = [], 0.0
    for x in csv.DictReader(open(DATA / "ledger.csv", encoding="utf-8-sig")):
        t = datetime.fromisoformat(x["datetime"][:19])
        if x["bucket"] != "expense":
            continue
        in_week = start <= t.date() < end
        cat = category(x) if x["sub"] in CARD_SUBS else NONCARD.get(x["sub"], "Other / unknown")
        if cat in PERSONAL and t.date().replace(day=1) == today.replace(day=1):
            month_personal += float(x["amount"])
        if in_week and cat not in EXCLUDE:
            rows.append((t, cat, merchant(x).upper()[:24], float(x["amount"])))
    total = sum(r[3] for r in rows)
    late = [r for r in rows if r[0].hour >= 22 or r[0].hour < 4]
    delivery = [r for r in rows if r[1] == "Food delivery"]
    by_cat = Counter()
    for r in rows:
        by_cat[r[1]] += r[3]
    over = total - WEEKLY_BUDGET
    print(f"Week {start} → {end - timedelta(days=1)}: {total:,.0f} SAR spent (budget {WEEKLY_BUDGET:,}) — "
          + (f"{over:,.0f} OVER" if over > 0 else f"{-over:,.0f} under"))
    left = PERSONAL_BUDGET - month_personal
    print(f"SAFE TO SPEND this month (personal): {left:,.0f} SAR of {PERSONAL_BUDGET:,} "
          f"({month_personal:,.0f} spent so far in {today:%b})" + ("  ← OVER" if left < 0 else ""))
    print(f"Late-night (10pm–4am): {len(late)} purchases, {sum(r[3] for r in late):,.0f} SAR")
    print(f"Food delivery: {len(delivery)} orders, {sum(r[3] for r in delivery):,.0f} SAR")
    print("Top categories:", ", ".join(f"{c} {v:,.0f}" for c, v in by_cat.most_common(4)))
    print("Biggest buys:", ", ".join(f"{m or '?'} {a:,.0f} ({t:%a %H:%M})"
                                     for t, _, m, a in sorted(rows, key=lambda r: -r[3])[:5]))


if __name__ == "__main__":
    main()