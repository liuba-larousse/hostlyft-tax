"""
Automatic checks for the rest of Stage 11 (reconciliation).

The two the plan named explicitly:

  * someone who earned $5,000 and withdrew $3,200 shows a $1,800 running
    gap, and the jar balance agrees
  * a sheet-versus-database mismatch is detected and reported

Plus the parsing, which is where this would break quietly: the monthly
tabs are not identically laid out, and reading a row by its position
instead of its label would pick up the wrong person's money.
"""

import pytest

from taxlib import db, reconcile


@pytest.fixture
def conn():
    connection = db.init_db(":memory:")
    yield connection
    connection.close()


def fixed_rate(rate):
    """
    A stand-in for the exchange-rate service, so tests never go online.

    Returns (rate, date) - the shape fetch_rate uses.
    """
    def fetcher(date, base_currency, quote_currency="USD"):
        return float(rate), date
    return fetcher


# A monthly tab, laid out the way hers are.
def month_tab(*, regular=None, one_time=None, payouts=None,
              sunniva_hours=0.0, sunniva_pay=0.0, extra_payout_row=None):
    rows = [
        ["Hostlyft - Test month"], [],
        ["INCOME - Regular Clients"], [],
        ["Client", "Currency", "Amount", "Katerina Split", "Ayoka Split",
         "Evgeniya Split", "Liuba Cut (auto)", "Business Fund (auto)"],
    ]
    rows += [["A client", "USD", "100.00", "-", "-", "-", "-", "-"]]
    for currency, values in (regular or {}).items():
        rows.append([f"Total Regular Income ({currency})", "",
                     values.get("amount", ""), values.get("katerina", ""),
                     values.get("ayoka", ""), values.get("evgeniya", ""),
                     values.get("liuba", ""), ""])
    rows += [[], ["INCOME - One-Time Clients"], []]
    # NOTE the different column layout - this section has a Sunniva column.
    rows += [["Client", "Currency", "Amount", "Katerina Split", "Ayoka Split",
              "Evgeniya Split", "Sunniva Split", "Liuba Cut (auto 5%)",
              "Business Fund (auto)"]]
    for currency, values in (one_time or {}).items():
        rows.append([f"Total One-Time Income ({currency})", "",
                     values.get("amount", ""), values.get("katerina", ""),
                     values.get("ayoka", ""), values.get("evgeniya", ""),
                     values.get("sunniva", ""), values.get("liuba", ""), ""])
    rows += [[], ["EXPENSES"],
             ["Monthly Subscriptions (USD)", "", "", "$0.00"],
             ["Sunniva - Hours Worked This Month", f"{sunniva_hours}h", "",
              f"${sunniva_pay:,.2f}" if sunniva_pay else "-"],
             ["Contractor & Founder Payouts"],
             ["", "USD", "EUR", "GBP"]]
    for person, amounts in (payouts or {}).items():
        rows.append([person, amounts.get("USD", "-"), amounts.get("EUR", "-"),
                     amounts.get("GBP", "-")])
    if extra_payout_row:
        rows.append(extra_payout_row)
    rows.append(["Total Payouts", "", "", ""])
    return rows


# ---------------------------------------------------------------------------
#  Reading money out of a sheet cell
# ---------------------------------------------------------------------------

def test_money_reads_the_formats_the_sheet_actually_uses():
    assert reconcile.money("$1,234.56") == 1234.56
    assert reconcile.money("£932.52") == 932.52
    assert reconcile.money("-") == 0.0
    assert reconcile.money("") == 0.0
    assert reconcile.money(None) == 0.0


def test_a_bracketed_number_is_negative():
    """The sheet writes negatives as ($5,461.51), not -$5,461.51."""
    assert reconcile.money("($5,461.51)") == -5461.51


def test_hours_are_read_without_the_h():
    assert reconcile.hours("20.0h") == 20.0
    assert reconcile.hours("0.0h") == 0.0


# ---------------------------------------------------------------------------
#  Parsing a monthly tab
# ---------------------------------------------------------------------------

def test_each_person_is_read_from_their_own_column():
    rows = month_tab(regular={"USD": {"amount": "$1,000.00",
                                      "katerina": "$300.00",
                                      "ayoka": "$250.00",
                                      "evgeniya": "$200.00",
                                      "liuba": "$50.00"}})
    parsed = reconcile.parse_month(rows)
    assert parsed["earned"]["Katerina Mrvova"]["USD"] == 300.00
    assert parsed["earned"]["Yetunde Olaniyan"]["USD"] == 250.00
    assert parsed["earned"]["Evgeniya Dyatlovskaya"]["USD"] == 200.00
    assert parsed["earned"][reconcile.FOUNDER]["USD"] == 50.00


