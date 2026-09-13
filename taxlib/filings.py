"""
What has to be filed, when, and where to get the form.

Every date here is for a calendar-year filer. Two of them are NOT the dates
most guidance gives, and both differences are in her favour:

  1. SHE LIVES ABROAD, so Form 1040 gets an AUTOMATIC two-month extension
     to 15 June. Nothing has to be requested for it - it applies because on
     the normal due date she is living outside the United States with her
     main place of business outside it.

     THE TRAP: it extends the FILING, not the PAYING. Interest still runs
     from 15 April on anything unpaid. So the extension is worth having and
     is not worth relying on.

  2. The FBAR is filed with FinCEN, NOT the IRS, and its extension to 15
     October is automatic too - no form, no request.

Estimated-tax quarters are the IRS's own, which are not three months each:
Q2 is two months and Q4 is four. See taxlib/distribution.py.
"""

import datetime as dt

from taxlib import config

IRS = "https://www.irs.gov"

# (label, when it is due, what it is, where to get it)
FORMS = [
    {
        "form": "Form 1040-ES",
        "what": "Estimated tax payment vouchers - four a year",
        "due": "15 Apr, 15 Jun, 15 Sep, 15 Jan",
        "who": "IRS",
        "url": f"{IRS}/forms-pubs/about-form-1040-es",
        "note": ("This is the one with money attached. Self-employment tax "
                 "is the whole bill; income tax is $0 under the FEIE."),
    },
    {
        "form": "Form 1040",
        "what": "The annual return itself",
        "due": "15 June (automatic 2-month extension - you live abroad)",
        "who": "IRS",
        "url": f"{IRS}/forms-pubs/about-form-1040",
        "note": ("Normally 15 April. Living abroad moves the FILING to 15 "
                 "June automatically - no request needed. It does NOT move "
                 "the PAYING: interest runs from 15 April on anything "
                 "unpaid. Form 4868 pushes filing to 15 October if needed."),
    },
    {
        "form": "Schedule C",
        "what": "Profit or loss from the business",
        "due": "with Form 1040",
        "who": "IRS",
        "url": f"{IRS}/forms-pubs/about-schedule-c-form-1040",
        "note": ("Gross receipts, then expenses by line. Marcus and Hostlyft "
                 "can go on one Schedule C or two - a decision to make "
                 "before filing. The tax is the same either way."),
    },
    {
        "form": "Schedule SE",
        "what": "Self-employment tax",
        "due": "with Form 1040",
        "who": "IRS",
        "url": f"{IRS}/forms-pubs/about-schedule-se-form-1040",
        "note": ("Computed on BOTH businesses combined. This is where your "
                 "actual bill comes from - the FEIE does not touch it."),
    },
    {
        "form": "Form 2555",
        "what": "Foreign Earned Income Exclusion",
        "due": "with Form 1040",
        "who": "IRS",
        "url": f"{IRS}/forms-pubs/about-form-2555",
        "note": ("What makes your income tax $0. You must FILE it to claim "
                 "it - owing nothing is not the same as filing nothing."),
    },
    {
        "form": "Form 8829",
        "what": "Home office, actual-cost method",
        "due": "with Schedule C",
        "who": "IRS",
        "url": f"{IRS}/forms-pubs/about-form-8829",
        "note": ("Needed because the actual method beats simplified for you. "
                 "As a renter you skip the depreciation part entirely."),
    },
    {
        "form": "Form 4562",
        "what": "Section 179 election - expensing equipment in one year",
        "due": "with Schedule C",
        "who": "IRS",
        "url": f"{IRS}/forms-pubs/about-form-4562",
        "note": ("Needed for the work laptop: at $3,905.65 it is over the "
                 "$2,500 de minimis safe harbour, so it cannot simply be "
                 "expensed. Section 179 writes it off in full this year "
                 "instead of depreciating it over several. Requires more "
                 "than 50% business use - it is 100%."),
    },
    {
        "form": "FinCEN Form 114 (FBAR)",
        "what": "Foreign bank accounts, if they ever totalled over $10,000",
        "due": "15 April, automatic extension to 15 October",
        "who": "FinCEN - NOT the IRS",
        "url": "https://bsaefiling.fincen.treas.gov/main.html",
        "note": ("Wise is a foreign account and your jars count toward the "
                 "$10,000. It is the HIGHEST balance at any moment in the "
                 "year that matters, not the year-end one. Filed on FinCEN's "
                 "own site, not with your return. Penalties are severe."),
    },
    {
        "form": "Form 1099-NEC",
        "what": "Reports what you paid Katerina",
        "due": "31 January",
        "who": "To Katerina AND to the IRS",
        "url": f"{IRS}/forms-pubs/about-form-1099-nec",
        "note": ("Only Katerina - she is the only US person on the roster. "
                 "Triggered by $600 of WITHDRAWALS, not allocations. You "
                 "need her W-9 with a TIN first, or 24% must be withheld."),
    },
    {
        "form": "Form W-9",
        "what": "Collected from Katerina - kept, never filed",
        "due": "before you pay her, ideally",
        "who": "You keep it",
        "url": f"{IRS}/forms-pubs/about-form-w-9",
        "note": ("This is what you produce if anyone asks why no tax was "
                 "withheld. Without a TIN on it, 24% backup withholding "
                 "applies to what you have already paid her."),
    },
    {
        "form": "Form W-8BEN",
        "what": "Collected from each foreign contractor - kept, never filed",
        "due": "from the first dollar; valid 3 years",
        "who": "You keep it",
        "url": f"{IRS}/forms-pubs/about-form-w-8ben",
        "note": ("Ayoka, Olaide, Jane and Sunniva. No 1099 and no $600 "
                 "threshold applies to them - work done outside the US by a "
                 "non-US person is foreign-source. The form is the whole "
                 "obligation."),
    },
]

