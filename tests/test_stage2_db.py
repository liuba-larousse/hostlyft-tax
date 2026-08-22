"""
Automatic checks for Stage 2 (the database).

The two that matter most:

  * test_reimporting_the_same_data_changes_nothing
        proves you can re-run any import as often as you like

  * test_the_two_thousand_not_three_thousand_nine_hundred_and_forty_case
        proves the data model can hold the double-count situation correctly:
        a $2,000 invoice stays $2,000 even though $1,940 also lands in Wise
"""

import pytest

from taxlib import db


@pytest.fixture
def conn():
    """
    A fresh, empty database for each test, built in memory and thrown away
    afterwards. Your real tax/hostlyft_tax.db is never touched by the tests.
    """
    connection = db.init_db(":memory:")
    yield connection
    connection.close()


# ---------------------------------------------------------------------------
#  Creating the database
# ---------------------------------------------------------------------------

def test_all_five_tables_are_created(conn):
    names = db.table_names(conn)
    for expected in ["income", "expenses", "stripe_payouts", "fx_rates",
                     "alerts_sent"]:
        assert expected in names


def test_creating_twice_is_harmless(conn):
    """Re-running init must never wipe existing data."""
    db.upsert_income(conn, source="stripe", source_id="in_1",
                     date="2026-09-03", amount=2000, currency="USD")
    conn.commit()

    conn.executescript(db.SCHEMA)   # exactly what init_db does again

    assert conn.execute("SELECT COUNT(*) FROM income").fetchone()[0] == 1


def test_schema_version_is_recorded(conn):
    assert db.schema_version(conn) == db.SCHEMA_VERSION


# ---------------------------------------------------------------------------
#  Money rounding
# ---------------------------------------------------------------------------

def test_money_rounds_a_half_upwards():
    """
    Python's built-in round() rounds a halfway value to the nearest EVEN
    number, which is wrong for money. round_money() always rounds half up.
    """
    assert db.round_money(0.125) == 0.13
    assert round(0.125, 2) == 0.12          # the behaviour being avoided
    assert db.round_money(2.675) == 2.68
    assert db.round_money(1939.994) == 1939.99


def test_no_amount_stays_no_amount():
    """A not-yet-converted USD amount must stay empty, never become $0.00."""
    assert db.round_money(None) is None


# ---------------------------------------------------------------------------
#  Re-running imports
# ---------------------------------------------------------------------------

def test_reimporting_the_same_data_changes_nothing(conn):
    """
    THE ONE THAT PROTECTS YOU FROM YOURSELF.

    Import three things, then import the exact same three things again.
    Row counts and totals must be identical.
    """
    def do_the_import():
        db.upsert_income(conn, source="stripe", source_id="in_ABC",
                         date="2026-09-03", amount=2000, currency="USD",
                         amount_usd=2000, description="Invoice #14")
        db.upsert_expense(conn, source="stripe", source_id="fee_ABC",
                          date="2026-09-03", amount=60, currency="USD",
                          amount_usd=60, category="fees", vendor="Stripe")
        db.upsert_payout(conn, payout_id="po_XYZ", arrival_date="2026-09-09",
                         amount=1940, currency="USD", status="paid")
        conn.commit()

    do_the_import()
    first = db.totals(conn, 2026)
    first_rows = [conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  for t in ["income", "expenses", "stripe_payouts"]]

    do_the_import()   # again
    do_the_import()   # and a third time for good measure

    second = db.totals(conn, 2026)
    second_rows = [conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                   for t in ["income", "expenses", "stripe_payouts"]]

    assert first_rows == second_rows == [1, 1, 1]
    assert first == second
    assert second["income_usd"] == 2000.00
    assert second["net_profit_usd"] == 1940.00


def test_a_corrected_amount_updates_rather_than_duplicates(conn):
    """If Stripe later reports a different figure, the row is corrected."""
    db.upsert_income(conn, source="stripe", source_id="in_ABC",
                     date="2026-09-03", amount=2000, currency="USD",
                     amount_usd=2000)
    db.upsert_income(conn, source="stripe", source_id="in_ABC",
                     date="2026-09-03", amount=2500, currency="USD",
                     amount_usd=2500)
    conn.commit()

    rows = conn.execute("SELECT * FROM income").fetchall()
    assert len(rows) == 1
    assert rows[0]["amount_usd"] == 2500.00


