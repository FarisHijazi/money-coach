"""Placeholder personal values. Copy to personal.py (gitignored) and put your real ones there.

config.py loads personal.py when it exists, else this file. Every regex runs on the raw bank SMS /
statement text, so write names the way your bank prints them (Latin and Arabic).
"""
import re
from datetime import date

# ---------- parse.py: who is who in the SMS text ----------
SELF = re.compile(r"YOUR_NAME|اسمك", re.I)  # your own name on transfers -> internal self-transfer
SELF_NAME = "YOUR_NAME"  # counterparty label for Rajhi "payment has been approved" (an own transfer)
BTC = re.compile(r"CRYPTO_BROKER_NAME", re.I)  # transfers that buy crypto = still your money
SPOUSE = re.compile(r"SPOUSE_NAME", re.I)
FAMILY = re.compile(r"FAMILY_NAME", re.I)  # checked after SELF
PROPERTY = re.compile(r"PROPERTY_DEVELOPER|OWNERS_ASSOCIATION")  # property purchase / ownership costs
PROPERTY_FEE_SNIPPETS = []  # exact fee-SMS fragments (newlines shown as " | ") that are property costs
THERAPY = re.compile(r"THERAPY_PROVIDER")
SALARY_CP = re.compile(r"MONTHLY_INCOME_A")  # incoming transfer from this payer = salary
TRANSFER_OUT_FROM = re.compile(r"From:\s*0000")  # Local/Internal Transfer "From:" your account = outgoing
COMPANY_CARDS = {"COMPANY_CARD_SENDER": "CompanyCard"}  # SMS sender -> bank label; all of it is company spend
UNNAMED_INTERNAL_SUB = "people"  # sub for Jazira internal transfers that carry no payee name

# Manual labels: (regex on SMS text, bucket, sub). First match wins, checked before everything else.
OVERRIDES = [
    (r"COMPANY_NAME", "company", "reimbursement"),
    (r"TENANT_NAME", "income", "tenant_rent"),
    (r"FRIEND_NAME", "debt", "friend_loan"),
]

# ---------- categorize.py ----------
WINDOW = ("2026-01", date.today().strftime("%Y-%m"))  # months averaged in summary.json / the dashboard
SPOUSE_LABEL = "Spouse (allowance + house)"  # category of transfers to SPOUSE
SPOUSE_GROUP = "Spouse"                      # dashboard group for SPOUSE_LABEL
ONE_OFF_ATM_DATES = ()  # ATM withdrawals on these dates are a one-off purchase, not cash spending
ONE_OFF_LABEL = "One-off purchase"
CATS = [  # first match wins; regex on merchant + SMS text
    ("Home lab / gadgets", r"EXTRA|JARIR|APPLE STORE"),
    ("AI & software subs", r"CLAUDE|ANTHROPIC|OPENAI|\bAWS\b|APPLE\.COM|NETFLIX|GOOGLE|SPOTIFY|CHATGPT|GITHUB|"
                           r"ANGHAMI|SHAHID|OSN|YOUTUBE"),
    ("Travel", r"BOOKING|BKG\*|TRIP\.COM|MOSAFER|AIRWAYS|AIRLINE|FLYNAS|FLYADEAL|SAUDIA|HOTEL|MARRIOTT|HYATT|"
               r"RESORT|AIRALO|GETYOURGUIDE|KLOOK|AGODA|AIRBNB|EXPEDIA"),
    ("Food delivery", r"HUNGERSTATION|KEETA|JAHEZ|MRSOOL|CHEFZ|TOYOU|TALABAT|DELIVEROO|NINJA"),
    ("Groceries", r"PANDA|TAMIMI|LULU|DANUBE|OTHAIM|CARREFOUR|NESTO|SUPERMARKET|BAQALA"),
    ("Online shopping", r"AMAZON|SHEIN|NOON|TRENDYOL|IHERB|NAMSHI|ALIEXPRESS|TEMU|SALLA"),
    ("Home & furniture", r"IKEA|SACO|HOME ?CENT"),
    ("Clothes & beauty", r"ZARA|H&M|NIKE|ADIDAS|DEFACTO|REDTAG|SALON|BARBER|PERFUM"),
    ("Health & gym", r"PHARMAC|NAHDI|DAWAA|CLINIC|HOSPITAL|DENTAL|FITNESS|GYM"),
    ("Transport & car", r"UBER|CAREEM|BOLT|TAXI|ALDREES|SASCO|PETROMIN|PARKING|CAR WASH|NAJM"),
    ("Fun & events", r"AMC|VOX|MUVI|PLATINUMLIST|WEBOOK|BOWLING|THEATRE"),
    ("Gov, rent fees & telecom", r"EJAR|ABSHER|MOI|STC|ZAIN|MOBILY"),
    ("Charity", r"EHSAN"),
    ("Gifts & flowers", r"FLOWE|ROSES"),
    ("Laundry & home services", r"LAUNDR|DRY ?CLEAN"),
    ("Restaurants & cafés", r"CAFE|COFFEE|RESTAURANT|BURGER|STEAK|GRILL|PIZZA|SUSHI|BAKERY|STARBUCKS|DUNKIN|"
                            r"KUDU|ALBAIK|MCDONALD|KFC|SHAWARMA|KITCHEN|BISTRO"),
]

