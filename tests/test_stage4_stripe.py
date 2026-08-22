"""
Automatic checks for Stage 4 (Stripe income).

All of these run on made-up Stripe data. No account, no key, no internet.

The one that matters most is
    test_an_invoice_and_its_own_payment_are_not_counted_twice
because that mistake is invisible: nothing errors, the numbers just come out
double.
"""

import pytest

from taxlib import db
from taxlib.stripe_import import build_records, from_stripe_amount, stripe_date


# ---------------------------------------------------------------------------
#  Helpers to build fake Stripe objects
# ---------------------------------------------------------------------------

def invoice(id, status, currency, amount, paid_at=None, payment_intent=None,
            number=None, amount_due=None):
    return {
        "id": id,
        "status": status,
        "currency": currency,
        "number": number or id,
        "amount_paid": amount,
        "amount_due": amount_due if amount_due is not None else amount,
        "created": 1754179200,                      # 2025-08-03
        "status_transitions": {"paid_at": paid_at},
        "payments": {"data": [
            {"payment": {"payment_intent": payment_intent}}
        ]} if payment_intent else {"data": []},
    }


def charge(id, currency, amount, created, payment_intent=None, status="succeeded",
           invoice_id=None):
    return {
        "id": id, "status": status, "currency": currency, "amount": amount,
        "created": created, "payment_intent": payment_intent,
        "invoice": invoice_id, "billing_details": {"name": "A Client"},
        "description": None,
    }


def ledger(id, type, currency, amount, fee=0, net=None, created=1788393600,
           description=None, source=None):
    return {
        "id": id, "type": type, "currency": currency, "amount": amount,
        "fee": fee, "net": net if net is not None else amount - fee,
        "created": created, "description": description, "source": source,
    }


def payout(id, currency, amount, arrival, status="paid"):
    return {"id": id, "currency": currency, "amount": amount,
            "arrival_date": arrival, "status": status}


# 2026 timestamps
SEP_03 = 1788393600   # 2026-09-03
SEP_09 = 1788912000   # 2026-09-09


# ---------------------------------------------------------------------------
#  Stripe's number format
# ---------------------------------------------------------------------------

def test_ordinary_currencies_are_divided_by_a_hundred():
    assert from_stripe_amount(22500, "usd") == 225.00
    assert from_stripe_amount(379800, "gbp") == 3798.00


def test_yen_is_not_divided():
    """
    Japanese yen has no smaller unit, so 1000 means 1000. Dividing it by 100
    would understate the amount by a hundred times.
    """
    assert from_stripe_amount(1000, "jpy") == 1000.0
    assert from_stripe_amount(1000, "krw") == 1000.0


def test_three_decimal_currencies_are_divided_by_a_thousand():
    assert from_stripe_amount(1500, "kwd") == 1.5


def test_a_timestamp_becomes_a_plain_date():
    assert stripe_date(SEP_03) == "2026-09-03"
    assert stripe_date(None) is None


# ---------------------------------------------------------------------------
#  THE DOUBLE-COUNT TRAP
# ---------------------------------------------------------------------------

def test_an_invoice_and_its_own_payment_are_not_counted_twice():
    """
    THE ONE THAT MATTERS.

    A $225 invoice is settled by a $225 payment. That is ONE piece of income.

    Stripe's newer API leaves `charge.invoice` empty, so the payment looks
    standalone when it isn't. The real link is
        invoice -> payments -> payment_intent -> charge
    and this proves the importer follows it.

    Without it, income here would be $450 instead of $225.
    """
    records = build_records(
        invoices=[invoice("in_1", "paid", "usd", 22500,
                          paid_at=SEP_03, payment_intent="pi_1")],
        charges=[charge("py_1", "usd", 22500, SEP_03, payment_intent="pi_1")],
        balance_transactions=[],
        payouts=[],
    )

    assert len(records["income"]) == 1, "the payment was counted a second time"
    assert records["income"][0]["amount"] == 225.00
    assert records["income"][0]["source_id"] == "in_1"


def test_a_genuine_standalone_payment_is_counted_but_flagged():
    """
    A payment with no invoice behind it - a payment link, say - IS income
    and must not be dropped. But it is flagged, because that is exactly where
    a double-count would show up if Stripe ever changed the linkage.
    """
    records = build_records(
        invoices=[],
        charges=[charge("ch_solo", "usd", 5000, SEP_03, payment_intent="pi_9")],
        balance_transactions=[],
        payouts=[],
    )

    assert len(records["income"]) == 1
    row = records["income"][0]
    assert row["amount"] == 50.00
    assert row["needs_review"] is True
    assert "not linked to any invoice" in row["review_note"]


# ---------------------------------------------------------------------------
#  Gross, not net
# ---------------------------------------------------------------------------

