"""Seeded, deterministic generator for the personal-finance demo dataset.

Produces deliberately messy files that mirror real Indian bank / UPI exports:

- mixed date formats (ISO, DD/MM/YYYY, DD-Mon-YY), "Jan-2025" month labels
- amounts as "₹1,20,000.00" (lakh grouping), "Rs. 1234.5", "INR 1,234.50", plain
- inconsistent header casing / whitespace, a header with a currency symbol
- blank rows, a repeated header row, trailing whitespace, "N/A" placeholders
- Yes / Y / yes / No / N booleans
- merchant aliases inside free-text descriptions

The same seed always yields byte-identical files, so the benchmark is reproducible.

Usage:  python -m app.demo.generate --out ../data/demo
"""

from __future__ import annotations

import argparse
import csv
import random
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

DEFAULT_SEED = 42
START = date(2025, 1, 1)
END = date(2026, 6, 30)

CATEGORIES: list[tuple[str, str, str, bool]] = [
    # id, name, group, essential
    ("CAT01", "Food & Dining", "Wants", False),
    ("CAT02", "Groceries", "Needs", True),
    ("CAT03", "Transport", "Needs", True),
    ("CAT04", "Shopping", "Wants", False),
    ("CAT05", "Utilities", "Needs", True),
    ("CAT06", "Rent", "Needs", True),
    ("CAT07", "Entertainment", "Wants", False),
    ("CAT08", "Health", "Needs", True),
    ("CAT09", "Education", "Needs", True),
    ("CAT10", "Travel", "Wants", False),
    ("CAT11", "Salary", "Income", False),
    ("CAT12", "Investments", "Savings", False),
    ("CAT13", "Transfers", "Transfers", False),
    ("CAT14", "Subscriptions", "Wants", False),
    ("CAT15", "Cash", "Needs", False),
]


@dataclass(frozen=True)
class Merchant:
    id: str
    name: str
    category: str
    city: str
    handle: str
    aliases: tuple[str, ...]


