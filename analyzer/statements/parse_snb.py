#!/usr/bin/env python3
"""Parse SNB (Saudi National Bank) e-statements snb_*.pdf -> snb.csv, with validation.

Two layouts are handled:
  - "old": header "STATEMENT DATE From/To", opening row "الرصيد السابق",
           columns Date | Type | Description | Credit | Debit | Balance,
           closing summary "STATEMENT MOVEMENTS start + credits - debits = end".
  - "new": "Account Movement" summary "end = debit - credit + start",
           columns Balance | Debit | Credit | Description | Type | Date.

Text comes from `pdftotext -layout`; debit vs credit is decided by the amount's column
position relative to the page's column header, and then cross-checked against the running
balance and the statement's own totals.

Usage: python3 parse_snb.py   (run inside the statements dir; writes snb.csv)
"""
import csv
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import P  # noqa: E402

HERE = Path(__file__).resolve().parent
BIDI = re.compile("[\u200e\u200f\u202a-\u202e\u2066-\u2069]")
AMT = r"[\d,]+\.\d\d"
DATE = r"\d\d/\d\d/\d{4}"
TOL = 0.01


def num(s):
    return round(float(s.replace(",", "")), 2)


def iso(d):
    dd, mm, yy = d.split("/")
    return f"{yy}-{mm}-{dd}"


def norm(s):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s)).strip()


def lines_of(pdf):
    out = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, text=True, check=True).stdout
    return [BIDI.sub("", l.rstrip()) for l in out.splitlines()]


def nearest(pos, cols):
    """Name of the column whose header centre is closest to char position `pos`."""
    return min(cols, key=lambda k: abs(cols[k] - pos))


def col_centres(line, names):
    return {n: line.index(n) + len(n) / 2 for n in names}


def amount_centre(line, m, group):
    return (m.start(group) + m.end(group)) / 2


# ---------------------------------------------------------------- old layout
OLD_TXN = re.compile(rf"^\s*({DATE})\s+(.*?)\s*({AMT})\s+({AMT})\s*$")


def parse_old(lines):
    hdr, rows, cur, cols, active = {}, [], None, None, False
    for i, line in enumerate(lines):
        n = norm(line)
        if "period" not in hdr and (m := re.search(rf"From:\s*({DATE})\s+To:\s*({DATE})", line)):
            hdr["period"] = (iso(m[1]), iso(m[2]))
        if re.match(r"^\s*Date\s+Transaction Type\s+Description\s+Credit\s+Debit\s+Balance", line):
            cols = col_centres(line, ["Credit", "Debit"])
            active = True
            continue
        if "الرصيد السابق" in n and (m := re.search(rf"({AMT})\s*$", line)):
            hdr["open"] = num(m[1])
            continue
        if line.strip().startswith("STARTING BALANCE"):
            active, cur = False, None
            continue
        if line.startswith("STATEMENT MOVEMENTS"):
            a = [num(x) for x in re.findall(AMT, line)]
            hdr.update(open_hdr=a[0], credits=a[1], debits=a[2], close=a[3])
            continue
        if line.startswith("NUMBER OF MOVEMENTS"):
            c = [int(x) for x in re.findall(r"\d+", line)]
            hdr.update(n_credits=c[0], n_debits=c[1])
            continue
        if re.match(r"^\s*Page\s*$", line) or "Account Information" in line:
            active = False  # page footer/header block; resume at next column header
            continue
        if not active:
            continue
        if m := OLD_TXN.match(line):
            side = nearest(amount_centre(line, m, 3), cols)
            amt = num(m[3])
            parts = [p for p in re.split(r"\s{2,}", m[2].strip()) if p]
            cur = dict(date=iso(m[1]), debit=amt if side == "Debit" else 0.0,
                       credit=amt if side == "Credit" else 0.0, balance=num(m[4]), desc=parts)
            rows.append(cur)
            continue
        if cur is None or not line.strip() or re.match(r"^\s*\d\d:\d\d\s*$", line):
            continue
        cur["desc"] += [p for p in re.split(r"\s{2,}", line.strip()) if p]
    return hdr, rows


