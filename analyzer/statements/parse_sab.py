"""SAB (Saudi Awwal Bank) account statements sab_*.pdf -> sab.csv, with validation.

Usage: uv run --with pdfplumber python parse_sab.py
Layout (x0 in PDF points, RTL): date >=500 | type 400-500 | details 280-400 | withdrawals 170-260 |
deposits 100-170 | balance <100. A transaction is a block of lines (gap <=14pt); its first date token is
the Gregorian MM/DD (no year), the second the Hijri date. Balance is printed only on some rows.
Header 'balance' is the CLOSING balance; opening = closing - deposits + withdrawals.
"""
import datetime as dt
import glob
import re
import sys
from decimal import Decimal

from stmt_utils import (ascii_digits, blocks, check, check_running, clean, header_lines, page_lines,
                        text_of, to_number, top_n, write_csv)

COLS = ["date", "debit", "credit", "balance", "description", "source_file", "date_inferred"]
DATE_RE = re.compile(r"^(\d{1,2})/(\d{1,2})$")


def skip(pn, top):
    return top > 780 or top < (380 if pn == 0 else 120)


def parse_header(path):
    lines = header_lines(path)
    period = []
    for ws in lines:
        s = ascii_digits("".join(w["text"] for w in ws if w["x0"] < 145))
        m = re.fullmatch(r"(\d{4})/(\d{1,2})/(\d{1,2})", s)
        if m:
            period.append(dt.date(*map(int, m.groups())))
    summary = next(ws for ws in lines if sum(to_number(w["text"]) is not None for w in ws) >= 5
                   and 280 < ws[0]["top"] < 330)  # account summary row
    h = {}
    for w in summary:
        v, x = to_number(w["text"]), w["x0"]
        if v is None:
            continue
        key = ("closing" if x < 100 else "dep_total" if x < 190 else "wd_total" if x < 260
               else "dep_count" if x < 320 else "wd_count")
        h[key] = v
    h["start"], h["end"] = period[:2]
    h["opening"] = h["closing"] - h["dep_total"] + h["wd_total"]
    return h


def resolve_year(month, day, start, end):
    for y in sorted({start.year, end.year}):
        d = dt.date(y, month, day)
        if start <= d <= end:
            return d
    raise ValueError(f"{month}/{day} outside period {start}..{end}")


def is_date(w):
    return w["x0"] >= 500 and DATE_RE.match(ascii_digits(w["text"]))


def has_amount(blk):
    return any(w["x0"] < 260 and to_number(w["text"]) is not None for _, _, ws in blk for w in ws)


def group_transactions(path):
    """A transaction starts with a block holding a date or a 'type' cell; other blocks are page
    continuations (merged) or the trailing disclaimer (dropped: no amount, previous tx complete)."""
    txs = []
    for blk in blocks(page_lines(path, skip), gap=14):
        if any(is_date(w) or 400 <= w["x0"] < 500 for _, _, ws in blk for w in ws):
            txs.append(list(blk))
        elif txs and (has_amount(blk) or not has_amount(txs[-1])):
            txs[-1].extend(blk)
    return txs