def test_the_same_id_from_two_different_systems_is_two_rows(conn):
    """
    Uniqueness is source + source_id together. Stripe and Wise could both
    happen to use the ID "123" for unrelated things.
    """
    db.upsert_income(conn, source="stripe", source_id="123",
                     date="2026-09-03", amount=100, currency="USD")
    db.upsert_income(conn, source="wise", source_id="123",
                     date="2026-09-03", amount=200, currency="USD")
    conn.commit()

    assert conn.execute("SELECT COUNT(*) FROM income").fetchone()[0] == 2


def test_first_seen_time_survives_a_reimport(conn, monkeypatch):
    """created_at keeps the original moment; updated_at moves."""
    monkeypatch.setattr(db, "_now", lambda: "2026-09-03T10:00:00+00:00")
    db.upsert_income(conn, source="stripe", source_id="in_1",
                     date="2026-09-03", amount=100, currency="USD")

    monkeypatch.setattr(db, "_now", lambda: "2026-10-01T10:00:00+00:00")
    db.upsert_income(conn, source="stripe", source_id="in_1",
                     date="2026-09-03", amount=100, currency="USD")
    conn.commit()

    row = conn.execute("SELECT * FROM income").fetchone()
    assert row["created_at"] == "2026-09-03T10:00:00+00:00"
    assert row["updated_at"] == "2026-10-01T10:00:00+00:00"


# ---------------------------------------------------------------------------
#  Details filled in automatically
# ---------------------------------------------------------------------------

def test_tax_year_is_worked_out_from_the_date(conn):
    db.upsert_income(conn, source="manual", source_id="a", date="2026-12-31",
                     amount=10, currency="USD")
    db.upsert_income(conn, source="manual", source_id="b", date="2027-01-01",
                     amount=10, currency="USD")
    conn.commit()

    years = [r["tax_year"] for r in
             conn.execute("SELECT tax_year FROM income ORDER BY date")]
    assert years == [2026, 2027]


def test_currency_codes_are_stored_uppercase(conn):
    """So "eur" typed by hand still matches "EUR" from an API."""
    db.upsert_income(conn, source="manual", source_id="a", date="2026-05-01",
                     amount=10, currency="eur")
    conn.commit()
    assert conn.execute("SELECT currency FROM income").fetchone()[0] == "EUR"


# ---------------------------------------------------------------------------
#  Totals
# ---------------------------------------------------------------------------

def test_the_two_thousand_not_three_thousand_nine_hundred_and_forty_case(conn):
    """
    The situation the whole design exists to prevent.

      $2,000 invoice paid via Stripe on 3 Sept
      $60    Stripe fee
      $1,940 arrives in your Wise account on 9 Sept

    Counted properly: income $2,000, expense $60, net profit $1,940.
    Counted naively:  income $3,940 - tax on nearly double your earnings.

    Stage 6 does the actual matching. This proves the database can hold the
    right answer: the Wise credit is stored for the audit trail but marked
    excluded, so it never reaches the totals.
    """
    db.upsert_income(conn, source="stripe", source_id="in_ABC",
                     date="2026-09-03", amount=2000, currency="USD",
                     amount_usd=2000, description="Invoice #14 (gross)")
    db.upsert_expense(conn, source="stripe", source_id="fee_ABC",
                      date="2026-09-03", amount=60, currency="USD",
                      amount_usd=60, category="fees", vendor="Stripe")
    db.upsert_payout(conn, payout_id="po_XYZ", arrival_date="2026-09-09",
                     amount=1940, currency="USD", status="paid")
    db.upsert_income(conn, source="wise", source_id="wise_555",
                     date="2026-09-09", amount=1940, currency="USD",
                     amount_usd=1940,
                     excluded=True,
                     exclusion_reason="internal transfer - already counted via Stripe")
    db.mark_payout_matched(conn, payout_id="po_XYZ",
                           matched_source="wise", matched_source_id="wise_555")
    conn.commit()

    figures = db.totals(conn, 2026)

    assert figures["income_usd"] == 2000.00, "must not be 3940.00"
    assert figures["expenses_usd"] == 60.00
    assert figures["net_profit_usd"] == 1940.00
    assert figures["excluded_income_count"] == 1

    # the excluded row is still there, so the decision is auditable
    excluded = conn.execute(
        "SELECT * FROM income WHERE excluded = 1").fetchone()
    assert "already counted via Stripe" in excluded["exclusion_reason"]

    # and the payout records what it was matched to
    payout = conn.execute("SELECT * FROM stripe_payouts").fetchone()
    assert payout["matched_source_id"] == "wise_555"


