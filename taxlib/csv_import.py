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

# Upwork's published freelancer fee. Used ONLY to show roughly what is
# missing - never written to the database as if it were a real figure.
UPWORK_HEADLINE_FEE = 0.10

# Which contract belongs to which client. Contract names are stable, so this
# is filled in once per contract and never again. Anything not listed is
# flagged rather than guessed - Upwork mixes two businesses.
UPWORK_CONTRACTS = {}


def contract_id(name):
    """"OTA Optimization (42772450)" -> "42772450"."""
    found = re.search(r"\((\d+)\)\s*$", name or "")
    return found.group(1) if found else None


def read_upwork(paths):
    """Read one or more Upwork report exports, dropping exact duplicates."""
    seen, rows = set(), []
    for path in paths:
        with open(path, newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                if not row.get("Date") or not row.get("Amount"):
                    continue
                key = (row["Date"], row["Contract"], row["Amount"],
                       row.get("Payment type", ""))
                if key in seen:
                    continue
                seen.add(key)
                rows.append(row)
    return rows


def build_upwork_records(rows, year=None):
    """
    One income row per Upwork earning, at GROSS.

    What reaches the bank is net of Upwork's cut, so the bank figure would
    understate gross receipts AND lose the fee deduction.

    Every row is tagged to a business from UPWORK_CONTRACTS. Anything not
    listed is flagged for review: Upwork carries both Hostlyft work and the
    separate Marcus work, and a single payout can contain both.
    """
    income, notes = [], []
    unmapped = {}

    for row in rows:
        date = row["Date"]
        if year and not date.startswith(str(year)):
            continue

        contract = row["Contract"]
        cid = contract_id(contract)
        amount = float(row["Amount"])
        kind = row.get("Payment type") or "Hourly"

        mapping = UPWORK_CONTRACTS.get(cid)
        if mapping:
            client, business = mapping
            needs_review, note = False, None
        else:
            client, business = None, config.BUSINESS_HOSTLYFT
            needs_review = True
            note = (f"Upwork contract {cid} is not mapped to a client yet. "
                    f"Counted under Hostlyft; if this work is Marcus's the "
                    f"business tag is wrong. Tell Claude whose it is.")
            unmapped[contract] = unmapped.get(contract, 0) + amount

        income.append({
            "source": "upwork",
            "source_id": f"upwork:{date}:{cid or 'x'}:{amount:.2f}",
            "business": business, "date": date,
            "amount": amount, "currency": "USD", "amount_usd": amount,
            "description": f"{contract[:120]} [{kind}]",
            "payer": client,
            "needs_review": needs_review, "review_note": note,
        })

    gross = sum(r["amount"] for r in income)
    notes.append(
        f"This export is Upwork's WEEKLY SUMMARY, which has no fee column. "
        f"Gross of ${gross:,.2f} is recorded correctly, but roughly "
        f"${gross * UPWORK_HEADLINE_FEE:,.2f} of deductible Upwork fees are "
        f"missing. Upwork's TRANSACTION HISTORY report does include fees.")

    if unmapped:
        notes.append(f"{len(unmapped)} contracts are unmapped - see the "
                     f"review list below.")

    return {"income": income, "notes": notes, "unmapped": unmapped}
