"""
Contractor tax forms - Stage 12.

WHAT THIS STAGE IS ACTUALLY FOR

The money side is already handled: Stage 6 records what each person was
paid, and Stage 9 deducts it. This stage covers the paperwork that has to
exist alongside those payments, and it is a separate risk from the money.

There are two different obligations, and only one of them depends on how
much someone was paid:

  COLLECTING THE FORM      applies to every contractor from the first
                           dollar. There is no threshold. A missing W-8BEN
                           on a $5,000 contractor is a real exposure even
                           though no 1099 is ever owed.

  ISSUING A 1099-NEC       applies only to Katerina, and only once her
                           WITHDRAWALS reach $600 in a calendar year.

Confusing the two is the easy mistake: it is tempting to think nobody under
$600 needs anything. The opposite is true - the form is what establishes
that no 1099 is owed in the first place.

WHY A W-8BEN IS THE ONE THAT LAPSES

A W-9 is good until something about the person changes. A W-8BEN expires on
the last day of the third calendar year after signing. An expired one is
worth no more than a missing one, and nothing else in this system would
notice - so it is checked here.
"""

from datetime import date

from taxlib import config, db


# How far ahead a W-8BEN expiry is worth mentioning. A W-8BEN always lapses
# on 31 December, so anything under a year means "this is the year to
# re-collect it" - it lines up with the December review rather than raising
# something in March that cannot be acted on usefully yet.
EXPIRY_WARNING_DAYS = 365


# Ranked worst first. Used for sorting and for deciding whether a run has
# anything worth interrupting her for.
SEVERITY = {
    "missing_over_600": 0,   # no form, and the money is past the 1099 line
    "expired": 1,            # W-8BEN lapsed - as bad as never collected
    "missing": 2,            # no form on file at all
    "no_tin": 3,             # W-9 arrived without a taxpayer ID -> 24% held
    "expiring": 4,           # W-8BEN lapses within the year
    "december_check": 5,     # asked for explicitly, regardless of amount
    "ok": 9,
}


def _today(today=None):
    """Today, or a fixed date passed in by a test."""
    if today is None:
        return date.today()
    if isinstance(today, str):
        return date.fromisoformat(today)
    return today


def review(connection, tax_year=None, today=None):
    """
    The paperwork position for everyone on the roster.

    Returns one dictionary per person, worst problem first. Read-only -
    it decides nothing and sends nothing; `check_forms.py` prints it and
    `alerts.py` decides what is worth a notification.
    """
    today = _today(today)
    tax_year = tax_year or today.year

    money = db.contractor_totals(connection, tax_year)
    stored = db.all_forms(connection)

    results = []
    for person in config.CONTRACTORS:
        name = person["name"]
        required = person["form"]
        paid = money.get(name, {})
        withdrawn = paid.get("withdrawn_usd", 0.0)
        record = stored.get(name)

        problems = []
        status = "ok"

        # ---------------------------------------------------------- the form
        if record is None or not record["received"]:
            # No form. How bad depends on whether the 1099 line has been
            # crossed - not on whether one is owed, since the form is what
            # settles that question either way.
            status = "missing_over_600" if withdrawn >= 600 else "missing"
            problems.append(f"No {required} on file.")
        else:
            on_file = record["form_type"]

            if on_file != required:
                # Collected the wrong form. Worth its own message: a W-8BEN
                # signed by a US citizen is not merely useless, it is a
                # false certification of foreign status.
                status = "missing"
                problems.append(
                    f"The form on file is a {on_file}, but a {required} is "
                    f"the one required.")

            elif required == "W-8BEN" and record["expires_on"]:
                expires = date.fromisoformat(record["expires_on"])
                days_left = (expires - today).days
                if days_left < 0:
                    status = "expired"
                    problems.append(
                        f"The W-8BEN expired on {record['expires_on']}. An "
                        f"expired form counts as no form.")
                elif days_left <= EXPIRY_WARNING_DAYS:
                    status = "expiring"
                    problems.append(
                        f"The W-8BEN expires on {record['expires_on']} "
                        f"({days_left} days). Collect a fresh one.")

            if required == "W-9" and not record["has_tin"]:
                # Worse than it sounds, so it outranks an expiry warning.
                status = "no_tin"
                problems.append(
                    "The W-9 is on file but has no taxpayer ID number. "
                    "Without one, 24% backup withholding applies to what "
                    "you pay her.")

        # ------------------------------------------------- the December ask
        # Sunniva is flagged every December whatever the amount, so that a
        # year of no payments is a decision rather than an oversight.
        if (status == "ok" and person.get("always_flag_in_december")
                and today.month == 12):
            status = "december_check"
            problems.append(
                f"Year-end check: confirm the {required} is still correct "
                f"even though withdrawals are ${withdrawn:,.2f}.")

        # ------------------------------------------------------- the 1099
        needs_1099 = bool(person["issues_1099"] and withdrawn >= 600)
        if needs_1099:
            problems.append(
                f"1099-NEC due: withdrawals reached ${withdrawn:,.2f}, past "
                f"the $600 threshold.")

        results.append({
            "person": name,
            "required_form": required,
            "us_person": person["us_person"],
            "withdrawn_usd": withdrawn,
            "withdrawals": paid.get("withdrawals", 0),
            "latest_withdrawal": paid.get("latest_withdrawal"),
            "on_file": bool(record and record["received"]),
            "form_on_file": record["form_type"] if record else None,
            "received_on": record["received_on"] if record else None,
            "expires_on": record["expires_on"] if record else None,
            "has_tin": bool(record["has_tin"]) if record else False,
            "needs_1099": needs_1099,
            "status": status,
            "ok": status == "ok",
            "problems": problems,
            "note": person.get("note", ""),
        })

    results.sort(key=lambda row: (SEVERITY.get(row["status"], 9),
                                  -row["withdrawn_usd"]))
    return results


