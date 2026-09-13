"""
The estimated-tax calendar: what is owed, what has gone out, what to file.

Two things this must never do, and both are about honesty rather than
arithmetic.
"""

import datetime as dt

from taxlib import db, filings


class TestTheIrsQuartersAreNotCalendarQuarters:

    def test_q2_is_two_months_and_q4_is_four(self):
        periods = {q: p for q, p, _ in filings.ESTIMATED_QUARTERS}
        assert periods[2] == "Apr - May"
        assert periods[4] == "Sep - Dec"

    def test_q4_is_due_in_the_following_january(self):
        assert filings.due_date(4, 2026) == dt.date(2027, 1, 15)

    def test_the_other_three_are_due_in_their_own_year(self):
        assert filings.due_date(1, 2026) == dt.date(2026, 4, 15)
        assert filings.due_date(2, 2026) == dt.date(2026, 6, 15)
        assert filings.due_date(3, 2026) == dt.date(2026, 9, 15)


class TestLivingAbroadMovesTheFilingDeadline:
    """
    Worth two months, automatic, and nothing to request. It applies because
    on the normal due date she is outside the US with her business outside
    it - which is her situation every year.
    """

    def test_the_return_is_due_in_june_not_april(self):
        deadline = filings.filing_deadline(2026)
        assert deadline["abroad"] == dt.date(2027, 6, 15)
        assert deadline["normal"] == dt.date(2027, 4, 15)

    def test_interest_still_runs_from_april(self):
        """
        THE TRAP. It extends the filing, not the paying. Treating June as
        the deadline for the MONEY would quietly accrue interest.
        """
        deadline = filings.filing_deadline(2026)
        assert deadline["interest_from"] == dt.date(2027, 4, 15)
        assert deadline["interest_from"] < deadline["abroad"]

    def test_form_4868_reaches_october(self):
        assert filings.filing_deadline(2026)["with_4868"] == dt.date(2027,
                                                                     10, 15)


class TestMatchingAPaymentToItsQuarter:

    def test_paid_on_the_deadline_counts_for_that_quarter(self):
        assert filings.quarter_for_payment("2026-09-15") == (2026, 3)

    def test_the_day_after_a_deadline_belongs_to_the_next_quarter(self):
        assert filings.quarter_for_payment("2026-04-16") == (2026, 2)

    def test_an_early_january_payment_is_last_years_q4(self):
        """
        Q4 of 2026 is due 15 January 2027. A payment then is 2026 tax, not
        2027 tax - filing it against the wrong year would show one year
        overpaid and the next short.
        """
        assert filings.quarter_for_payment("2027-01-10") == (2026, 4)


class TestNothingSeenIsNotNothingPaid:
    """
    This tool can only read her Wise accounts. She may pay by card, through
    EFTPS, or from an account it cannot see. Reporting "UNPAID" would be a
    false alarm every quarter she pays another way - and the kind that
    trains someone to ignore the whole thing.
    """

    def test_a_payment_she_records_by_hand_is_kept(self):
        conn = db.init_db(":memory:")
        db.record_tax_payment(
            conn, tax_year=2026, quarter=2, paid_on="2026-06-14",
            amount=861.59, currency="USD", amount_usd=861.59,
            detected="manual")
        conn.commit()
        rows = db.tax_payments_for(conn, 2026)
        assert len(rows) == 1
        assert rows[0]["detected"] == "manual"

    def test_recording_the_same_payment_twice_does_not_double_it(self):
        conn = db.init_db(":memory:")
        for _ in range(3):
            db.record_tax_payment(
                conn, tax_year=2026, quarter=2, paid_on="2026-06-14",
                amount=861.59, currency="USD", amount_usd=861.59,
                detected="manual")
        conn.commit()
        assert len(db.tax_payments_for(conn, 2026)) == 1

    def test_tax_paid_is_never_an_expense(self):
        """
        Income tax and SE tax are her personal liabilities, not costs of the
        business - and a disregarded entity makes it irrelevant which
        account pays. An expense row would reduce the very profit the tax is
        computed on.
        """
        conn = db.init_db(":memory:")
        db.record_tax_payment(
            conn, tax_year=2026, quarter=2, paid_on="2026-06-14",
            amount=861.59, currency="USD", amount_usd=861.59)
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0] == 0


