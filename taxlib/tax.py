"""
tax.py - working out what to set aside.

HER SITUATION, AND WHY IT SPLITS IN TWO
    A US citizen, living permanently in France, filing Married Filing
    Separately, self-employed. That produces an unusual shape:

    INCOME TAX is expected to be $0. The Foreign Earned Income Exclusion
    (Form 2555) excludes foreign earned income up to $132,900, and net
    profit is well below that. She still files - owing nothing is not the
    same as filing nothing - but the bill is nil.

    SELF-EMPLOYMENT TAX is the entire bill. The FEIE does NOT reduce it.
    IRS: "You must pay self-employment tax on all your net profit from
    self-employment, even if you claimed the foreign earned income
    exclusion."

    So essentially everything owed is self-employment tax, and every
    business deduction is worth 15.3% x 92.35% = 14.13% - not the marginal
    income-tax rate a US resident would save.

THE ONE THING THAT WOULD CHANGE IT
    The US-France totalization agreement assigns a self-employed worker
    working only in France to French coverage. Claiming it needs a French
    Certificate of Coverage from the body collecting her contributions. She
    pays into nothing, so no certificate exists - hence the setting in
    config.py, which is False.

    Flipped to True, self-employment tax becomes $0. Both are modelled.

    Not a saving to reach for: French self-employed contributions for a
    service business run roughly 21-24% OF REVENUE, which can exceed 15.3%
    of PROFIT. Registering is about being compliant where she lives.

BOTH BUSINESSES, ONE CALCULATION
    Self-employment tax is charged on combined net earnings, and the FEIE
    and Social Security caps are combined limits. A single-member LLC is a
    disregarded entity, so Hostlyft and the separate Marcus work land on
    the same return. Reporting them apart while taxing them together is the
    whole reason for the `business` column.
"""

from taxlib import config, constants_2026 as k, db


def _round(value):
    return round(float(value or 0), 2)


# ===========================================================================
#  SELF-EMPLOYMENT TAX
# ===========================================================================

def self_employment_tax(net_profit, certificate_of_coverage=False):
    """
    Work it out, and show every step.

    Returns a dictionary rather than a number, because a single figure with
    no working behind it cannot be checked - and this is the figure the
    whole tool exists to produce.
    """
    steps = []

    if certificate_of_coverage:
        return {
            "total": 0.0, "taxable_base": 0.0, "social_security": 0.0,
            "medicare": 0.0, "additional_medicare": 0.0,
            "steps": ["A French Certificate of Coverage is on file, so the "
                      "US-France totalization agreement assigns you to French "
                      "coverage and US self-employment tax is $0."],
        }

    if net_profit <= 0:
        return {"total": 0.0, "taxable_base": 0.0, "social_security": 0.0,
                "medicare": 0.0, "additional_medicare": 0.0,
                "steps": ["No net profit, so no self-employment tax."]}

    base = _round(net_profit * k.SE_TAXABLE_SHARE)
    steps.append(f"Only {k.SE_TAXABLE_SHARE:.2%} of profit is subject to it "
                 f"(§1402(a)(12)): ${net_profit:,.2f} x "
                 f"{k.SE_TAXABLE_SHARE} = ${base:,.2f}")

    # Social Security stops at the wage base; Medicare never does.
    ss_base = min(base, k.SOCIAL_SECURITY_WAGE_BASE)
    social_security = _round(ss_base * k.SE_SOCIAL_SECURITY_RATE)
    if ss_base < base:
        steps.append(f"Social Security applies only to the first "
                     f"${k.SOCIAL_SECURITY_WAGE_BASE:,}: "
                     f"${ss_base:,.2f} x {k.SE_SOCIAL_SECURITY_RATE} "
                     f"= ${social_security:,.2f}")
    else:
        steps.append(f"Social Security at {k.SE_SOCIAL_SECURITY_RATE:.1%}: "
                     f"${ss_base:,.2f} x {k.SE_SOCIAL_SECURITY_RATE} "
                     f"= ${social_security:,.2f}  (under the "
                     f"${k.SOCIAL_SECURITY_WAGE_BASE:,} cap)")

    medicare = _round(base * k.SE_MEDICARE_RATE)
    steps.append(f"Medicare at {k.SE_MEDICARE_RATE:.1%}, with no cap: "
                 f"${base:,.2f} x {k.SE_MEDICARE_RATE} = ${medicare:,.2f}")

    additional = 0.0
    over = base - k.ADDITIONAL_MEDICARE_THRESHOLD_MFS
    if over > 0:
        additional = _round(over * k.ADDITIONAL_MEDICARE_RATE)
        steps.append(f"Additional Medicare Tax of "
                     f"{k.ADDITIONAL_MEDICARE_RATE:.1%} above "
                     f"${k.ADDITIONAL_MEDICARE_THRESHOLD_MFS:,} "
                     f"(the MFS threshold, NOT $200,000): "
                     f"${over:,.2f} x {k.ADDITIONAL_MEDICARE_RATE} "
                     f"= ${additional:,.2f}")
    else:
        steps.append(f"No Additional Medicare Tax - that starts above "
                     f"${k.ADDITIONAL_MEDICARE_THRESHOLD_MFS:,}")

    total = _round(social_security + medicare + additional)
    steps.append(f"Self-employment tax = ${total:,.2f}")

    return {"total": total, "taxable_base": base,
            "social_security": social_security, "medicare": medicare,
            "additional_medicare": additional, "steps": steps}


# ===========================================================================
#  INCOME TAX
# ===========================================================================

