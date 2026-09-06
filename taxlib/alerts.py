"""
The reminders - Stage 10.

WHAT DECIDES WHETHER SOMETHING IS SENT

Three separate questions, kept separate on purpose:

  1. Is this alert DUE today?          the rules below
  2. Has it ALREADY been sent?         the alerts_sent table
  3. How does it reach her?            notify.py

Splitting them is what makes this testable without sending real email, and
what stops the same warning arriving every morning for three weeks until it
is ignored - which would be worse than not sending it at all.

NOTHING HERE INSTALLS A SCHEDULE. Every alert is designed to be run by hand
and to work out for itself whether today is the day. The schedule is Stage
13, on her main Mac.

WHY EACH ALERT EXISTS

  QUARTERLY   the payment deadlines. Missing one is a penalty, not a
              rounding error.
  FBAR        nothing else in her year prompts for it, the penalties are
              severe, and it is filed with FinCEN rather than the IRS so it
              is not caught by doing her tax return.
  JARS        money still in a jar on 31 December was never paid to anyone,
              so it is not deductible that year - but it is still gone from
              her point of view. Emptying the jars before year end converts
              it into a deduction.
  $600        the moment Katerina crosses $600 of withdrawals a 1099-NEC is
              owed, and the W-9 that makes it possible has to exist first.
  FORMS       a missing W-8BEN or W-9 is an exposure from the first dollar,
              with no threshold at all.
"""

from datetime import date, timedelta

from taxlib import config, constants_2026 as k, db, forms


# How many days before a deadline the reminder goes out. A week is enough to
# move money and still be early.
DAYS_BEFORE_DEADLINE = 7


class Alert:
    """One thing worth telling her about."""

    def __init__(self, key, kind, subject, short, body, urgent=False):
        self.key = key          # unique; what stops it being sent twice
        self.kind = kind        # 'quarterly' | 'fbar' | 'jars' | ...
        self.subject = subject  # the email subject line
        self.short = short      # the one line the desktop pop-up can fit
        self.body = body        # the full email
        self.urgent = urgent

    def __repr__(self):
        return f"<Alert {self.key}>"


def _today(today=None):
    if today is None:
        return date.today()
    if isinstance(today, str):
        return date.fromisoformat(today)
    return today


# ===========================================================================
#  1. QUARTERLY ESTIMATED TAX
# ===========================================================================

def quarterly_deadlines(year):
    """
    The four estimated-tax deadlines covering a tax year.

    The fourth is in JANUARY OF THE FOLLOWING YEAR - the payment for the
    last quarter of `year` is due 15 January of `year + 1`. Getting that
    wrong would silently drop a quarter.

    A deadline landing on a weekend or a federal holiday moves to the next
    business day. For 2026 all four fall on weekdays, so nothing shifts;
    the rule is noted here because a later year will need it.
    """
    return [
        (date(year, 4, 15), f"Q1 {year}", f"1 January - 31 March {year}"),
        (date(year, 6, 15), f"Q2 {year}", f"1 April - 31 May {year}"),
        (date(year, 9, 15), f"Q3 {year}", f"1 June - 31 August {year}"),
        (date(year + 1, 1, 15), f"Q4 {year}",
         f"1 September - 31 December {year}"),
    ]


def quarterly_alerts(connection, today, tax_year):
    """A reminder in the week before each estimated-tax deadline."""
    out = []
    # Last year's Q4 deadline falls in January of this year, so both years'
    # schedules are checked - otherwise the January payment is never warned.
    for year in (tax_year - 1, tax_year):
        for due, label, covers in quarterly_deadlines(year):
            days = (due - today).days
            if not 0 <= days <= DAYS_BEFORE_DEADLINE:
                continue

            when = "today" if days == 0 else f"in {days} day{'' if days == 1 else 's'}"
            subject = f"Estimated tax due {when} - {label} ({due:%d %B %Y})"
            body = (
                f"{label} estimated tax payment is due on {due:%A %d %B %Y}"
                f" - {when}.\n\n"
                f"This payment covers {covers}.\n\n"
                "HOW TO PAY\n"
                "  IRS Direct Pay, free, no account needed:\n"
                "  https://www.irs.gov/payments/direct-pay\n"
                "  Choose 'Estimated Tax' and the 1040-ES form.\n\n"
                "HOW MUCH\n"
                "  Run  python scripts/calc_tax.py  for the current figure.\n"
                "  Almost all of it is self-employment tax; the Foreign\n"
                "  Earned Income Exclusion takes income tax to zero.\n\n"
                "THE SAFE HARBOUR\n"
                "  Paying 100% of LAST year's total tax protects you from\n"
                "  underpayment penalties no matter how this year turns out.\n"
                "  If this year ends up bigger than expected, you are not\n"
                "  penalised for having estimated from last year's figure.\n"
            )
            out.append(Alert(
                key=f"quarterly:{due.isoformat()}",
                kind="quarterly",
                subject=subject,
                short=f"{label} estimated tax due {when}.",
                body=body,
                urgent=days <= 2,
            ))
    return out


