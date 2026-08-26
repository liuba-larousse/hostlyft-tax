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

# Client email to the name used everywhere else. Built from HubSpot's own
# contacts and companies, so it stays consistent with the accounting sheet
# and with the Upwork mapping.
HUBSPOT_CLIENT_EMAILS = {
    "cody@hemlockhillscabinrentals.com": "Cody Hibbard",
    "don-nima@hotmail.co.uk": "Nima Karam",
    "michelleglohr@gmail.com": "Michelle Gilboa",
    "jennifer@makegoal.com": "Jennifer Moraci",
    "info@settler.homes": "Timur Khabirov",
    "binethandgroup@ap.ramp.com": "Chananya Bineth",
    "cb@21b.dev": "Chananya Bineth",
    "alessio@failla.co.uk": "Alessio Failla",
    "kohnalex76@gmail.com": "Alexandr Jaitner",
    "tomek@oomph.apartments": "Tomasz Jagiello",
    "tomasz.jerzy.jagiello@gmail.com": "Tomasz Jagiello",
    "office@oomph.apartments": "Tomasz Jagiello",
    "dorota.raczkiewicz@oomph.apartments": "Tomasz Jagiello",
    "tyler@enjoyuniquestays.com": "Tyler Willey",
    "accounting@enjoyuniquestays.com": "Tyler Willey",
    "invoices@enjoyuniquestays.com": "Tyler Willey",
    "shawn@airvevo.com": "Shawn Ye",
    "lokanitours@gmail.com": "Brian Costley",
    "marcus@thecloud9team.com": "Marcus Halawi",
    "stephenpnewall@gmail.com": "Stephen Newall",
    "apnewall@mac.com": "Andrew Newall",
}


def client_lookup_from_payments(payment_rows):
    """
    Build {(amount, date): client name} from the payments export.

    The invoice file has no customer column, so 48 income rows had no client
    against them. The payments export does carry the email, and the two agree
    on amount and date - so one can name the other.
    """
    exact, by_amount = {}, {}
    for row in payment_rows:
        email = (row.get("Customer email") or "").strip().lower()
        date = (row.get("Payment date") or "")[:10]
        try:
            amount = round(float(row.get("Gross amount") or 0), 2)
        except ValueError:
            continue
        if not (email and date and amount):
            continue
        who = HUBSPOT_CLIENT_EMAILS.get(email, email)
        exact[(amount, date)] = who
        # a second index on amount alone, for the many invoices whose
        # recorded payment date is a batch reconciliation rather than the
        # day the money moved
        by_amount.setdefault(amount, set()).add(who)

    # only usable where one client ever paid that exact figure
    unique = {amount: next(iter(people))
              for amount, people in by_amount.items() if len(people) == 1}
    return {"exact": exact, "unique_amount": unique}


def name_for(clients, amount, date):
    """
    Who paid this. Exact amount and date first, then amount alone - but only
    where a single client ever paid that figure, so a shared round number
    like 90.00 is never attributed to the wrong person.
    """
    if not clients:
        return None
    amount = round(float(amount), 2)
    found = clients.get("exact", {}).get((amount, date))
    if found:
        return found
    return clients.get("unique_amount", {}).get(amount)


def read_hubspot(path):
    """Read the extracted invoice file, ignoring its comment header."""
    with open(path, newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(r for r in handle if not r.startswith("#")))


def build_hubspot_records(rows, year=None, clients=None):
    """
    One income row per PAID invoice, at the amount the client actually paid.

    Unpaid invoices are not income - the money has not arrived. They are
    reported separately so what is outstanding stays visible.

    `subtotal` differing from `amount_paid` is a DISCOUNT given, not a fee.
    """
    income, outstanding, notes = [], [], []
    clients = clients or {}
    named = unnamed = 0

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
        who = name_for(clients, paid, date)
        if who:
            named += 1
        else:
            unnamed += 1

        income.append({
            "source": "hubspot", "source_id": f"hubspot:{invoice}",
            "payer": who,
            "business": config.BUSINESS_HOSTLYFT,
            "date": date, "amount": paid, "currency": currency,
            "amount_usd": paid if currency == "USD" else None,
            "description": (f"HubSpot invoice {invoice} (gross)"
                            + (f", after {discount:,.2f} discount"
                               if discount > 0 else "")),
        })

    if clients:
        notes.append(f"Client names: {named} invoices matched to a payment, "
                     f"{unnamed} could not be named.")
    notes.append(
        "HubSpot's processing fees are NOT in this file - the payment records "
        "holding them were not readable. Those fees are deductible and are "
        "currently missing from expenses.")
    return {"income": income, "outstanding": outstanding, "notes": notes}


