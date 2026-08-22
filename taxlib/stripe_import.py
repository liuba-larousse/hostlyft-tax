"""
stripe_import.py - turning what Stripe reports into income and expense rows.

The decisions in here are the whole point, so they are spelled out.

WHAT COUNTS AS INCOME
    Paid invoices, at their GROSS amount.

    A $225 invoice where Stripe keeps $10.20 is income of $225 plus a
    deductible expense of $10.20. It is never income of $214.80. Schedule C
    asks for gross receipts; recording the net figure silently throws away
    the fee deduction.

WHY NOT SIMPLY IMPORT EVERY PAYMENT
    Because in this Stripe account every payment is ALSO an invoice. Import
    both and every single payment is counted twice.

    This is easy to get wrong, because Stripe's newer API deliberately no
    longer fills in `charge.invoice` - it is always empty. A payment looks
    standalone when it isn't.

    The real link runs the other way:

        invoice  ->  payments  ->  payment_intent  ->  charge

    So this module builds the set of payment_intents that belong to invoices,
    and only treats a payment as separate income if it is genuinely not in
    that set. Anything it does treat as separate is flagged for review rather
    than quietly added.

THREE KINDS OF STRIPE FEE, NOT ONE
    All three are deductible, and missing any of them costs real money.

      1. Processing fee   - taken out of each payment (e.g. $10.20 on $225)
      2. Invoicing fee    - charged for sending the invoice itself
      3. Settlement fee   - for converting a currency that isn't your own

    Fees 2 and 3 arrive as separate ledger entries with no payment attached,
    so anything that only looks at payments never sees them.

    Each fee entry can itself carry tax. The `net` figure includes it, so
    that is what gets recorded - a $0.90 invoicing fee with $0.07 of tax is
    an expense of $0.97.

    Checked against this account: for all three currencies,
        payout  =  payment  -  processing fee  -  invoicing fee  -  settlement fee
    to the cent.

CASH BASIS
    Income is recorded on the day the invoice was PAID, not the day it was
    sent. Unpaid and draft invoices are not income - the money hasn't
    arrived. They get reported separately so you can see what's outstanding.

CURRENCY
    Amounts stay in the currency they happened in. Only USD gets a USD figure
    here; Stage 5 converts the rest, and until then they are reported as
    unconverted rather than counted as zero.
"""

from datetime import datetime, timezone


# ===========================================================================
#  STRIPE'S NUMBER FORMAT
# ===========================================================================
#
# Stripe sends whole numbers in the currency's smallest unit: $225.00 arrives
# as 22500 cents. Most currencies divide by 100 - but not all, and getting
# this wrong is a 100x error.

# No subunit at all. 1000 yen arrives as 1000, not 100000.
ZERO_DECIMAL_CURRENCIES = {
    "BIF", "CLP", "DJF", "GNF", "JPY", "KMF", "KRW", "MGA",
    "PYG", "RWF", "UGX", "VND", "VUV", "XAF", "XOF", "XPF",
}

# Three decimal places. Divide by 1000.
THREE_DECIMAL_CURRENCIES = {"BHD", "JOD", "KWD", "OMR", "TND"}


def from_stripe_amount(amount, currency):
    """Convert Stripe's smallest-unit integer into a normal amount."""
    if amount is None:
        return None
    code = (currency or "").upper()
    if code in ZERO_DECIMAL_CURRENCIES:
        return float(amount)
    if code in THREE_DECIMAL_CURRENCIES:
        return amount / 1000.0
    return amount / 100.0


def stripe_date(timestamp):
    """Turn a Stripe timestamp into a plain YYYY-MM-DD date."""
    if not timestamp:
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).date().isoformat()


def usd_amount(amount, currency):
    """
    A USD figure only when the money was already in USD.

    Everything else stays empty until Stage 5 converts it properly. Guessing
    a rate here would be worse than admitting it isn't known yet.
    """
    return amount if (currency or "").upper() == "USD" else None


