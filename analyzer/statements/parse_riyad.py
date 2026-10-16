#!/usr/bin/env python3
"""Parse Riyad Bank statement (pdftotext -layout dump riyad.txt) into riyad.csv and validate it."""
import csv
import re
import subprocess
import sys
import unicodedata
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).parent
PDF, TXT, OUT = HERE / "riyad.pdf", HERE / "riyad.txt", HERE / "riyad.csv"

ROW = re.compile(r"^\s*\d{2}-\d{2}-14\d{2}\s+(\d{4}-\d{2}-\d{2})\s+(.*?)\s{2,}(\d[\d,]*\.\d{3})\s{2,}(-?[\d,]+\.\d{2})\s*$")
HEADER_TOTALS = re.compile(r"^\s*([\d,]+\.\d{2})\s+(\d+)\s+([\d,]+\.\d{2})\s+(\d+)\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s*$")


def dec(s):
    return Decimal(s.replace(",", ""))


def clean(s):
    return re.sub(r"\s+", " ", re.sub(r"[\u200e\u200f\u202a-\u202e]", "", unicodedata.normalize("NFKC", s))).strip()


def parse(text):
    rows, cur, in_footer, cols, totals = [], None, False, None, None
    for line in text.splitlines():
        if totals is None and (m := HEADER_TOTALS.match(line)):
            totals = m.groups()
            continue
        if "To Verify" in line:
            in_footer = True
            continue
        if "Gregorian" in line and "Debit" in line:
            cols = (line.index("Debit") + len("Debit"), line.index("Credit") + len("Credit"))
            in_footer = False
            continue
        if in_footer or not line.strip():
            continue
        if m := ROW.match(line):
            date, desc, amt, bal = m.groups()
            amt_end = m.end(3)
            is_debit = abs(amt_end - cols[0]) < abs(amt_end - cols[1])
            cur = {"date": date, "debit": dec(amt) if is_debit else Decimal(0),
                   "credit": Decimal(0) if is_debit else dec(amt), "balance": dec(bal), "desc": [desc]}
            rows.append(cur)
        elif cur is not None:
            cur["desc"].append(line)
    for r in rows:
        r["description"] = " | ".join(c for c in (clean(x) for x in r.pop("desc")) if c)
    return rows, totals


def chain_ok(prev, r):
    return abs(prev - r["debit"] + r["credit"] - r["balance"]) <= Decimal("0.01")


def to_posting_order(rows, opening):
    """The PDF lists rows by transaction date, but printed balances follow posting order.
    Where an adjacent pair is printed out of posting order (e.g. a card debit dated 06-26 that
    posted after the 06-27 salary), swap it so the running balance chains. Logs every swap."""
    prev = opening
    for i in range(len(rows)):
        if not chain_ok(prev, rows[i]) and i + 1 < len(rows):
            a, b = rows[i], rows[i + 1]
            if chain_ok(prev, b) and chain_ok(b["balance"], a):
                rows[i], rows[i + 1] = b, a
                print(f"  reordered to posting order: {b['date']} {b['balance']} before {a['date']} {a['balance']}")
        prev = rows[i]["balance"]
    return rows


def validate(rows, totals):
    opening, n_dr, t_dr, n_cr, t_cr, closing = totals
    opening, closing = dec(opening), dec(closing)
    ok = True
    bad = []
    prev = opening
    for i, r in enumerate(rows):
        if abs(prev - r["debit"] + r["credit"] - r["balance"]) > Decimal("0.01"):
            bad.append((i, r["date"], prev, r["debit"], r["credit"], r["balance"]))
        prev = r["balance"]
    print(f"[1] running balance: {'PASS' if not bad else f'FAIL ({len(bad)} rows)'}")
    for b in bad[:10]:
        print("    ", b)
    ok &= not bad
    drs = [r["debit"] for r in rows if r["debit"]]
    crs = [r["credit"] for r in rows if r["credit"]]
    c2 = (len(drs) == int(n_dr) and sum(drs) == dec(t_dr) and len(crs) == int(n_cr) and sum(crs) == dec(t_cr))
    print(f"[2] counts/totals: {'PASS' if c2 else 'FAIL'}  debits {len(drs)}/{n_dr} {sum(drs)}/{t_dr}  "
          f"credits {len(crs)}/{n_cr} {sum(crs)}/{t_cr}")
    c3 = rows[-1]["balance"] == closing
    print(f"[3] closing balance: {'PASS' if c3 else 'FAIL'}  {rows[-1]['balance']} vs {closing}")
    return ok and c2 and c3


def main():
    if not TXT.exists():
        subprocess.run(["pdftotext", "-layout", str(PDF), str(TXT)], check=True)
    rows, totals = parse(TXT.read_text())
    rows = to_posting_order(rows, dec(totals[0]))
    with OUT.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "debit", "credit", "balance", "description"])
        for r in rows:
            w.writerow([r["date"], f"{r['debit']:.2f}", f"{r['credit']:.2f}", f"{r['balance']:.2f}", r["description"]])
    print(f"rows: {len(rows)}  range: {rows[0]['date']} .. {rows[-1]['date']}  -> {OUT.name}")
    sys.exit(0 if validate(rows, totals) else 1)


if __name__ == "__main__":
    main()
