"""
manual_entry.py - for money that no system reports.

Some real transactions appear in no API at all. The one that prompted this:
Michelle's contract ended in July and $131 was refunded to her through
HubSpot. It is a genuine deductible cost, and it is invisible - HubSpot's
payment records are not readable through the available connection, and it
never touched Wise or the card.

Without somewhere to put it, the only options are to lose the deduction or
to invent a number in the database. Both are worse than a small file that
says plainly "this was entered by hand, and here is why".

Every row carries a `note` explaining where it came from, and is marked
needs_review so it stays visible rather than blending in with imported data.
"""

import csv

from taxlib import config


TEMPLATE = """\
# Transactions that no system reports - entered by hand.
#
# One row per transaction. Delete the examples and add your own.
#
#   date        YYYY-MM-DD, the day the money actually moved
#   kind        income  or  expense
#   amount      a positive number
#   currency    USD, EUR, GBP ...
#   category    for expenses: see rules.txt. Ignored for income.
#   who         who was paid, or who paid you
#   note        WHY this is here and where the figure came from.
#               Required - a hand-entered figure with no explanation is
#               indistinguishable from a mistake a year from now.
#
date,kind,amount,currency,category,who,note
"""


def ensure_template():
    """Create the file with its explanation if it isn't there yet."""
    path = config.IMPORTS_DIR / "manual.csv"
    if not path.exists():
        config.IMPORTS_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(TEMPLATE)
        path.chmod(0o600)
    return path


def read(path=None):
    path = path or (config.IMPORTS_DIR / "manual.csv")
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8-sig") as handle:
        return [row for row in csv.DictReader(
            line for line in handle if not line.startswith("#"))
            if row.get("date") and row.get("amount")]


def build_records(rows, year=None):
    """Turn the hand-entered rows into income and expense records."""
    income, expenses, problems = [], [], []

    for index, row in enumerate(rows, start=1):
        date = (row.get("date") or "").strip()
        kind = (row.get("kind") or "").strip().lower()
        note = (row.get("note") or "").strip()

        if year and not date.startswith(str(year)):
            continue
        if kind not in ("income", "expense"):
            problems.append(f"row {index}: kind must be 'income' or "
                            f"'expense', not '{kind}'")
            continue
        if not note:
            problems.append(f"row {index}: needs a note saying where this "
                            f"figure came from")
            continue

        try:
            amount = abs(float(row["amount"]))
        except ValueError:
            problems.append(f"row {index}: '{row['amount']}' is not a number")
            continue

        currency = (row.get("currency") or "USD").strip().upper()
        who = (row.get("who") or "").strip() or None
        common = {
            "source": "manual", "source_id": f"manual:{date}:{index}",
            "business": config.BUSINESS_HOSTLYFT,
            "date": date, "amount": amount, "currency": currency,
            "amount_usd": amount if currency == "USD" else None,
            "description": note[:200],
            "needs_review": True,
            "review_note": f"entered by hand: {note[:150]}",
        }
        if kind == "income":
            income.append({**common, "payer": who})
        else:
            expenses.append({**common, "vendor": who,
                             "category": (row.get("category") or "").strip()
                                         or "uncategorized"})

    return {"income": income, "expenses": expenses, "problems": problems}
