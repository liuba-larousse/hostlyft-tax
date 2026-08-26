"""
receipts.py - only count an invoice if the money can be traced.

THE PROBLEM
    Income was taken from invoices marked paid. But "paid" is a status
    somebody set in HubSpot or Stripe, not evidence that money arrived.

    On a cash basis that is the wrong test. Worse, it produced double
    counting: an invoice for $1,689.25 was counted, AND the $1,683.14 that
    actually arrived was counted as a separate payment - the same money,
    twice, differing only by a $6.11 wire fee.

THE TEST APPLIED HERE
    For every invoice, ask: can the money be traced?

    1. Paid through a processor - Stripe, or HubSpot Payments.
       The money arrives BATCHED and net: a $270 invoice turns up inside a
       $438.48 payout. It cannot be matched one to one, but the payout is
       visible and already excluded as an internal transfer, so the invoice
       is the right place to count it. VERIFIED.

    2. Paid directly, and a bank credit matches it.
       Exactly, or within 1% - a client wires an invoice and their bank
       takes a fee, so $1,689.25 arrives as $1,683.14. VERIFIED: the
       invoice is counted at gross, the credit is excluded as its arrival,
       and the difference is recorded as a bank fee, which is deductible.

    3. Neither.
       NOT COUNTED. Flagged instead, saying which invoice and how much.
       Money may well have arrived somewhere not being read - but counting
       income that cannot be traced is exactly how a return becomes
       indefensible.

    A credit is only ever matched to ONE invoice, and only if it is not
    already attributed to something else. Without that, an Upwork payout of
    $1,302.15 would happily "verify" an unrelated $1,300.50 invoice.
"""

import datetime as dt

from taxlib import config, csv_import, db


# A client's bank takes a fee on the way. 1% covers that without being loose
# enough to match a different invoice of roughly similar size.
WIRE_FEE_TOLERANCE = 0.01
MATCH_WINDOW_DAYS = 45

PROCESSED = {"HubSpot Payments"}


# The invoice's payment date and the payment record's date can differ by a
# day: HubSpot stamps the payment in UTC, so 2026-07-03 01:23 is the evening
# of 2026-07-02 locally. Exact-date matching missed INV-1049 for GBP 2,479
# because of it, and the money - which had arrived, converted to USD - was
# reported as untraceable.
PROCESSOR_DATE_SLACK_DAYS = 3


def processor_lookup():
    """
    (amount, date) -> which processor handled it, from the export.

    Keyed on amount and date, with a few days of slack on the date.
    """
    lookup = {}
    for path in sorted(config.IMPORTS_DIR.glob("*payment*.csv")):
        if not csv_import.is_payments_export(path):
            continue
        for row in csv_import.read_hubspot_payments(path):
            date = (row.get("Payment date") or "")[:10]
            try:
                amount = round(float(row.get("Gross amount") or 0), 2)
            except ValueError:
                continue
            if date and amount:
                lookup[(amount, date)] = row.get("Processor")
    return lookup


def processor_for(lookup, amount, date):
    """Which processor handled this, allowing for a day or two of drift."""
    day = dt.date.fromisoformat(date)
    for offset in range(0, PROCESSOR_DATE_SLACK_DAYS + 1):
        for shift in ((offset,) if offset == 0 else (offset, -offset)):
            found = lookup.get(
                (amount, (day + dt.timedelta(days=shift)).isoformat()))
            if found:
                return found
    return None


