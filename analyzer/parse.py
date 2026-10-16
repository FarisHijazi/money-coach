"""Classify bank SMS into a ledger: income / expense / internal transfer.

Reads ../sms-export-*.csv, writes ledger.csv (one row per money movement)
and unparsed.csv (transaction-looking SMS no rule matched).
"""
import csv
import glob
import os
import re
from datetime import datetime, timedelta

from config import DATA, P

SRC = str(DATA / "sms-export*.csv")  # newest match is used
BANKS = {
    "RiyadBank": "Riyad", "SAB": "SAB", "SNB-AlAhli": "SNB", "AlRajhiBank": "Rajhi",
    "anb": "ANB", "D360 Bank": "D360", "Jazira Bank": "Jazira", "AlJaziraSMS": "Jazira",
    "STC Bank": "STC", "barq app": "Barq", "EmiratesNBD": "ENBD", "meemKSA": "meem", **P.COMPANY_CARDS,
}
# Approximate SAR rates, only used when the SMS gives no SAR total.
FX = {"SAR": 1, "SR": 1, "USD": 3.75, "EUR": 4.36, "GBP": 5.0, "TRY": 0.085, "MUR": 0.081,
      "ZAR": 0.21, "OMR": 9.75, "AED": 1.02, "QAR": 1.03, "CZK": 0.175, "TZS": 0.0015,
      "EGP": 0.077, "BHD": 9.95, "KWD": 12.2, "JOD": 5.29}
CUR = "|".join(FX)
NUM = r"\d[\d,]*\.?\d*|\.\d+"

INTERNAL_MERCHANT = re.compile(r"barq|stc ?pay|stc bank|transfer t|urpay|tiqmo", re.I)

# Segments holding balances/limits/fees, never the transaction amount.
NOISE_SEG = re.compile(r"رصيد|Balance|الرصيد|الصرف المتبقي|المبلغ المتبقي|Remaining|رسوم|Fee|"
                       r"حد الصرف|سعر الصرف|Exchange|المبلغ بالريال|Min due|Total due:", re.I)
TOTAL_SEG = re.compile(r"إجمالي المبلغ(?! المستحق)|المبلغ الإجمالي|Total amount|Total due amount", re.I)


def clean(t):
    return re.sub(r"[‎‏‪-‮​⁦-⁩]", "", t)


def to_float(s):
    s = s.replace(",", "")
    return float(s) if s not in ("", ".") else 0.0


def amount(text):
    """Best-effort SAR amount of the transaction in an SMS."""
    segs = [s.strip() for s in text.split("\n")]
    m = re.search(r"مبلغ (MUR) [^\n]*\n.*?من (\d+\.\d+)", text, re.S)
    if m:
        return round(float(m.group(2)) * FX["MUR"], 2)
    for s in segs:  # an explicit SAR total wins (international purchases)
        if TOTAL_SEG.search(s):
            m = re.search(NUM, s.split(":")[-1])
            if m:
                return to_float(m.group())
    m = re.search(rf"\((?:SAR)\s*({NUM})\)|\(({NUM})\s*SAR\)", text)  # D360/Rajhi "(SAR 19.71)"
    if m:
        return to_float(m.group(1) or m.group(2))
    for s in segs:
        if NOISE_SEG.search(s) and not re.search(r"مبلغ|Amount|بمبلغ|القسط|Instalment", s, re.I):
            continue
        m = (re.search(rf"\b({CUR})\s*({NUM})", s) or re.search(rf"({NUM})\s*({CUR})\b", s))
        if m:
            a, b = m.groups()
            cur, num = (a, b) if a in FX else (b, a)
            return round(to_float(num) * FX[cur], 2)
        m = re.search(rf"(?:مبلغ|Amount|القسط|القيمة)\s*:?\s*({NUM})", s, re.I)
        if m:
            return to_float(m.group(1))
    return None


def field(text, *keys):
    for k in keys:
        m = re.search(rf"(?:^|\n|\|)\s*{k}\s*:?\s*([^\n|]+)", text)
        if m:
            return m.group(1).strip()
    return ""