class TestSpottingATaxPaymentInWise:

    def test_the_irs_is_recognised(self):
        from taxlib import wise_import
        assert wise_import.looks_like_tax_payment("Sent money to IRS USA TAX")
        assert wise_import.looks_like_tax_payment("UNITED STATES TREASURY")
        assert wise_import.looks_like_tax_payment("EFTPS payment")

    def test_an_airport_coffee_is_not_a_tax_payment(self):
        """
        "IRS" as a substring hits "A-IRS-ide", which is what an airport
        Costa is called. Found on the very first search of her account, and
        the same trap that made an Uber Eats order a taxi.
        """
        from taxlib import wise_import
        assert not wise_import.looks_like_tax_payment(
            "Card transaction of 218.00 CZK issued by Costa T2 Airside 62277")

    def test_paying_a_contractor_is_not_a_tax_payment(self):
        from taxlib import wise_import
        assert not wise_import.looks_like_tax_payment(
            "Sent money to Katerina Mrvova")


class TestTheFormsList:

    def test_every_form_carries_a_date_and_a_working_style_link(self):
        for form in filings.FORMS:
            assert form["due"], form["form"]
            assert form["url"].startswith("https://"), form["form"]
            assert form["note"], form["form"]

    def test_the_fbar_is_filed_with_fincen_not_the_irs(self):
        """People file it with the return. It is a different agency."""
        fbar = next(f for f in filings.FORMS if "FBAR" in f["form"])
        assert "FinCEN" in fbar["who"]
        assert "NOT the IRS" in fbar["who"]
        assert "fincen" in fbar["url"].lower()

    def test_the_1099_is_due_in_january_not_with_the_return(self):
        nec = next(f for f in filings.FORMS if "1099-NEC" in f["form"])
        assert "31 January" in nec["due"]

    def test_w8ben_has_no_threshold(self):
        w8 = next(f for f in filings.FORMS if "W-8BEN" in f["form"])
        assert "first dollar" in w8["due"]