# Estimated tax: the quarter, the period it covers, and when it is due.
ESTIMATED_QUARTERS = [
    (1, "Jan - Mar", (4, 15)),
    (2, "Apr - May", (6, 15)),
    (3, "Jun - Aug", (9, 15)),
    (4, "Sep - Dec", (1, 15)),      # due in the FOLLOWING January
]


def due_date(quarter, tax_year):
    """When quarter `quarter` of `tax_year` has to be paid."""
    month, day = dict((q, d) for q, _, d in ESTIMATED_QUARTERS)[quarter]
    year = tax_year + 1 if quarter == 4 else tax_year
    return dt.date(year, month, day)


def quarters(tax_year, today=None):
    """Each quarter with its period, due date and how it stands."""
    today = today or dt.date.today()
    out = []
    for quarter, period, _ in ESTIMATED_QUARTERS:
        due = due_date(quarter, tax_year)
        days = (due - today).days
        out.append({
            "quarter": quarter,
            "period": period,
            "due": due,
            "days_away": days,
            "overdue": days < 0,
        })
    return out


def filing_deadline(tax_year):
    """
    When the return is due for someone living abroad.

    The automatic two-month extension is a real thing and is not requested -
    it applies because she is outside the US on the normal due date.
    """
    return {
        "normal": dt.date(tax_year + 1, 4, 15),
        "abroad": dt.date(tax_year + 1, 6, 15),
        "with_4868": dt.date(tax_year + 1, 10, 15),
        "interest_from": dt.date(tax_year + 1, 4, 15),
    }


def quarter_for_payment(paid_on):
    """
    Which quarter a payment made on this date is most likely paying.

    A guess, and it says so wherever it is shown. Payments are matched to
    the next deadline they fall before, which is what paying on time looks
    like:

        16 Jan - 15 Apr  ->  Q1 of that year
        16 Apr - 15 Jun  ->  Q2
        16 Jun - 15 Sep  ->  Q3
        16 Sep - 31 Dec  ->  Q4 of that year
         1 Jan - 15 Jan  ->  Q4 of the PREVIOUS year

    A late payment lands on the wrong quarter and she can correct it by
    hand. Guessing here is cheap to fix; refusing to guess would leave a
    detected payment sitting against nothing at all.
    """
    if isinstance(paid_on, str):
        paid_on = dt.date.fromisoformat(paid_on[:10])
    year = paid_on.year
    if paid_on <= dt.date(year, 1, 15):
        return year - 1, 4
    if paid_on <= dt.date(year, 4, 15):
        return year, 1
    if paid_on <= dt.date(year, 6, 15):
        return year, 2
    if paid_on <= dt.date(year, 9, 15):
        return year, 3
    return year, 4


# The share of the year's required tax that must be paid by each deadline.
# Level quarters: a quarter of it each time.
CUMULATIVE_SHARE = {1: 0.25, 2: 0.50, 3: 0.75, 4: 1.00}

# Pay at least this much of the year's tax and no underpayment penalty
# applies. The other safe harbour - 100% of LAST year's total tax - protects
# her regardless of how this year lands, and is the one to lean on if the
# year ends bigger than expected.
REQUIRED_SHARE_OF_YEAR = 0.90


def installments(tax_for_year, paid_by_quarter=None, today=None,
                 tax_year=None):
    """
    What each voucher should say, recomputed from the year SO FAR.

    WHY NOT SIMPLY A QUARTER OF THE TOTAL, WHICH IS WHAT THIS USED TO DO
        Her question, and she is right. Dividing the tax on income received
        SO FAR by four treats a part-year figure as the whole year. Income
        keeps arriving, the annual tax keeps rising, and four equal
        payments of a number computed in March would end the year short.

        So each voucher is worked out as: the share of the year's tax that
        must be paid by THAT deadline, less whatever has already gone. A
        quarter where earnings jumped produces a bigger voucher on its own,
        and a missed quarter is caught up by the next one rather than
        quietly forgotten.

        THIS ONLY WORKS IF IT IS RE-RUN EACH QUARTER. That is the point of
        it - the figure is a snapshot of what is known today, and what is
        known changes. scripts/fill_1040es.py recomputes before it fills.

    The required annual payment is 90% of the year's tax. The other safe
    harbour - 100% of last year's total - is not modelled here because her
    2025 figures are not in the database; it is mentioned wherever this is
    shown, because it is the stronger protection if the year ends big.
    """
    paid_by_quarter = paid_by_quarter or {}
    required_year = round(tax_for_year * REQUIRED_SHARE_OF_YEAR, 2)

    rows, paid_so_far = [], 0.0
    for quarter in (1, 2, 3, 4):
        due = required_year * CUMULATIVE_SHARE[quarter]
        already = paid_by_quarter.get(quarter, 0.0)
        voucher = max(0.0, round(due - paid_so_far, 2))
        paid_so_far += already
        rows.append({
            "quarter": quarter,
            "cumulative_required": round(due, 2),
            "paid": round(already, 2),
            "voucher": voucher,
            "period": dict((q, p) for q, p, _ in ESTIMATED_QUARTERS)[quarter],
            "due": due_date(quarter, tax_year) if tax_year else None,
        })
    return {"required_year": required_year, "quarters": rows}