MERCHANTS: list[Merchant] = [
    Merchant(
        "M001",
        "Swiggy",
        "CAT01",
        "Bengaluru",
        "swiggy@icici",
        ("SWIGGY", "Swiggy Ltd", "swiggy*order"),
    ),
    Merchant(
        "M002",
        "Zomato",
        "CAT01",
        "Gurugram",
        "zomato@hdfcbank",
        ("ZOMATO", "Zomato Pvt Ltd", "zomato order"),
    ),
    Merchant(
        "M003", "Starbucks", "CAT01", "Bengaluru", "starbucks@ybl", ("STARBUCKS", "Tata Starbucks")
    ),
    Merchant(
        "M004",
        "BigBasket",
        "CAT02",
        "Bengaluru",
        "bigbasket@axis",
        ("BIGBASKET", "Big Basket", "bb now"),
    ),
    Merchant(
        "M005", "Blinkit", "CAT02", "Gurugram", "blinkit@icici", ("BLINKIT", "Blinkit Commerce")
    ),
    Merchant("M006", "DMart", "CAT02", "Bengaluru", "dmart@sbi", ("DMART", "Avenue Supermarts")),
    Merchant(
        "M007", "Uber", "CAT03", "Bengaluru", "uber@axis", ("UBER", "Uber India", "uber trip")
    ),
    Merchant("M008", "Ola", "CAT03", "Bengaluru", "olacabs@ybl", ("OLA", "ANI Technologies")),
    Merchant("M009", "IRCTC", "CAT03", "New Delhi", "irctc@sbi", ("IRCTC", "IRCTC E-Ticket")),
    Merchant(
        "M010",
        "Indian Oil",
        "CAT03",
        "Bengaluru",
        "iocl@hdfcbank",
        ("IOCL", "Indian Oil Petrol Pump"),
    ),
    Merchant(
        "M011",
        "Amazon",
        "CAT04",
        "Bengaluru",
        "amazon@apl",
        ("AMAZON", "Amazon Pay India", "amzn mktp"),
    ),
    Merchant(
        "M012", "Flipkart", "CAT04", "Bengaluru", "flipkart@axis", ("FLIPKART", "Flipkart Internet")
    ),
    Merchant("M013", "Myntra", "CAT04", "Bengaluru", "myntra@icici", ("MYNTRA", "Myntra Designs")),
    Merchant(
        "M014", "BESCOM", "CAT05", "Bengaluru", "bescom@sbi", ("BESCOM", "Bangalore Electricity")
    ),
    Merchant("M015", "Airtel", "CAT05", "New Delhi", "airtel@ybl", ("AIRTEL", "Bharti Airtel")),
    Merchant(
        "M016",
        "ACT Fibernet",
        "CAT05",
        "Bengaluru",
        "actfibernet@hdfcbank",
        ("ACT FIBERNET", "Atria Convergence"),
    ),
    Merchant(
        "M017",
        "Landlord - R. Sharma",
        "CAT06",
        "Bengaluru",
        "rsharma@okhdfc",
        ("RENT R SHARMA", "R Sharma Rent"),
    ),
    Merchant("M018", "PVR Cinemas", "CAT07", "Bengaluru", "pvr@icici", ("PVR", "PVR INOX")),
    Merchant(
        "M019",
        "BookMyShow",
        "CAT07",
        "Mumbai",
        "bookmyshow@axis",
        ("BOOKMYSHOW", "Bigtree Entertainment"),
    ),
    Merchant(
        "M020",
        "Apollo Pharmacy",
        "CAT08",
        "Chennai",
        "apollo@hdfcbank",
        ("APOLLO PHARMACY", "Apollo Health"),
    ),
    Merchant(
        "M021", "Practo", "CAT08", "Bengaluru", "practo@ybl", ("PRACTO", "Practo Technologies")
    ),
    Merchant(
        "M022", "Coursera", "CAT09", "Mountain View", "coursera@icici", ("COURSERA", "Coursera Inc")
    ),
    Merchant("M023", "Udemy", "CAT09", "San Francisco", "udemy@axis", ("UDEMY", "Udemy Inc")),
    Merchant(
        "M024", "IndiGo", "CAT10", "Gurugram", "indigo@hdfcbank", ("INDIGO", "InterGlobe Aviation")
    ),
    Merchant(
        "M025", "MakeMyTrip", "CAT10", "Gurugram", "makemytrip@icici", ("MAKEMYTRIP", "MMT India")
    ),
    Merchant(
        "M026",
        "Acme Technologies Payroll",
        "CAT11",
        "Bengaluru",
        "acmepayroll@hdfcbank",
        ("ACME TECH SALARY", "SAL ACME TECHNOLOGIES"),
    ),
    Merchant(
        "M027", "Zerodha", "CAT12", "Bengaluru", "zerodha@hdfcbank", ("ZERODHA", "Zerodha Broking")
    ),
    Merchant("M028", "Groww", "CAT12", "Bengaluru", "groww@axis", ("GROWW", "Nextbillion Tech")),
    Merchant(
        "M029",
        "ICICI Credit Card Bill",
        "CAT13",
        "Mumbai",
        "icicicc@icici",
        ("ICICI CC PAYMENT", "CC BILLPAY ICICI"),
    ),
    Merchant(
        "M030",
        "Paytm Wallet Top-up",
        "CAT13",
        "Noida",
        "paytm@paytm",
        ("PAYTM ADD MONEY", "Paytm Wallet"),
    ),
    Merchant(
        "M031", "Netflix", "CAT14", "Mumbai", "netflix@icici", ("NETFLIX", "Netflix Entertainment")
    ),
    Merchant("M032", "Spotify", "CAT14", "Mumbai", "spotify@axis", ("SPOTIFY", "Spotify India")),
    Merchant(
        "M033", "Cult.fit", "CAT08", "Bengaluru", "cultfit@ybl", ("CULTFIT", "Curefit Healthcare")
    ),
]
M = {m.name: m for m in MERCHANTS}

