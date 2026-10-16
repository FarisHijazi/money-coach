"""ANB (Arab National Bank) account statement anb.pdf -> anb.csv, with validation.

Usage: uv run --with pdfplumber python parse_anb.py
Layout (x0 in PDF points): posting/value date <100 | description 100-440 | signed amount 440-520 |
balance >=520. A transaction is a block of lines (gap <=15pt) with the posting date first.
"""
import re
import sys
from decimal import Decimal

from stmt_utils import (blocks, check, check_running, clean, header_lines, page_lines, text_of,
                        to_number, top_n, write_csv)

PDF = "anb.pdf"
COLS = ["date", "debit", "credit", "balance", "description"]
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
HEADER_KEYS = {"Opening Balance": "opening", "Closing Balance": "closing", "Total Debited": "debit_total",
               "Total Credited": "credit_total", "No. of Debit Transactions": "debit_count",
               "No. of Credit Transactions": "credit_count", "From Date": "start", "To Date": "end"}


def parse_header():
    h = {}
    for ws in header_lines(PDF):
        line = " ".join(w["text"] for w in ws)
        for label, key in HEADER_KEYS.items():
            if line.startswith(label):
                val = ws[-1]["text"]
                h[key] = val if key in ("start", "end") else to_number(val)
    return h


def table_top(pn):
    return 465 if pn == 0 else 70  # below the 'Posting Date | Description | Amount | Balance' header


def skip(pn, top):
    return top < table_top(pn) or top > 755


def parse():
    h = parse_header()
    txs = []
    for blk in blocks(page_lines(PDF, skip), gap=15):
        if any(w["x0"] < 100 and DATE_RE.match(w["text"]) for _, _, ws in blk for w in ws):
            txs.append(list(blk))
        else:  # continuation of a transaction split across a page break
            txs[-1].extend(blk)
    rows = []
    for blk in txs:
        date = next(w["text"] for _, _, ws in blk for w in ws if w["x0"] < 100)
        amount = [to_number(w["text"]) for _, _, ws in blk for w in ws if 440 <= w["x0"] < 520]
        balance = [to_number(w["text"]) for _, _, ws in blk for w in ws if w["x0"] >= 520]
        assert len(amount) == 1 and len(balance) == 1 and None not in amount + balance, (date, amount, balance)
        desc = [clean(text_of([w for w in ws if 100 <= w["x0"] < 440])) for _, _, ws in blk]
        a = amount[0]
        rows.append({"date": date, "debit": -a if a < 0 else None, "credit": a if a > 0 else None,
                     "balance": balance[0], "description": " | ".join(d for d in desc if d)})
    return h, rows


def main():
    h, rows = parse()
    print(f"{PDF}: {h['start']} .. {h['end']}  rows={len(rows)}")
    deb = [r["debit"] for r in rows if r["debit"]]
    cre = [r["credit"] for r in rows if r["credit"]]
    ok = check("debits", len(deb) == h["debit_count"] and -sum(deb) == h["debit_total"],
               f"{len(deb)} / -{sum(deb)} vs header {h['debit_count']} / {h['debit_total']}")
    ok &= check("credits", len(cre) == h["credit_count"] and sum(cre) == h["credit_total"],
                f"{len(cre)} / {sum(cre)} vs header {h['credit_count']} / {h['credit_total']}")
    errs, final = check_running(rows, h["opening"], PDF)
    ok &= check("running balance", not errs, f"{len(rows)} balances checked, opening {h['opening']}"
                + "".join("\n      " + e for e in errs))
    ok &= check("closing", abs(final - h["closing"]) <= Decimal("0.01"), f"{final} vs header {h['closing']}")
    ok &= check("dates in period", all(h["start"] <= r["date"] <= h["end"] for r in rows), "")
    write_csv("anb.csv", rows, COLS)
    top_n(rows, "credit")
    top_n(rows, "debit")
    print("ALL CHECKS PASS" if ok else "SOME CHECKS FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
