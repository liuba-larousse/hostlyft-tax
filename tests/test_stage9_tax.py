"""
Automatic checks for Stage 9 (the tax calculator).

The two the plan named explicitly:

  * $80,000 profit -> income tax $0, self-employment tax about $11,304
  * $150,000 profit -> exercises the FEIE cap and the stacking rule

Plus the bracket table checked against its own arithmetic, so a mistyped
figure fails here rather than quietly changing the answer.
"""

import pytest

from taxlib import constants_2026 as k, tax


# ---------------------------------------------------------------------------
#  The bracket table, checked against itself
# ---------------------------------------------------------------------------

def test_each_bracket_starts_where_the_one_below_it_ends():
    """
    Revenue Procedure 2025-32 states the cumulative tax at the bottom of
    every band. That is redundant - it can be derived - which is exactly
    what makes it useful: recompute it and a mistyped threshold or rate
    shows up as a mismatch instead of a slightly wrong tax bill.
    """
    running, low = 0.0, 0
    for limit, rate, stated_base in k.MFS_BRACKETS:
        assert abs(running - stated_base) < 0.01, (
            f"band starting at ${low:,} says ${stated_base:,.2f} but the "
            f"bands below it add up to ${running:,.2f}")
        if limit is None:
            break
        running += (limit - low) * rate
        low = limit


def test_the_mfs_top_threshold_is_half_the_joint_one():
    """
    $384,350 is half of the $768,700 joint threshold - the relationship that
    distinguishes it from the $640,600 single-filer figure sitting on the
    same page of the PDF.
    """
    top_band = k.MFS_BRACKETS[-2]
    assert top_band[0] == 384_350
    assert 768_700 / 2 == 384_350


def test_the_additional_medicare_threshold_is_the_separate_filer_one():
    """$125,000, not the $200,000 quoted almost everywhere."""
    assert k.ADDITIONAL_MEDICARE_THRESHOLD_MFS == 125_000


def test_the_headline_rate_is_its_two_parts():
    assert (k.SE_SOCIAL_SECURITY_RATE + k.SE_MEDICARE_RATE
            == pytest.approx(0.153))


# ---------------------------------------------------------------------------
#  The plan's worked examples
# ---------------------------------------------------------------------------

def test_at_eighty_thousand_income_tax_is_zero_and_se_tax_is_about_11304():
    result = tax.estimate(80_000)

    assert result["income_tax"]["total"] == 0.00
    assert result["self_employment_tax"]["total"] == pytest.approx(11_304, abs=1)
    assert result["total"] == result["self_employment_tax"]["total"]


def test_the_certificate_of_coverage_turns_self_employment_tax_off():
    """
    The US-France totalization agreement assigns a self-employed worker
    working only in France to French coverage - but only with a Certificate
    of Coverage from the body collecting the contributions.
    """
    without = tax.estimate(80_000, {"certificate_of_coverage": False,
                                    "relief_method": "FEIE",
                                    "bona_fide_resident": True})
    with_it = tax.estimate(80_000, {"certificate_of_coverage": True,
                                    "relief_method": "FEIE",
                                    "bona_fide_resident": True})

    assert without["total"] == pytest.approx(11_304, abs=1)
    assert with_it["total"] == 0.00


def test_at_one_hundred_and_fifty_thousand_the_cap_applies_but_tax_is_still_nil():
    """
    The plan's second worked example. At $150,000 the exclusion runs out -
    $17,100 is above the cap - but the standard deduction and the allowed
    share of the half-self-employment-tax deduction together cover it, so
    income tax is still $0.

    Worth pinning: the cap being reached does NOT automatically mean tax is
    owed, and a calculator that assumed it did would overstate the bill.
    """
    result = tax.estimate(150_000)
    it = result["income_tax"]

    assert it["excluded"] == 132_900.00
    assert it["taxable"] == 0.00
    assert it["total"] == 0.00
    # self-employment tax is unaffected by the exclusion and keeps growing
    assert result["self_employment_tax"]["total"] == pytest.approx(21_316,
                                                                  abs=2)


def test_above_the_cap_the_excess_is_taxed_at_the_rate_it_would_have_met():
    """
    THE STACKING RULE (§911(f)), and why it matters.

    At $160,000, $9,068.10 ends up taxable. Taxed from the bottom of the
    table that would be 10% - $906.81. Stacked on top of the excluded
    $132,900, it meets the 24% band instead: $2,176.34.

    Two and a half times the tax. A calculator that ignored stacking would
    understate every year above the cap.
    """
    result = tax.estimate(160_000)
    it = result["income_tax"]

    assert it["excluded"] == 132_900.00
    assert it["taxable"] == pytest.approx(9_068.10, abs=0.05)

    from_the_bottom = tax.tax_on_brackets(it["taxable"])
    assert from_the_bottom == pytest.approx(906.81, abs=0.05)
    assert it["total"] == pytest.approx(2_176.34, abs=0.05)
    assert it["total"] > from_the_bottom * 2