def test_income_is_gross_and_the_fee_is_a_separate_expense():
    """
    $225 invoice, $10.20 fee. That is income of $225 AND an expense of
    $10.20 - never income of $214.80.

    Netting would silently lose the $10.20 deduction.
    """
    records = build_records(
        invoices=[invoice("in_1", "paid", "usd", 22500,
                          paid_at=SEP_03, payment_intent="pi_1")],
        charges=[charge("py_1", "usd", 22500, SEP_03, payment_intent="pi_1")],
        balance_transactions=[
            ledger("txn_1", "payment", "usd", 22500, fee=1020, created=SEP_03)],
        payouts=[],
    )

    assert records["income"][0]["amount"] == 225.00      # not 214.80
    assert len(records["expenses"]) == 1
    assert records["expenses"][0]["amount"] == 10.20
    assert records["expenses"][0]["vendor"] == "Stripe"


# ---------------------------------------------------------------------------
#  All three kinds of fee
# ---------------------------------------------------------------------------

def test_invoicing_and_settlement_fees_are_captured_too():
    """
    Stripe charges three different things, and two of them arrive as ledger
    entries with no payment attached. Anything that only looks at payments
    never sees them - and every one missed is a lost deduction.
    """
    records = build_records(
        invoices=[],
        charges=[],
        balance_transactions=[
            ledger("txn_a", "payment", "gbp", 379800, fee=16731, created=SEP_03),
            ledger("txn_b", "stripe_fee", "gbp", -1519, fee=122, net=-1641,
                   created=SEP_03, description="Invoicing (2026-09-03)"),
            ledger("txn_c", "stripe_fee", "gbp", -3798, fee=0, net=-3798,
                   created=SEP_03, description="Multicurrency Settlement"),
        ],
        payouts=[],
    )

    amounts = sorted(row["amount"] for row in records["expenses"])
    assert amounts == [16.41, 37.98, 167.31]
    assert sum(amounts) == 221.70


def test_tax_charged_on_a_fee_is_included_in_the_expense():
    """
    A 0.90 fee with 0.07 of tax costs 0.97. `net` carries the true total, so
    that is what gets recorded.
    """
    records = build_records(
        invoices=[], charges=[],
        balance_transactions=[
            ledger("txn_f", "stripe_fee", "usd", -90, fee=7, net=-97,
                   created=SEP_03, description="Invoicing")],
        payouts=[])

    assert records["expenses"][0]["amount"] == 0.97     # not 0.90


def test_a_fee_expense_is_positive_even_though_stripe_reports_it_negative():
    records = build_records(
        invoices=[], charges=[],
        balance_transactions=[
            ledger("txn_f", "stripe_fee", "eur", -900, net=-900, created=SEP_03)],
        payouts=[])
    assert records["expenses"][0]["amount"] == 9.00


# ---------------------------------------------------------------------------
#  What is and isn't income
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status", ["open", "draft", "void", "uncollectible"])
def test_only_paid_invoices_are_income(status):
    """
    Cash basis: money owed is not money received. An unpaid invoice is not
    income, and a cancelled one never will be.
    """
    records = build_records(
        invoices=[invoice("in_x", status, "usd", 0, amount_due=400000)],
        charges=[], balance_transactions=[], payouts=[])

    assert records["income"] == []


def test_unpaid_invoices_are_reported_so_you_can_see_what_is_owed():
    records = build_records(
        invoices=[invoice("in_x", "open", "usd", 0, amount_due=400000)],
        charges=[], balance_transactions=[], payouts=[])

    assert len(records["outstanding"]) == 1
    assert records["outstanding"][0]["amount"] == 4000.00


def test_a_void_invoice_is_not_even_listed_as_outstanding():
    """It was cancelled. It is not owed and never will be."""
    records = build_records(
        invoices=[invoice("in_v", "void", "usd", 0, amount_due=90000)],
        charges=[], balance_transactions=[], payouts=[])
    assert records["outstanding"] == []


def test_income_is_dated_when_it_was_paid_not_when_it_was_sent():
    records = build_records(
        invoices=[invoice("in_1", "paid", "usd", 9000, paid_at=SEP_09)],
        charges=[], balance_transactions=[], payouts=[])
    assert records["income"][0]["date"] == "2026-09-09"


def test_a_refund_reduces_income_and_is_flagged():
    records = build_records(
        invoices=[], charges=[],
        balance_transactions=[
            ledger("txn_r", "refund", "usd", -5000, created=SEP_09,
                   description="Refund")],
        payouts=[])

    assert records["income"][0]["amount"] == -50.00
    assert records["income"][0]["needs_review"] is True


# ---------------------------------------------------------------------------
#  Payouts
# ---------------------------------------------------------------------------

def test_payouts_are_kept_separately_and_are_never_income():
    records = build_records(
        invoices=[], charges=[],
        balance_transactions=[
            ledger("txn_p", "payout", "usd", -8535, created=SEP_09)],
        payouts=[payout("po_1", "usd", 8535, SEP_09)])

    assert records["income"] == []
    assert records["expenses"] == []       # a payout is not a cost
    assert len(records["payouts"]) == 1
    assert records["payouts"][0]["amount"] == 85.35
    assert records["payouts"][0]["arrival_date"] == "2026-09-09"