def parse_file(path):
    h = parse_header(path)
    rows, prev = [], {"greg": None, "hijri": None, "date": h["start"]}
    for blk in group_transactions(path):
        dates = [ascii_digits(w["text"]) for _, _, ws in blk for w in ws if is_date(w)]
        amounts = {"debit": None, "credit": None, "balance": None}
        desc = []
        for _, _, ws in blk:
            typ = [w for w in ws if 400 <= w["x0"] < 500]
            det = [w for w in ws if 260 <= w["x0"] < 400]
            for w in ws:
                if w["x0"] < 260 and (v := to_number(w["text"])) is not None:
                    key = "balance" if w["x0"] < 100 else "credit" if w["x0"] < 170 else "debit"
                    assert amounts[key] is None, (path, dates, key)
                    amounts[key] = v
            desc += [clean(text_of(p)) for p in (typ, det) if p]
        assert (amounts["debit"] is None) != (amounts["credit"] is None), (path, dates, amounts)
        description = " | ".join(d for d in desc if d)
        inferred = ""
        if len(dates) == 1 and dates[0] == prev["hijri"]:  # only the Hijri date printed: same day as previous
            greg, hijri = prev["greg"], dates[0]
        elif dates:
            greg, hijri = dates[0], (dates[1] if len(dates) > 1 else None)
        else:  # sab_4 prints no date column at all
            greg = hijri = None
        if greg:
            date = resolve_year(*map(int, DATE_RE.match(greg).groups()), h["start"], h["end"])
        else:  # infer: card purchase date in the text (DDMONYY), else carry the previous row's date forward
            m = re.search(r"(?<![A-Z0-9])\d{2}(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{2}(?![0-9])", description)
            date = dt.datetime.strptime(m.group(0), "%d%b%y").date() if m else prev["date"]
            date = min(max(date, h["start"]), h["end"])
            inferred = "purchase_date" if m else "carried_forward"
        prev = {"greg": greg, "hijri": hijri, "date": date}
        rows.append({"date": date.isoformat(), **amounts, "description": description,
                     "source_file": path, "date_inferred": inferred})
    return h, rows


def validate_file(path, h, rows):
    print(f"{path}: {h['start']} .. {h['end']}  rows={len(rows)}")
    deb = [r["debit"] for r in rows if r["debit"]]
    cre = [r["credit"] for r in rows if r["credit"]]
    ok = check("withdrawals", len(deb) == h["wd_count"] and sum(deb) == h["wd_total"],
               f"{len(deb)} / {sum(deb)} vs header {h['wd_count']} / {h['wd_total']}")
    ok &= check("deposits", len(cre) == h["dep_count"] and sum(cre) == h["dep_total"],
                f"{len(cre)} / {sum(cre)} vs header {h['dep_count']} / {h['dep_total']}")
    errs, final = check_running(rows, h["opening"], path)
    shown = sum(r["balance"] is not None for r in rows)
    ok &= check("running balance", not errs, f"{shown} shown balances checked, opening {h['opening']}"
                + "".join("\n      " + e for e in errs))
    ok &= check("closing", abs(final - h["closing"]) <= Decimal("0.01"), f"{final} vs header {h['closing']}")
    return ok


def main():
    files = sorted(glob.glob("sab_*.pdf"))
    parsed = sorted((parse_file(f) for f in files), key=lambda hr: hr[0]["start"])
    all_ok = all([validate_file(rows[0]["source_file"], h, rows) for h, rows in parsed])

    print("Period chain:")
    for (a, _), (b, _) in zip(parsed, parsed[1:]):
        gap = (b["start"] - a["end"]).days
        all_ok &= check(f"{a['end']} -> {b['start']}", gap == 1 and abs(a["closing"] - b["opening"]) <= Decimal("0.01"),
                        ("contiguous" if gap == 1 else f"GAP/OVERLAP of {gap - 1} days")
                        + f", closing {a['closing']} vs next opening {b['opening']}")

    seen, out, dups = set(), [], 0
    for h, rows in parsed:
        file_keys = set()
        for r in rows:
            key = (r["date"], r["debit"], r["credit"], r["description"])
            if key in seen:  # same transaction already emitted from an overlapping statement
                dups += 1
                continue
            file_keys.add(key)
            out.append(r)
        seen |= file_keys
    print(f"De-duplicated {dups} overlapping rows; {len(out)} rows total")
    errs, final = check_running(out, parsed[0][0]["opening"], "combined")
    all_ok &= check("combined running balance", not errs, f"final {final} vs last closing {parsed[-1][0]['closing']}"
                    + "".join("\n      " + e for e in errs))
    write_csv("sab.csv", out, COLS)
    top_n(out, "credit")
    top_n(out, "debit")
    print("ALL CHECKS PASS" if all_ok else "SOME CHECKS FAILED")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