SKIP = re.compile(r"OTP|رمز|One Time|Enter code|password|كلمة مرور|الرقم السري|Declined|Decline|مرفوض|"
                  r"غير كاف|Insufficient|Beneficiary|مستفيد|المستفيد|Statement|كشف|Loan Request|طلب تمويل|"
                  r"Reason:|لـ:|حد الائتماني|حدك الائتماني|حوّل عمليتك|الرصيد المتوفر|القيمة المستحقة|"
                  r"توجد دفعات متعثرة|عملية تمويل|consent|Open Banking|المصرفية المفتوحة|تأكيد السداد|"
                  r"application|طلب بطاقة", re.I)

# (first-line regex, kind). Order matters; first match wins.
RULES = [
    (r"حوالة واردة راتب|Salary|حوالة داخلية", "salary"),
    (r"Savings Account Profit", "income_other"),
    (r"قسط تمويل|Loan Instalment", "loan"),
    (r"Administration Fees|خصم: رسوم|Annual Fee|الرسوم السنوية|مدين بمبلغ", "fee"),
    (r"الغاء حجز|Amount Release", "refund"),
    (r"تسديد|سداد بطاقة|Credit Card:\s*Payment|Card Payment", "cc_payment"),
    (r"Credit Card:\s*transfer|حوالة من بطاقة ائتمانية|تحويل بنكي", "cc_cash_advance"),
    (r"Money Added|Adding money", "wallet_topup"),
    (r"Transfer Between Your Accounts", "own_accounts"),
    (r"استرداد|Refund|عكسية|Reversal|Reverse", "refund"),
    (r"سحب|ATM|Withdrawal", "atm"),
    (r"سداد فاتورة|Bill Payment|MOI|مدفوعات وزارة", "bill"),
    (r"شراء عملة|ايداع فرع|Cash Deposit", "cash_deposit"),
    (r"payment has been approved", "transfer_out"),
    (r"^حوالة محلية$", "transfer_in"),
    (r"صادرة|Outgoing|Debit Transfer|outward|Debit Local|qattah", "transfer_out"),
    (r"واردة|Incoming|Credit Transfer|Inward|Credit Local|Credit transfer", "transfer_in"),
    (r"Local Transfer|Internal Transfer|Internal transfer", "transfer_dir"),
    (r"شراء|Purchase|PoS|POS", "purchase"),
]


def counterparty(text, kind):
    if kind == "transfer_in":
        return field(text, "مرسل من", "Sender Name", "اسم المرسل", "Sender", "من", "From") or \
            (re.search(r"From ([^|\n]+)", text) or [None, ""])[1]
    if kind == "transfer_out":
        return field(text, "مستفيد", "إلى", "To", "الى", "ل\\*?\\d*") or (re.search(r"To ([^|\n]+)", text) or [None, ""])[1]
    if kind in ("purchase", "refund", "atm"):
        m = re.search(r"لدى\s*:?\s*([^|\n]+?)(?: بمبلغ| من خلال| في |\||$)", text, re.M)
        return (m.group(1) if m else field(text, "At", "من", "From", "الموقع", "Location", "At:")).strip()
    return ""


def classify(bank, text):
    first = text.split("\n")[0]
    if SKIP.search(first) and not re.search(r"payment has been approved", first):
        return None
    for pat, kind in RULES:
        if re.search(pat, first, re.I):
            break
    else:
        return None
    if kind == "transfer_dir":
        kind = "transfer_out" if P.TRANSFER_OUT_FROM.search(text) else "transfer_in"
    amt = amount(text)
    if amt is None:
        return None
    cp = counterparty(text, kind)
    # Jazira "internal outgoing" carries no payee name; bucket() files it under P.UNNAMED_INTERNAL_SUB.
    if bank == "Jazira" and kind == "transfer_out" and "داخلية" in first:
        cp = cp or "(Jazira internal, no name)"
    if kind == "transfer_out" and bank == "Rajhi" and "approved" in first:
        cp = f"{P.SELF_NAME} (Rajhi payment)"
    return kind, amt, cp