def test_the_two_income_sections_have_different_columns():
    """
    The one-time section has a Sunniva column where the regular section has
    Liuba's cut. Reading a fixed column number would put Sunniva's money in
    Liuba's row - so each section's own header has to be read.
    """
    rows = month_tab(
        regular={"USD": {"amount": "$100.00", "katerina": "$70.00",
                         "liuba": "$5.00"}},
        one_time={"USD": {"amount": "$200.00", "katerina": "$40.00",
                          "sunniva": "$60.00", "liuba": "$10.00"}})
    parsed = reconcile.parse_month(rows)

    assert parsed["earned"]["Sunniva Texe"]["USD"] == 60.00
    assert parsed["earned"][reconcile.FOUNDER]["USD"] == 15.00   # 5 + 10
    assert parsed["earned"]["Katerina Mrvova"]["USD"] == 110.00  # 70 + 40


def test_currencies_are_kept_apart():
    rows = month_tab(regular={
        "USD": {"amount": "$100.00", "katerina": "$70.00"},
        "EUR": {"amount": "€200.00", "katerina": "€140.00"},
        "GBP": {"amount": "£300.00", "katerina": "£210.00"}})
    earned = reconcile.parse_month(rows)["earned"]["Katerina Mrvova"]
    assert earned == {"USD": 70.0, "EUR": 140.0, "GBP": 210.0}


def test_sunnivas_hourly_pay_is_counted_as_earnings():
    """
    She is hourly, so her earnings are not a split of client revenue and
    would otherwise be missed entirely.
    """
    rows = month_tab(sunniva_hours=20.0, sunniva_pay=500.0)
    parsed = reconcile.parse_month(rows)
    assert parsed["sunniva_hours"] == 20.0
    assert parsed["earned"]["Sunniva Texe"]["USD"] == 500.0


def test_payout_rows_are_found_by_label_not_position():
    """
    The real failure this guards against: May has an extra payout row that
    July does not, which shifts every row below it.
    """
    without = month_tab(payouts={"Katerina Mrvova": {"USD": "$211.00"},
                                 "Liuba (Founder)": {"USD": "$4,060.33"}})
    with_extra = month_tab(
        payouts={"Katerina Mrvova": {"USD": "$211.00"},
                 "Liuba (Founder)": {"USD": "$4,060.33"}},
        extra_payout_row=["Olaniyan (subcontractor)", "$118.73"])

    a = reconcile.parse_month(without)["paid"]
    b = reconcile.parse_month(with_extra)["paid"]
    assert a["Katerina Mrvova"]["USD"] == 211.00
    assert b["Katerina Mrvova"]["USD"] == 211.00
    assert b[reconcile.FOUNDER]["USD"] == 4060.33


def test_an_ambiguous_payout_row_is_reported_not_guessed():
    """
    Two people share the surname Olaniyan. Crediting the row to the wrong
    one would move somebody's $600 threshold.
    """
    rows = month_tab(payouts={"Katerina Mrvova": {"USD": "$211.00"}},
                     extra_payout_row=["Olaniyan (subcontractor)", "$118.73"])
    parsed = reconcile.parse_month(rows)

    assert len(parsed["unmatched_payouts"]) == 1
    assert parsed["unmatched_payouts"][0]["label"] == "Olaniyan (subcontractor)"
    for person in parsed["paid"]:
        assert "subcontractor" not in person


# ---------------------------------------------------------------------------
#  Test 8 from the plan
# ---------------------------------------------------------------------------

def test_earned_5000_withdrew_3200_shows_an_1800_gap(conn):
    """
    The plan's test 8. The gap is what is neither paid nor set aside, so
    with $1,800 sitting in the jar the person is square.
    """
    months = {"Jan 2026": reconcile.parse_month(month_tab(
        regular={"USD": {"amount": "$10,000.00", "katerina": "$5,000.00"}}))}
    months.update({f"{m} 2026": reconcile.parse_month(month_tab())
                   for m in reconcile.MONTHS if m != "Jan"})

    db.upsert_expense(conn, source="wise", source_id="w1", date="2026-02-01",
                      amount=3200, currency="USD", amount_usd=3200,
                      category="contractor", vendor="Katerina Mrvova")
    db.record_jar_balance(conn, balance_id="jar-k", jar_name="Katerina",
                          person="Katerina Mrvova", observed_on="2026-08-01",
                          amount=1800, currency="USD", amount_usd=1800)

    rows = reconcile.per_person(conn, 2026, months=months)
    katerina = next(r for r in rows if r["person"] == "Katerina Mrvova")

    assert katerina["earned_usd"] == 5000.0
    assert katerina["withdrawn_usd"] == 3200.0
    assert katerina["in_jar_usd"] == 1800.0
    assert katerina["gap_usd"] == 0.0     # 5000 - 3200 - 1800