# ===========================================================================
#  2. FBAR
# ===========================================================================

# Late March, ahead of the 15 April deadline; and October, ahead of the
# automatic extension running out on the 15th.
FBAR_WINDOWS = [((3, 20), (3, 31), "march", date(1, 4, 15)),
                ((10, 1), (10, 8), "october", date(1, 10, 15))]


def fbar_alerts(connection, today, tax_year):
    """
    The FBAR reminder.

    THIS IS A PROMPT, NOT A TEST. It deliberately does not tell her whether
    she is over the $10,000 line, because the database cannot answer that
    honestly: FBAR asks for the highest COMBINED balance across ALL foreign
    accounts at ANY point in the year, and what is stored here is jar
    balances on the handful of days a sync happened to run. Her main Wise
    operating balance is not stored at all.

    Reporting "you are under $10,000" from that data would be a confident
    wrong answer about something carrying criminal penalties. So the alert
    shows what IS known, says plainly what is missing, and sends her to the
    one place that can answer it - her Wise statements.
    """
    out = []
    for (start, end, tag, deadline_template) in FBAR_WINDOWS:
        window_start = date(today.year, *start)
        window_end = date(today.year, *end)
        if not window_start <= today <= window_end:
            continue

        # FBAR reports the year that has ENDED.
        report_year = today.year - 1
        deadline = date(today.year, deadline_template.month,
                        deadline_template.day)

        jars = db.latest_jar_balances(connection)
        jar_total = sum(row["amount_usd"] or 0 for row in jars)
        observed = max((row["observed_on"] for row in jars), default=None)

        known = (f"  Jar balances last read on {observed}: "
                 f"${jar_total:,.2f}\n" if observed else
                 "  No jar balances have been recorded yet.\n")

        extended = " (the automatic extension)" if tag == "october" else ""
        body = (
            f"FBAR for {report_year} is due {deadline:%d %B %Y}{extended}.\n\n"
            "WHAT IT IS\n"
            "  FinCEN Form 114. If all your foreign financial accounts\n"
            "  ADDED TOGETHER were worth more than $10,000 at ANY moment\n"
            f"  during {report_year} - even for one day - you must file it.\n"
            "  Your Wise account is a foreign financial account.\n\n"
            "  It is filed with FinCEN, NOT the IRS, and doing your tax\n"
            "  return does not cover it. Nothing else will prompt you.\n"
            "  https://bsaefiling.fincen.treas.gov/\n\n"
            "  There is no tax to pay. It is a disclosure form. The\n"
            "  penalties for not filing are civil and can be criminal.\n\n"
            "YOU HAVE TO CHECK THIS YOURSELF - I CANNOT\n"
            "  The test is the HIGHEST combined balance at any point in\n"
            f"  {report_year}. This system only stores jar balances on the\n"
            "  days a sync ran, and does not store your main Wise balance\n"
            "  at all, so it cannot work that out.\n\n"
            "  What is on record here:\n"
            f"{known}\n"
            "  Do this: open Wise -> Statements, cover "
            f"1 January to 31 December {report_year}, and find the highest\n"
            "  combined balance across every currency and every jar.\n\n"
            "  If it ever topped $10,000, file. If it was close, file\n"
            "  anyway - there is no cost to filing and a real cost to\n"
            "  getting it wrong.\n"
        )
        out.append(Alert(
            key=f"fbar:{report_year}:{tag}",
            kind="fbar",
            subject=f"FBAR for {report_year} due {deadline:%d %B} - check your "
                    f"Wise balance history",
            short=f"FBAR for {report_year} due {deadline:%d %B}. Check your "
                  f"highest Wise balance.",
            body=body,
            urgent=(tag == "october"),
        ))
    return out


# ===========================================================================
#  3. MONEY STILL IN JARS ON 1 DECEMBER
# ===========================================================================

JARS_ALERT_FROM = (12, 1)
JARS_TARGET_DAY = 20      # empty by about the 20th, leaving room for delays