def bucket(kind, cp, text, bank=""):
    """Map to income / expense / internal."""
    if bank in P.COMPANY_CARDS.values():  # company card: never personal spend
        return "company", f"{bank.lower()}_card"
    for pat, b, s in P.OVERRIDES:
        if re.search(pat, text):
            return b, s
    if P.PROPERTY.search(text) and kind != "purchase":
        return "property", "apartment"
    if kind == "fee" and ("التمويل العقاري" in text or any(x in text.replace("\n", " | ") for x in P.PROPERTY_FEE_SNIPPETS)):
        return "property", "apartment"
    if kind == "bill" and "ايجار" in text:
        return "expense", "rent"
    if P.THERAPY.search(cp):
        return "expense", "therapy"
    if kind == "transfer_in" and P.SALARY_CP.search(cp):
        return "income", "salary"
    if kind in ("cc_payment", "own_accounts", "wallet_topup", "cc_cash_advance"):
        return "internal", kind
    if kind in ("transfer_in", "transfer_out"):
        if re.search(r"STCPAY", text) or P.SELF.search(cp):
            return "internal", "self_transfer"
        if P.BTC.search(cp) or P.BTC.search(text):
            return "internal", "bitcoin"
        if P.SPOUSE.search(cp):
            return "expense" if kind == "transfer_out" else "income", "wife"
        if P.FAMILY.search(cp):
            return ("expense" if kind == "transfer_out" else "income"), "family"
        if "no name" in cp:
            return "expense", P.UNNAMED_INTERNAL_SUB
        return ("expense", "people") if kind == "transfer_out" else ("income", "other_in")
    if kind == "purchase" and INTERNAL_MERCHANT.search(cp):
        return "internal", "card_to_wallet"
    if kind in ("salary", "income_other"):
        return "income", kind
    if kind == "cash_deposit":
        return "internal", "cash_deposit"
    if kind == "refund":
        return "expense", "refund"  # negative expense
    return "expense", kind


def main():
    rows = list(csv.DictReader(open(max(glob.glob(SRC), key=os.path.getmtime), encoding="utf-8-sig")))
    ledger, unparsed = [], []
    for r in rows:
        bank = BANKS.get(r["sender"])
        if not bank:
            continue
        text = clean(r["text"]).replace(" | ", "\n")
        res = classify(bank, text)
        if not res:
            if re.search(rf"({CUR})\s*{NUM}|{NUM}\s*({CUR})", text) and not SKIP.search(text.split("\n")[0]):
                unparsed.append({"datetime": r["datetime"], "bank": bank, "text": text.replace("\n", " | ")})
            continue
        kind, amt, cp = res
        b, sub = bucket(kind, cp, text, bank)
        sign = -1 if kind == "refund" else 1
        ledger.append({"datetime": r["datetime"], "bank": bank, "bucket": b, "sub": sub, "kind": kind,
                       "amount": round(sign * amt, 2), "counterparty": cp,
                       "text": text.replace("\n", " | ")})
    dedupe(ledger)
    match_transfers(ledger)
    cols = ["datetime", "bank", "bucket", "sub", "kind", "amount", "counterparty", "match", "text"]
    with open(DATA / "ledger.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, cols)
        w.writeheader()
        w.writerows(ledger)
    with open(DATA / "unparsed.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, ["datetime", "bank", "text"])
        w.writeheader()
        w.writerows(unparsed)
    print(f"{len(ledger)} ledger rows, {len(unparsed)} unparsed money-looking SMS")


def dedupe(ledger):
    """Banks sometimes send the same transaction twice within a few minutes."""
    seen, out, prev_text = {}, [], {}
    for x in ledger:
        t = datetime.fromisoformat(x["datetime"])
        key = (x["bank"], x["kind"], x["amount"], x["counterparty"])
        same_sms = x["kind"] == "purchase" and prev_text.get(key) == x["text"]  # bank sent identical SMS twice
        if key in seen and t - seen[key] < timedelta(minutes=10) and (x["kind"] != "purchase" or same_sms):
            continue
        seen[key] = t
        prev_text[key] = x["text"]
        out.append(x)
    ledger[:] = out


def match_transfers(ledger):
    """Pair an outgoing self-transfer with the incoming one at another bank (same amount ±2, ≤4 days)."""
    outs = [x for x in ledger if x["sub"] == "self_transfer" and x["kind"] == "transfer_out"]
    ins = [x for x in ledger if x["sub"] == "self_transfer" and x["kind"] == "transfer_in"]
    for x in ledger:
        x["match"] = ""
    for o in outs:
        to = datetime.fromisoformat(o["datetime"])
        for i in ins:
            if i["match"] or i["bank"] == o["bank"]:
                continue
            if abs(i["amount"] - o["amount"]) <= 2 and abs(datetime.fromisoformat(i["datetime"]) - to) <= timedelta(days=4):
                o["match"] = f'{i["bank"]} {i["datetime"]}'
                i["match"] = f'{o["bank"]} {o["datetime"]}'
                break


if __name__ == "__main__":
    main()