def test_the_gap_shows_money_neither_paid_nor_set_aside(conn):
    months = {"Jan 2026": reconcile.parse_month(month_tab(
        regular={"USD": {"amount": "$10,000.00", "katerina": "$5,000.00"}}))}
    months.update({f"{m} 2026": reconcile.parse_month(month_tab())
                   for m in reconcile.MONTHS if m != "Jan"})

    db.upsert_expense(conn, source="wise", source_id="w1", date="2026-02-01",
                      amount=3200, currency="USD", amount_usd=3200,
                      category="contractor", vendor="Katerina Mrvova")

    rows = reconcile.per_person(conn, 2026, months=months)
    katerina = next(r for r in rows if r["person"] == "Katerina Mrvova")
    assert katerina["gap_usd"] == 1800.0


def test_someone_the_sheet_never_mentions_is_not_shown_as_zero(conn):
    """
    "Never appeared in the split calculation" and "earned nothing" are
    different facts. Showing 0.00 would claim it had been checked.
    """
    months = {f"{m} 2026": reconcile.parse_month(month_tab())
              for m in reconcile.MONTHS}
    db.upsert_expense(conn, source="wise", source_id="w1", date="2026-02-01",
                      amount=5470.39, currency="USD", amount_usd=5470.39,
                      category="contractor", vendor="Olaide Olaniyan")

    rows = reconcile.per_person(conn, 2026, months=months)
    olaide = next(r for r in rows if r["person"] == "Olaide Olaniyan")

    assert olaide["in_sheet"] is False
    assert olaide["earned_usd"] is None
    assert olaide["gap_usd"] is None
    assert olaide["withdrawn_usd"] == 5470.39


def test_a_jar_allocation_is_never_counted_as_a_withdrawal(conn):
    months = {"Jan 2026": reconcile.parse_month(month_tab(
        regular={"USD": {"amount": "$10,000.00", "katerina": "$5,000.00"}}))}
    months.update({f"{m} 2026": reconcile.parse_month(month_tab())
                   for m in reconcile.MONTHS if m != "Jan"})
    db.record_jar_balance(conn, balance_id="jar-k", jar_name="Katerina",
                          person="Katerina Mrvova", observed_on="2026-08-01",
                          amount=5000, currency="USD", amount_usd=5000)

    rows = reconcile.per_person(conn, 2026, months=months)
    katerina = next(r for r in rows if r["person"] == "Katerina Mrvova")
    assert katerina["withdrawn_usd"] == 0.0
    assert katerina["in_jar_usd"] == 5000.0


def test_foreign_earnings_are_converted_with_the_cached_rate(conn):
    months = {"Jan 2026": reconcile.parse_month(month_tab(
        regular={"EUR": {"amount": "€1,000.00", "katerina": "€500.00"}}))}
    months.update({f"{m} 2026": reconcile.parse_month(month_tab())
                   for m in reconcile.MONTHS if m != "Jan"})

    rows = reconcile.per_person(conn, 2026, months=months,
                               fetcher=fixed_rate(1.10))
    katerina = next(r for r in rows if r["person"] == "Katerina Mrvova")
    assert katerina["earned_usd"] == 550.0
    assert katerina["earned_by_currency"]["EUR"] == 500.0


# ---------------------------------------------------------------------------
#  Test 9 from the plan - sheet against database
# ---------------------------------------------------------------------------

def test_a_mismatch_between_sheet_and_database_is_detected(conn):
    """The plan's test 9."""
    months = {f"{m} 2026": reconcile.parse_month(month_tab())
              for m in reconcile.MONTHS}
    months["Mar 2026"] = reconcile.parse_month(month_tab(
        regular={"USD": {"amount": "$1,000.00"}}))

    db.upsert_income(conn, source="stripe", source_id="i1", date="2026-03-10",
                     amount=1500, currency="USD", amount_usd=1500)

    checks = reconcile.sheet_vs_database(conn, 2026, months=months)
    march = next(row for row in checks if row["month"] == "Mar 2026")

    assert march["sheet_usd"] == 1000.0
    assert march["database_usd"] == 1500.0
    assert march["difference_usd"] == 500.0
    assert march["agrees"] is False


def test_agreement_is_reported_as_agreement(conn):
    months = {f"{m} 2026": reconcile.parse_month(month_tab())
              for m in reconcile.MONTHS}
    months["Mar 2026"] = reconcile.parse_month(month_tab(
        regular={"USD": {"amount": "$1,500.00"}}))
    db.upsert_income(conn, source="stripe", source_id="i1", date="2026-03-10",
                     amount=1500, currency="USD", amount_usd=1500)

    checks = reconcile.sheet_vs_database(conn, 2026, months=months)
    march = next(row for row in checks if row["month"] == "Mar 2026")
    assert march["agrees"] is True
    assert reconcile.summarise(checks)["months_disagreeing"] == []


