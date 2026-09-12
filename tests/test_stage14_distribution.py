"""Stage 14 - the quarterly profit distribution."""

import datetime as dt

import pytest

from taxlib import config, db, distribution


class TestTheTaxQuarterIsNotTheCalendarQuarter:
    """
    Her choice, and the thing most likely to be got wrong by anyone reading
    "quarterly" and assuming three months. US estimated tax quarters are
    Jan-Mar, Apr-MAY, Jun-AUG, Sep-DEC. She runs the distribution just
    before filing the estimate, so the two must line up.
    """

    def test_q2_is_two_months_and_q4_is_four(self):
        assert distribution.TAX_QUARTER_MONTHS[2] == ["Apr", "May"]
        assert distribution.TAX_QUARTER_MONTHS[4] == ["Sep", "Oct", "Nov",
                                                      "Dec"]

    def test_every_month_belongs_to_exactly_one_quarter(self):
        seen = [m for months in distribution.TAX_QUARTER_MONTHS.values()
                for m in months]
        assert sorted(seen) == sorted(config.MONTH_ABBR)
        assert len(seen) == 12

    def test_september_files_the_june_to_august_quarter(self):
        """
        The case that actually happens. Run on 12 September - three days
        before the deadline - this is FOR June to August, not for the
        September we are standing in. Getting this wrong distributed a
        quarter that had not happened yet.
        """
        year, quarter = distribution.quarter_to_distribute(
            dt.date(2026, 9, 12))
        assert (year, quarter) == (2026, 3)
        assert distribution.TAX_QUARTER_MONTHS[quarter] == ["Jun", "Jul",
                                                            "Aug"]

    def test_january_files_the_previous_years_q4(self):
        year, quarter = distribution.quarter_to_distribute(dt.date(2027, 1, 5))
        assert (year, quarter) == (2026, 4)


class TestThePool:
    def test_jars_and_buffer_come_out(self):
        pool = distribution.compute_pool(
            balances_usd=12324.09, jars_usd=6881.16, buffer_usd=1000.0)
        assert pool["pool_usd"] == 4442.93

    def test_her_own_jar_is_already_distributed(self):
        """
        Confirmed by her 2026-09-12: money in her jar is hers already, the
        same as the team's jars are theirs. So every jar comes out, and the
        pool is the operating money less the buffer.
        """
        pool = distribution.compute_pool(
            balances_usd=5000.0 + 900.0, jars_usd=900.0, buffer_usd=1000.0)
        assert pool["pool_usd"] == 4000.0

    def test_a_pool_smaller_than_the_buffer_is_not_negative(self):
        pool = distribution.compute_pool(
            balances_usd=1200.0, jars_usd=900.0, buffer_usd=1000.0)
        assert pool["pool_usd"] == 0.0
        assert pool["negative"] is True


class TestEarnedWeights:
    EARNED = {config.KATERINA: 5667.13, config.AYOKA: 5721.11,
              config.JANE: 1388.17}

    def test_the_shared_client_group_is_not_counted_twice(self):
        """
        THE TRAP. Katerina and Ayoka split ONE client group 50/50, so
        inverting both their formulas recovers the SAME revenue twice.
        Adding them puts gross near $34,250 against a true $18,952 - which
        under this method inflates HER 5%, since that is what her weight is.
        """
        weights, gross = distribution.earned_weights(self.EARNED)
        assert 18_000 < gross < 20_000, gross
        # Her 5% rides on gross, so a doubled gross doubles her share too.
        assert weights[config.FOUNDER] == pytest.approx(947.59, abs=0.05)

    def test_a_manager_is_weighted_by_what_the_sheet_says_they_earned(self):
        """
        Weighted on DOLLARS EARNED, not on revenue driven. The two differ,
        and the difference is the whole point of her instruction, so this
        pins the one that is meant.
        """
        weights, _ = distribution.earned_weights(self.EARNED)
        assert weights[config.KATERINA] == 5667.13
        assert weights[config.AYOKA] == 5721.11
        assert weights[config.JANE] == 1388.17

    def test_her_weight_is_the_five_percent_she_takes_off_the_top(self):
        weights, gross = distribution.earned_weights(self.EARNED)
        assert weights[config.FOUNDER] == pytest.approx(gross * 0.05, abs=0.05)

    def test_five_percent_of_revenue_is_about_seven_percent_of_the_pool(self):
        """
        The result that looks wrong and is not, so it is written down.

        On one $1,000 client payment she takes $50 while Katerina and Ayoka
        take $665 between them. Her 5% is a RATE ON REVENUE; the 80% share is
        divided on DOLLARS EARNED. Measured in dollars, $50 against $665
        lands her near 7% of the combined earned pool, not 5%.

        Anyone "fixing" this to read 5% would be changing the method, not
        correcting a bug.
        """
        weights, _ = distribution.earned_weights(self.EARNED)
        total = sum(weights.values())
        assert weights[config.FOUNDER] / total == pytest.approx(0.069,
                                                                abs=0.002)

    def test_one_thousand_pounds_of_client_money_splits_as_she_described(self):
        assert round(1000 * 0.05, 2) == 50.00
        assert round(1000 * 0.95 * 0.70, 2) == 665.00
        assert round(1000 * (0.95 - 0.95 * 0.70), 2) == 285.00

    def test_a_quarter_with_no_revenue_does_not_divide_by_zero(self):
        weights, gross = distribution.earned_weights({})
        assert gross == 0.0
        assert weights == {}