# ===========================================================================
#  BUILDING THE ROWS
# ===========================================================================
#
# build_records() is deliberately "pure": it takes plain data in and gives
# plain data out, touching neither the internet nor the database. That is
# what lets the tests feed it the $2,000 double-count scenario and check the
# answer without a Stripe account.

FEE_CATEGORY = "payment processing"


def build_records(invoices, charges, balance_transactions, payouts,
                  since=None, until=None):
    """
    Work out every row that should go into the database.

    Returns a dictionary with:
        income      rows for the income table
        expenses    rows for the expenses table
        payouts     rows for stripe_payouts (NOT income)
        outstanding invoices sent but not yet paid - information only
        notes       anything a human needs to look at
    """
    income, expenses, payout_rows, outstanding, notes = [], [], [], [], []

    def in_range(date_text):
        if not date_text:
            return False
        if since and date_text < since:
            return False
        if until and date_text > until:
            return False
        return True

    # -- 1. which payment_intents belong to an invoice -----------------------
    invoice_payment_intents = {}
    for invoice in invoices:
        if invoice.get("status") != "paid":
            continue
        payments = (invoice.get("payments") or {}).get("data", [])
        for entry in payments:
            payment = entry.get("payment") or {}
            intent = payment.get("payment_intent")
            if intent:
                invoice_payment_intents[intent] = invoice.get("id")

    # -- 2. income from paid invoices ---------------------------------------
    for invoice in invoices:
        status = invoice.get("status")
        currency = (invoice.get("currency") or "").upper()

        if status != "paid":
            # Not income - the money hasn't arrived. Reported, not counted.
            if status in ("open", "draft"):
                due = from_stripe_amount(invoice.get("amount_due"), currency)
                if due:
                    outstanding.append({
                        "id": invoice.get("id"),
                        "number": invoice.get("number"),
                        "status": status,
                        "amount": due,
                        "currency": currency,
                    })
            continue

        paid_on = stripe_date(
            (invoice.get("status_transitions") or {}).get("paid_at")
            or invoice.get("created"))
        if not in_range(paid_on):
            continue

        gross = from_stripe_amount(invoice.get("amount_paid"), currency)
        label = invoice.get("number") or invoice.get("id")

        income.append({
            "source": "stripe",
            "source_id": invoice.get("id"),
            "date": paid_on,
            "amount": gross,
            "currency": currency,
            "amount_usd": usd_amount(gross, currency),
            "description": f"Invoice {label} (gross, before Stripe's fee)",
            "payer": invoice.get("customer_name") or invoice.get("customer_email"),
        })

    # -- 3. payments that genuinely belong to no invoice ---------------------
    for charge in charges:
        if charge.get("status") != "succeeded":
            continue
        intent = charge.get("payment_intent")

        # Belongs to an invoice, which was already counted above. Skipping
        # this is what stops every payment being counted twice.
        if intent and intent in invoice_payment_intents:
            continue
        if charge.get("invoice"):
            continue

        when = stripe_date(charge.get("created"))
        if not in_range(when):
            continue

        currency = (charge.get("currency") or "").upper()
        gross = from_stripe_amount(charge.get("amount"), currency)

        income.append({
            "source": "stripe",
            "source_id": charge.get("id"),
            "date": when,
            "amount": gross,
            "currency": currency,
            "amount_usd": usd_amount(gross, currency),
            "description": (charge.get("description")
                            or "Payment not linked to an invoice"),
            "payer": (charge.get("billing_details") or {}).get("name"),
            # Counted, but flagged: if Stripe ever changes how invoices link
            # to payments, this is where a double-count would appear.
            "needs_review": True,
            "review_note": ("payment not linked to any invoice - confirm it "
                            "is income and not a duplicate of one"),
        })

    # -- 4. every kind of fee, from the ledger -------------------------------
    unknown_types = {}

    for entry in balance_transactions:
        kind = entry.get("type")
        currency = (entry.get("currency") or "").upper()
        when = stripe_date(entry.get("created"))

        # a) processing fee taken out of a payment
        if kind in ("charge", "payment"):
            fee = from_stripe_amount(entry.get("fee"), currency)
            if fee and in_range(when):
                expenses.append({
                    "source": "stripe",
                    "source_id": f"{entry.get('id')}:fee",
                    "date": when,
                    "amount": fee,
                    "currency": currency,
                    "amount_usd": usd_amount(fee, currency),
                    "category": FEE_CATEGORY,
                    "vendor": "Stripe",
                    "description": "Stripe processing fee",
                })

        # b) invoicing and currency-settlement fees, which have no payment
        elif kind == "stripe_fee":
            # `net` is negative and already includes any tax on the fee.
            cost = abs(from_stripe_amount(entry.get("net"), currency) or 0)
            if cost and in_range(when):
                expenses.append({
                    "source": "stripe",
                    "source_id": entry.get("id"),
                    "date": when,
                    "amount": cost,
                    "currency": currency,
                    "amount_usd": usd_amount(cost, currency),
                    "category": FEE_CATEGORY,
                    "vendor": "Stripe",
                    "description": entry.get("description") or "Stripe fee",
                })

        # c) money moving to your bank. Not an expense - handled below.
        elif kind == "payout":
            continue

        # d) a refund reduces income (Schedule C: returns and allowances)
        elif kind in ("refund", "payment_refund", "payment_failure_refund"):
            amount = from_stripe_amount(entry.get("amount"), currency)
            if amount and in_range(when):
                income.append({
                    "source": "stripe",
                    "source_id": entry.get("id"),
                    "date": when,
                    "amount": amount,          # already negative
                    "currency": currency,
                    "amount_usd": usd_amount(amount, currency),
                    "description": entry.get("description") or "Refund issued",
                    "needs_review": True,
                    "review_note": ("refund - reduces income. Check it is "
                                    "matched to the right original payment"),
                })

        # e) anything else is reported rather than silently dropped
        else:
            unknown_types[kind] = unknown_types.get(kind, 0) + 1

    for kind, count in sorted(unknown_types.items()):
        notes.append(
            f"{count} ledger entr{'y' if count == 1 else 'ies'} of type "
            f"'{kind}' were NOT imported - this importer doesn't know that "
            f"type yet. Mention it to Claude so it can be handled.")

    # -- 5. payouts: NOT income, but the double-count reference list ---------
    for payout in payouts:
        if payout.get("status") not in ("paid", "in_transit", "pending"):
            continue
        currency = (payout.get("currency") or "").upper()
        arrival = stripe_date(payout.get("arrival_date"))
        payout_rows.append({
            "payout_id": payout.get("id"),
            "arrival_date": arrival,
            "amount": from_stripe_amount(payout.get("amount"), currency),
            "currency": currency,
            "status": payout.get("status"),
        })

    return {
        "income": income,
        "expenses": expenses,
        "payouts": payout_rows,
        "outstanding": outstanding,
        "notes": notes,
    }


# ===========================================================================
#  TALKING TO STRIPE
# ===========================================================================

def fetch_everything(stripe_module, created_since=None):
    """
    Download the four things needed, as plain dictionaries.

    Kept separate from build_records() so the decision-making above can be
    tested without a Stripe account or an internet connection.

    `expand=["data.payments"]` is essential: without it, invoices arrive with
    no way of telling which payment settled them.
    """
    date_filter = {"created": {"gte": created_since}} if created_since else {}

    invoices = [dict(o) for o in stripe_module.Invoice.list(
        limit=100, expand=["data.payments"], **date_filter).auto_paging_iter()]
    charges = [dict(o) for o in stripe_module.Charge.list(
        limit=100, **date_filter).auto_paging_iter()]
    balance_transactions = [dict(o) for o in stripe_module.BalanceTransaction.list(
        limit=100, **date_filter).auto_paging_iter()]
    payouts = [dict(o) for o in stripe_module.Payout.list(
        limit=100, **date_filter).auto_paging_iter()]

    return invoices, charges, balance_transactions, payouts