def test_the_stacking_rule_uses_the_rates_the_income_would_have_met():
    """
    Checked directly: tax on everything, less tax on the excluded part.
    """
    net = 200_000
    result = tax.estimate(net)
    it = result["income_tax"]

    expected = (tax.tax_on_brackets(it["taxable"] + it["excluded"])
                - tax.tax_on_brackets(it["excluded"]))
    assert it["total"] == pytest.approx(round(expected, 2), abs=0.01)


# ---------------------------------------------------------------------------
#  Self-employment tax details
# ---------------------------------------------------------------------------

def test_only_ninety_two_point_three_five_percent_is_taxed():
    result = tax.self_employment_tax(100_000)
    assert result["taxable_base"] == pytest.approx(92_350, abs=1)


def test_social_security_stops_at_the_wage_base_but_medicare_does_not():
    """
    At a profit high enough to pass the cap, Social Security stops growing
    and Medicare keeps going. Getting this backwards would overcharge every
    high year.
    """
    big = tax.self_employment_tax(400_000)
    base_capped = k.SOCIAL_SECURITY_WAGE_BASE * k.SE_SOCIAL_SECURITY_RATE

    assert big["social_security"] == pytest.approx(base_capped, abs=1)
    assert big["medicare"] > 400_000 * k.SE_TAXABLE_SHARE * 0.028


def test_the_extra_medicare_tax_starts_at_the_right_place():
    """
    It applies above $125,000 of the TAXABLE BASE, not of profit. A profit
    of $130,000 has a base of $120,055 and so pays none.
    """
    under = tax.self_employment_tax(130_000)
    assert under["additional_medicare"] == 0.00

    over = tax.self_employment_tax(200_000)
    expected = (200_000 * k.SE_TAXABLE_SHARE - 125_000) * 0.009
    assert over["additional_medicare"] == pytest.approx(expected, abs=0.01)


def test_no_profit_means_no_tax():
    for amount in (0, -5_000):
        result = tax.estimate(amount)
        assert result["total"] == 0.00


# ---------------------------------------------------------------------------
#  Against the real database
# ---------------------------------------------------------------------------

def test_it_runs_against_the_database_and_shows_its_working():
    from taxlib import db

    conn = db.init_db(":memory:")
    db.upsert_income(conn, source="stripe", source_id="a", date="2026-03-01",
                     amount=60_000, currency="USD", amount_usd=60_000)
    db.upsert_expense(conn, source="wise", source_id="b", date="2026-03-02",
                      amount=10_000, currency="USD", amount_usd=10_000,
                      category="contractor")
    conn.commit()

    result = tax.from_database(conn, 2026)

    assert result["net_profit"] == 50_000.00
    assert result["income_tax"]["total"] == 0.00
    assert result["self_employment_tax"]["total"] == pytest.approx(7_065, abs=2)
    # every figure comes with the reasoning that produced it
    assert result["self_employment_tax"]["steps"]
    assert result["income_tax"]["steps"]
    conn.close()


def test_both_businesses_are_taxed_together():
    """
    Self-employment tax is charged on COMBINED net earnings. Taxing them
    apart would waste the Social Security cap and get the total wrong.
    """
    from taxlib import db

    conn = db.init_db(":memory:")
    db.upsert_income(conn, source="stripe", source_id="h", date="2026-03-01",
                     amount=30_000, currency="USD", amount_usd=30_000,
                     business="hostlyft")
    db.upsert_income(conn, source="wise", source_id="m", date="2026-03-01",
                     amount=20_000, currency="USD", amount_usd=20_000,
                     business="marcus")
    conn.commit()

    combined = tax.from_database(conn, 2026)
    separate = (tax.estimate(30_000)["total"] + tax.estimate(20_000)["total"])

    assert combined["net_profit"] == 50_000.00
    assert combined["total"] == pytest.approx(separate, abs=1)
    conn.close()


def test_quarterly_splits_what_is_left():
    assert tax.quarterly(11_304) == 2_826.00
    assert tax.quarterly(11_304, paid_so_far=3_304) == 2_000.00
    assert tax.quarterly(1_000, paid_so_far=5_000) == 0.00