# ---------- weekly_check.py ----------
WEEKLY_BUDGET = 3000  # discretionary spend per Sun-Sat week (excludes rent, loans, spouse)
PERSONAL_BUDGET = 2000  # personal spend per month (cafés, delivery, online, gadgets, subs, clothes, fun)

# ---------- reconcile.py (bank statements) ----------
SNB_GAPS = []  # [("YYYY-MM-DD", "YYYY-MM-DD")] periods with no SNB statement -> filled from SMS
SNB_CARD_DIGITS = ("0000",)  # last-4 of SNB cards: their SMS rows are skipped in gap-fill
SNB_ACCOUNT = ""  # statements/parse_snb.py checks every PDF mentions this account number ("" = skip)
STATEMENT_OWN = re.compile(r"YOUR_ACCOUNT_NUMBER|YOUR_NAME", re.I)  # transfers between your own accounts
STATEMENT_CARD_PAY = re.compile(r"CC NBR|Credit Cards Transactions|مدفوعات بطاق|Transfer to Master Card|"
                                r"Transfer to VISA|Own Card|تسوية بطاقة ائتمان|Visa Payment", re.I)
STATEMENT_RULES = [  # (regex on description, flow, sub) — first match wins
    (r"MONTHLY_INCOME_A|MONTHLY_INCOME_B|Credit Salary", "income", "salary"),
    (r"EJAR|ايجار|إيجار", "rent", "ejar"),  # "rent": credit = tenant rent in, debit = Ejar fees
    (r"قسط قرض|installments", "expense", "loan_instalment"),
    (r"Administration Fees", "expense", "loan_fee"),
    (r"SPOUSE_NAME", "expense", "wife"),
    (r"FAMILY_NAME", "income_or_family", "family"),  # credit = gift in, debit = family out
    (r"THERAPY_PROVIDER", "expense", "therapy"),
    (r"ايداع نقدي|Cash Deposit", "own", "cash_deposit"),
]

# ---------- build_dashboard.py + dashboard_template.html ----------
INCOME_SUBS = ("salary", "tenant_rent")  # flows.csv income subs counted as income
CITIES = re.compile(r"(RIYADH|JEDDAH|DAMMAM|MAKKAH|MADINAH)", re.I)  # added to the Maps merchant search
DRAHIM_REPORT = []  # optional: Drahim app's monthly {"from", "to", "spend", "income", "xfer"} to compare
DASHBOARD = {
    "subtitle": "bank SMS + statements · local file",
    "window": "2026",
    "anchor": "2026-12-26T12:00:00",  # period view opens on this date
    "rent": {"monthly": 5000, "bank": "BANK", "toggle": "Spread prepaid rent (60k/yr → 5k/mo)",
             "mer": "Rent (prepaid, spread)", "sms": "Yearly rent paid up front, spread over 12 months"},
    "one_off_toggle": "Hide one-offs",
    "budget": {"Rent": 5000, "Loans": 5000, "Spouse": 5000, "Travel": 3000, "Shopping": 2000, "Food": 3000,
               "Life admin": 3000, "People & giving": 1000, "Fun": 500, "One-offs": 0, "Unknown": 1000},
    "plan": {
        "title": "The plan — savings goal", "note": "(standing orders)",
        "start": "2027-01-01", "goal": 100000, "goal_label": "Goal reached",
        "bar_note": "goal reached when this bar fills",
        "orders": [  # [what, SAR/month, note, counts as savings]
            ["Bank A → Spouse, 28th", 3000, "Allowance", 0],
            ["Bank A → Bank B, 1st (loan debit)", 5000, "Loan + buffer", 0],
            ["Bank B → Savings, 1st", 5000, "Savings", 1],
        ],
    },
    "lifestyle": {"label": "Household lifestyle", "groups": ["Spouse", "Travel", "Shopping"], "budget": 10000,
                  "note": "(allowance, shopping, travel)"},
}

# ---------- tools/counterfactual.py ----------
TOY_SUBS = re.compile(r"STEAM|AUDIBLE", re.I)  # subscriptions the "no toy subscriptions" rule would cut
TRIPS = []  # [("YYYY-MM-DD", "YYYY-MM-DD")] travel days, excluded from the counterfactual
