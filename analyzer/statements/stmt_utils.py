"""Shared helpers for parse_sab.py / parse_anb.py: PDF line blocks, RTL text, numbers, validation.

Run the parsers with pdfplumber available, e.g. `uv run --with pdfplumber python parse_sab.py`.
"""
import csv
import re
import unicodedata
from decimal import Decimal
from itertools import groupby

import pdfplumber

ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩٫٬ﺭﺮ", "0123456789.,..")
# The SAB font maps the Arabic decimal separator to a Reh glyph ("ﺭ"); only translate it inside numbers.
NUM_RE = re.compile(r"^-?[\d,]+(\.\d+)?$")


def is_arabic(ch):
    return "؀" <= ch <= "ۿ" or "ﭐ" <= ch <= "﻿"


def to_number(text):
    """Parse '1,234.56' / '١,٢٣٤ﺭ٥٦' / '-485' -> Decimal, or None if not a number."""
    t = text.strip().translate(ARABIC_DIGITS)
    return Decimal(t.replace(",", "")) if NUM_RE.match(t) else None


def ascii_digits(text):
    return text.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))


def visual_to_logical(visual):
    """pdfplumber returns RTL text in visual (left-to-right glyph) order. Reverse the run order and
    the characters inside Arabic runs; Latin/digit runs (with spaces between them) keep their order."""
    cls = ["A" if is_arabic(c) else ("S" if c == " " else "L") for c in visual]
    for i, c in enumerate(cls):  # a space joins its neighbours' run when both sides agree
        if c == "S":
            left = next((cls[j] for j in range(i - 1, -1, -1) if cls[j] != "S"), None)
            right = next((cls[j] for j in range(i + 1, len(cls)) if cls[j] != "S"), None)
            if left == right and left is not None:
                cls[i] = left
    runs, i = [], 0
    for k, g in groupby(cls):
        n = len(list(g))
        seg = visual[i:i + n]
        runs.append(seg[::-1] if k == "A" else seg)
        i += n
    if not any(is_arabic(c) for c in visual):
        return visual
    return "".join(reversed(runs))


def clean(text):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip()


def page_lines(pdf_path, skip):
    """Yield (page_no, top, [words]) for every text line, words sorted left->right.
    skip(page_no, top) -> True drops header/footer lines."""
    with pdfplumber.open(pdf_path) as pdf:
        for pn, page in enumerate(pdf.pages):
            words = page.extract_words(x_tolerance=1.5)
            words.sort(key=lambda w: (round(w["top"]), w["x0"]))
            for top, grp in groupby(words, key=lambda w: round(w["top"])):
                if not skip(pn, top):
                    yield pn, top, list(grp)


def header_lines(pdf_path, page_no=0):
    with pdfplumber.open(pdf_path) as pdf:
        words = pdf.pages[page_no].extract_words(x_tolerance=1.5)
    words.sort(key=lambda w: (round(w["top"]), w["x0"]))
    return [list(g) for _, g in groupby(words, key=lambda w: round(w["top"]))]


def blocks(lines, gap):
    """Group consecutive lines into blocks split where the vertical gap exceeds `gap` (or page changes)."""
    out, prev = [], None
    for pn, top, words in lines:
        if prev is None or pn != prev[0] or top - prev[1] > gap:
            out.append([])
        out[-1].append((pn, top, words))
        prev = (pn, top)
    return out


def text_of(words):
    return visual_to_logical(" ".join(w["text"] for w in words))


def fmt(d):
    return "" if d is None else f"{d:.2f}"


def write_csv(path, rows, cols):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: fmt(r[c]) if isinstance(r[c], Decimal) or r[c] is None else r[c] for c in cols})


def check_running(rows, opening, label):
    """prev - debit + credit == balance on every row that shows a balance. Returns (errors, final)."""
    errs, bal = [], opening
    for i, r in enumerate(rows):
        bal = bal - (r["debit"] or 0) + (r["credit"] or 0)
        if r["balance"] is not None and abs(bal - r["balance"]) > Decimal("0.01"):
            errs.append(f"{label} row {i} {r['date']}: running {bal} != shown {r['balance']}")
            bal = r["balance"]
    return errs, bal


def check(label, cond, detail):
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}: {detail}")
    return cond


def top_n(rows, key, n=10):
    print(f"  10 largest {key}s:")
    for r in sorted((r for r in rows if r[key]), key=lambda r: r[key], reverse=True)[:n]:
        print(f"    {r['date']}  {r[key]:>12,.2f}  {r['description'][:90]}")
