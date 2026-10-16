"""Match every Drahim transaction (drahim_tx.csv) to SMS ledger or bank statements.
Match = |amount| within 1 SAR and date within ±3 days; prefer merchant-token overlap. Each source row used once."""
import csv, re
from collections import Counter
from datetime import date

D = list(csv.DictReader(open("drahim_tx.csv")))
src = [("sms", x["datetime"][:10], abs(float(x["amount"])), x["bucket"] + "/" + x["sub"], x["text"])
       for x in csv.DictReader(open("ledger.csv", encoding="utf-8-sig"))]
src += [("stmt", r["date"], abs(float(r["amount"])), r["flow"] + "/" + r["sub"], r["desc"])
        for r in csv.DictReader(open("flows.csv", encoding="utf-8-sig"))]
tok = lambda s: set(re.findall(r"[a-z]{4,}", s.lower()))
used, res = set(), Counter()
with open("drahim_match.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["date", "drahim_category", "merchant", "amount", "matched_in", "my_label", "evidence"])
    for d in D:
        a, dd = float(d["amount"]), date.fromisoformat(d["date"])
        c = [i for i, s in enumerate(src) if i not in used and abs(s[2] - a) <= 1
             and abs((date.fromisoformat(s[1]) - dd).days) <= 3]
        c.sort(key=lambda i: (-len(tok(d["merchant"]) & tok(src[i][4])), src[i][0] != "sms"))
        if c:
            used.add(c[0]); s = src[c[0]]
            w.writerow([d["date"], d["category"], d["merchant"], a, s[0], s[3], s[4][:90]])
            res[(d["category"], s[3])] += a
        else:
            w.writerow([d["date"], d["category"], d["merchant"], a, "NONE", "", ""])
            res[(d["category"], "UNMATCHED")] += a
for (cat, lab), v in sorted(res.items()):
    print(f"{cat:12} {lab:34} {v:10,.2f}")