class TestTheSplit:
    EARNED = {config.KATERINA: 5667.13, config.AYOKA: 5721.11,
              config.JANE: 1388.17}

    def _rows(self, pool=4442.93):
        weights, _ = distribution.earned_weights(self.EARNED)
        return distribution.split(pool, weights)

    def test_the_whole_pool_is_distributed(self):
        rows = self._rows()
        assert sum(r["total_usd"] for r in rows) == pytest.approx(4442.93,
                                                                 abs=0.05)

    def test_the_flat_share_is_equal_and_sunniva_is_not_in_it(self):
        rows = self._rows()
        flat = {r["even_usd"] for r in rows}
        assert len(flat) == 1
        assert len(rows) == 4
        assert "Sunniva Texe" not in {r["person"] for r in rows}

    def test_her_own_share_is_not_deductible(self):
        """
        The point of the whole stage. A single-member LLC is disregarded, so
        paying herself is an owner draw and reduces taxable profit by
        nothing. Marking it deductible would understate her tax.
        """
        rows = self._rows()
        hers = next(r for r in rows if r["person"] == config.FOUNDER)
        assert hers["deductible"] is False
        assert all(r["deductible"] for r in rows
                   if r["person"] != config.FOUNDER)

    def test_a_team_bonus_is_deductible_only_when_withdrawn(self):
        rows = self._rows()
        team = next(r for r in rows if r["person"] == config.KATERINA)
        assert "WITHDRAWN" in team["deductible_when"]


class TestRerunningAQuarterDoesNotPayTwice:
    """
    Without this the September run, done twice, reads as two bonuses each.
    """

    def test_the_same_quarter_revises_rather_than_adds(self):
        conn = db.init_db(":memory:")
        for _ in range(3):
            db.upsert_distribution(
                conn, tax_year=2026, quarter=3, person=config.KATERINA,
                pool_usd=4442.93, even_usd=222.15, weight_usd=8134.46,
                proportional_usd=1525.60, total_usd=1747.74)
        conn.commit()
        rows = db.distributions_for(conn, 2026, 3)
        assert len(rows) == 1
        assert rows[0]["total_usd"] == 1747.74

    def test_different_quarters_are_kept_apart(self):
        conn = db.init_db(":memory:")
        for quarter in (2, 3):
            db.upsert_distribution(
                conn, tax_year=2026, quarter=quarter, person=config.KATERINA,
                pool_usd=1000.0, even_usd=50.0, weight_usd=500.0,
                proportional_usd=200.0, total_usd=250.0)
        conn.commit()
        assert len(db.distributions_for(conn, 2026)) == 2

    def test_recomputing_does_not_un_pay_someone(self):
        """
        Once the money has left, that is a fact about the world. A later
        recomputation must not quietly clear it and make the deduction
        vanish.
        """
        conn = db.init_db(":memory:")
        db.upsert_distribution(
            conn, tax_year=2026, quarter=3, person=config.KATERINA,
            pool_usd=4442.93, even_usd=222.15, weight_usd=8134.46,
            proportional_usd=1525.60, total_usd=1747.74,
            withdrawn_on="2026-09-14")
        db.upsert_distribution(
            conn, tax_year=2026, quarter=3, person=config.KATERINA,
            pool_usd=4500.00, even_usd=225.00, weight_usd=8134.46,
            proportional_usd=1530.00, total_usd=1755.00)
        conn.commit()
        row = db.distributions_for(conn, 2026, 3)[0]
        assert row["withdrawn_on"] == "2026-09-14"
        assert row["total_usd"] == 1755.00
