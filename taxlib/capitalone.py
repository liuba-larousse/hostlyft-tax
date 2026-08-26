"""
capitalone.py - the credit card statement.

WHY THE COLUMNS ARE DETECTED RATHER THAN ASSUMED
    Banks change their exports without telling anyone. Today the file is

        Transaction Date, Posted Date, Card No., Description, Category,
        Debit, Credit

    A hard-coded reader breaks silently the first time that changes - or
    worse, reads the wrong column and produces plausible nonsense. So the
    columns are found by name, and a file that cannot be understood is
    refused with an explanation rather than half-read.

THE DOUBLE-COUNT TRAP
    A credit-card statement contains PAYMENTS TO THE CARD. Those are not
    expenses - they are money moving from one of your accounts to another.
    The expenses are the purchases; the payment settles them.

    Counting both doubles everything on the card. Worse, those payments are
    ALSO visible in Wise as "Paid to CAPITAL ONE", where they are already
    excluded for the same reason. This file skips them.

REFUNDS AND CASHBACK
    A refund of a business purchase reduces what that purchase cost, so it
    is recorded as a negative expense rather than as income. Same for
    cashback: it is a rebate on spending, not earnings.
"""

import csv
import hashlib
import re

from taxlib import config


# How each column is recognised, in order of preference.
COLUMN_PATTERNS = {
    "date": [r"^transaction\s*date$", r"^date$", r"^posted\s*date$"],
    "posted": [r"^posted\s*date$"],
    "description": [r"^description$", r"^merchant$", r"^payee$"],
    "category": [r"^category$"],
    "debit": [r"^debit$", r"^amount$", r"^charges?$"],
    "credit": [r"^credit$", r"^payments?$", r"^credits?$"],
    "card": [r"^card\s*no\.?$", r"^card$", r"^account$"],
}

# Payments to the card itself. Not expenses.
CARD_PAYMENT_PATTERNS = [
    "capital one online pymt", "capital one autopay pymt",
    "capital one mobile pymt", "online payment", "autopay",
    "payment thank you", "payment - thank you",
]

# Cashback and rewards: a rebate on spending, not income.
REWARD_PATTERNS = ["cash back reward", "cashback", "rewards credit"]


class CapitalOneError(Exception):
    """The file could not be understood."""


def detect_columns(header):
    """Map our names onto whatever the bank called its columns."""
    found = {}
    for name, patterns in COLUMN_PATTERNS.items():
        for pattern in patterns:
            for column in header:
                if re.match(pattern, (column or "").strip(), re.IGNORECASE):
                    found.setdefault(name, column)
                    break
            if name in found:
                break

    missing = [n for n in ("date", "description") if n not in found]
    if missing or not ("debit" in found or "credit" in found):
        raise CapitalOneError(
            f"This does not look like a card statement.\n"
            f"Columns found: {', '.join(header)}\n"
            f"Expected something like: Transaction Date, Description, "
            f"Debit, Credit.\n"
            f"If the bank has changed its export, tell Claude and the reader "
            f"will be adjusted - it is deliberately not guessing.")
    return found


def read(path):
    with open(path, newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise CapitalOneError(f"{path} has no rows.")
    return rows, detect_columns(list(rows[0].keys()))


def _is(description, patterns):
    low = (description or "").lower()
    return any(p in low for p in patterns)


def _amount(row, columns, key):
    raw = (row.get(columns.get(key) or "") or "").strip()
    if not raw:
        return 0.0
    try:
        return abs(float(raw.replace(",", "").replace("$", "")))
    except ValueError:
        return 0.0


def row_id(date, description, amount):
    """
    A stable id, since the statement gives none.

    Built from the date, description and amount, so re-importing the same
    file updates the same rows instead of adding a second copy - and two
    genuinely identical charges on the same day stay distinguishable by the
    counter the caller appends.
    """
    digest = hashlib.sha1(
        f"{date}|{description}|{amount:.2f}".encode()).hexdigest()[:12]
    return f"capitalone:{digest}"


def build_records(rows, columns, year=None):
    """Turn statement lines into expense rows."""
    expenses, skipped, notes = [], [], []
    seen = {}

    for row in rows:
        date = (row.get(columns["date"]) or "").strip()[:10]
        if not date or (year and not date.startswith(str(year))):
            continue

        description = (row.get(columns["description"]) or "").strip()
        bank_category = (row.get(columns.get("category") or "") or "").strip()
        debit = _amount(row, columns, "debit")
        credit = _amount(row, columns, "credit")

        # a payment to the card is a transfer between your own accounts
        if _is(description, CARD_PAYMENT_PATTERNS):
            skipped.append({"date": date, "description": description,
                            "amount": credit or debit,
                            "why": "payment to the card, not an expense"})
            continue

        if debit:
            amount, kind = debit, "purchase"
        elif credit:
            # a refund reduces what the original purchase cost; cashback is
            # a rebate on spending. Neither is income.
            amount = -credit
            kind = ("cashback" if _is(description, REWARD_PATTERNS)
                    else "refund")
        else:
            continue

        source_id = row_id(date, description, amount)
        seen[source_id] = seen.get(source_id, 0) + 1
        if seen[source_id] > 1:
            source_id = f"{source_id}:{seen[source_id]}"

        expenses.append({
            "source": "capitalone", "source_id": source_id,
            "business": config.BUSINESS_HOSTLYFT,
            "date": date, "amount": amount, "currency": "USD",
            "amount_usd": amount,
            "category": "uncategorized",
            "vendor": description[:60],
            "description": (f"{description[:80]}"
                            + (f" [{bank_category}]" if bank_category else "")
                            + (f" — {kind}" if kind != "purchase" else "")),
        })

    total = sum(r["amount"] for r in expenses)
    notes.append(f"Capital One: {len(expenses)} lines, ${total:,.2f} net.")
    if skipped:
        paid = sum(s["amount"] for s in skipped)
        notes.append(f"{len(skipped)} payments to the card, ${paid:,.2f}, "
                     f"skipped - they settle the purchases rather than being "
                     f"expenses of their own. Wise shows the same payments "
                     f"going out, where they are already excluded.")

    return {"expenses": expenses, "skipped": skipped, "notes": notes}


def find_duplicates(connection, expenses, days=3):
    """
    Charges that look like something already recorded from another source.

    Anthropic is paid on both this card and the Wise card, so a genuine
    duplicate is possible. Reported, never removed automatically - deleting
    a real expense is worse than showing a pair to check.
    """
    import datetime as dt

    hits = []
    for row in expenses:
        if row["amount"] <= 0:
            continue
        day = dt.date.fromisoformat(row["date"])
        low = (day - dt.timedelta(days=days)).isoformat()
        high = (day + dt.timedelta(days=days)).isoformat()
        match = connection.execute(
            "SELECT date, vendor, amount_usd, source FROM expenses "
            "WHERE source != 'capitalone' AND excluded = 0 "
            "AND ABS(amount_usd - ?) < 0.005 AND date BETWEEN ? AND ?",
            (row["amount"], low, high)).fetchone()
        if match:
            hits.append((row, match))
    return hits
