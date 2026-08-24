"""
csv_import.py - one-time imports from files, for sources with no live API.

Two platforms Hostlyft has left or cannot query:

  HubSpot   invoices for January-July 2026. Hostlyft moved off HubSpot after
            30 July, so this is a fixed historical record, extracted once.

  Upwork    earnings exported from the Upwork reports page. There is no
            usable API, and the notification emails only reach back to
            20 July 2026 - the address changed that day.

Both record income GROSS. What arrives in the bank is net of the platform's
cut, and recording that instead would understate gross receipts and throw
away the fee deduction.
"""

import csv
import re

from taxlib import config


# ===========================================================================
#  HUBSPOT
# ===========================================================================

def read_hubspot(path):
    """Read the extracted invoice file, ignoring its comment header."""
    with open(path, newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(r for r in handle if not r.startswith("#")))


def build_hubspot_records(rows, year=None):
    """
    One income row per PAID invoice, at the amount the client actually paid.

    Unpaid invoices are not income - the money has not arrived. They are
    reported separately so what is outstanding stays visible.

    `subtotal` differing from `amount_paid` is a DISCOUNT given, not a fee.
    """
    income, outstanding, notes = [], [], []

    for row in rows:
        invoice = row["invoice"]
        currency = row["currency"].upper()
        paid = float(row["amount_paid"] or 0)
        subtotal = float(row["subtotal"] or 0)
        date = row["payment_date"]

        if row["status"] != "paid" or not date:
            if subtotal:
                outstanding.append({"invoice": invoice, "amount": subtotal,
                                    "currency": currency,
                                    "status": row["status"]})
            continue

        if year and not date.startswith(str(year)):
            continue

        discount = round(subtotal - paid, 2)
        income.append({
            "source": "hubspot", "source_id": f"hubspot:{invoice}",
            "business": config.BUSINESS_HOSTLYFT,
            "date": date, "amount": paid, "currency": currency,
            "amount_usd": paid if currency == "USD" else None,
            "description": (f"HubSpot invoice {invoice} (gross)"
                            + (f", after {discount:,.2f} discount"
                               if discount > 0 else "")),
        })

    notes.append(
        "HubSpot's processing fees are NOT in this file - the payment records "
        "holding them were not readable. Those fees are deductible and are "
        "currently missing from expenses.")
    return {"income": income, "outstanding": outstanding, "notes": notes}


# ===========================================================================
#  UPWORK
# ===========================================================================
#
# Upwork offers two exports and they are NOT equivalent:
#
#   Weekly summary      date, contract, amount. Gross only - no fees.
#   Transaction report  every ledger line: earnings, service fees, sales tax,
#                       withdrawals, AND the client name on each one.
#
# The transaction report is used whenever it is present, because it carries
# the fees (a real deduction) and the client (which decides whether the work
# is Hostlyft's or the separate Marcus work).
#
# Using both would double-count everything they overlap on, so the weekly
# summaries are ignored for any period the transaction report covers.

# Upwork's client names, and which business each one's work belongs to.
# Taken from the "Client team" column, so new clients appear by themselves.
UPWORK_CLIENT_BUSINESS = {
    # Marcus Halawi trades as Cloud 9 - this is the separate Marcus work.
    "the cloud nine team": config.BUSINESS_MARCUS,
}

EARNING_TYPES = {"hourly", "fixed-price", "bonus"}
FEE_TYPES = {"service fee", "state sales tax"}
# Moving money to her own bank. Not an expense; the Wise credit is handled
# separately as an internal transfer.
TRANSFER_TYPES = {"withdrawal"}


def _upwork_date(text):
    """Upwork writes "Aug 21, 2026"."""
    import datetime as dt
    try:
        return dt.datetime.strptime((text or "").strip().strip('"'),
                                    "%b %d, %Y").date().isoformat()
    except ValueError:
        return None


def is_transaction_report(path):
    """Tell the two export formats apart by their columns."""
    with open(path, newline="", encoding="utf-8-sig") as handle:
        header = handle.readline()
    return "Transaction type" in header


def read_upwork_transactions(path):
    with open(path, newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def business_for_client(client):
    """Which business an Upwork client's work belongs to."""
    low = (client or "").strip().lower()
    for pattern, business in UPWORK_CLIENT_BUSINESS.items():
        if pattern in low:
            return business
    return config.BUSINESS_HOSTLYFT


def build_upwork_records(rows, year=None):
    """
    Turn the transaction report into income and expense rows.

    Earnings are recorded GROSS. Upwork's service fee and the sales tax it
    charges on that fee are separate deductible expenses - which is exactly
    the treatment Stripe gets, and exactly what the bank figure alone would
    have thrown away.

    Withdrawals are skipped: that is money moving to her own bank, not a
    cost.
    """
    income, expenses, notes = [], [], []
    clients = {}

    for row in rows:
        date = _upwork_date(row.get("Date"))
        if not date or (year and not date.startswith(str(year))):
            continue

        kind = (row.get("Transaction type") or "").strip().lower()
        amount = float(row.get("Amount $") or 0)
        contract = (row.get("Transaction summary") or "").strip()
        client = (row.get("Client team") or "").strip()
        txn_id = row.get("Ref ID") or row.get("Transaction ID") or ""

        if kind in TRANSFER_TYPES:
            continue

        if kind in EARNING_TYPES:
            business = business_for_client(client)
            clients.setdefault(client or "(none)", {"total": 0.0,
                                                    "business": business})
            clients[client or "(none)"]["total"] += amount
            income.append({
                "source": "upwork", "source_id": f"upwork:{txn_id}",
                "business": business, "date": date,
                "amount": amount, "currency": "USD", "amount_usd": amount,
                "description": f"{contract[:110]} [{row.get('Transaction type')}]",
                "payer": client or None,
            })
            continue

        if kind in FEE_TYPES:
            expenses.append({
                "source": "upwork", "source_id": f"upwork:{txn_id}",
                "business": business_for_client(client), "date": date,
                "amount": abs(amount), "currency": "USD",
                "amount_usd": abs(amount),
                "category": "payment processing", "vendor": "Upwork",
                "description": f"{row.get('Transaction type')} - {contract[:70]}",
            })
            continue

        notes.append(f"Upwork transaction type '{row.get('Transaction type')}' "
                     f"on {date} was not imported - tell Claude about it.")

    gross = sum(r["amount"] for r in income)
    fees = sum(r["amount"] for r in expenses)
    notes.insert(0, f"Upwork: ${gross:,.2f} gross earnings and ${fees:,.2f} of "
                    f"deductible fees, taken from the transaction report.")

    return {"income": income, "expenses": expenses, "notes": notes,
            "clients": clients}
