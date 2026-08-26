"""
Automatic checks for receipt verification.

The rule: an invoice marked "paid" is a status somebody set, not evidence
that money arrived. On a cash basis the money is the test.
"""

import pytest

from taxlib import db, receipts


@pytest.fixture
def conn():
    connection = db.init_db(":memory:")
    yield connection
    connection.close()


def add_invoice(conn, source_id, date, amount, currency="USD", source="hubspot"):
    db.upsert_income(conn, source=source, source_id=source_id, date=date,
                     amount=amount, currency=currency,
                     amount_usd=amount if currency == "USD" else None,
                     description=f"invoice {source_id}")
    conn.commit()


def add_credit(conn, source_id, date, amount, currency="USD", excluded=False,
               reason=None):
    db.upsert_income(conn, source="wise", source_id=source_id, date=date,
                     amount=amount, currency=currency,
                     amount_usd=amount if currency == "USD" else None,
                     excluded=excluded, exclusion_reason=reason,
                     description="bank credit")
    conn.commit()


def test_an_invoice_with_no_money_behind_it_is_not_counted(conn):
    """
    THE POINT OF THIS FILE.

    Counting an invoice because somebody ticked "paid" overstates income and
    is indefensible if anyone asks where the money went.
    """
    add_invoice(conn, "in_1", "2026-02-01", 1508.75)

    result = receipts.reconcile(conn, 2026)

    assert len(result["unverified"]) == 1
    assert db.totals(conn, 2026)["income_usd"] == 0.00

    row = conn.execute("SELECT * FROM income WHERE source = 'hubspot'").fetchone()
    assert row["excluded"] == 1
    assert "no money matching it" in row["exclusion_reason"]
    assert row["needs_review"] == 1


def test_an_invoice_matched_to_a_credit_is_counted_at_gross(conn):
    add_invoice(conn, "in_1", "2026-04-16", 282.00)
    add_credit(conn, "wise_1", "2026-04-16", 282.00)

    result = receipts.reconcile(conn, 2026)

    assert len(result["matched"]) == 1
    # counted once, from the invoice, at gross
    assert db.totals(conn, 2026)["income_usd"] == 282.00
    credit = conn.execute(
        "SELECT * FROM income WHERE source_id = 'wise_1'").fetchone()
    assert credit["excluded"] == 1
    assert "the arrival of invoice" in credit["exclusion_reason"]


def test_a_wire_fee_is_recovered_as_a_deduction(conn):
    """
    A client wires $1,689.25 and their bank takes $6.11, so $1,683.14
    arrives. The invoice is the income; the $6.11 is a real cost that would
    otherwise vanish.
    """
    add_invoice(conn, "in_1", "2026-03-02", 1689.25)
    add_credit(conn, "wise_1", "2026-02-21", 1683.14)

    result = receipts.reconcile(conn, 2026)

    assert len(result["matched"]) == 1
    assert result["fees"][0][1] == 6.11
    assert db.totals(conn, 2026)["income_usd"] == 1689.25
    assert db.totals(conn, 2026)["expenses_usd"] == 6.11


def test_a_credit_can_only_settle_one_invoice(conn):
    """
    Two invoices of the same size and one credit: only one is verified. The
    other has no money behind it and must not borrow the same evidence.
    """
    add_invoice(conn, "in_1", "2026-05-01", 500.00)
    add_invoice(conn, "in_2", "2026-05-02", 500.00)
    add_credit(conn, "wise_1", "2026-05-01", 500.00)

    result = receipts.reconcile(conn, 2026)

    assert len(result["matched"]) == 1
    assert len(result["unverified"]) == 1
    assert db.totals(conn, 2026)["income_usd"] == 500.00


def test_a_credit_already_matched_by_the_importer_still_counts_as_evidence(conn):
    """
    Guards against a circular failure: the Wise importer excludes a credit
    because it matched an invoice, then this cannot find a credit for that
    invoice and drops the income. Both would be right on their own and
    together they lose the money.
    """
    add_invoice(conn, "in_1", "2026-02-01", 1195.00, currency="EUR")
    add_credit(conn, "wise_1", "2026-01-01", 1195.00, currency="EUR",
               excluded=True,
               reason="Alexandr Jaitner paying an invoice already counted")

    result = receipts.reconcile(conn, 2026)

    assert len(result["matched"]) == 1
    assert result["unverified"] == []


def test_a_processor_payout_is_not_treated_as_a_receipt(conn):
    """
    An Upwork payout of $1,302.15 must not "verify" an unrelated $1,300.50
    invoice. That money belongs to the Upwork earnings behind it.
    """
    add_invoice(conn, "in_1", "2026-02-01", 1300.50)
    add_credit(conn, "wise_1", "2026-03-26", 1302.15, excluded=True,
               reason="Upwork payout. The earnings behind it are already "
                      "counted")

    result = receipts.reconcile(conn, 2026)

    assert result["matched"] == []
    assert len(result["unverified"]) == 1


def test_a_stripe_invoice_is_taken_on_trust(conn):
    """
    Stripe pays out in batches, so an invoice never matches a credit one to
    one. The payout is visible and already excluded, so the invoice is the
    right place to count it.
    """
    add_invoice(conn, "in_1", "2026-08-03", 3798.00, currency="GBP",
                source="stripe")

    result = receipts.reconcile(conn, 2026)

    assert len(result["verified"]) == 1
    assert result["unverified"] == []


def test_a_dry_run_changes_nothing(conn):
    add_invoice(conn, "in_1", "2026-02-01", 1508.75)

    result = receipts.reconcile(conn, 2026, dry_run=True)

    assert len(result["unverified"]) == 1
    assert db.totals(conn, 2026)["income_usd"] == 1508.75   # untouched


def test_running_twice_gives_the_same_answer(conn):
    add_invoice(conn, "in_1", "2026-04-16", 282.00)
    add_credit(conn, "wise_1", "2026-04-16", 282.00)

    receipts.reconcile(conn, 2026)
    first = db.totals(conn, 2026)
    receipts.reconcile(conn, 2026)
    second = db.totals(conn, 2026)

    assert first == second