def test_amounts_not_yet_converted_are_reported_not_hidden(conn):
    """
    An entry with no USD figure counts as $0 in the total. That is a partial
    answer, so it must be flagged rather than passed off as complete.
    """
    db.upsert_income(conn, source="wise", source_id="w1", date="2026-06-01",
                     amount=1000, currency="EUR")          # no amount_usd
    conn.commit()

    figures = db.totals(conn, 2026)
    assert figures["income_usd"] == 0.00
    assert figures["unconverted_income_count"] == 1


def test_totals_can_be_limited_to_one_tax_year(conn):
    db.upsert_income(conn, source="manual", source_id="a", date="2025-06-01",
                     amount=500, currency="USD", amount_usd=500)
    db.upsert_income(conn, source="manual", source_id="b", date="2026-06-01",
                     amount=900, currency="USD", amount_usd=900)
    conn.commit()

    assert db.totals(conn, 2025)["income_usd"] == 500.00
    assert db.totals(conn, 2026)["income_usd"] == 900.00
    assert db.totals(conn)["income_usd"] == 1400.00      # every year


def test_many_small_amounts_add_up_exactly(conn):
    """
    Guards against rounding drift: 1,000 entries of $0.10 must total exactly
    $100.00, not $99.99 or $100.01.
    """
    for i in range(1000):
        db.upsert_income(conn, source="manual", source_id=f"x{i}",
                         date="2026-03-01", amount=0.10, currency="USD",
                         amount_usd=0.10)
    conn.commit()
    assert db.totals(conn, 2026)["income_usd"] == 100.00


# ---------------------------------------------------------------------------
#  Exchange rate cache
# ---------------------------------------------------------------------------

def test_a_saved_rate_can_be_read_back(conn):
    db.cache_fx_rate(conn, requested_date="2026-09-05", rate_date="2026-09-04",
                     base_currency="EUR", quote_currency="USD", rate=1.1699)
    conn.commit()

    row = db.get_cached_fx_rate(conn, requested_date="2026-09-05",
                                base_currency="EUR", quote_currency="USD")
    assert row["rate"] == 1.1699
    # the rate came from the previous business day, and says so
    assert row["rate_date"] == "2026-09-04"


def test_a_rate_never_fetched_returns_nothing(conn):
    """So Stage 5 knows to go and ask, rather than inventing a number."""
    assert db.get_cached_fx_rate(conn, requested_date="2026-01-01",
                                 base_currency="GBP",
                                 quote_currency="USD") is None


# ---------------------------------------------------------------------------
#  Alerts
# ---------------------------------------------------------------------------

def test_an_alert_fires_once_and_then_stays_quiet(conn):
    """
    Without this, the $600 contractor alarm would email you every morning
    for the rest of the year.
    """
    key = "contractor600:Ayoka:2026"

    assert db.record_alert(conn, alert_key=key, alert_type="contractor600",
                           subject="Ayoka passed $600") is True
    conn.commit()

    assert db.alert_already_sent(conn, key) is True
    assert db.record_alert(conn, alert_key=key,
                           alert_type="contractor600") is False
    conn.commit()

    assert conn.execute("SELECT COUNT(*) FROM alerts_sent").fetchone()[0] == 1


def test_alerts_for_different_people_and_years_are_separate(conn):
    db.record_alert(conn, alert_key="contractor600:Ayoka:2026",
                    alert_type="contractor600")
    db.record_alert(conn, alert_key="contractor600:Jane:2026",
                    alert_type="contractor600")
    db.record_alert(conn, alert_key="contractor600:Ayoka:2027",
                    alert_type="contractor600")
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM alerts_sent").fetchone()[0] == 3


# ---------------------------------------------------------------------------
#  Contractor totals
# ---------------------------------------------------------------------------

def test_contractor_totals_add_up_per_person(conn):
    db.upsert_expense(conn, source="wise", source_id="p1", date="2026-02-01",
                      amount=350, currency="USD", amount_usd=350,
                      vendor="Ayoka", category="contractor")
    db.upsert_expense(conn, source="wise", source_id="p2", date="2026-05-01",
                      amount=300, currency="USD", amount_usd=300,
                      vendor="Ayoka", category="contractor")
    db.upsert_expense(conn, source="wise", source_id="p3", date="2026-05-01",
                      amount=100, currency="USD", amount_usd=100,
                      vendor="Jane", category="contractor")
    conn.commit()

    figures = db.contractor_totals(conn, 2026)

    assert figures["Ayoka"]["usd"] == 650.00     # over the $600 threshold
    assert figures["Ayoka"]["payments"] == 2
    assert figures["Jane"]["usd"] == 100.00
    assert figures["Katerina"]["usd"] == 0.00    # listed even with no payments