def jar_alerts(connection, today, tax_year):
    """
    From 1 December: what the money still sitting in jars will cost.

    The point people miss: a jar is a label inside her own Wise account, not
    a payment. Allocating to it deducts nothing. Only the withdrawal does.
    So money still in a jar on 31 December is taxed as her profit even
    though she thinks of it as already spoken for.
    """
    if (today.month, today.day) < JARS_ALERT_FROM:
        return []
    if today.month != 12:
        return []

    jars = db.latest_jar_balances(connection)
    # Only jars held for a team member. Her own admin/tax/fund jars are
    # hers either way and withdrawing from them changes nothing.
    owed = [row for row in jars if row["person"]]
    total = sum(row["amount_usd"] or 0 for row in owed)

    if total <= 0:
        return []

    cost = round(total * k.SE_TAXABLE_SHARE * k.SE_TAX_RATE, 2)
    days_left = JARS_TARGET_DAY - today.day
    observed = max((row["observed_on"] for row in owed), default="unknown")

    by_person = {}
    for row in owed:
        by_person[row["person"]] = (by_person.get(row["person"], 0)
                                    + (row["amount_usd"] or 0))
    breakdown = "\n".join(
        f"    {person:<26} ${amount:>10,.2f}"
        for person, amount in sorted(by_person.items(),
                                     key=lambda item: -item[1]))

    urgency = (f"About {days_left} days to the {JARS_TARGET_DAY}th."
               if days_left > 0 else
               "You are past the target date - transfers can take days to "
               "land, so do this now.")

    body = (
        f"${total:,.2f} is still sitting in team jars.\n"
        f"(Balances as last read on {observed}.)\n\n"
        f"{breakdown}\n\n"
        "WHY THIS COSTS YOU MONEY\n"
        "  A jar is a label inside your own Wise account, not a payment.\n"
        "  Moving money into one deducts nothing. Only the transfer OUT\n"
        "  to the person is deductible.\n\n"
        f"  Anything still in a jar on 31 December is taxed as your profit\n"
        f"  for {tax_year}, even though you think of it as already theirs.\n\n"
        f"  ${total:,.2f} left in the jars costs roughly ${cost:,.2f} in\n"
        f"  self-employment tax you would not otherwise pay\n"
        f"  ({k.SE_TAX_RATE:.1%} on {k.SE_TAXABLE_SHARE:.2%} of profit).\n\n"
        "WHAT TO DO\n"
        f"  Pay out what is genuinely owed before 31 December. {urgency}\n"
        "  Aim for the 20th so a slow transfer still lands in time.\n\n"
        "  Only pay what is actually owed. Paying someone early just to\n"
        "  move the deduction into this year is not a good reason, and the\n"
        "  money is gone either way.\n\n"
        "  Note: withdrawals also count toward the $600 that triggers a\n"
        "  1099-NEC for Katerina. Emptying her jar may cross that line.\n"
    )
    return [Alert(
        key=f"jars:{tax_year}",
        kind="jars",
        subject=f"${total:,.2f} still in jars - about ${cost:,.2f} of "
                f"avoidable tax",
        short=f"${total:,.2f} still in team jars. Pay out before 31 December.",
        body=body,
        urgent=today.day >= JARS_TARGET_DAY,
    )]


# ===========================================================================
#  4. THE $600 CONTRACTOR THRESHOLD
# ===========================================================================

