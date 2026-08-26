"""
Automatic checks for Stage 7 (the Capital One statement).

The one that matters most is that a payment to the card is skipped. A card
statement contains both the purchases AND the payment that settles them;
counting both doubles everything on the card.
"""

import pytest

from taxlib import capitalone, db


HEADER = ["Transaction Date", "Posted Date", "Card No.", "Description",
          "Category", "Debit", "Credit"]


def row(date, description, debit="", credit="", category="Merchandise"):
    return {"Transaction Date": date, "Posted Date": date, "Card No.": "6984",
            "Description": description, "Category": category,
            "Debit": debit, "Credit": credit}


# ---------------------------------------------------------------------------
#  Reading the file
# ---------------------------------------------------------------------------

def test_the_columns_are_found_by_name():
    found = capitalone.detect_columns(HEADER)
    assert found["date"] == "Transaction Date"
    assert found["description"] == "Description"
    assert found["debit"] == "Debit"
    assert found["credit"] == "Credit"


def test_a_differently_named_export_still_works():
    """
    Banks rename their columns without warning. Detecting them by pattern
    means a changed export is read rather than silently misread.
    """
    found = capitalone.detect_columns(["Date", "Payee", "Amount", "Payments"])
    assert found["date"] == "Date"
    assert found["description"] == "Payee"
    assert found["debit"] == "Amount"


def test_a_file_that_cannot_be_understood_is_refused():
    """
    Better to stop with an explanation than to read the wrong column and
    produce plausible nonsense.
    """
    with pytest.raises(capitalone.CapitalOneError) as caught:
        capitalone.detect_columns(["Foo", "Bar", "Baz"])
    assert "does not look like a card statement" in str(caught.value)


# ---------------------------------------------------------------------------
#  The double-count trap
# ---------------------------------------------------------------------------

def test_a_payment_to_the_card_is_not_an_expense():
    """
    THE ONE THAT MATTERS.

    A statement holds the purchases AND the payment settling them. Counting
    both doubles the card. Those payments also appear in Wise as "Paid to
    CAPITAL ONE", where they are already excluded for the same reason.
    """
    rows = [row("2026-07-21", "CAPITAL ONE ONLINE PYMT", credit="349.83"),
            row("2026-07-15", "CAPITAL ONE AUTOPAY PYMT", credit="59.02"),
            row("2026-07-20", "Hubspot Inc.", debit="15.99")]

    result = capitalone.build_records(rows, capitalone.detect_columns(HEADER))

    assert len(result["expenses"]) == 1
    assert result["expenses"][0]["amount"] == 15.99
    assert len(result["skipped"]) == 2
    assert all("payment to the card" in s["why"] for s in result["skipped"])


def test_the_skipped_payments_are_reported_not_hidden():
    rows = [row("2026-07-21", "CAPITAL ONE ONLINE PYMT", credit="349.83")]
    result = capitalone.build_records(rows, capitalone.detect_columns(HEADER))
    assert any("skipped" in n for n in result["notes"])


# ---------------------------------------------------------------------------
#  Refunds and cashback
# ---------------------------------------------------------------------------

def test_a_refund_reduces_what_was_spent():
    """
    A refund of a business purchase is not income - it makes the purchase
    cost less. Recorded negative so it subtracts from expenses.
    """
    rows = [row("2026-02-10", "MY DATA VALUE LIMITED", debit="547.32"),
            row("2026-03-23", "MY DATA VALUE LIMITED", credit="150.00")]

    result = capitalone.build_records(rows, capitalone.detect_columns(HEADER))

    amounts = sorted(r["amount"] for r in result["expenses"])
    assert amounts == [-150.00, 547.32]
    # -150.00 + 547.32 is 397.32000000000005 in binary floating point,
    # which is why money is rounded on the way into the database
    assert sum(amounts) == pytest.approx(397.32)


def test_cashback_is_a_rebate_not_income():
    rows = [row("2026-03-17", "CREDIT-CASH BACK REWARD", credit="93.67",
                category="Payment/Credit")]
    result = capitalone.build_records(rows, capitalone.detect_columns(HEADER))

    assert result["expenses"][0]["amount"] == -93.67
    assert "cashback" in result["expenses"][0]["description"]


# ---------------------------------------------------------------------------
#  Re-running
# ---------------------------------------------------------------------------

def test_the_same_statement_can_be_imported_twice():
    """
    The statement carries no transaction id, so one is derived from the
    date, description and amount. Without it, re-importing would double
    every line.
    """
    rows = [row("2026-07-20", "Hubspot Inc.", debit="15.99"),
            row("2026-06-27", "ANTHROPIC* CLAUDE SUB", debit="106.60")]
    columns = capitalone.detect_columns(HEADER)

    conn = db.init_db(":memory:")
    for _ in range(3):
        for record in capitalone.build_records(rows, columns)["expenses"]:
            db.upsert_expense(conn, **record)
        conn.commit()

    assert conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0] == 2
    assert db.totals(conn, 2026)["expenses_usd"] == 122.59
    conn.close()


def test_two_identical_charges_on_one_day_are_both_kept():
    """
    Same shop, same amount, same day is unusual but real - two seats on the
    same subscription, say. They must not collapse into one row.
    """
    rows = [row("2026-05-01", "NEO", debit="4.99"),
            row("2026-05-01", "NEO", debit="4.99")]
    result = capitalone.build_records(rows, capitalone.detect_columns(HEADER))

    assert len(result["expenses"]) == 2
    ids = {r["source_id"] for r in result["expenses"]}
    assert len(ids) == 2, "the two charges collapsed into one row"


# ---------------------------------------------------------------------------
#  Duplicates against other sources
# ---------------------------------------------------------------------------

def test_a_charge_matching_another_source_is_reported_not_removed():
    """
    Anthropic is paid on both this card and the Wise card, so a genuine
    duplicate is possible. Deleting a real expense is worse than showing a
    pair to check, so it is only ever reported.
    """
    conn = db.init_db(":memory:")
    db.upsert_expense(conn, source="wise", source_id="w1", date="2026-07-27",
                      amount=108.00, currency="USD", amount_usd=108.00,
                      vendor="Anthropic", category="software")
    conn.commit()

    records = [{"date": "2026-07-28", "amount": 108.00,
                "vendor": "ANTHROPIC", "source_id": "capitalone:x"}]
    hits = capitalone.find_duplicates(conn, records)

    assert len(hits) == 1
    assert hits[0][1]["source"] == "wise"
    conn.close()


def test_a_refund_is_never_reported_as_a_duplicate():
    conn = db.init_db(":memory:")
    db.upsert_expense(conn, source="wise", source_id="w1", date="2026-07-27",
                      amount=93.67, currency="USD", amount_usd=93.67)
    conn.commit()

    hits = capitalone.find_duplicates(
        conn, [{"date": "2026-07-27", "amount": -93.67, "vendor": "CASHBACK",
                "source_id": "capitalone:y"}])
    assert hits == []
    conn.close()