class TestTheFormWorksheet:
    """
    She asked for pre-filled PDFs in a Drive folder. Three things blocked
    it, and the third settles it: THE 2026 FORMS DO NOT EXIST YET. Only
    Form 1040-ES is published; 1040, Schedule C, SE, 2555 and 8829 are all
    still the 2025 editions. A 2025 form carrying 2026 figures is wrong on
    its face while looking official.

    So the figures are mapped to their lines instead.
    """

    @staticmethod
    def _tab():
        from taxlib import db, tax, tax_sheet
        conn = db.init_db()
        return tax_sheet.form_lines_tab(conn, 2026,
                                        tax.from_database(conn, 2026))

    def test_meals_have_a_schedule_c_line(self):
        """
        They had none, so every meal landed as "review - no line assigned"
        on the one tab meant to say exactly where numbers go.
        """
        from taxlib import tax_sheet
        assert tax_sheet.SCHEDULE_C["meals"].startswith("24b")

    def test_entertainment_is_marked_as_zero_not_just_categorised(self):
        from taxlib import tax_sheet
        assert "0" in tax_sheet.SCHEDULE_C["entertainment"]

    def test_the_worksheet_is_on_the_same_basis_as_the_calculator(self):
        """
        THE GUARD AGAINST THE MISTAKE I ALREADY MADE ONCE.

        Her instruction is that the contractor jars count as paid, because
        they will be. A first version of this tab used the jars-STAY
        figures instead, reasoning that a filed return reports what
        happened rather than what is planned. Wrong, and she caught it: by
        filing time those payouts are real expenses in the database, so the
        projection is an early view of the same number, not another basis.

        This asserts the tab's bottom line IS the calculator's headline, so
        the two cannot drift apart again whichever way the setting is set.
        """
        from taxlib import db, tax
        conn = db.init_db()
        result = tax.from_database(conn, 2026)
        rows = self._tab().rows
        profit = [r for r in rows if len(r) > 3 and r[1] == "31"][0][3]
        se = [r for r in rows if len(r) > 3 and r[0] == "Schedule SE"
              and r[1] == "12"][0][3]
        assert profit == result["net_profit"]
        assert abs(se - result["total"]) < 1.0

    def test_contract_labor_includes_the_jars_about_to_be_paid(self):
        """
        The knock-on I missed first time. If the jars count as paid, they
        are contractor EXPENSE - line 11 has to carry them, or the form
        does not add up to its own net profit.
        """
        from taxlib import db, tax
        conn = db.init_db()
        result = tax.from_database(conn, 2026)
        jars = (result.get("contractor_jars") or {}).get("usd") or 0
        rows = self._tab().rows
        withdrawn = conn.execute(
            "SELECT COALESCE(SUM(amount_usd), 0) FROM expenses WHERE "
            "excluded = 0 AND category = 'contractor' AND tax_year = 2026"
        ).fetchone()[0]
        line11 = [r for r in rows if len(r) > 3 and r[1] == "11"][0][3]
        assert abs(line11 - (withdrawn + jars)) < 0.05

    def test_the_schedule_c_lines_actually_add_up(self):
        """Line 1 minus line 28 minus line 30 must equal line 31."""
        rows = self._tab().rows
        def line(n):
            return [r for r in rows
                    if len(r) > 3 and r[0] == "Schedule C" and r[1] == n][0][3]
        assert abs((line("1") - line("28") - line("30")) - line("31")) < 0.05

    def test_deductible_amounts_are_shown_not_gross_spend(self):
        """
        Line 24b wants the halved figure. Printing what she spent would
        overstate the deduction on the face of the form and stop the lines
        adding up to line 28.
        """
        rows = self._tab().rows
        meals = [r for r in rows if len(r) > 3 and r[1] == "24b"]
        if meals:
            assert "at 50%" in str(meals[0][4])

    def test_lines_that_only_she_can_fill_are_marked(self):
        rows = self._tab().rows
        assert any(len(r) > 1 and r[1] == "YOU" for r in rows)


class TestEachVoucherIsRecomputedNotJustTheTotalOverFour:
    """
    Her correction. Dividing the tax on income received SO FAR by four
    treats a part-year figure as the whole year: income keeps arriving, the
    annual tax keeps rising, and four equal payments computed in March end
    the year short.

    Each voucher is now the share due by ITS deadline less what has been
    paid - so a quarter that earned more produces a bigger voucher on its
    own, and a missed quarter is caught up by the next.
    """

    def test_the_vouchers_are_not_all_the_same(self):
        from taxlib import filings
        plan = filings.installments(3446.36, {}, tax_year=2026)
        amounts = [row["voucher"] for row in plan["quarters"]]
        assert len(set(amounts)) > 1

    def test_a_missed_quarter_is_caught_up_by_the_next(self):
        """Nothing paid by September means Q3 carries Q1 and Q2 as well."""
        from taxlib import filings
        plan = filings.installments(3446.36, {}, tax_year=2026)
        third = [r for r in plan["quarters"] if r["quarter"] == 3][0]
        assert third["voucher"] == third["cumulative_required"]
        assert third["voucher"] > plan["required_year"] / 4

    def test_paying_on_time_keeps_each_voucher_level(self):
        from taxlib import filings
        paid = {1: 775.43, 2: 775.43}
        plan = filings.installments(3446.36, paid, tax_year=2026)
        third = [r for r in plan["quarters"] if r["quarter"] == 3][0]
        assert abs(third["voucher"] - 775.43) < 1.0

    def test_the_required_payment_is_ninety_percent_of_the_year(self):
        from taxlib import filings
        plan = filings.installments(1000.0, {}, tax_year=2026)
        assert plan["required_year"] == 900.0

    def test_a_voucher_never_goes_negative(self):
        """Overpaying early must not produce a negative demand."""
        from taxlib import filings
        plan = filings.installments(1000.0, {1: 5000.0}, tax_year=2026)
        assert all(row["voucher"] >= 0 for row in plan["quarters"])


