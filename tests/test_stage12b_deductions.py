"""
Automatic checks for Stage 12b (home office, meals and the other deductions).

The ones the plan named:

  * both home office methods computed, the better one identified, capped
    at net profit and never turning it negative
  * a business meal deducted at 50%, not 100%
  * $1,000 of deduction reduces income tax by $0 and self-employment tax
    by about $141 - the FEIE framing, proved against the calculator
"""

import pytest

from taxlib import categorize, config, db, home_office, tax


@pytest.fixture
def conn():
    connection = db.init_db(":memory:")
    yield connection
    connection.close()


def fixed_rate(rate):
    def fetcher(date, base_currency, quote_currency="USD"):
        return float(rate), date
    return fetcher


HER_HOME = {
    "exclusive_use": True,
    "total_area": 60.0, "office_area": 12.0, "area_unit": "m2",
    "monthly_rent": 720.0, "monthly_utilities": 120.0,
    "monthly_insurance": 0.0, "currency": "EUR", "months": 12,
}


# ---------------------------------------------------------------------------
#  The share of the home
# ---------------------------------------------------------------------------

def test_the_business_share_is_the_ratio_of_the_two_areas():
    assert home_office.business_share(HER_HOME) == 0.2


def test_the_unit_does_not_matter_because_only_the_ratio_is_used():
    metric = dict(HER_HOME, total_area=60.0, office_area=12.0)
    imperial = dict(HER_HOME, total_area=645.83, office_area=129.17,
                    area_unit="sqft")
    assert round(home_office.business_share(metric), 4) == \
        round(home_office.business_share(imperial), 4)


def test_an_office_bigger_than_the_home_is_refused():
    with pytest.raises(home_office.HomeOfficeNotClaimed):
        home_office.business_share(dict(HER_HOME, office_area=100.0))


def test_square_metres_are_converted_for_the_simplified_method():
    assert round(home_office.office_sqft(HER_HOME), 1) == 129.2


# ---------------------------------------------------------------------------
#  The two methods
# ---------------------------------------------------------------------------

def test_the_actual_method_takes_the_share_of_rent_and_utilities(conn):
    result = home_office.actual(conn, 2026, HER_HOME,
                                fetcher=fixed_rate(1.10), today="2026-08-31")
    # 20% of EUR 840 = EUR 168 a month, eight elapsed months, at 1.10
    assert result["monthly_business_native"] == 168.00
    assert result["months_counted"] == 8
    assert result["amount_usd"] == pytest.approx(168 * 8 * 1.10, abs=0.02)


def test_the_simplified_method_is_a_flat_rate_per_square_foot():
    result = home_office.simplified(HER_HOME)
    assert result["amount_usd"] == pytest.approx(129.17 * 5.00, abs=0.05)
    assert result["capped"] is False


def test_the_simplified_method_caps_the_area_not_the_money():
    """A huge office still counts only the first 300 square feet."""
    result = home_office.simplified(dict(HER_HOME, office_area=500.0,
                                         area_unit="sqft"))
    assert result["capped"] is True
    assert result["counted_sqft"] == 300
    assert result["amount_usd"] == 1500.00


def test_both_are_computed_and_the_better_one_named(conn):
    result = home_office.best(conn, 2026, net_profit=50_000, settings=HER_HOME,
                              fetcher=fixed_rate(1.10), today="2026-08-31")
    assert result["actual"]["amount_usd"] > result["simplified"]["amount_usd"]
    assert result["better_method"] == "actual"
    assert result["claimed_usd"] == result["actual"]["amount_usd"]


def test_the_simplified_method_wins_when_it_is_bigger(conn):
    """Cheap rent, big office - the flat rate can win, so it is not assumed."""
    # Tiny rent, large office: the flat rate wins comfortably.
    cheap = dict(HER_HOME, monthly_rent=10.0, monthly_utilities=0.0,
                 total_area=500.0, office_area=250.0, area_unit="sqft")
    result = home_office.best(conn, 2026, net_profit=50_000, settings=cheap,
                              fetcher=fixed_rate(1.10), today="2026-08-31")
    assert result["better_method"] == "simplified"


def test_only_elapsed_months_are_counted(conn):
    """
    A month that has not finished has no exchange rate, and inventing one
    would be a guess. Counting stops at today and says so.
    """
    result = home_office.actual(conn, 2026, HER_HOME,
                                fetcher=fixed_rate(1.10), today="2026-09-06")
    assert result["months_counted"] == 8       # January to August
    assert result["part_year"] is True


def test_both_methods_are_prorated_over_the_same_months(conn):
    """
    Otherwise the "better" method would be decided by the calendar rather
    than by the arithmetic.
    """
    result = home_office.best(conn, 2026, net_profit=50_000, settings=HER_HOME,
                              fetcher=fixed_rate(1.10), today="2026-09-06")
    assert result["actual"]["months_counted"] == 8
    assert result["simplified"]["months"] == 8


# ---------------------------------------------------------------------------
#  The conditions
# ---------------------------------------------------------------------------

def test_no_deduction_without_exclusive_use(conn):
    """The condition people fail. No arithmetic rescues it."""
    with pytest.raises(home_office.HomeOfficeNotClaimed) as problem:
        home_office.best(conn, 2026, net_profit=50_000,
                         settings=dict(HER_HOME, exclusive_use=False),
                         fetcher=fixed_rate(1.10))
    assert "ONLY for work" in str(problem.value)


def test_the_deduction_cannot_exceed_net_profit(conn):
    result = home_office.best(conn, 2026, net_profit=500, settings=HER_HOME,
                              fetcher=fixed_rate(1.10), today="2026-08-31")
    assert result["claimed_usd"] == 500.00
    assert result["limited_by_profit"] is True
    assert result["carried_forward_usd"] > 0