def test_a_few_cents_apart_still_counts_as_agreeing(conn):
    """Rounding and a fractionally different rate are not a missing payment."""
    months = {f"{m} 2026": reconcile.parse_month(month_tab())
              for m in reconcile.MONTHS}
    months["Mar 2026"] = reconcile.parse_month(month_tab(
        regular={"USD": {"amount": "$1,500.40"}}))
    db.upsert_income(conn, source="stripe", source_id="i1", date="2026-03-10",
                     amount=1500, currency="USD", amount_usd=1500)

    checks = reconcile.sheet_vs_database(conn, 2026, months=months)
    assert next(r for r in checks if r["month"] == "Mar 2026")["agrees"]


def test_marcus_is_left_out_of_the_comparison(conn):
    """
    Her sheet's Hostlyft figures exclude Marcus, so including his income on
    the database side would invent a disagreement every month.
    """
    months = {f"{m} 2026": reconcile.parse_month(month_tab())
              for m in reconcile.MONTHS}
    months["Mar 2026"] = reconcile.parse_month(month_tab(
        regular={"USD": {"amount": "$1,000.00"}}))

    db.upsert_income(conn, source="stripe", source_id="i1", date="2026-03-10",
                     amount=1000, currency="USD", amount_usd=1000)
    db.upsert_income(conn, source="wise", source_id="m1", date="2026-03-15",
                     amount=4000, currency="USD", amount_usd=4000,
                     business="marcus")

    checks = reconcile.sheet_vs_database(conn, 2026, months=months)
    assert next(r for r in checks if r["month"] == "Mar 2026")["agrees"]


def test_excluded_income_is_left_out_of_the_comparison(conn):
    """
    A Wise credit already counted as a Stripe payout is excluded from
    income, so it must not reappear here and look like a surplus.
    """
    months = {f"{m} 2026": reconcile.parse_month(month_tab())
              for m in reconcile.MONTHS}
    months["Mar 2026"] = reconcile.parse_month(month_tab(
        regular={"USD": {"amount": "$1,000.00"}}))

    db.upsert_income(conn, source="stripe", source_id="i1", date="2026-03-10",
                     amount=1000, currency="USD", amount_usd=1000)
    db.upsert_income(conn, source="wise", source_id="w1", date="2026-03-12",
                     amount=970, currency="USD", amount_usd=970,
                     excluded=True, exclusion_reason="internal transfer")

    checks = reconcile.sheet_vs_database(conn, 2026, months=months)
    assert next(r for r in checks if r["month"] == "Mar 2026")["agrees"]


# ---------------------------------------------------------------------------
#  The audit record
# ---------------------------------------------------------------------------

def test_the_ledger_records_contractors_and_not_the_founder(conn):
    months = {"Jan 2026": reconcile.parse_month(month_tab(
        regular={"USD": {"amount": "$10,000.00", "katerina": "$5,000.00",
                         "liuba": "$500.00"}}))}
    months.update({f"{m} 2026": reconcile.parse_month(month_tab())
                   for m in reconcile.MONTHS if m != "Jan"})

    rows = reconcile.per_person(conn, 2026, months=months)
    saved = reconcile.save_ledger(conn, 2026, rows, "2026-09-06")
    conn.commit()

    people = [r["person"] for r in
              conn.execute("SELECT person FROM contractor_ledger").fetchall()]
    assert saved == 5
    assert reconcile.FOUNDER not in people
    assert "Katerina Mrvova" in people


def test_saving_the_same_day_twice_updates_rather_than_duplicates(conn):
    months = {f"{m} 2026": reconcile.parse_month(month_tab())
              for m in reconcile.MONTHS}
    rows = reconcile.per_person(conn, 2026, months=months)

    reconcile.save_ledger(conn, 2026, rows, "2026-09-06")
    reconcile.save_ledger(conn, 2026, rows, "2026-09-06")
    conn.commit()

    count = conn.execute(
        "SELECT COUNT(*) FROM contractor_ledger").fetchone()[0]
    assert count == 5


def test_a_later_date_is_kept_as_a_separate_snapshot(conn):
    """The position at a past date stays readable rather than overwritten."""
    months = {f"{m} 2026": reconcile.parse_month(month_tab())
              for m in reconcile.MONTHS}
    rows = reconcile.per_person(conn, 2026, months=months)

    reconcile.save_ledger(conn, 2026, rows, "2026-09-06")
    reconcile.save_ledger(conn, 2026, rows, "2026-10-06")
    conn.commit()

    dates = [r[0] for r in conn.execute(
        "SELECT DISTINCT as_of FROM contractor_ledger ORDER BY as_of")]
    assert dates == ["2026-09-06", "2026-10-06"]