ACCOUNTS = [
    # id, name, bank, type, opened_on, opening_balance, credit_limit, active
    (
        "ACC01",
        "HDFC Salary Account",
        "HDFC Bank",
        "Savings",
        date(2019, 7, 15),
        85000.0,
        None,
        True,
    ),
    (
        "ACC02",
        "SBI Savings",
        "State Bank of India",
        "Savings",
        date(2016, 3, 2),
        42000.0,
        None,
        True,
    ),
    (
        "ACC03",
        "ICICI Coral Credit Card",
        "ICICI Bank",
        "Credit Card",
        date(2021, 11, 20),
        0.0,
        200000.0,
        True,
    ),
    ("ACC04", "Paytm Wallet", "Paytm Payments Bank", "Wallet", date(2020, 1, 8), 500.0, None, True),
    (
        "ACC05",
        "Kotak Old Savings",
        "Kotak Mahindra Bank",
        "Savings",
        date(2014, 6, 30),
        1200.0,
        None,
        False,
    ),
]

MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


@dataclass
class Txn:
    d: date
    account: str
    merchant: Merchant | None
    amount: float
    direction: str  # Debit | Credit
    mode: str
    status: str = "Success"
    note: str = ""
    desc: str = ""


# ----------------------------------------------------------------------------- formatting


def indian_grouping(value: float) -> str:
    """1234567.5 -> '12,34,567.50' (Indian lakh/crore grouping)."""
    neg = value < 0
    whole, frac = f"{abs(value):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups: list[str] = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join([*groups, tail])
    return f"{'-' if neg else ''}{whole}.{frac}"


def fmt_amount(rng: random.Random, value: float) -> str:
    r = rng.random()
    if r < 0.45:
        return f"₹{indian_grouping(value)}"
    if r < 0.65:
        return f"Rs. {round(value, 1)}"
    if r < 0.80:
        return f"INR {indian_grouping(value)}"
    return f"{value:.2f}"


def fmt_date(rng: random.Random, d: date) -> str:
    r = rng.random()
    if r < 0.6:
        return d.isoformat()
    if r < 0.9:
        return d.strftime("%d/%m/%Y")
    return f"{d.day:02d}-{MONTH_NAMES[d.month - 1]}-{d.year % 100:02d}"


def fmt_bool(rng: random.Random, v: bool) -> str:
    return rng.choice(["Yes", "Y", "yes"] if v else ["No", "N", "no"])


# ----------------------------------------------------------------------------- simulation


def _months() -> list[tuple[int, int]]:
    out = []
    y, m = START.year, START.month
    while (y, m) <= (END.year, END.month):
        out.append((y, m))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def _rand_day(rng: random.Random, y: int, m: int) -> date:
    return date(y, m, rng.randint(1, monthrange(y, m)[1]))


def _amt(rng: random.Random, lo: float, hi: float) -> float:
    return round(rng.uniform(lo, hi), 2)