def reconcile(connection, tax_year, dry_run=False):
    """
    Check every invoice against the money that arrived. Returns a summary.
    """
    processors = processor_lookup()
    used_credits = set()

    verified, matched, unverified, fees = [], [], [], []

    invoices = connection.execute(
        "SELECT * FROM income WHERE source IN ('hubspot', 'stripe') "
        "AND tax_year = ? ORDER BY date", (tax_year,)).fetchall()

    for invoice in invoices:
        amount = db.round_money(invoice["amount"])
        currency = invoice["currency"]
        date = invoice["date"]

        # 1. did it go through a processor?
        processor = processor_for(processors, amount, date)
        if invoice["source"] == "stripe" or processor in PROCESSED:
            verified.append(invoice)
            # Clear any exclusion an earlier run left behind. Without this an
            # invoice wrongly flagged once stays flagged for ever, even after
            # the reason it was flagged has been fixed - which is exactly what
            # happened to INV-1049 once the date-slack change found its
            # payout.
            if not dry_run and invoice["excluded"]:
                connection.execute(
                    "UPDATE income SET excluded = 0, exclusion_reason = NULL, "
                    "needs_review = 0, review_note = NULL, updated_at = ? "
                    "WHERE id = ?", (db._now(), invoice["id"]))
            continue

        # 2. is there an unattributed credit that matches?
        day = dt.date.fromisoformat(date)
        low = (day - dt.timedelta(days=MATCH_WINDOW_DAYS)).isoformat()
        high = (day + dt.timedelta(days=MATCH_WINDOW_DAYS)).isoformat()
        span = amount * WIRE_FEE_TOLERANCE

        # A credit counts as evidence if it is not already attributable to
        # something else.
        #
        # Credits the Wise importer ALREADY matched to an invoice must be
        # included: they are the receipts. Excluding them would make this
        # circular - the importer hides the credit because it matched the
        # invoice, then this cannot find a credit for the invoice and drops
        # the income.
        #
        # What stays out is money that belongs elsewhere: processor payouts
        # (which are the arrival of a batch of earnings), transfers between
        # her own accounts, and top-ups.
        candidates = connection.execute(
            "SELECT * FROM income WHERE source = 'wise' "
            "AND (excluded = 0 "
            "     OR exclusion_reason LIKE '%paying an invoice already counted%' "
            "     OR exclusion_reason LIKE '%the arrival of invoice%') "
            "AND currency = ? AND amount BETWEEN ? AND ? "
            "AND date BETWEEN ? AND ? ORDER BY ABS(amount - ?)",
            (currency, amount - span, amount + span, low, high, amount),
        ).fetchall()
        candidate = next((row for row in candidates
                          if row["id"] not in used_credits), None)

        if candidate is not None:
            used_credits.add(candidate["id"])
            difference = db.round_money(amount - candidate["amount"])
            matched.append((invoice, candidate, difference))
            if not dry_run:
                connection.execute(
                    "UPDATE income SET excluded = 1, exclusion_reason = ?, "
                    "needs_review = 0, review_note = NULL, updated_at = ? "
                    "WHERE id = ?",
                    (f"the arrival of invoice "
                     f"{(invoice['description'] or '')[:40]} — counted there "
                     f"at gross, not here",
                     db._now(), candidate["id"]))
                connection.execute(
                    "UPDATE income SET excluded = 0, needs_review = 0, "
                    "review_note = NULL, updated_at = ? WHERE id = ?",
                    (db._now(), invoice["id"]))
            if difference > 0:
                fees.append((invoice, difference))
                if not dry_run:
                    db.upsert_expense(
                        connection, source="wise",
                        source_id=f"wirefee:{invoice['source_id']}",
                        business=invoice["business"], date=candidate["date"],
                        amount=difference, currency=currency,
                        amount_usd=(difference if currency == "USD" else None),
                        category="bank fees", vendor="Bank wire fee",
                        description=(f"deducted in transit from invoice "
                                     f"{(invoice['description'] or '')[:60]}"))
            continue

        # 3. nothing found
        unverified.append(invoice)
        if not dry_run:
            connection.execute(
                "UPDATE income SET excluded = 1, exclusion_reason = ?, "
                "needs_review = 1, review_note = ?, updated_at = ? "
                "WHERE id = ?",
                ("marked paid, but no money matching it can be found in any "
                 "account being read — NOT counted as income",
                 f"Invoice {(invoice['description'] or '')[:50]} for "
                 f"{amount:,.2f} {currency} is marked paid, but nothing "
                 f"matching arrived in Wise. Either it landed somewhere not "
                 f"being read, or it was marked paid without payment. Not "
                 f"counted until you confirm.",
                 db._now(), invoice["id"]))

    if not dry_run:
        connection.commit()

    return {"verified": verified, "matched": matched,
            "unverified": unverified, "fees": fees}
