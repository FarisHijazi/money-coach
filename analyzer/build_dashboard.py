"""Build dashboard.html (self-contained, local only) from categorized.csv + flows.csv.

Run after: parse.py -> reconcile.py -> categorize.py
"""
import csv
import json
import os
import re
import urllib.parse as up

from config import CODE, DATA, P

GROUP = {
    "Rent": "Rent", "Loans": "Loans",
    P.SPOUSE_LABEL: P.SPOUSE_GROUP,
    "Travel": "Travel",
    "Online shopping": "Shopping", "Home & furniture": "Shopping", "Clothes & beauty": "Shopping",
    "Home lab / gadgets": "Shopping",
    "Restaurants & cafés": "Food", "Food delivery": "Food", "Groceries": "Food",
    "Bills (power, phone, fines)": "Life admin", "Gov, rent fees & telecom": "Life admin", "Health & gym": "Life admin",
    "Therapy": "Life admin", "Transport & car": "Life admin", "Bank fees": "Life admin",
    "AI & software subs": "Life admin", "Laundry & home services": "Life admin",
    "Transfers to people": "People & giving", "Family & gifts": "People & giving", "Charity": "People & giving",
    "Gifts & flowers": "People & giving", "Cash withdrawals": "People & giving",
    "Fun & events": "Fun", P.ONE_OFF_LABEL: "One-offs", "Other / unknown": "Unknown",
}
CITY = P.CITIES  # city names to add to the Google Maps merchant search


def card(text):
    m = re.search(r"(\d{4})\*|\*{2,}(\d{4})|Card:\s*\*?(\d{4})|By:(\d{4})|\((\d{4})\)|Card: ?\*(\d{4})|\*\*(\d{4})", text)
    return next((g for g in (m.groups() if m else []) if g), "")


def main():
    txs = []
    for r in csv.DictReader(open(DATA / "categorized.csv", encoding="utf-8-sig")):
        m = r["merchant"] or r["counterparty"]
        cm = CITY.search(r["text"])
        city = cm.group(1) if cm else "Saudi Arabia"
        d = r["datetime"][:10].replace("-", "/")
        txs.append({
            "d": r["datetime"][:16], "m": r["datetime"][:7], "bank": r["bank"], "card": card(r["text"]),
            "a": round(float(r["amount"]), 2), "cat": r["category"], "grp": GROUP.get(r["category"], "Unknown"),
            "mer": m.strip()[:40], "sms": r["text"].replace("\n", " | "),
            "maps": "https://www.google.com/maps/search/" + up.quote(f"{m} {city}") if m.strip() else "",
            "gmail": "https://mail.google.com/mail/u/0/#search/" + up.quote(f"after:{d} before:{next_day(r['datetime'][:10])}"),
        })
    f = DATA / "flows.csv"  # from reconcile.py; absent when you have no bank statements
    flows = list(csv.DictReader(open(f, encoding="utf-8-sig"))) if f.exists() else []
    income = {}
    for r in flows:
        if r["flow"] == "income" and r["sub"] in P.INCOME_SUBS and P.WINDOW[0] <= r["date"][:7] <= P.WINDOW[1]:
            income[r["date"][:7]] = income.get(r["date"][:7], 0) + float(r["amount"])
    inc_tx, xfer_tx = [], []
    for r in flows:
        if r["flow"] == "income":
            inc_tx.append({"d": r["date"], "a": float(r["amount"]), "s": r["sub"], "t": r["desc"][:120]})
        elif r["flow"] in ("own", "card_payment") and float(r["amount"]) < 0:
            xfer_tx.append({"d": r["date"], "a": -float(r["amount"])})
    drahim = P.DRAHIM_REPORT  # Drahim app's own monthly numbers, shown next to ours
    dcat = {}
    for r in csv.DictReader(open(DATA / "drahim_categories.csv")) if (DATA / "drahim_categories.csv").exists() else []:
        dcat.setdefault(r["window"], {})[r["category"]] = float(r["amount"])
    data = {"txs": txs, "income": income, "inc_tx": inc_tx, "xfer_tx": xfer_tx, "drahim": drahim, "dcat": dcat,
            "cfg": {**P.DASHBOARD, "spouse": P.SPOUSE_GROUP}}
    html = open(CODE / "dashboard_template.html", encoding="utf-8").read().replace("/*DATA*/", json.dumps(data, ensure_ascii=False))
    open(DATA / "dashboard.html", "w", encoding="utf-8").write(html)
    print(f"dashboard.html: {len(txs)} transactions")


def next_day(d):
    from datetime import date, timedelta
    return (date.fromisoformat(d) + timedelta(days=1)).strftime("%Y/%m/%d")


if __name__ == "__main__":
    main()