def simulate(rng: random.Random) -> list[Txn]:
    txns: list[Txn] = []

    def add(
        d: date, acct: str, merchant: str | None, amount: float, direction: str, mode: str
    ) -> None:
        txns.append(
            Txn(d, acct, M[merchant] if merchant else None, round(amount, 2), direction, mode)
        )

    for y, m in _months():
        last = monthrange(y, m)[1]
        festive = m in (10, 11)
        holiday = m in (5, 12)
        salary = 135000.0 if (y, m) >= (2026, 4) else 120000.0

        add(date(y, m, 1), "ACC01", "Acme Technologies Payroll", salary, "Credit", "NEFT")
        add(date(y, m, 5), "ACC01", "Landlord - R. Sharma", 28000.0, "Debit", "NetBanking")
        add(date(y, m, 10), "ACC01", "Zerodha", 10000.0, "Debit", "Auto-debit")
        add(date(y, m, 10), "ACC02", "Groww", 5000.0, "Debit", "Auto-debit")
        add(
            date(y, m, rng.randint(12, 18)),
            "ACC02",
            "BESCOM",
            _amt(rng, 1200, 3600 if m in (4, 5) else 2400),
            "Debit",
            "UPI",
        )
        add(date(y, m, 3), "ACC03", "Airtel", 599.0, "Debit", "Auto-debit")
        add(date(y, m, 7), "ACC01", "ACT Fibernet", 999.0, "Debit", "UPI")
        add(date(y, m, 14), "ACC03", "Netflix", 649.0, "Debit", "Auto-debit")
        add(date(y, m, 21), "ACC03", "Spotify", 119.0, "Debit", "Auto-debit")
        if (y, m) >= (2025, 9):
            add(date(y, m, 2), "ACC01", "Cult.fit", 1499.0, "Debit", "Auto-debit")

        # card bill: pay previous month's card spend from HDFC, credited on the card
        if (y, m) != (START.year, START.month):
            bill = _amt(rng, 18000, 42000 if festive else 30000)
            add(date(y, m, 18), "ACC01", "ICICI Credit Card Bill", bill, "Debit", "NetBanking")
            add(date(y, m, 18), "ACC03", "ICICI Credit Card Bill", bill, "Credit", "NetBanking")

        # wallet top-up
        topup = rng.choice([500.0, 1000.0, 2000.0])
        add(_rand_day(rng, y, m), "ACC02", "Paytm Wallet Top-up", topup, "Debit", "UPI")
        add(txns[-1].d, "ACC04", "Paytm Wallet Top-up", topup, "Credit", "UPI")

        for _ in range(rng.randint(9, 16)):
            mer = rng.choice(["Swiggy", "Zomato", "Swiggy", "Starbucks"])
            acct = rng.choice(["ACC01", "ACC03", "ACC04"])
            add(
                _rand_day(rng, y, m),
                acct,
                mer,
                _amt(rng, 140, 950),
                "Debit",
                "Card" if acct == "ACC03" else "UPI",
            )
        for _ in range(rng.randint(6, 10)):
            mer = rng.choice(["BigBasket", "Blinkit", "DMart"])
            add(
                _rand_day(rng, y, m),
                rng.choice(["ACC01", "ACC02"]),
                mer,
                _amt(rng, 180, 3200),
                "Debit",
                "UPI",
            )
        for _ in range(rng.randint(10, 20)):
            add(
                _rand_day(rng, y, m),
                rng.choice(["ACC01", "ACC04"]),
                rng.choice(["Uber", "Ola"]),
                _amt(rng, 85, 620),
                "Debit",
                "UPI",
            )
        for _ in range(rng.randint(2, 4)):
            add(_rand_day(rng, y, m), "ACC03", "Indian Oil", _amt(rng, 500, 3000), "Debit", "Card")
        if rng.random() < 0.5 or holiday:
            add(_rand_day(rng, y, m), "ACC02", "IRCTC", _amt(rng, 450, 2600), "Debit", "UPI")
        for _ in range(rng.randint(5, 9) if festive else rng.randint(2, 5)):
            mer = rng.choice(["Amazon", "Flipkart", "Myntra"])
            add(
                _rand_day(rng, y, m),
                "ACC03",
                mer,
                _amt(rng, 300, 9000 if festive else 5000),
                "Debit",
                "Card",
            )
        if rng.random() < 0.35:
            add(
                _rand_day(rng, y, m), "ACC03", "Amazon", _amt(rng, 200, 2500), "Credit", "Card"
            )  # refund
        for _ in range(rng.randint(1, 3)):
            add(
                _rand_day(rng, y, m),
                "ACC03",
                rng.choice(["PVR Cinemas", "BookMyShow"]),
                _amt(rng, 200, 1200),
                "Debit",
                "Card",
            )
        for _ in range(rng.randint(1, 2)):
            add(
                _rand_day(rng, y, m),
                "ACC01",
                "Apollo Pharmacy",
                _amt(rng, 90, 1600),
                "Debit",
                "UPI",
            )
        if rng.random() < 0.25:
            add(_rand_day(rng, y, m), "ACC01", "Practo", _amt(rng, 400, 900), "Debit", "UPI")
        if rng.random() < 0.2:
            add(
                _rand_day(rng, y, m),
                "ACC03",
                rng.choice(["Coursera", "Udemy"]),
                _amt(rng, 450, 3999),
                "Debit",
                "Card",
            )
        if holiday or rng.random() < 0.15:
            add(
                _rand_day(rng, y, m),
                "ACC03",
                rng.choice(["IndiGo", "MakeMyTrip"]),
                _amt(rng, 3200, 16000),
                "Debit",
                "Card",
            )
        for _ in range(rng.randint(0, 2)):
            add(
                _rand_day(rng, y, m),
                rng.choice(["ACC01", "ACC02"]),
                None,
                float(rng.choice([2000, 3000, 5000])),
                "Debit",
                "ATM",
            )
        if m == 3:
            add(
                date(y, m, last),
                "ACC02",
                None,
                round(rng.uniform(800, 1400), 2),
                "Credit",
                "Interest",
            )

    # statuses: ~2% failed, ~0.5% pending (never for salary / rent)
    for t in txns:
        if t.merchant and t.merchant.category in ("CAT11", "CAT06"):
            continue
        r = rng.random()
        if r < 0.02:
            t.status = "Failed"
        elif r < 0.025:
            t.status = "Pending"

    txns.sort(key=lambda t: (t.d, t.account, t.merchant.id if t.merchant else "", t.amount))
    return txns


