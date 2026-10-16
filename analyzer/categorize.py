"""Categorize every spend row of ledger.csv and emit summary.json for the dashboard.

Card/mada purchases get a merchant category (P.CATS); non-card flows (spouse, loans, rent,
people, bills...) keep their ledger sub-bucket. Window: P.WINDOW.
"""
import csv
import json
import re
from collections import defaultdict

from config import DATA, P

WIN = P.WINDOW
CATS = P.CATS  # first match wins; regex on merchant + SMS text
CARD_SUBS = {"purchase", "refund", "atm", "travel_cash"}
NONCARD = {  # ledger sub -> category
    "wife": P.SPOUSE_LABEL, "loan": "Loans", "rent": "Rent", "therapy": "Therapy",
    "people": "Transfers to people", "family": "Family & gifts", "bill": "Bills (power, phone, fines)",
    "fee": "Bank fees",
}

# Display only: names stay plain everywhere they are matched (budgets, weekly check, colors).
ICONS = {
    # categories
    "Restaurants & cafés": "🍽️", "Food delivery": "🛵", "Groceries": "🛒", "Online shopping": "📦",
    "Home & furniture": "🛋️", "Clothes & beauty": "👗", "Home lab / gadgets": "🖥️", "AI & software subs": "🤖",
    "Travel": "✈️", "Transport & car": "🚗", "Health & gym": "💪", "Therapy": "🧠",
    "Bills (power, phone, fines)": "🧾", "Gov, rent fees & telecom": "🏛️", "Laundry & home services": "🧺",
    "Bank fees": "🏦", "Transfers to people": "💸", "Family & gifts": "👨‍👩‍👧", "Gifts & flowers": "💐",
    "Charity": "🤲", "Cash withdrawals": "💵", "Fun & events": "🎉", "Loans": "📉", "Rent": "🏠",
    "Other / unknown": "❓", P.SPOUSE_LABEL: "💍", P.ONE_OFF_LABEL: "🎁",
    # dashboard groups
    "Shopping": "🛍️", "Food": "🍔", "Life admin": "🗂️", "People & giving": "🤝", "Fun": "🎉",
    "One-offs": "🎁", "Unknown": "❓", P.SPOUSE_GROUP: "💍",
}


def label(name):
    """ "🍽️ Restaurants & cafés" — for printing only."""
    return f"{ICONS[name]} {name}" if name in ICONS else name


def merchant(x):
    m = x["counterparty"]
    if not m or re.fullmatch(r"[\d*;\s]+", m):
        mm = re.search(r"لدى\s*:?\s*([^|\n]+)", x["text"]) or re.search(r"(?:At|From)\s*:?\s*([^|\n]+)", x["text"])
        m = mm.group(1) if mm else ""
    return re.sub(r"\s+", " ", m).strip()


def foreign(text):
    return bool(re.search(r"دولي|International|دولة: (?!SA)|Country:(?!\s*SA)|\b(USD|EUR|TRY|MUR|ZAR|OMR|TZS|CZK|GBP|AED)\b",
                          text)) and not re.search(r"Country:\s*Saudi|في SAU", text)


def category(x):
    if x["sub"] == "atm" and x["datetime"][:10] in P.ONE_OFF_ATM_DATES:
        return P.ONE_OFF_LABEL
    if x["sub"] == "atm":
        return "Travel" if foreign(x["text"]) else "Cash withdrawals"
    if x["sub"] == "travel_cash":
        return "Travel"
    m = merchant(x)
    hay = f"{m} {x['text']}".upper()
    for cat, pat in CATS:
        if re.search(pat, m.upper()):
            return cat
    for cat, pat in CATS:  # fall back to the whole SMS text
        if cat not in ("Restaurants & cafés",) and re.search(pat, hay):
            return cat
    return "Travel" if foreign(x["text"]) else "Other / unknown"


def main():
    L = list(csv.DictReader(open(DATA / "ledger.csv", encoding="utf-8-sig")))
    out, monthly, merch = [], defaultdict(lambda: defaultdict(float)), defaultdict(lambda: defaultdict(float))
    for x in L:
        mo = x["datetime"][:7]
        if not (WIN[0] <= mo <= WIN[1]) or x["bucket"] != "expense":
            continue
        if x["sub"] in CARD_SUBS:
            cat = category(x)
        else:
            cat = NONCARD.get(x["sub"], "Other / unknown")
        a = float(x["amount"])
        monthly[mo][cat] += a
        if x["sub"] in CARD_SUBS:
            merch[cat][merchant(x).upper()[:28] or "?"] += a
        out.append({**{k: x[k] for k in ("datetime", "bank", "amount", "counterparty")}, "merchant": merchant(x),
                    "category": cat, "text": x["text"]})
    with open(DATA / "categorized.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, list(out[0]))
        w.writeheader()
        w.writerows(out)
    tot = defaultdict(float)
    for mo in monthly:
        for c, v in monthly[mo].items():
            tot[c] += v
    n = len(monthly)
    print(f"{'category':32}{'total':>10}{'/mo':>9}")
    for c in sorted(tot, key=lambda c: -tot[c]):
        print(f"{c:32}{tot[c]:10,.0f}{tot[c]/n:9,.0f}")
    print(f"{'TOTAL':32}{sum(tot.values()):10,.0f}{sum(tot.values())/n:9,.0f}")
    unk = sorted(merch["Other / unknown"].items(), key=lambda kv: -kv[1])[:40]
    print("\nTop unknown merchants:", [(k, round(v)) for k, v in unk])
    json.dump({"months": sorted(monthly), "monthly": {m: dict(v) for m, v in monthly.items()},
               "top_merchants": {c: sorted(((k, round(v)) for k, v in d.items()), key=lambda kv: -kv[1])[:12]
                                 for c, d in merch.items()}},
              open(DATA / "summary.json", "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