# The last day of income that counts toward each estimated-tax quarter.
QUARTER_ENDS = {1: (3, 31), 2: (5, 31), 3: (8, 31), 4: (12, 31)}


def period_end(quarter, tax_year):
    """The cut-off date for a quarter's income - NOT today's date."""
    month, day = QUARTER_ENDS[quarter]
    return dt.date(tax_year, month, day)


def quarterly_plan(connection, tax_year, paid_by_quarter=None):
    """
    What each voucher should say - THE one place that works it out.

    Two tabs and a PDF all need this figure, and when the Summary tab
    computed its own version of the tax it printed a number no other tab
    agreed with. The same trap was waiting here: fill_1040es.py said
    $1,953.80 for Q3 while the Tax Calendar said $2,538.38, because one
    projected the year and the other accrued the period.

    The method is hers: pay the tax that has actually accrued by the end of
    each quarter, less what has already been paid. No forecast of income
    that has not arrived.

    EACH QUARTER IS COMPUTED ON ITS OWN CUT-OFF - Q3 ends 31 AUGUST, not
    today. Income that arrives in September belongs to Q4, and counting it
    in Q3 pays its tax four months early.
    """
    from taxlib import tax as _tax

    paid_by_quarter = paid_by_quarter or {}
    rows, paid_running = [], 0.0

    accrued = {}
    for quarter in (1, 2, 3, 4):
        end = period_end(quarter, tax_year).isoformat()
        accrued[quarter] = round(
            _tax.from_database(connection, tax_year,
                               through=end).get("total") or 0.0, 2)

    for quarter in (1, 2, 3, 4):
        voucher = max(0.0, round(accrued[quarter] - paid_running, 2))
        already = round(paid_by_quarter.get(quarter, 0.0), 2)
        paid_running += already
        rows.append({
            "quarter": quarter,
            "period": dict((q, p) for q, p, _ in ESTIMATED_QUARTERS)[quarter],
            "period_end": period_end(quarter, tax_year),
            "due": due_date(quarter, tax_year),
            "accrued": accrued[quarter],
            "paid": already,
            "voucher": voucher,
        })
    return {"year_tax": accrued[4], "quarters": rows}


def current_quarter(tax_year, today=None):
    """
    The quarter we are standing INSIDE right now.

    Not the one being filed - that is quarter_to_distribute(). On 13
    September the estimate being paid is Q3 (June-August), but the quarter
    currently running is Q4, which began on 1 September.
    """
    today = today or dt.date.today()
    for quarter in (1, 2, 3, 4):
        if today <= period_end(quarter, tax_year):
            return quarter
    return 4


def position(connection, tax_year, paid_by_quarter=None, today=None):
    """
    Where she stands: this quarter so far, and what is behind it.

    The running quarter's figure is the tax accrued SINCE the last cut-off -
    what this quarter has added on its own, not the year to date. It is
    incomplete by definition and grows until the quarter closes.
    """
    from taxlib import tax as _tax

    today = today or dt.date.today()
    quarter = current_quarter(tax_year, today)
    plan = quarterly_plan(connection, tax_year, paid_by_quarter)

    to_today = round(_tax.from_database(
        connection, tax_year, through=today.isoformat()).get("total") or 0.0, 2)
    previous = [row for row in plan["quarters"] if row["quarter"] < quarter]
    to_last_cutoff = previous[-1]["accrued"] if previous else 0.0

    return {
        "quarter": quarter,
        "period": dict((q, p) for q, p, _ in ESTIMATED_QUARTERS)[quarter],
        "due": due_date(quarter, tax_year),
        "accrued_this_quarter": round(to_today - to_last_cutoff, 2),
        "past": previous,

        # NOT the sum of the vouchers. Each voucher already carries the
        # unpaid amount of every quarter before it, so adding them counted
        # Q1 three times and produced $4,235.06 where the truth was
        # $2,538.38. What is genuinely outstanding is the tax accrued by the
        # last CLOSED quarter, less everything paid.
        "outstanding": round(max(0.0, to_last_cutoff
                                 - sum(row["paid"] for row in previous)), 2),
        "accrued_to_last_cutoff": round(to_last_cutoff, 2),
        "paid_so_far": round(sum(row["paid"] for row in previous), 2),
    }
