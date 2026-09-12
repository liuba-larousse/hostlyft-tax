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
