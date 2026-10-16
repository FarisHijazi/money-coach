"""Month-to-date pace: will each budget group end this calendar month within budget?

Three kinds of group:
- fixed (rent, loans, spouse): count at their budget (prepaid rent is always exactly the budget);
- lumpy (travel, one-offs): what is spent is what counts, no extrapolation (one trip isn't a daily rate);
- daily (everything else): projected linearly from this month's spending so far.
Reads DATA/categorized.csv.

Run: python3 pace.py
"""
import calendar
import csv
from collections import defaultdict
from datetime import date

from categorize import GROUP, label
from config import DATA, P

BUDGET = P.DASHBOARD["budget"]
FIXED = {"Rent", "Loans", P.SPOUSE_GROUP}
LUMPY = {"Travel", "One-offs"}


def compute(today=None):
    today = today or date.today()
    days = calendar.monthrange(today.year, today.month)[1]
    day, left, month = today.day, days - today.day, today.strftime("%Y-%m")
    spent = defaultdict(float)
    f = DATA / "categorized.csv"
    for r in csv.DictReader(open(f, encoding="utf-8-sig")) if f.exists() else []:
        if r["datetime"].startswith(month):
            spent[GROUP.get(r["category"], "Unknown")] += float(r["amount"])
    groups = []
    for g, b in BUDGET.items():
        s = b * day / days if g == "Rent" else spent[g]  # rent is prepaid yearly: always on budget
        kind = "fixed" if g in FIXED else "lumpy" if g in LUMPY else "daily"
        proj = max(s, b) if kind == "fixed" else s if kind == "lumpy" else s / day * days
        groups.append({"group": g, "label": label(g), "kind": kind, "budget": b, "spent": round(s),
                       "expected_by_now": round(b * day / days), "projected": round(proj),
                       "on_track": proj <= b + 1})
    daily = [x for x in groups if x["kind"] == "daily"]
    var_left = sum(x["budget"] - x["spent"] for x in daily)
    return {"month": month, "day": day, "days": days, "days_left": left, "groups": groups,
            "budget": sum(x["budget"] for x in groups), "spent": sum(x["spent"] for x in groups),
            "projected": sum(x["projected"] for x in groups),
            "daily_left": round(var_left), "per_day_left": round(var_left / left) if left else 0}


def text(p=None):
    p = p or compute()
    over = p["projected"] - p["budget"]
    lines = [f"Month pace (day {p['day']}/{p['days']}): projected {p['projected']:,} vs budget {p['budget']:,} — "
             + (f"{over:,} OVER" if over > 0 else f"{-over:,} under")]
    for x in sorted(p["groups"], key=lambda x: x["budget"] - x["projected"]):
        if x["kind"] == "fixed" and x["on_track"]:
            continue
        mark = (f"{x['projected'] - x['budget']:,} over" if not x["on_track"]
                else f"{x['budget'] - x['spent']:,} left" if x["kind"] == "lumpy" else "on track")
        lines.append(f"  {'🟢' if x['on_track'] else '🔴'} {x['label']}: {x['spent']:,} so far → {x['projected']:,} "
                     f"projected (budget {x['budget']:,}) {mark}")
    lines.append(f"Everyday budget left (food, shopping, life admin, fun, giving, unknown): "
                 f"{p['daily_left']:,} SAR → {p['per_day_left']:,}/day for the remaining {p['days_left']} days")
    return "\n".join(lines)


if __name__ == "__main__":
    print(text())