# ---------------------------------------------------------------- new layout
NEW_TXN = re.compile(rf"^\s*({AMT})\s+({AMT})\s+(.*?)\s*({DATE})\s*$")


def parse_new(lines):
    hdr, rows, cur, credit_start, active = {}, [], None, None, False
    for i, line in enumerate(lines):
        if "Total Pages" in line and "period" not in hdr:
            ds = [d for d in re.findall(DATE, lines[i + 2]) if int(d[-4:]) > 1900]
            hdr["period"] = (iso(ds[0]), iso(ds[1]))
            continue
        if "End Balance" in line and "Starting Balance" in line:
            a = [num(x) for x in re.findall(AMT, lines[i + 2])]
            hdr.update(close=a[0], debits=a[1], credits=a[2], open=a[3])
            c = [int(x) for x in lines[i + 5].split()]
            hdr.update(n_debits=c[0], n_credits=c[1])
            continue
        if re.match(r"^\s*Balance\s.*Debit\s.*Credit\s.*Description", line):
            credit_start = line.index("Credit")  # debit amounts end before the Credit label starts
            active = True
            continue
        if "This statement would be considered correct" in line or line.startswith("Page:"):
            active = False
            continue
        if not active:
            continue
        if m := NEW_TXN.match(line):
            side = "Debit" if m.end(2) < credit_start else "Credit"
            amt = num(m[2])
            parts = [p for p in re.split(r"\s{2,}", m[3].strip()) if p]
            parts = parts[-1:] + parts[:-1]  # transaction type (rightmost) first, like the old layout
            cur = dict(date=iso(m[4]), debit=amt if side == "Debit" else 0.0,
                       credit=amt if side == "Credit" else 0.0, balance=num(m[1]), desc=parts)
            rows.append(cur)
            continue
        if cur is None or not line.strip():
            continue
        text = re.sub(r"\s+\d\d:\d\d\s*$", "", line).strip()
        if text:
            cur["desc"] += [p for p in re.split(r"\s{2,}", text) if p]
    return hdr, rows


# ---------------------------------------------------------------- validation
def close(a, b):
    return abs(a - b) <= TOL


def validate(name, hdr, rows):
    errs = []
    if "open" not in hdr:
        return [f"{name}: no opening balance found"]
    bal = hdr["open"]
    for r in rows:
        exp = round(bal - r["debit"] + r["credit"], 2)
        if not close(exp, r["balance"]):
            errs.append(f"{name}: {r['date']} running balance {exp} != stated {r['balance']} ({r['desc'][:1]})")
        if (r["debit"] > 0) == (r["credit"] > 0):
            errs.append(f"{name}: {r['date']} row has both/neither debit and credit")
        bal = r["balance"]
    deb = round(sum(r["debit"] for r in rows), 2)
    cred = round(sum(r["credit"] for r in rows), 2)
    nd = sum(r["debit"] > 0 for r in rows)
    nc = sum(r["credit"] > 0 for r in rows)
    checks = [("open_hdr", hdr["open"]), ("close", bal), ("debits", deb), ("credits", cred),
              ("n_debits", nd), ("n_credits", nc)]
    for key, got in checks:
        if key in hdr and not close(hdr[key], got):
            errs.append(f"{name}: header {key}={hdr[key]} but parsed {got}")
    missing = [k for k in ("close", "debits", "credits", "n_debits", "n_credits") if k not in hdr]
    if missing:
        errs.append(f"{name}: header totals missing {missing}")
    return errs


