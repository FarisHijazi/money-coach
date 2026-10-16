"""Combine the 5 bank account statements (+ SMS for SNB statement gaps) into one
classified money-flow table, then roll up per month.

Statements: statements/{riyad,rajhi,snb,sab,anb}.csv (from statements/parse_*.py).
Description rules, own-account numbers and card numbers come from personal.py (P.STATEMENT_*).
Everything else (AJB, D360, STC, Barq, meem, all credit cards) is "unseen": money
reaches it only via transfers/card payments from these 5, so
    net money sent to unseen own accounts + card payments ≈ what was spent there.
Writes flows.csv and prints monthly totals.
"""
import csv
import re
from collections import defaultdict

from config import DATA, P

S = DATA / "statements"
BANKS = ["riyad", "rajhi", "snb", "sab", "anb"]
SNB_GAPS = P.SNB_GAPS  # SNB statement periods missing -> filled from SMS
OWN, CARD_PAY, RULES = P.STATEMENT_OWN, P.STATEMENT_CARD_PAY, P.STATEMENT_RULES


def num(x):
    return float(x or 0)


def classify(desc, debit, credit):
    for pat, flow, sub in RULES:
        if re.search(pat, desc, re.I):
            if flow == "rent":
                return ("income", "tenant_rent") if credit else ("expense", "ejar_fees")
            if flow == "income_or_family":
                return ("income", "family_gift") if credit else ("expense", "family_out")
            return flow, sub
    if CARD_PAY.search(desc):
        return "card_payment", "credit_card_bill"
    if OWN.search(desc):
        return "own", "own_transfer"
    if credit:
        return "income", "other_in"
    if re.search(r"POS|نقاط بيع|MADA|مدى|purchase|شراء", desc, re.I):
        return "expense", "debit_card"
    if re.search(r"ATM|صراف|Withdrawal|سحب", desc, re.I):
        return "expense", "cash"
    if re.search(r"Sadad|سداد|BILL|Traffic|المخالفات", desc, re.I):
        return "expense", "bills"
    if re.search(r"FEE|عمولة|Charges|رسوم", desc, re.I) and debit < 50:
        return "expense", "bank_fees"
    return "expense", "transfer_to_people"


def load():
    rows = []
    for b in BANKS:
        for r in csv.DictReader(open(S / f"{b}.csv", encoding="utf-8")):
            d, c = num(r["debit"]), num(r["credit"])
            if b == "snb" and any(a <= r["date"] <= z for a, z in SNB_GAPS):
                continue
            flow, sub = classify(r["description"], d, c)
            rows.append({"date": r["date"], "bank": b, "flow": flow, "sub": sub,
                         "amount": round(c - d, 2), "src": "statement", "desc": r["description"][:160]})
    # SNB statement gaps: fill from SMS ledger (SNB current account rows only)
    sms_map = {"income": "income", "expense": "expense", "internal": "own", "property": "property",
               "debt": "debt", "company": "company"}
    for x in csv.DictReader(open(DATA / "ledger.csv", encoding="utf-8-sig")):
        if x["bank"] != "SNB" or any(c in x["text"] for c in P.SNB_CARD_DIGITS):
            continue  # card rows are handled via card payments
        if not any(a <= x["datetime"][:10] <= z for a, z in SNB_GAPS):
            continue
        a = float(x["amount"])
        sign = 1 if x["kind"] in ("transfer_in", "salary", "income_other", "refund", "cash_deposit") else -1
        flow = "card_payment" if x["kind"] == "cc_payment" else sms_map.get(x["bucket"], "expense")
        rows.append({"date": x["datetime"][:10], "bank": "snb", "flow": flow, "sub": x["sub"],
                     "amount": round(sign * abs(a), 2), "src": "sms_gapfill", "desc": x["text"][:160]})
    rows.sort(key=lambda r: r["date"])
    return rows


def main():
    rows = load()
    with open(DATA / "flows.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    m = defaultdict(lambda: defaultdict(float))
    for r in rows:
        mo = r["date"][:7]
        if "2025-10" <= mo <= "2026-09":
            m[mo][r["flow"]] += r["amount"]
            if r["flow"] in ("income", "expense"):
                m[mo][f"{r['flow']}:{r['sub']}"] += r["amount"]
    cols = ["income", "expense", "card_payment", "own", "property", "loan_in", "debt", "company"]
    print("month    " + "".join(c[:12].rjust(13) for c in cols))
    for mo in sorted(m):
        print(mo, " " + "".join(f"{m[mo][c]:13,.0f}" for c in cols))
    tot = defaultdict(float)
    for mo in m:
        for k, v in m[mo].items():
            tot[k] += v
    print("\nTOTALS Oct25–Sep26 by sub:")
    for k in sorted(tot, key=lambda k: tot[k]):
        if ":" in k:
            print(f"  {k:40} {tot[k]:12,.0f}")


if __name__ == "__main__":
    main()