def outstanding(rows):
    """Just the people with something wrong."""
    return [row for row in rows if not row["ok"]]


def needs_1099(rows):
    """Just the people a 1099-NEC is owed for."""
    return [row for row in rows if row["needs_1099"]]


# ===========================================================================
#  TURNING IT INTO WORDS
# ===========================================================================

def summary_line(row):
    """One line describing where a person stands."""
    if row["ok"]:
        held = f"{row['form_on_file']} on file"
        if row["expires_on"]:
            held += f", good to {row['expires_on']}"
        return f"{row['person']}: {held}."
    return f"{row['person']}: " + " ".join(row["problems"])


def report(rows, tax_year):
    """
    The full plain-English write-up, as a list of lines.

    Used by `check_forms.py` on screen and by the alert email, so the two
    can never drift apart and tell her different things.
    """
    lines = []
    lines.append(f"CONTRACTOR TAX FORMS - {tax_year}")
    lines.append("=" * 70)
    lines.append("")

    problems = outstanding(rows)
    if not problems:
        lines.append("Every form is on file and current. Nothing to chase.")
    else:
        lines.append(f"{len(problems)} of {len(rows)} need attention.")
    lines.append("")

    for row in rows:
        mark = "  " if row["ok"] else "! "
        lines.append(f"{mark}{row['person']}")
        lines.append(f"    needs           {row['required_form']}"
                     f"{'  (US person)' if row['us_person'] else ''}")

        if row["on_file"]:
            held = f"{row['form_on_file']} received {row['received_on']}"
            if row["expires_on"]:
                held += f", expires {row['expires_on']}"
            lines.append(f"    on file         {held}")
        else:
            lines.append("    on file         nothing recorded")

        lines.append(f"    withdrawn {row['withdrawn_usd']:>12,.2f} USD "
                     f"across {row['withdrawals']} payment"
                     f"{'' if row['withdrawals'] == 1 else 's'}")

        for problem in row["problems"]:
            lines.append(f"    -> {problem}")
        lines.append("")

    owed = needs_1099(rows)
    if owed:
        lines.append("-" * 70)
        lines.append("1099-NEC REQUIRED THIS YEAR")
        for row in owed:
            lines.append(f"  {row['person']} - ${row['withdrawn_usd']:,.2f} "
                         f"withdrawn")
        lines.append("")
        lines.append("  Due to the contractor by 31 January, and to the IRS")
        lines.append("  by 31 January. Only WITHDRAWALS count toward the")
        lines.append("  $600 - money still sitting in someone's jar has not")
        lines.append("  been paid to them and does not count.")
        lines.append("")

    return lines