def contractor_600_alerts(connection, today, tax_year, form_rows=None):
    """
    Katerina crossing $600 of WITHDRAWALS.

    Only withdrawals count. Money moved into her jar has not been paid to
    her and does not count, which is the whole reason the two are stored in
    different tables.

    The alert changes depending on whether her W-9 is on file, because that
    is what decides whether this is a form to fill in or a 24% withholding
    problem.
    """
    rows = form_rows if form_rows is not None else forms.review(
        connection, tax_year, today=today)

    out = []
    for row in rows:
        if not row["needs_1099"]:
            continue

        if not row["on_file"]:
            standing = (
                "  HER W-9 IS NOT ON FILE.\n"
                "  You need it to issue the 1099 at all - it carries the\n"
                "  taxpayer ID number that goes on the form. Until you have\n"
                "  it, 24% backup withholding applies to what you pay her.\n\n"
                "  Send her: https://www.irs.gov/pub/irs-pdf/fw9.pdf\n")
        elif not row["has_tin"]:
            standing = (
                "  HER W-9 IS ON FILE BUT HAS NO TAXPAYER ID NUMBER.\n"
                "  Without it the form cannot be issued and 24% backup\n"
                "  withholding applies. Go back and ask for the number.\n")
        else:
            standing = ("  Her W-9 is on file with a taxpayer ID number, so\n"
                        "  you have what you need to issue the form.\n")

        body = (
            f"{row['person']} has passed $600 of withdrawals for {tax_year}.\n\n"
            f"  Withdrawn so far   ${row['withdrawn_usd']:,.2f}\n"
            f"  Payments           {row['withdrawals']}\n"
            f"  Most recent        {row['latest_withdrawal']}\n\n"
            "WHAT THIS MEANS\n"
            f"  A 1099-NEC is now required for {tax_year}. She is a US\n"
            "  citizen, which is what decides this - dual nationality and\n"
            "  living abroad do not change it.\n\n"
            "  Due to her by 31 January, and to the IRS by 31 January.\n\n"
            f"{standing}\n"
            "WHAT COUNTS TOWARD THE $600\n"
            "  Only money actually transferred out to her. Money sitting\n"
            "  in her jar is still yours and does not count - though it\n"
            "  will the moment you pay it out.\n"
        )
        out.append(Alert(
            key=f"contractor600:{row['person']}:{tax_year}",
            kind="contractor600",
            subject=f"{row['person']} passed $600 - 1099-NEC required for "
                    f"{tax_year}",
            short=f"{row['person']} passed $600 "
                  f"(${row['withdrawn_usd']:,.2f}). 1099-NEC required.",
            body=body,
            urgent=not row["on_file"],
        ))
    return out


# ===========================================================================
#  5. MISSING FORMS  (Stage 12 feeding Stage 10)
# ===========================================================================

def form_alerts(connection, today, tax_year, form_rows=None):
    """
    Anyone whose W-9 or W-8BEN is missing, wrong or expired.

    Separate from the $600 alert because it has no threshold: the form is
    owed from the first dollar, and for the three non-US contractors it is
    the ONLY paperwork there is. It is also what establishes that no 1099 is
    owed - so "under $600" is not a reason to skip it.
    """
    rows = form_rows if form_rows is not None else forms.review(
        connection, tax_year, today=today)
    problems = forms.outstanding(rows)
    if not problems:
        return []

    lines = ["\n".join(forms.report(rows, tax_year))]
    lines.append("WHERE TO GET THE FORMS")
    lines.append("  W-9     https://www.irs.gov/pub/irs-pdf/fw9.pdf")
    lines.append("  W-8BEN  https://www.irs.gov/pub/irs-pdf/fw8ben.pdf")
    lines.append("")
    lines.append("  Neither is filed with the IRS. You collect them and keep")
    lines.append("  them. They are what you produce if anyone asks why no")
    lines.append("  tax was withheld.")
    lines.append("")
    lines.append("  Once one arrives, record it:")
    lines.append("    python scripts/check_forms.py --received \"Full Name\" "
                 "--on YYYY-MM-DD")

    worst = problems[0]
    return [Alert(
        key=f"forms:{tax_year}",
        kind="forms",
        subject=f"{len(problems)} contractor form"
                f"{'' if len(problems) == 1 else 's'} outstanding for "
                f"{tax_year}",
        short=f"{len(problems)} contractor form"
              f"{'' if len(problems) == 1 else 's'} missing. "
              f"Worst: {worst['person']}.",
        body="\n".join(lines),
        urgent=any(row["status"] in ("missing_over_600", "expired", "no_tin")
                   for row in problems),
    )]


# ===========================================================================
#  PUTTING IT TOGETHER
# ===========================================================================

def due(connection, today=None, tax_year=None):
    """
    Every alert that is due today, before checking what has been sent.

    The forms review is worked out once and passed down, so the $600 alarm
    and the missing-forms alert cannot disagree with each other about
    whether a W-9 exists.
    """
    today = _today(today)
    tax_year = tax_year or config.SETTINGS.get("tax_year") or today.year

    form_rows = forms.review(connection, tax_year, today=today)

    alerts = []
    alerts += quarterly_alerts(connection, today, tax_year)
    alerts += fbar_alerts(connection, today, tax_year)
    alerts += jar_alerts(connection, today, tax_year)
    alerts += contractor_600_alerts(connection, today, tax_year, form_rows)
    alerts += form_alerts(connection, today, tax_year, form_rows)
    return alerts


def unsent(connection, alerts):
    """The ones that have not gone out before."""
    return [alert for alert in alerts
            if not db.alert_already_sent(connection, alert.key)]