def tax_on_brackets(taxable, brackets=None):
    """Ordinary bracket arithmetic, from the bottom up."""
    brackets = brackets or k.MFS_BRACKETS
    if taxable <= 0:
        return 0.0

    tax, low = 0.0, 0
    for limit, rate, _base in brackets:
        top = taxable if limit is None else min(taxable, limit)
        if top > low:
            tax += (top - low) * rate
        if limit is not None and taxable <= limit:
            break
        low = limit or low
    return _round(tax)


def income_tax(net_profit, half_se_tax, feie_applies=True,
               feie_cap=None, standard_deduction=None):
    """
    US income tax, with the exclusion applied and the stacking rule above it.

    THE STACKING RULE (§911(f)) matters only if profit exceeds the cap. The
    excess is NOT taxed from the bottom bracket up as though the excluded
    income never existed - it is taxed at the rates that would have applied
    with it. Ignoring that would understate the bill on any income above
    $132,900.
    """
    feie_cap = k.FEIE_CAP if feie_cap is None else feie_cap
    standard_deduction = (k.STANDARD_DEDUCTION_MFS if standard_deduction is None
                          else standard_deduction)
    steps = []

    if not feie_applies:
        taxable = max(0.0, net_profit - half_se_tax - standard_deduction)
        steps.append(f"No exclusion claimed. Taxable income = "
                     f"${net_profit:,.2f} - ${half_se_tax:,.2f} (half the "
                     f"self-employment tax) - ${standard_deduction:,.2f} "
                     f"(standard deduction) = ${taxable:,.2f}")
        tax = tax_on_brackets(taxable)
        steps.append(f"Income tax on ${taxable:,.2f} = ${tax:,.2f}")
        return {"total": tax, "excluded": 0.0, "taxable": taxable,
                "steps": steps}

    excluded = _round(min(net_profit, feie_cap))
    steps.append(f"Foreign Earned Income Exclusion (Form 2555): "
                 f"${excluded:,.2f} of ${net_profit:,.2f} is excluded "
                 f"(the cap is ${feie_cap:,})")

    if net_profit <= feie_cap:
        steps.append("All of it is excluded, so US income tax is $0.")
        steps.append("You still file Form 1040 and Form 2555 - owing nothing "
                     "is not the same as filing nothing.")
        return {"total": 0.0, "excluded": excluded, "taxable": 0.0,
                "steps": steps}

    # Above the cap: the excess is taxed at the rates it would have met had
    # nothing been excluded.
    excess = _round(net_profit - feie_cap)
    steps.append(f"${excess:,.2f} is above the cap and stays taxable.")

    # Deductions allocable to excluded income are disallowed (§911(d)(6)),
    # so only the share of the half-SE-tax deduction belonging to the
    # taxable part may be used.
    taxable_share = excess / net_profit if net_profit else 0
    allowed_half_se = _round(half_se_tax * taxable_share)
    steps.append(f"Only the part of the half-self-employment-tax deduction "
                 f"belonging to the taxable share is allowed (§911(d)(6)): "
                 f"${half_se_tax:,.2f} x {taxable_share:.4f} = "
                 f"${allowed_half_se:,.2f}")

    taxable = max(0.0, excess - allowed_half_se - standard_deduction)
    steps.append(f"Taxable income = ${excess:,.2f} - "
                 f"${allowed_half_se:,.2f} - ${standard_deduction:,.2f} = "
                 f"${taxable:,.2f}")

    # §911(f): tax the total, then subtract tax on the excluded amount.
    tax_on_everything = tax_on_brackets(taxable + excluded)
    tax_on_excluded = tax_on_brackets(excluded)
    tax = _round(max(0.0, tax_on_everything - tax_on_excluded))
    steps.append(f"Stacking rule (§911(f)): tax on "
                 f"${taxable + excluded:,.2f} is "
                 f"${tax_on_everything:,.2f}, less tax on the excluded "
                 f"${excluded:,.2f} which is ${tax_on_excluded:,.2f}, "
                 f"leaving ${tax:,.2f}")
    steps.append("The excess is taxed at the rates it would have met if "
                 "nothing had been excluded - not from the bottom bracket up.")

    return {"total": tax, "excluded": excluded, "taxable": taxable,
            "steps": steps}


# ===========================================================================
#  PUTTING IT TOGETHER
# ===========================================================================

def estimate(net_profit, settings=None):
    """The whole calculation, with the working for every step."""
    settings = settings or config.SETTINGS
    certificate = bool(settings.get("certificate_of_coverage"))
    feie = settings.get("relief_method", "FEIE") == "FEIE" and \
        settings.get("bona_fide_resident", False)

    se = self_employment_tax(net_profit, certificate_of_coverage=certificate)
    half_se = _round(se["total"] / 2)
    it = income_tax(net_profit, half_se, feie_applies=feie)

    total = _round(se["total"] + it["total"])
    return {
        "net_profit": _round(net_profit),
        "self_employment_tax": se,
        "income_tax": it,
        "half_se_deduction": half_se,
        "total": total,
        "effective_rate": (total / net_profit) if net_profit > 0 else 0.0,
    }


def quarterly(total_tax, paid_so_far=0.0):
    """What to set aside per remaining quarter."""
    return _round(max(0.0, total_tax - paid_so_far) / 4)


def from_database(connection, tax_year, settings=None):
    """Run the estimate against what is actually recorded."""
    totals = db.totals(connection, tax_year)
    result = estimate(totals["net_profit_usd"], settings)
    result["totals"] = totals
    return result
