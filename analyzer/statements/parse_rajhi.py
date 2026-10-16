#!/usr/bin/env python3
"""Parse Al Rajhi account statement (pdftotext -layout dump) into rajhi.csv and validate it."""
import csv
import re
import subprocess
import sys
import unicodedata
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).parent
PDF, OUT = HERE / "rajhi.pdf", HERE / "rajhi.csv"

DATE_RE = re.compile(r"^\s*(\d{4})/(\d{2})/(\d{2})\s+(.*)$")
AMT_RE = re.compile(r"(-?[\d,]+\.\d{2})\s*SAR")
NOISE_RE = re.compile(r"^\s*(\d+|Ref\. No\b.*|Date\s+Transaction Details.*)\s*$")
FOOTER_RE = re.compile(r"^\s*Notes\s{5,}")  # end-of-statement notes box


def num(s):
    return Decimal(s.replace(",", ""))


def norm(s):
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"[‎‏‪-‮⁦-⁩]", "", s)  # bidi marks
    return re.sub(r"\s+", " ", s).strip()


def header_value(text, label):
    m = re.search(rf"^{label}\s+([\d,]+(?:\.\d\d)?)", text, re.M)
    return num(m.group(1))


def parse(text):
    lines = text.replace("\f", "\n").split("\n")
    start = next(i for i, l in enumerate(lines) if "Transaction Details" in l)
    body = []
    for l in lines[start:]:
        if FOOTER_RE.match(l):
            break
        if not NOISE_RE.match(l):
            body.append(l)
    date_idx = [i for i, l in enumerate(body) if DATE_RE.match(l)]
    # a txn starts at its title line (non-blank line right before the date line)
    starts = [i - 1 if i > 0 and body[i - 1].strip() and not DATE_RE.match(body[i - 1]) else i for i in date_idx]
    rows = []
    for k, s in enumerate(starts):
        e = starts[k + 1] if k + 1 < len(starts) else len(body)
        block = body[s:e]
        d = DATE_RE.match(body[date_idx[k]])
        amts, desc = [], []
        for l in block:
            dm = DATE_RE.match(l)
            if dm:
                l = dm.group(4)
            amts += AMT_RE.findall(l)
            l = AMT_RE.sub(" ", l)
            if l.strip():
                desc.append(norm(l))
        if len(amts) != 3:
            sys.exit(f"bad amounts {amts} in block:\n" + "\n".join(block))
        debit, credit, bal = map(num, amts)
        rows.append({"date": f"{d[1]}-{d[2]}-{d[3]}", "debit": debit, "credit": credit,
                     "balance": bal, "description": " | ".join(desc)})
    return rows


def validate(text, rows):
    opening = header_value(text, "Opening Balance")
    closing = header_value(text, "Closing Balance")
    n_dep, n_wd = header_value(text, "Number Of Deposits"), header_value(text, "Number Of Withdrawals")
    t_dep, t_wd = header_value(text, "Total Deposits"), header_value(text, "Total Withdrawals")
    bad, prev = [], opening
    for i, r in enumerate(rows):
        if abs(prev - r["debit"] + r["credit"] - r["balance"]) > Decimal("0.01"):
            bad.append((i, r["date"], prev, r["debit"], r["credit"], r["balance"]))
        prev = r["balance"]
    deps = [r for r in rows if r["credit"] > 0]
    wds = [r for r in rows if r["debit"] > 0]
    both = [r for r in rows if r["credit"] > 0 and r["debit"] > 0]
    checks = {
        "1 running balance": (not bad, f"{len(bad)} mismatches {bad[:5]}"),
        "2a deposit count": (len(deps) == n_dep, f"{len(deps)} vs {n_dep}"),
        "2b withdrawal count": (len(wds) == n_wd, f"{len(wds)} vs {n_wd}"),
        "2c total deposits": (sum(r["credit"] for r in rows) == t_dep, f"{sum(r['credit'] for r in rows)} vs {t_dep}"),
        "2d total withdrawals": (sum(r["debit"] for r in rows) == t_wd, f"{sum(r['debit'] for r in rows)} vs {t_wd}"),
        "2e rows with both debit+credit": (not both, f"{len(both)}"),
        "3 closing balance": (rows[-1]["balance"] == closing, f"{rows[-1]['balance']} vs {closing}"),
    }
    for name, (ok, detail) in checks.items():
        print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")
    return all(ok for ok, _ in checks.values())


def main():
    text = subprocess.run(["pdftotext", "-layout", str(PDF), "-"], capture_output=True, text=True, check=True).stdout
    rows = parse(text)
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["date", "debit", "credit", "balance", "description"])
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} rows, {min(r['date'] for r in rows)} .. {max(r['date'] for r in rows)} -> {OUT.name}")
    ok = validate(text, rows)
    for key, label in (("credit", "CREDITS"), ("debit", "DEBITS")):
        print(f"\nTop 15 {label}:")
        for r in sorted(rows, key=lambda r: r[key], reverse=True)[:15]:
            print(f"  {r['date']}  {r[key]:>12,.2f}  {r['description'][:110]}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