class TestTheRightAmountOnTheRightVoucher:
    """
    While every quarter was the same figure, which voucher was which did
    not matter. Now that they differ, putting the wrong number on a real
    form is a real error - so each voucher is identified by the DUE DATE it
    prints, not by guessing at opaque field names like f15_1[0].
    """

    def test_each_quarter_has_a_due_date_pattern_to_match_on(self):
        import re
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path.cwd() / "scripts"))
        import fill_1040es
        assert set(fill_1040es.DUE_TEXT) == {1, 2, 3, 4}
        for quarter, pattern in fill_1040es.DUE_TEXT.items():
            filled = pattern % {"y": 2026, "next": 2027}
            re.compile(filled)

    def test_the_patterns_match_the_dates_the_form_actually_prints(self):
        """Read off the real 2026 form: 'Calendar year-Due Sept. 15, 2026'."""
        import re
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path.cwd() / "scripts"))
        import fill_1040es
        printed = {1: "Calendar year—Due April 15, 2026",
                   2: "Calendar year—Due June 15, 2026",
                   3: "Calendar year—Due Sept. 15, 2026",
                   4: "Calendar year—Due Jan. 15, 2027"}
        for quarter, text in printed.items():
            pattern = fill_1040es.DUE_TEXT[quarter] % {"y": 2026, "next": 2027}
            assert re.search(pattern, text, re.I), (quarter, text)


class TestEachQuarterUsesItsOwnPeriod:
    """
    Her catch. The calculator ran on everything in the tax year, which on
    13 September meant everything up to 13 September - so a $4,000 payment
    received on 2 September was inside the Q3 figure. Q3 ends 31 AUGUST.
    That September money belongs to Q4, and taxing it in Q3 pays it four
    months early.
    """

    def test_the_quarter_cut_offs_are_the_irs_periods(self):
        import datetime as dt
        from taxlib import filings
        assert filings.period_end(1, 2026) == dt.date(2026, 3, 31)
        assert filings.period_end(2, 2026) == dt.date(2026, 5, 31)
        assert filings.period_end(3, 2026) == dt.date(2026, 8, 31)
        assert filings.period_end(4, 2026) == dt.date(2026, 12, 31)

    def test_income_after_the_cut_off_is_excluded(self):
        from taxlib import db, tax
        conn = db.init_db(":memory:")
        for date, amount in (("2026-08-15", 10000.0), ("2026-09-02", 4000.0)):
            db.upsert_income(conn, source="wise", source_id=f"i{date}",
                             date=date, amount=amount, currency="USD",
                             amount_usd=amount, description="fees")
        conn.commit()
        q3 = tax.from_database(conn, 2026, include_home_office=False,
                               through="2026-08-31")
        assert q3["totals"]["income_usd"] == 10000.0

    def test_a_later_quarter_picks_it_up(self):
        from taxlib import db, tax
        conn = db.init_db(":memory:")
        for date, amount in (("2026-08-15", 10000.0), ("2026-09-02", 4000.0)):
            db.upsert_income(conn, source="wise", source_id=f"i{date}",
                             date=date, amount=amount, currency="USD",
                             amount_usd=amount, description="fees")
        conn.commit()
        q4 = tax.from_database(conn, 2026, include_home_office=False,
                               through="2026-12-31")
        assert q4["totals"]["income_usd"] == 14000.0

    def test_the_home_office_is_never_asked_about_the_future(self):
        """
        It pro-rates on monthly exchange rates. A 31 December cut-off asks
        for rates that do not exist yet, the lookup failed, and the Q4 home
        office silently became $0.
        """
        from taxlib import db, tax
        conn = db.init_db()
        q4 = tax.from_database(conn, 2026, through="2026-12-31")
        assert q4["home_office_usd"] > 0
        assert q4["home_office_problem"] is None

    def test_the_voucher_pdf_and_the_sheet_use_the_same_function(self):
        """
        They drifted within an hour: the PDF said $1,953.80 for Q3 while
        the Tax Calendar said $2,538.38, because one projected the year and
        the other accrued the period. One function now, as with the tax.
        """
        import inspect
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path.cwd() / "scripts"))
        import fill_1040es
        from taxlib import tax_sheet
        assert "quarterly_plan" in inspect.getsource(fill_1040es.main)
        assert "quarterly_plan" in inspect.getsource(tax_sheet.tax_calendar_tab)


