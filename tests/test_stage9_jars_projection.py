"""
Estimating tax as if the contractor jars are emptied before 31 December.

HER INSTRUCTION, 2026-09-12. The reasoning is sound for an ESTIMATE: that
money will be paid out this year, so the year-end deduction will include it
and the final bill really is lower. Paying quarterly tax on money she is
going to deduct anyway just lends the IRS cash for a year.

WHAT IT IS NOT
    It is not a change to what is deductible. Finding 4 of the plan stands
    exactly as written - a jar is a label inside her own Wise account, and
    allocating to one deducts nothing. This is a projection about WHEN the
    money leaves, and it is conditional on it actually leaving.

    So both figures are computed every time, and the calculator prints both.
    If the jars are still full on 31 December the deduction falls into the
    next year and she owes the higher one.
"""

import datetime as dt

from taxlib import config, db, tax


def _jar(conn, name, person, amount, observed="2026-09-12"):
    conn.execute(
        "INSERT INTO wise_jars (balance_id, jar_name, person, observed_on,"
        " amount, currency, amount_usd, created_at, updated_at) "
        "VALUES (?,?,?,?,?,'USD',?,'x','x')",
        (f"bal-{name}-{amount}", name, person, observed, amount, amount))
    conn.commit()


class TestOnlyContractorJarsCount:

    def test_her_own_jar_is_never_projected_away(self):
        """
        THE ONE THAT WOULD UNDERSTATE THE TAX. Paying herself out of her own
        jar is an owner draw, and a draw is not deductible on any date. It
        is not a timing question like the team's money is - including it
        would make the bill wrong rather than merely early.
        """
        conn = db.init_db(":memory:")
        _jar(conn, "Katerina", "Katerina Mrvova", 3955.60)
        _jar(conn, "Liuba", None, 440.28)
        pending = tax.pending_contractor_jars(conn, 2026,
                                              today=dt.date(2026, 9, 12))
        assert pending["usd"] == 3955.60

    def test_an_admin_pot_belongs_to_nobody_and_is_left_in(self):
        conn = db.init_db(":memory:")
        _jar(conn, "ADMIN 30%", None, 1200.00)
        pending = tax.pending_contractor_jars(conn, 2026,
                                              today=dt.date(2026, 9, 12))
        assert pending["usd"] == 0.0

    def test_a_contractor_jar_counts(self):
        conn = db.init_db(":memory:")
        _jar(conn, "Ayoka", "Yetunde Olaniyan", 2485.28)
        pending = tax.pending_contractor_jars(conn, 2026,
                                              today=dt.date(2026, 9, 12))
        assert pending["usd"] == 2485.28


class TestTheAssumptionExpiresWithTheYear:

    def test_once_the_year_is_over_it_cannot_come_true(self):
        """
        On 5 January the money either went out or it did not. Carrying the
        assumption forward would keep quietly reducing a bill that is now
        fixed.
        """
        conn = db.init_db(":memory:")
        _jar(conn, "Katerina", "Katerina Mrvova", 3955.60)
        pending = tax.pending_contractor_jars(conn, 2026,
                                              today=dt.date(2027, 1, 5))
        assert pending["usd"] == 0.0
        assert pending["still_possible"] is False

    def test_during_the_year_it_still_can(self):
        conn = db.init_db(":memory:")
        _jar(conn, "Katerina", "Katerina Mrvova", 3955.60)
        pending = tax.pending_contractor_jars(conn, 2026,
                                              today=dt.date(2026, 12, 30))
        assert pending["still_possible"] is True


class TestBothFiguresAreAlwaysAvailable:

    def _result(self, settings=None):
        conn = db.init_db(":memory:")
        _jar(conn, "Katerina", "Katerina Mrvova", 6440.88)
        db.upsert_income(conn, source="wise", source_id="i1",
                         date="2026-03-01", amount=40000.0, currency="USD",
                         amount_usd=40000.0, description="fees")
        conn.commit()
        return tax.from_database(conn, 2026, settings,
                                 include_home_office=False,
                                 today=dt.date(2026, 9, 12))

    def test_the_higher_figure_is_never_hidden(self):
        """
        The projection rests on a condition. Reporting only the lower number
        would present a plan as a fact.
        """
        result = self._result()
        assert result["tax_if_jars_stay"] > result["tax_if_jars_paid"]
        assert result["jars_saving_usd"] > 0

    def test_the_default_uses_the_projected_figure(self):
        result = self._result()
        assert result["jars_assumption_applied"] is True
        assert result["total"] == result["tax_if_jars_paid"]

    def test_it_can_be_turned_off(self):
        """She can estimate on what has actually been paid instead."""
        settings = {**config.SETTINGS,
                    "assume_contractor_jars_paid_by_year_end": False}
        result = self._result(settings)
        assert result["jars_assumption_applied"] is False
        assert result["total"] == result["tax_if_jars_stay"]

    def test_the_jars_never_become_an_expense_row(self):
        """
        It is a projection, not a transaction. Given a row in `expenses` it
        would flow into the sheet, the reconciliation and the Schedule C
        totals as though somebody had been paid.
        """
        conn = db.init_db(":memory:")
        _jar(conn, "Katerina", "Katerina Mrvova", 6440.88)
        tax.from_database(conn, 2026, include_home_office=False,
                          today=dt.date(2026, 9, 12))
        assert conn.execute(
            "SELECT COUNT(*) FROM expenses").fetchone()[0] == 0


class TestTheDecemberReminderCarriesTheConsequence:
    """
    The 1 December alert already existed. What changed on 2026-09-12 is that
    it became load-bearing: the quarterly payments are now worked out on the
    assumption it enforces. So it must say what happens if it is ignored,
    in those words.
    """

    @staticmethod
    def _alert(day):
        conn = db.init_db(":memory:")
        conn.execute(
            "INSERT INTO wise_jars (balance_id, jar_name, person, observed_on,"
            " amount, currency, amount_usd, created_at, updated_at) "
            "VALUES ('b1','Katerina','Katerina Mrvova','2026-09-12',"
            "6440.88,'USD',6440.88,'x','x')")
        conn.commit()
        from taxlib import alerts
        return alerts.jar_alerts(conn, day, 2026)

    def test_it_does_not_fire_in_november(self):
        assert self._alert(dt.date(2026, 11, 30)) == []

    def test_it_fires_from_the_first_of_december(self):
        assert len(self._alert(dt.date(2026, 12, 1))) == 1

    def test_it_says_she_has_underpaid_not_merely_missed_a_saving(self):
        """
        The distinction that matters. Under the old wording this was an
        opportunity forgone; now the money has already been left out of her
        quarterly payments, so it is a shortfall.
        """
        body = self._alert(dt.date(2026, 12, 15))[0].body
        assert "UNDERPAID" in body
        assert "already assumed" in body.lower()

    def test_it_mentions_safe_harbour_rather_than_only_alarming_her(self):
        body = self._alert(dt.date(2026, 12, 15))[0].body
        assert "afe harbour" in body or "afe harbor" in body

    def test_it_still_warns_about_katerinas_1099(self):
        """Emptying her jar may cross $600 - that was already there and
        must survive the rewrite."""
        body = self._alert(dt.date(2026, 12, 15))[0].body
        assert "1099" in body