def _describe(rng: random.Random, t: Txn, ref: int) -> str:
    if t.merchant is None:
        return (
            f"ATM WDL {rng.choice(['MG ROAD', 'KORAMANGALA', 'INDIRANAGAR'])} {ref}"
            if t.mode == "ATM"
            else "INTEREST CREDIT"
        )
    alias = rng.choice(t.merchant.aliases)
    if t.mode == "UPI":
        return f"UPI/{alias}/{t.merchant.handle}/{ref}"
    if t.mode == "Card":
        return f"POS {alias.upper()} {t.merchant.city.upper()}"
    if t.mode in ("NEFT", "NetBanking"):
        return f"NEFT-{alias}-{ref}"
    return f"ACH/{alias}/{ref}"


# ----------------------------------------------------------------------------- writers


def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def generate(out_dir: Path, seed: int = DEFAULT_SEED) -> dict[str, Path]:
    """Write the demo files into `out_dir` and return {table_name: path}."""
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)

    # categories
    cat_rows = [[cid, name, group, fmt_bool(rng, ess)] for cid, name, group, ess in CATEGORIES]
    _write_csv(
        out_dir / "categories.csv",
        ["Category ID", "Category Name", "Category Group", "Is Essential"],
        cat_rows,
    )

    # merchants (trailing whitespace on some names)
    mer_rows = [
        [m.id, m.name + (" " if rng.random() < 0.2 else ""), m.category, m.city, m.handle]
        for m in MERCHANTS
    ]
    _write_csv(
        out_dir / "merchants.csv",
        ["merchant_id", "Merchant Name", "category_id", "City", "UPI Handle"],
        mer_rows,
    )

    # accounts
    acc_rows = [
        [
            aid,
            name,
            bank,
            atype,
            fmt_date(rng, opened),
            fmt_amount(rng, bal),
            fmt_amount(rng, limit) if limit else "N/A",
            fmt_bool(rng, active),
        ]
        for aid, name, bank, atype, opened, bal, limit, active in ACCOUNTS
    ]
    _write_csv(
        out_dir / "accounts.csv",
        [
            "Account ID",
            "Account Name",
            "Bank",
            "Account Type",
            "Opened On",
            "Opening Balance",
            "Credit Limit",
            "Active",
        ],
        acc_rows,
    )

    # transactions
    txns = simulate(rng)
    header = [
        " Txn ID",
        "TXN DATE",
        "Account ID",
        "Description ",
        "Merchant ID",
        "Amount",
        "Type",
        "Payment Mode",
        "Status",
        "Notes",
    ]
    rows: list[list[str]] = []
    for i, t in enumerate(txns, start=1):
        ref = 400000000 + rng.randint(0, 99999999)
        note = ""
        nr = rng.random()
        if nr < 0.05:
            note = "N/A"
        elif nr < 0.08:
            note = rng.choice(["split with friends", "reimbursable", "gift", "office expense"])
        rows.append(
            [
                f"T{i:06d}",
                fmt_date(rng, t.d),
                t.account,
                _describe(rng, t, ref),
                t.merchant.id if t.merchant else "",
                fmt_amount(rng, t.amount),
                t.direction,
                t.mode,
                t.status + (" " if rng.random() < 0.03 else ""),
                note,
            ]
        )
    # mess: a repeated header mid-file and a few blank rows
    rows.insert(len(rows) // 2, [h.strip() for h in header])
    for _ in range(4):
        rows.insert(rng.randint(1, len(rows) - 1), [""] * len(header))
    _write_csv(out_dir / "transactions.csv", header, rows)

    # budgets (XLSX, month labels like "Jan-2025", header with currency symbol)
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Budgets"
    ws.append(["Month", "Category ID", "Budget (₹)"])
    budget_base = {
        "CAT01": 8000,
        "CAT02": 9000,
        "CAT03": 6000,
        "CAT04": 12000,
        "CAT05": 4500,
        "CAT07": 2500,
        "CAT08": 2500,
        "CAT10": 10000,
        "CAT14": 800,
    }
    for y, mth in _months():
        for cid, base in budget_base.items():
            bump = 1.1 if y == 2026 else 1.0
            ws.append([f"{MONTH_NAMES[mth - 1]}-{y}", cid, round(base * bump)])
    wb.properties.created = datetime(2026, 1, 1)
    wb.properties.modified = datetime(2026, 1, 1)
    wb.save(out_dir / "budgets.xlsx")

    return {
        "categories": out_dir / "categories.csv",
        "merchants": out_dir / "merchants.csv",
        "accounts": out_dir / "accounts.csv",
        "transactions": out_dir / "transactions.csv",
        "budgets": out_dir / "budgets.xlsx",
    }


DEMO_GLOSSARY: list[tuple[str, str]] = [
    (
        "spend",
        "Money going out: SUM(transactions.amount) WHERE transactions.type = 'Debit' AND transactions.status = 'Success'. Exclude the 'Transfers' and 'Investments' category groups unless asked.",
    ),
    (
        "income",
        "Money coming in from salary or interest: transactions.type = 'Credit' AND status = 'Success' in category 'Salary', or with no merchant and payment_mode = 'Interest'.",
    ),
    (
        "successful transaction",
        "transactions.status = 'Success'. Failed and Pending transactions never count towards spend or income.",
    ),
    ("savings rate", "(income - spend) / income for the same period."),
    ("essential spend", "Spend in categories where categories.is_essential is true."),
    ("UPI", "transactions.payment_mode = 'UPI'."),
    (
        "budget utilisation",
        "Spend in a category during a month divided by budgets.budget for that category and month (budgets.month is the first day of the month).",
    ),
]


def main() -> None:  # pragma: no cover
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, default=Path("data/demo"))
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = p.parse_args()
    for name, path in generate(args.out, args.seed).items():
        print(f"{name:14s} -> {path}")


if __name__ == "__main__":  # pragma: no cover
    main()