# ---------------------------------------------------------------------------
#  Nothing is silently dropped
# ---------------------------------------------------------------------------

def test_an_unrecognised_ledger_entry_is_reported_not_ignored():
    """
    If Stripe invents a new kind of entry, staying quiet would mean money
    quietly missing from the totals. It says so instead.
    """
    records = build_records(
        invoices=[], charges=[],
        balance_transactions=[
            ledger("txn_z", "something_new", "usd", -1000, created=SEP_03)],
        payouts=[])

    assert records["notes"]
    assert "something_new" in records["notes"][0]
    assert "NOT imported" in records["notes"][0]


# ---------------------------------------------------------------------------
#  Currency
# ---------------------------------------------------------------------------

def test_only_dollars_get_a_dollar_figure():
    """
    Guessing a rate here would be worse than admitting it isn't known.
    Stage 5 fills these in properly; until then they stay empty and get
    reported as unconverted.
    """
    records = build_records(
        invoices=[
            invoice("in_u", "paid", "usd", 9000, paid_at=SEP_03),
            invoice("in_g", "paid", "gbp", 379800, paid_at=SEP_03),
        ],
        charges=[], balance_transactions=[], payouts=[])

    by_currency = {r["currency"]: r for r in records["income"]}
    assert by_currency["USD"]["amount_usd"] == 90.00
    assert by_currency["GBP"]["amount_usd"] is None


# ---------------------------------------------------------------------------
#  Date range
# ---------------------------------------------------------------------------

def test_only_the_requested_tax_year_is_imported():
    records = build_records(
        invoices=[
            invoice("in_2026", "paid", "usd", 9000, paid_at=SEP_03),
            invoice("in_2025", "paid", "usd", 9000, paid_at=1756857600),
        ],
        charges=[], balance_transactions=[], payouts=[],
        since="2026-01-01", until="2026-12-31")

    assert len(records["income"]) == 1
    assert records["income"][0]["source_id"] == "in_2026"


# ---------------------------------------------------------------------------
#  Writing to the database, twice
# ---------------------------------------------------------------------------

def test_importing_the_same_stripe_data_twice_changes_nothing():
    """The whole point of matching on Stripe's own IDs."""
    records = build_records(
        invoices=[invoice("in_1", "paid", "usd", 22500,
                          paid_at=SEP_03, payment_intent="pi_1")],
        charges=[charge("py_1", "usd", 22500, SEP_03, payment_intent="pi_1")],
        balance_transactions=[
            ledger("txn_1", "payment", "usd", 22500, fee=1020, created=SEP_03)],
        payouts=[payout("po_1", "usd", 21480, SEP_09)])

    connection = db.init_db(":memory:")

    for _ in range(3):
        for row in records["income"]:
            db.upsert_income(connection, **row)
        for row in records["expenses"]:
            db.upsert_expense(connection, **row)
        for row in records["payouts"]:
            db.upsert_payout(connection, **row)
        connection.commit()

    figures = db.totals(connection, 2026)
    assert figures["income_count"] == 1
    assert figures["income_usd"] == 225.00
    assert figures["expenses_usd"] == 10.20
    assert figures["net_profit_usd"] == 214.80
    connection.close()


def test_the_worked_example_from_the_plan():
    """
    PLAN.md's worked example, the Stripe half.

      $2,000 invoice paid 3 Sept, Stripe keeps $60, pays out $1,940 on 9 Sept

    Income must be $2,000 - not $1,940 (netting), and not $3,940 (which is
    what happens in Stage 6 without the payout matching).
    """
    records = build_records(
        invoices=[invoice("in_ABC", "paid", "usd", 200000,
                          paid_at=SEP_03, payment_intent="pi_ABC")],
        charges=[charge("ch_ABC", "usd", 200000, SEP_03,
                        payment_intent="pi_ABC")],
        balance_transactions=[
            ledger("txn_ABC", "charge", "usd", 200000, fee=6000, created=SEP_03),
            ledger("txn_PAY", "payout", "usd", -194000, created=SEP_09)],
        payouts=[payout("po_XYZ", "usd", 194000, SEP_09)])

    connection = db.init_db(":memory:")
    for row in records["income"]:
        db.upsert_income(connection, **row)
    for row in records["expenses"]:
        db.upsert_expense(connection, **row)
    for row in records["payouts"]:
        db.upsert_payout(connection, **row)
    connection.commit()

    figures = db.totals(connection, 2026)
    assert figures["income_usd"] == 2000.00, "must be gross, and counted once"
    assert figures["expenses_usd"] == 60.00
    assert figures["net_profit_usd"] == 1940.00

    # the payout is recorded, ready for Stage 6 to match the Wise credit
    row = connection.execute("SELECT * FROM stripe_payouts").fetchone()
    assert row["amount"] == 1940.00
    assert row["arrival_date"] == "2026-09-09"
    connection.close()