class TestWhereSheStandsRightNow:
    """
    Her request: the Summary should say what this RUNNING quarter has cost
    so far, and what is still outstanding behind it.

    The running quarter is not the one being filed. On 13 September the
    estimate being paid is Q3 (June-August), while the quarter currently
    running is Q4, which started on 1 September.
    """

    def test_september_is_inside_q4_not_q3(self):
        import datetime as dt
        from taxlib import filings
        assert filings.current_quarter(2026, dt.date(2026, 9, 13)) == 4
        assert filings.current_quarter(2026, dt.date(2026, 8, 31)) == 3

    def test_it_differs_from_the_quarter_being_filed(self):
        """
        The two are different questions and both are needed - one says what
        to pay on Monday, the other what is accruing now.
        """
        import datetime as dt
        from taxlib import distribution, filings
        today = dt.date(2026, 9, 13)
        assert filings.current_quarter(2026, today) == 4
        assert distribution.quarter_to_distribute(today)[1] == 3

    def test_the_running_figure_is_this_quarter_only(self):
        """
        Not the year to date. It is what has accrued SINCE the last
        cut-off, so it starts near zero each quarter and grows.
        """
        from taxlib import db, filings, tax
        conn = db.init_db()
        import datetime as dt
        here = filings.position(conn, 2026, today=dt.date(2026, 9, 13))
        to_aug = tax.from_database(conn, 2026, through="2026-08-31")["total"]
        to_today = tax.from_database(conn, 2026,
                                     through="2026-09-13")["total"]
        assert abs(here["accrued_this_quarter"] - (to_today - to_aug)) < 0.05
        assert here["accrued_this_quarter"] < to_today

    def test_past_quarters_are_listed_with_what_is_still_owed(self):
        import datetime as dt
        from taxlib import db, filings
        conn = db.init_db()
        here = filings.position(conn, 2026, today=dt.date(2026, 9, 13))
        assert [row["quarter"] for row in here["past"]] == [1, 2, 3]
        # NOT the sum of the vouchers - each already carries the unpaid
        # amount of the ones before it, so adding them counts Q1 three
        # times. Outstanding is the tax accrued by the last CLOSED quarter
        # less everything paid.
        assert here["outstanding"] == here["accrued_to_last_cutoff"]
        assert here["outstanding"] < sum(r["voucher"] for r in here["past"])

    def test_recording_a_payment_reduces_what_is_outstanding(self):
        import datetime as dt
        from taxlib import db, filings
        conn = db.init_db()
        before = filings.position(conn, 2026,
                                  today=dt.date(2026, 9, 13))["outstanding"]
        after = filings.position(conn, 2026, {1: 256.04},
                                 today=dt.date(2026, 9, 13))["outstanding"]
        assert round(before - after, 2) == 256.04