# ===========================================================================
#  HUBSPOT PAYMENTS EXPORT  -  fees and refunds only
# ===========================================================================
#
# HubSpot offers two payment exports and only one is useful here. The plain
# one has no fee columns at all; the "net" one adds Refunded amount,
# Platform fee, Processing fees and Net amount.
#
# THIS IS NOT AN INCOME SOURCE. Income already comes from the invoices, and
# importing both would count every payment twice - the mistake this project
# has already made once with Stripe payouts and once with Upwork earnings.
#
# What it contributes is the two deductions the invoices cannot show:
#
#   fees     what HubSpot kept. Only charged on payments that actually went
#            through HubSpot Payments - most of Hostlyft's were "Manually
#            recorded", meaning the client paid directly and the invoice was
#            marked paid afterwards. Those bore no fee.
#   refunds  money given back. On Schedule C these are "returns and
#            allowances" against gross receipts rather than an expense, so
#            they are categorised separately to be reported that way.


def is_payments_export(path):
    """The useful export is the one with the fee columns."""
    with open(path, newline="", encoding="utf-8-sig") as handle:
        header = handle.readline()
    return "Processing fees" in header and "Gross amount" in header


def read_hubspot_payments(path):
    with open(path, newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def build_hubspot_payment_records(rows, year=None):
    """Fees and refunds. Deliberately no income rows."""
    expenses, notes = [], []
    number = lambda row, key: float(row.get(key) or 0)

    fees_total = refunds_total = 0.0
    skipped_failed = 0

    for row in rows:
        date = (row.get("Payment date") or "")[:10]
        if not date or (year and not date.startswith(str(year))):
            continue
        if (row.get("Status") or "").lower() == "failed":
            skipped_failed += 1
            continue

        record = row.get("Record ID") or date
        who = (row.get("Customer email") or "").strip() or None

        fee = number(row, "Platform fee") + number(row, "Processing fees")
        if fee:
            fees_total += fee
            expenses.append({
                "source": "hubspot", "source_id": f"hubspot-fee:{record}",
                "business": config.BUSINESS_HOSTLYFT, "date": date,
                "amount": round(fee, 2), "currency": "USD",
                "amount_usd": round(fee, 2),
                "category": "payment processing", "vendor": "HubSpot",
                "description": (f"HubSpot fee on a "
                                f"{number(row, 'Gross amount'):,.2f} payment"),
            })

        refunded = number(row, "Refunded amount")
        if refunded:
            refunds_total += refunded
            expenses.append({
                "source": "hubspot", "source_id": f"hubspot-refund:{record}",
                "business": config.BUSINESS_HOSTLYFT, "date": date,
                "amount": round(refunded, 2), "currency": "USD",
                "amount_usd": round(refunded, 2),
                "category": "refunds to clients", "vendor": who,
                "description": (f"Refund of {refunded:,.2f} against a "
                                f"{number(row, 'Gross amount'):,.2f} payment "
                                f"[{row.get('Status')}]"),
            })

    notes.append(f"HubSpot: ${fees_total:,.2f} of fees and ${refunds_total:,.2f} "
                 f"of refunds, both deductible, from the payments export. "
                 f"Fees are only charged on payments that went through "
                 f"HubSpot Payments - the rest were paid to you directly.")
    if skipped_failed:
        notes.append(f"{skipped_failed} failed payment(s) skipped - not income "
                     f"and no fee.")

    return {"expenses": expenses, "notes": notes,
            "fees_total": round(fees_total, 2),
            "refunds_total": round(refunds_total, 2)}


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

# Upwork shows the company; the accounting sheet uses the person's name.
# Without this, "Sand, Gravel, and Mulch LLC." and "Brian" look like two
# different clients and his income lands nowhere in the team splits.
UPWORK_CLIENT_PEOPLE = {
    "sand, gravel, and mulch": "Brian Costley",
    "the cloud nine team": "Marcus Halawi",
    "jennifer m": "Jennifer Moraci",
    "michelle frankel": "Michelle Frankel",
    "21b": "Chananya Bineth",
}


def person_for_client(client):
    """The human behind an Upwork client name, where one is known."""
    low = (client or "").strip().lower()
    for pattern, person in UPWORK_CLIENT_PEOPLE.items():
        if pattern in low:
            return person
    return None

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
                "payer": person_for_client(client) or client or None,
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