def test_the_deduction_never_turns_a_profit_into_a_loss(conn):
    result = home_office.best(conn, 2026, net_profit=0, settings=HER_HOME,
                              fetcher=fixed_rate(1.10), today="2026-08-31")
    assert result["claimed_usd"] == 0.0


def test_what_is_capped_carries_forward_rather_than_vanishing(conn):
    result = home_office.best(conn, 2026, net_profit=1000, settings=HER_HOME,
                              fetcher=fixed_rate(1.10), today="2026-08-31")
    assert result["claimed_usd"] + result["carried_forward_usd"] == \
        pytest.approx(result["before_limit_usd"], abs=0.01)


# ---------------------------------------------------------------------------
#  Meals at 50%
# ---------------------------------------------------------------------------

def test_a_business_meal_is_half_deductible(conn):
    db.upsert_expense(conn, source="capitalone", source_id="m1",
                      date="2026-05-01", amount=100, currency="USD",
                      amount_usd=100, category="meals", vendor="Le Bistro")
    conn.commit()

    totals = db.totals(conn, 2026)
    assert totals["expenses_usd"] == 100.00
    assert totals["deductible_expenses_usd"] == 50.00
    assert totals["non_deductible_usd"] == 50.00


def test_everything_else_is_still_fully_deductible(conn):
    db.upsert_expense(conn, source="stripe", source_id="s1",
                      date="2026-05-01", amount=100, currency="USD",
                      amount_usd=100, category="software", vendor="Notion")
    conn.commit()
    totals = db.totals(conn, 2026)
    assert totals["deductible_expenses_usd"] == 100.00
    assert totals["non_deductible_usd"] == 0.00


def test_the_gross_figure_is_kept_so_the_sheet_still_matches_the_bank(conn):
    """
    Reporting only the deductible half would leave the sheet disagreeing
    with her bank statement for no visible reason.
    """
    db.upsert_expense(conn, source="capitalone", source_id="m1",
                      date="2026-05-01", amount=80, currency="USD",
                      amount_usd=80, category="meals", vendor="Cafe")
    conn.commit()
    assert db.totals(conn, 2026)["expenses_usd"] == 80.00


def test_the_2021_hundred_percent_allowance_is_not_used():
    """It ran in 2021-2022 only and has expired."""
    assert config.deductible_share("meals") == 0.50


# ---------------------------------------------------------------------------
#  Categorisation traps found while building this
# ---------------------------------------------------------------------------

def test_uber_eats_is_a_meal_and_not_a_taxi():
    """
    The travel rule matches the bare word "Uber". With travel tried first,
    a takeaway was being deducted as a train fare.
    """
    rules = categorize.load_rules()
    assert categorize.categorize("UBER *EATS Paris", rules)[0] == "meals"
    assert categorize.categorize("UBER TRIP 4321", rules)[0] == "travel"


def test_a_persons_name_is_not_mistaken_for_a_bakery():
    """
    "Paul" is a French bakery chain and also a common first name. Matching
    it put a consultant's invoice in meals - a wrong deduction, and an
    invisible one.
    """
    rules = categorize.load_rules()
    assert categorize.categorize("Paul Smith consulting", rules)[0] == \
        "uncategorized"


# ---------------------------------------------------------------------------
#  What a deduction is actually worth to her
# ---------------------------------------------------------------------------

def test_a_deduction_saves_no_income_tax_and_about_14_percent_in_se_tax():
    """
    The plan's test 18, and the framing the whole stage rests on. Her
    income tax is $0 under the FEIE either way, so $1,000 of deduction is
    worth 15.3% of 92.35% - about $141 - and not a cent more.
    """
    before = tax.estimate(50_000)
    after = tax.estimate(49_000)

    assert before["income_tax"]["total"] == 0.0
    assert after["income_tax"]["total"] == 0.0

    saved = before["self_employment_tax"]["total"] - after["self_employment_tax"]["total"]
    assert saved == pytest.approx(1000 * 0.9235 * 0.153, abs=0.02)
    assert saved == pytest.approx(141.30, abs=0.05)


def test_the_home_office_reduces_the_tax_it_is_supposed_to(conn):
    db.upsert_income(conn, source="stripe", source_id="i1", date="2026-03-01",
                     amount=50_000, currency="USD", amount_usd=50_000)
    conn.commit()

    without = tax.from_database(conn, 2026, include_home_office=False)
    with_office = tax.from_database(conn, 2026, today="2026-08-31")

    assert with_office["home_office_usd"] > 0
    assert with_office["net_profit"] < without["net_profit"]
    assert with_office["self_employment_tax"]["total"] < without["self_employment_tax"]["total"]
    assert with_office["income_tax"]["total"] == 0.0
    assert without["income_tax"]["total"] == 0.0


def test_a_broken_home_office_setting_does_not_stop_the_tax_estimate(conn, monkeypatch):
    """
    The tax figure matters more than the home office. A bad setting must
    be reported, not crash the run.
    """
    monkeypatch.setattr(config, "HOME_OFFICE",
                        dict(HER_HOME, exclusive_use=False))
    db.upsert_income(conn, source="stripe", source_id="i1", date="2026-03-01",
                     amount=50_000, currency="USD", amount_usd=50_000)
    conn.commit()

    result = tax.from_database(conn, 2026)
    assert result["home_office"] is None
    assert result["home_office_usd"] == 0.0
    assert "ONLY for work" in result["home_office_problem"]
    assert result["self_employment_tax"]["total"] > 0