def main():
    pdfs = sorted(HERE.glob("snb_*.pdf"), key=lambda p: int(re.search(r"(\d+)", p.stem)[1]))
    stmts, all_errs = [], []
    for pdf in pdfs:
        lines = lines_of(pdf)
        layout = "new" if any("Account Movement" in l for l in lines) else "old"
        hdr, raw = (parse_new if layout == "new" else parse_old)(lines)
        # some new-layout PDFs print the whole transaction table twice; balance is in the key,
        # so a genuine repeated transaction can never collide
        keys, rows = set(), []
        for r in raw:
            k = (r["date"], r["debit"], r["credit"], r["balance"], tuple(r["desc"]))
            if k not in keys:
                keys.add(k)
                rows.append(r)
        if len(rows) != len(raw):
            print(f"{pdf.name}: dropped {len(raw) - len(rows)} rows repeated within the same PDF")
        if P.SNB_ACCOUNT and not any(P.SNB_ACCOUNT in l for l in lines):
            all_errs.append(f"{pdf.name}: account {P.SNB_ACCOUNT} not found")
        errs = validate(pdf.name, hdr, rows)
        all_errs += errs
        stmts.append(dict(file=pdf.name, layout=layout, hdr=hdr, rows=rows, errs=errs))
        p = hdr.get("period", ("?", "?"))
        print(f"{pdf.name:10} {layout}  {p[0]} -> {p[1]}  rows={len(rows):3}  open={hdr.get('open')} "
              f"close={hdr.get('close')}  {'PASS' if not errs else 'FAIL'}")
        for e in errs:
            print("   ", e)

    # chain + gaps. Statements sorted by period; a statement whose period is identical to the
    # previous one is a duplicate. Consecutive periods may overlap by a day, so rows already
    # seen (same date/amounts/balance) are dropped before the close->open comparison.
    print("\nChain / gaps:")
    ordered = sorted(stmts, key=lambda s: (s["hdr"].get("period", ("",))[0], s["file"]))
    key = lambda r: (r["date"], r["debit"], r["credit"], r["balance"])
    seen, out, prev, gaps = set(), [], None, []
    for s in ordered:
        if prev and s["hdr"]["period"] == prev["hdr"]["period"]:
            same = [key(r) for r in s["rows"]] == [key(r) for r in prev["rows"]]
            print(f"  {s['file']} has the same period as {prev['file']} (identical rows: {same}) -> skipped")
            continue
        new = [r for r in s["rows"] if key(r) not in seen]
        overlap = len(s["rows"]) - len(new)
        if prev:
            pe, sb = prev["hdr"]["period"][1], s["hdr"]["period"][0]
            opening = s["rows"][overlap - 1]["balance"] if overlap else s["hdr"]["open"]
            chained = close(prev["hdr"]["close"], opening)
            gap = sb > pe
            note = f"  GAP {pe}..{sb}, balance moved {round(opening - prev['hdr']['close'], 2):+}" if gap else ""
            print(f"  {prev['file']} close {prev['hdr']['close']} -> {s['file']} open {opening}"
                  f"{f' (after {overlap} overlapping rows)' if overlap else ''}: "
                  f"{'OK' if chained else 'BREAK'}{note}")
            if gap:
                gaps.append((prev["file"], s["file"], pe, sb))
            elif not chained:
                all_errs.append(f"chain break {prev['file']} -> {s['file']} with no period gap")
        for r in new:
            seen.add(key(r))
            out.append(dict(date=r["date"], debit=f"{r['debit']:.2f}" if r["debit"] else "",
                            credit=f"{r['credit']:.2f}" if r["credit"] else "",
                            balance=f"{r['balance']:.2f}",
                            description=" | ".join(x for x in map(norm, r["desc"]) if x),
                            source_file=s["file"]))
        prev = s
    with open(HERE / "snb.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["date", "debit", "credit", "balance", "description", "source_file"])
        w.writeheader()
        w.writerows(out)
    print(f"\nWrote {len(out)} rows to snb.csv")
    for a, b, pe, sb in gaps:
        print(f"Period gap (missing statement) between {a} and {b}: {pe} .. {sb}")
    if all_errs:
        print(f"{len(all_errs)} validation errors")
        sys.exit(1)
    print("All validation checks passed")


if __name__ == "__main__":
    main()
