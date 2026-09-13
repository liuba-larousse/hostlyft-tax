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

import datetime as _dt

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


def pending_contractor_jars(connection, tax_year, today=None):
    """
    Contractor money sitting in jars that will be deductible once paid out.

    HER INSTRUCTION, 2026-09-12: estimate tax on the assumption that these
    jars ARE emptied before 31 December, because they will be. That is a
    reasonable basis for an ESTIMATE - the whole point of a quarterly
    estimate is to approximate the final bill, and if the money goes out in
    December the final bill is genuinely lower. Paying tax all year on
    money she is going to deduct anyway is just lending the IRS cash.

    IT IS A PROJECTION, AND IT IS CONDITIONAL. Nothing has been paid yet.
    Finding 4 of the plan still holds exactly as written: a jar is a label
    inside her own Wise account, and allocating to one deducts nothing. If
    the money is still sitting there on 31 December, the deduction falls
    into the FOLLOWING year and the real bill is the higher figure. So both
    numbers are computed and both are shown, always.

    ONLY CONTRACTOR JARS - and this is the part that is easy to get wrong.
    Her own jar is an owner draw whenever it is paid. A draw is never
    deductible, at any date, so including it would understate the tax
    rather than time it differently. Jars carry a `person` only when they
    belong to somebody on the roster; hers and the admin pots do not.

    Once the tax year is over the assumption cannot come true any more, so
    it stops being applied and the real figure stands on its own.
    """
    # `today` arrives as a date from some callers and an ISO string from
    # others - the home office path passes a string. Accept both rather
    # than making every caller convert.
    today = today or _dt.date.today()
    if isinstance(today, str):
        today = _dt.date.fromisoformat(today[:10])
    if today.year > tax_year:
        return {"usd": 0.0, "rows": [], "still_possible": False}

    rows = [row for row in db.latest_jar_balances(connection)
            if row["person"] and (row["amount_usd"] or 0) > 0]
    return {
        "usd": db.round_money(sum(row["amount_usd"] or 0 for row in rows)),
        "rows": rows,
        "still_possible": True,
    }


def from_database(connection, tax_year, settings=None,
                  include_home_office=True, today=None, through=None):
    """
    Run the estimate against what is actually recorded.

    The home office is applied here rather than inside db.totals because it
    is not a transaction. Nothing was paid to anybody for it - it is a
    share of costs you were paying anyway - so it has no row in `expenses`
    and must not be given one. It reduces net profit at the point the tax
    is worked out.
    """
    from taxlib import home_office as ho

    totals = db.totals(connection, tax_year, through=through)
    profit_before = totals["net_profit_usd"]

    # A DEDUCTION CANNOT BE CLAIMED BEFORE IT HAPPENS.
    #
    # When a period cut-off is given, the home office must be pro-rated to
    # the months inside that period. Applied at its full-year value to a
    # March computation it took Q1 profit down to $840 - and with the jar
    # payout on top, almost to nothing.
    # NEVER ASK THE HOME OFFICE ABOUT THE FUTURE. It pro-rates on monthly
    # exchange rates, and a cut-off of 31 December needs rates for months
    # that have not happened - which fails, and the deduction silently
    # became $0 on the Q4 line. Capped at today: the deduction claimable so
    # far, which is the honest figure and grows as the year does.
    _today = today or _dt.date.today()
    if isinstance(_today, str):
        _today = _dt.date.fromisoformat(_today[:10])
    as_of = through or today
    if through:
        cut = (_dt.date.fromisoformat(through[:10])
               if isinstance(through, str) else through)
        as_of = min(cut, _today).isoformat()

    office, office_problem = None, None
    if include_home_office:
        try:
            office = ho.best(connection, tax_year, net_profit=profit_before,
                             today=as_of)
        except ho.HomeOfficeNotClaimed as problem:
            office_problem = str(problem)
        except Exception as problem:      # noqa: BLE001 - reported, not raised
            # A missing exchange rate must not stop the tax being estimated.
            office_problem = f"The home office could not be worked out: {problem}"

    claimed = office["claimed_usd"] if office else 0.0
    net_profit = db.round_money(profit_before - claimed)

    # The jar projection, applied like the home office: not a transaction,
    # so it has no row in `expenses` and must never be given one.
    active = (settings or config.SETTINGS).get(
        "assume_contractor_jars_paid_by_year_end", True)
    jars = pending_contractor_jars(connection, tax_year, today=today)

    # THE JAR DEDUCTION APPLIES TO EVERY PERIOD, NOT JUST TO DECEMBER.
    #
    # Strictly the money leaves in December, so a quarter ending in August
    # has not yet seen it. But she has stated twice, as a fact, that it WILL
    # be paid this year - and an estimated payment exists to approximate the
    # final bill. Leaving the deduction out of the earlier quarters would
    # have her pay tax now on a deduction she is certain to take, and
    # reclaim it in April. That is precisely the overpayment she asked to
    # stop.
    #
    # The risk it carries is the one the 1 December alert already chases: if
    # the jars are still full at year end, these estimates were low.
    projected_profit = net_profit
    if active and jars["usd"]:
        projected_profit = db.round_money(max(0.0, net_profit - jars["usd"]))

    # BOTH are computed, every time. The projected figure is what she plans
    # and pays quarterly against; the actual figure is what she owes if the
    # jars are not emptied. Showing only one would hide the condition the
    # projection rests on.
    actual = estimate(net_profit, settings)
    result = estimate(projected_profit, settings) if active else dict(actual)

    result["totals"] = totals
    result["net_profit_before_home_office"] = profit_before
    result["home_office"] = office
    result["home_office_problem"] = office_problem
    result["home_office_usd"] = claimed

    result["through"] = through
    result["contractor_jars"] = jars
    result["jars_assumption_applied"] = bool(active and jars["usd"])
    result["net_profit_if_jars_stay"] = net_profit
    result["tax_if_jars_stay"] = actual["total"]
    result["tax_if_jars_paid"] = result["total"]
    result["jars_saving_usd"] = db.round_money(
        actual["total"] - result["total"])
    return result
