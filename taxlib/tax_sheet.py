"""
tax_sheet.py - build the tax spreadsheet.

A SEPARATE sheet from Hostlyft_Accounting_2026, deliberately.

    The accounting sheet groups a month by SERVICE PERIOD, because some
    clients pay after the work is done and team payouts run at month end.
    That is what makes the splits correct.

    Tax needs CASH RECEIVED - what actually arrived, in the month it
    arrived. The two genuinely differ, and forcing one sheet to do both
    would corrupt whichever it was not built for.

    So the accounting sheet keeps its convention and is never written to.
    This one is cash-received throughout.

WHAT IT HOLDS
    Summary     the tax picture: gross receipts, expenses by Schedule C
                line, net profit per business and combined
    By month    cash received and spent, month by month
    Income      every receipt, with gross, currency, the USD figure, the
                rate used and the date that rate came from
    Expenses    every cost, with its Schedule C line
    Excluded    money deliberately not counted, with the reason - the
                audit trail for every double-count decision
    Jars        what is set aside per person, and the December warning
    Review      everything flagged as needing a human

WHY EVERY ROW CARRIES ITS SOURCE ID
    So any figure can be traced back to the Stripe invoice, Wise
    transaction or Upwork payment it came from. A tax return you cannot
    audit is one you cannot defend.
"""

import datetime as dt

from taxlib import config, db, gsheets, reconcile, tax
from taxlib.sheet_style import Tab, format_requests


TITLE = "Hostlyft_Tax_{year}"

# Where each category belongs on Schedule C. A starting point for filing,
# not advice.
SCHEDULE_C = {
    "contractor": "11 - Contract labor",
    "payment processing": "10 - Commissions and fees",
    "bank fees": "27a - Other expenses",
    "software": "27a - Other expenses",
    "phone and internet": "25 - Utilities",
    "compliance and admin": "17 - Legal and professional",
    "professional services": "17 - Legal and professional",
    "advertising": "8 - Advertising",
    "travel": "24a - Travel",
    "meals": "24b - Deductible meals",
    "entertainment": "24b - Deductible meals (NOT deductible - enter 0)",
    "taxes and licences": "23 - Taxes and licenses",
    "refunds to clients": "2 - Returns and allowances",
    # Cashback is a rebate on spending, so it nets against the costs it came
    # from rather than being reported as income. It carries a negative
    # amount, which is why it reduces line 27a rather than adding to it.
    "cashback and rebates": "27a - Other expenses (reduces)",
    "uncategorized": "NEEDS A CATEGORY",
}


# Self-employment tax: 15.3% on 92.35% of net profit.
#
# US income tax is expected to be $0 - the Foreign Earned Income Exclusion
# covers everything up to $132,900 and net profit is well below that - so
# self-employment tax is effectively the whole bill.
#
# An ESTIMATE. Stage 9 verifies every figure against the IRS PDF before
# anything here should be relied on.
SE_TAX_RATE = 0.153
SE_TAXABLE_SHARE = 0.9235


def se_tax(net_profit):
    return round(max(0.0, net_profit) * SE_TAXABLE_SHARE * SE_TAX_RATE, 2)


def money(value):
    return round(float(value or 0), 2)


# ===========================================================================
#  GATHERING THE DATA
# ===========================================================================

def collect(connection, year):
    """Everything the sheet needs, as plain lists of rows."""
    totals = db.totals(connection, year)
    hostlyft = db.totals(connection, year, business=config.BUSINESS_HOSTLYFT)
    marcus = db.totals(connection, year, business=config.BUSINESS_MARCUS)

    income = connection.execute(
        "SELECT date, source, source_id, business, payer, description, "
        "       amount, currency, amount_usd, fx_rate, fx_date, needs_review "
        "FROM income WHERE excluded = 0 AND tax_year = ? ORDER BY date",
        (year,)).fetchall()

    expenses = connection.execute(
        "SELECT date, source, source_id, business, vendor, category, "
        "       description, amount, currency, amount_usd, fx_rate, fx_date, "
        "       needs_review "
        "FROM expenses WHERE excluded = 0 AND tax_year = ? ORDER BY date",
        (year,)).fetchall()

    excluded = connection.execute(
        "SELECT date, 'income' AS kind, source, payer AS who, amount, "
        "       currency, amount_usd, exclusion_reason "
        "FROM income WHERE excluded = 1 AND tax_year = ? "
        "UNION ALL "
        "SELECT date, 'expense', source, vendor, amount, currency, "
        "       amount_usd, exclusion_reason "
        "FROM expenses WHERE excluded = 1 AND tax_year = ? ORDER BY date",
        (year, year)).fetchall()

    review = connection.execute(
        "SELECT date, 'income' AS kind, amount, currency, payer AS who, "
        "       review_note FROM income "
        "WHERE needs_review = 1 AND excluded = 0 AND tax_year = ? "
        "UNION ALL "
        "SELECT date, 'expense', amount, currency, vendor, review_note "
        "FROM expenses WHERE needs_review = 1 AND excluded = 0 AND tax_year = ? "
        "ORDER BY date", (year, year)).fetchall()

    by_category = connection.execute(
        "SELECT category, COUNT(*) n, SUM(amount_usd) total FROM expenses "
        "WHERE excluded = 0 AND tax_year = ? GROUP BY category "
        "ORDER BY total DESC", (year,)).fetchall()

    by_month = connection.execute(
        "SELECT substr(date, 1, 7) AS month, "
        "  SUM(CASE WHEN kind = 'income' THEN usd ELSE 0 END) AS income, "
        "  SUM(CASE WHEN kind = 'expense' THEN usd ELSE 0 END) AS expenses "
        "FROM ("
        "  SELECT date, 'income' AS kind, amount_usd AS usd FROM income "
        "  WHERE excluded = 0 AND tax_year = ? "
        "  UNION ALL "
        "  SELECT date, 'expense', amount_usd FROM expenses "
        "  WHERE excluded = 0 AND tax_year = ?"
        ") GROUP BY month ORDER BY month", (year, year)).fetchall()

    jars = db.latest_jar_balances(connection)
    contractors = db.contractor_totals(connection, year)

    # Reading her accounting sheet needs the network, and the tax sheet
    # must still build without it. A failure here costs the two
    # reconciliation tabs, not the whole run - but it is reported rather
    # than leaving empty tabs that look like "nothing to reconcile".
    reconciliation, checks, checks_summary, recon_error = [], [], {}, None
    recomputed = {"earned": {}, "unattributed": [], "unattributed_usd": 0.0}
    try:
        months = reconcile.read_sheet(year)
        reconciliation = reconcile.per_person(connection, year, months=months)
        checks = reconcile.sheet_vs_database(connection, year, months=months)
        checks_summary = reconcile.summarise(checks)
        # The independent second opinion on "earned" - rates from the
        # sheet, amounts from the bank. A failure here must not cost the
        # whole reconciliation, so it is caught separately.
        try:
            recomputed = reconcile.recomputed_earnings(connection, year)
        except Exception:                 # noqa: BLE001
            pass
    except Exception as problem:          # noqa: BLE001 - reported, not raised
        recon_error = str(problem)

    return {"totals": totals, "hostlyft": hostlyft, "marcus": marcus,
            "income": income, "expenses": expenses, "excluded": excluded,
            "review": review, "by_category": by_category, "by_month": by_month,
            "jars": jars, "contractors": contractors,
            "reconciliation": reconciliation, "checks": checks,
            "checks_summary": checks_summary, "recon_error": recon_error,
            "recomputed": recomputed}


# ===========================================================================
#  LAYING OUT THE TABS
# ===========================================================================

MONTH_NAMES = ["January", "February", "March", "April", "May", "June",
               "July", "August", "September", "October", "November",
               "December"]


def summary_tab(data, year, built_on):
    tab = Tab(money_columns=[1, 2, 3])
    t, h, m = data["totals"], data["hostlyft"], data["marcus"]

    tab.title(f"Hostlyft — Tax Summary {year}")
    tab.note("Cash received basis: what actually arrived, in the month it "
             "arrived. This is what tax is worked out on.")
    tab.note(f"Built from the tax database on {built_on}. Rewritten on every "
             "run — don't type into it.")
    tab.blank()

    tab.section("THE BOTTOM LINE")
    tab.head("", "Income USD", "Expenses USD", "Net profit USD")
    tab.row("Hostlyft LLC", money(h["income_usd"]), money(h["expenses_usd"]),
            money(h["net_profit_usd"]))
    tab.row("Marcus (separate work)", money(m["income_usd"]),
            money(m["expenses_usd"]), money(m["net_profit_usd"]))
    tab.total("COMBINED — tax is worked out on this", money(t["income_usd"]),
              money(t["expenses_usd"]), money(t["net_profit_usd"]))
    tab.note("A single-member LLC is a disregarded entity, so both land on "
             "the same 1040. Self-employment tax is charged on the combined "
             "figure, and the FEIE and Social Security caps are combined too.")
    tab.blank()

    tab.section("EXPENSES BY SCHEDULE C LINE")
    tab.head("Category", "Schedule C line", "Entries", "USD")
    for row in data["by_category"]:
        cells = [row["category"], SCHEDULE_C.get(row["category"], "review"),
                 row["n"], money(row["total"])]
        (tab.warn if row["category"] == "uncategorized" else tab.row)(*cells)
    tab.total("TOTAL", "", "", money(t["expenses_usd"]))
    tab.blank()

    tab.section("CONTRACTORS — deduction now, and what is still to come")
    tab.head("Person", "Withdrawn so far", "Still in their jar",
             "Expected total", "Form", "1099?")
    for name, info in data["contractors"].items():
        in_jar = data["jar_totals"].get(name, 0.0)
        cells = [name, money(info["withdrawn_usd"]), money(in_jar),
                 money(info["withdrawn_usd"] + in_jar), info["form"],
                 "YES" if info["needs_1099"] else "no"]
        (tab.warn if info["needs_1099"] else tab.row)(*cells)
    tab.note("Withdrawn is deductible NOW. Money still in a jar is not — it "
             "is yours until it leaves. It becomes deductible when they "
             "withdraw it, which is what the Expected column shows.")
    tab.note("Only withdrawals count toward the $600 that triggers a 1099.")
    tab.blank()

    tab.section("WHAT THE JARS WILL DO TO YOUR TAX")
    in_jars = sum(data["jar_totals"].values())
    contractor_now = sum(info["withdrawn_usd"]
                         for info in data["contractors"].values())
    net_now = t["net_profit_usd"]
    net_after = money(net_now - in_jars)

    tab.head("", "Contractor cost", "Net profit", "Est. self-employment tax")
    tab.row("As things stand today", money(contractor_now), money(net_now),
            se_tax(net_now))
    tab.row("Once the jars are withdrawn",
            money(contractor_now + in_jars), net_after, se_tax(net_after))
    tab.total("Difference", money(in_jars), money(-in_jars),
              money(se_tax(net_after) - se_tax(net_now)))
    tab.note(f"${money(in_jars):,.2f} is sitting in contractor jars. It is "
             f"not deductible until it leaves — but it will leave, so the "
             f"second row is the more realistic picture.")
    tab.note("Estimated self-employment tax only: 15.3% on 92.35% of net "
             "profit. US income tax is expected to be $0, because the "
             "Foreign Earned Income Exclusion covers everything up to "
             "$132,900 and net profit is well below that.")
    tab.warn("An estimate. Stage 9 verifies every figure against the IRS "
             "publication before this should be relied on.")
    tab.note("Money still in jars on 31 December does NOT get this "
             "deduction — it lands in next year instead. Target: jars empty "
             "by about 20 December.")
    tab.blank()

    tab.section("WORTH KNOWING")
    tab.row("Excluded as internal transfers", t["excluded_income_count"],
            "same money arriving twice — see the Excluded tab")
    tab.row("Flagged for review", t["needs_review_count"], "see the Review tab")
    tab.row("Not yet converted to USD",
            t["unconverted_income_count"] + t["unconverted_expense_count"],
            "counted as $0 above if any")
    return tab


def month_tabs(connection, data, year):
    """One tab per month that has activity."""
    allocations = {}
    for row in db.jar_allocations_by_month(connection, year):
        allocations[(row["month"], row["person"])] = {
            "in": money(row["allocated"]), "out": money(row["returned"])}
    withdrawals = db.contractor_withdrawals_by_month(connection, year)

    months = sorted({r["date"][:7] for r in data["income"]}
                    | {r["date"][:7] for r in data["expenses"]})

    tabs = {}
    for month in months:
        name = f"{MONTH_NAMES[int(month[5:7]) - 1][:3]} {month[:4]}"
        tab = Tab(money_columns=[1, 2, 3, 4, 5, 6])
        tab.title(f"Hostlyft — Tax: {MONTH_NAMES[int(month[5:7]) - 1]} "
                  f"{month[:4]}")
        tab.note("Cash received basis — money that actually moved this month, "
                 "whenever the work was done.")
        tab.blank()

        income = [r for r in data["income"] if r["date"].startswith(month)]
        tab.section("INCOME RECEIVED")
        tab.head("Date", "Source", "Client", "Business", "Amount", "Currency",
                 "USD")
        for r in income:
            tab.row(r["date"], r["source"], r["payer"] or "", r["business"],
                    money(r["amount"]), r["currency"], money(r["amount_usd"]))
        tab.total("TOTAL INCOME", "", "", "", "", "",
                  money(sum(r["amount_usd"] or 0 for r in income)))
        tab.blank()

        expenses = [r for r in data["expenses"] if r["date"].startswith(month)]
        tab.section("EXPENSES PAID")
        tab.head("Date", "Vendor", "Category", "Schedule C", "Amount",
                 "Currency", "USD")
        for r in expenses:
            tab.row(r["date"], r["vendor"] or "", r["category"],
                    SCHEDULE_C.get(r["category"], "review"),
                    money(r["amount"]), r["currency"], money(r["amount_usd"]))
        tab.total("TOTAL EXPENSES", "", "", "", "", "",
                  money(sum(r["amount_usd"] or 0 for r in expenses)))
        tab.blank()

        tab.section("CONTRACTORS THIS MONTH")
        tab.head("Person", "Set aside into jar", "Taken back out",
                 "Actually withdrawn", "Deductible now",
                 "Expected once withdrawn")
        any_activity = False
        for person in config.CONTRACTORS:
            name_ = person["name"]
            moved = allocations.get((month, name_), {"in": 0.0, "out": 0.0})
            withdrawn = withdrawals.get((month, name_), 0.0)
            if not (moved["in"] or moved["out"] or withdrawn):
                continue
            any_activity = True
            net_allocated = money(moved["in"] - moved["out"])
            tab.row(name_, moved["in"], moved["out"], withdrawn,
                    withdrawn, net_allocated)
        if not any_activity:
            tab.row("no contractor activity this month")
        tab.note("Set aside into a jar is NOT a deduction — it is still your "
                 "money, sitting in your own account under a label.")
        tab.note("It becomes deductible when they withdraw it. Since the team "
                 "withdraw before year end, the last column is the best "
                 "estimate of the deduction still to come.")
        tab.blank()

        tab.section("THE MONTH'S TOTALS")
        income_total = sum(r["amount_usd"] or 0 for r in income)
        expense_total = sum(r["amount_usd"] or 0 for r in expenses)
        still_in_jars = money(sum(
            allocations.get((month, p["name"]), {"in": 0.0})["in"]
            - allocations.get((month, p["name"]), {"out": 0.0})["out"]
            for p in config.CONTRACTORS))

        tab.head("", "", "", "", "Income", "Expenses", "Net")
        tab.row("Cash basis — what has actually moved", "", "", "",
                money(income_total), money(expense_total),
                money(income_total - expense_total))
        tab.row("Set aside into jars this month", "", "", "", "",
                still_in_jars, money(-still_in_jars))
        tab.total("PROJECTED once the jars are withdrawn", "", "", "",
                  money(income_total), money(expense_total + still_in_jars),
                  money(income_total - expense_total - still_in_jars))
        tab.note("The cash-basis row is what you would file if the year ended "
                 "today. The projected row assumes the team withdraw what is "
                 "set aside for them, which they do before year end.")

        tabs[name] = tab
    return tabs


def simple_tab(title, notes, headers, rows, money_columns, empty_message=None):
    tab = Tab(money_columns=money_columns)
    tab.title(title)
    for note in notes:
        tab.note(note)
    tab.blank()
    tab.head(*headers)
    for row in rows:
        tab.row(*row)
    if not rows and empty_message:
        tab.row(empty_message)
    return tab


def distributions_tab(connection, year):
    """
    Stage 14 - what each quarter's profit split came to.

    Two columns carry the whole tax point and are worth the space:

      DEDUCTIBLE?  no for her own share. A single-member LLC is disregarded,
                   so paying herself is an owner draw and reduces taxable
                   profit by nothing.
      WITHDRAWN    blank until the money actually leaves. A bonus sitting in
                   a jar at the year end is not a deduction that year, and
                   the sheet should show that rather than imply it is done.
    """
    from taxlib import distribution

    rows = []
    for row in db.distributions_for(connection, year):
        months = "+".join(
            distribution.TAX_QUARTER_MONTHS[row["quarter"]])
        rows.append([
            f"Q{row['quarter']}", months, row["person"],
            money(row["weight_usd"]), money(row["even_usd"]),
            money(row["proportional_usd"]), money(row["total_usd"]),
            "no — owner draw" if not row["deductible"] else "yes, once paid",
            row["withdrawn_on"] or "NOT YET",
            money(row["pool_usd"]),
        ])

    return simple_tab(
        f"Quarterly profit distribution — {year}",
        ["US ESTIMATED TAX QUARTERS, NOT CALENDAR ONES: Q1 Jan–Mar, "
         "Q2 Apr–May, Q3 Jun–Aug, Q4 Sep–Dec. Run just before each "
         "quarterly estimate is filed.",
         "The pool is every Hostlyft balance converted to USD, less every "
         "jar (already set aside for a person, hers included), less the "
         "$1,000 operating buffer.",
         "20% is shared equally between the four; 80% goes by DOLLARS "
         "EARNED that quarter. Marcus is excluded — that work is hers "
         "alone. Sunniva is not in the split; she is hourly.",
         "A TEAM BONUS IS DEDUCTIBLE ONLY ONCE WITHDRAWN. Declared and left "
         "in a jar, it is not yet a cost. Her own share is never "
         "deductible.",
         "Liuba's 5% is a rate on revenue; the 80% is split on dollars "
         "earned. On a $1,000 client payment she takes $50 where Katerina "
         "and Ayoka take $665 — which is why she lands near 7% of the pool, "
         "not 5%. Different measures, not an error."],
        ["Quarter", "Months", "Person", "Earned", "Even 20%",
         "By earned 80%", "TOTAL", "Deductible?", "Withdrawn", "Pool"],
        rows, money_columns=[3, 4, 5, 6, 9],
        empty_message="No distribution has been recorded yet — run "
                      "scripts/quarterly_distribution.py")


def form_lines_tab(connection, year, result):
    """
    Every figure the calculator produced, against the line it belongs on.

    WHY THIS RATHER THAN PRE-FILLED PDFs, WHICH SHE ASKED FOR FIRST
        Three things block that, and the third is the one that settles it.

        1. Drive is out of reach. The Google token carries the spreadsheets
           scope only - a Drive write returns 403. Fixable, but it would
           mean granting this tool access to her whole Drive, where today it
           can touch exactly two spreadsheets.

        2. The identity half of a return is not ours to invent: SSN or
           ITIN, address, and on Married Filing Separately her husband's
           name and SSN too.

        3. THE 2026 FORMS DO NOT EXIST YET. Only Form 1040-ES is published
           for 2026; f1040.pdf, Schedule C, Schedule SE, 2555 and 8829 are
           all still the 2025 editions and will be until around January.
           Filling a 2025 form with 2026 figures produces a document that
           is wrong on its face - and looks official while being so.

        So the figures are mapped to their lines instead. It works today,
        for every form, needs no new permission over her Drive, and cannot
        be mistaken for a return.

    Line numbers are read off the current Schedule C. They move between
    years occasionally, so each row carries its label as well as its number
    - the label is what to match on if a number has shifted.
    """
    from taxlib import filings

    totals = result["totals"]

    # ONE BASIS, THE SAME ONE AS EVERYWHERE ELSE: the contractor jars are
    # paid out before 31 December.
    #
    # A first version of this tab used the jars-stay figures instead,
    # reasoning that a filed return reports what happened rather than what
    # is planned. That was wrong, and she said so. By the time the return
    # is filed - January at the earliest - those payouts will be REAL
    # contractor expenses sitting in the database, and this tab is rebuilt
    # on every run. The projection is not a different basis; it is an early
    # view of the same number.
    #
    # It also left line 11 at the withdrawals so far while the net profit
    # came from somewhere else, so the form did not even add up.
    #
    # Everything below therefore takes result["net_profit"] and
    # result["total"] - the calculator's own headline - and a test asserts
    # they match, so the two can never drift apart again.
    pending_jars = (result.get("contractor_jars") or {}).get("usd") or 0.0

    tab = Tab(money_columns=[3])
    tab.title(f"How to fill each form - {year}")
    tab.note("Every figure below comes from the calculator. Lines marked "
             "YOU are ones only you can fill - identity, dates, anything "
             "the bank never saw.")
    tab.note("NOT A RETURN AND NOT ADVICE. It says which number goes where. "
             "Check each figure against the form's own instructions before "
             "you file - the linked instructions are the authority, not "
             "this tab.")
    tab.note("Line NUMBERS shift between years; the line LABEL does not. If "
             "a number does not match your form, match the label.")
    tab.note("THE CONTRACTOR JARS ARE COUNTED AS PAID, the same assumption "
             "the whole calculator uses. They will be real contractor "
             "expenses once the money leaves, and this tab is rebuilt every "
             "run, so by filing time these figures will simply be the "
             "actuals.")
    tab.note("IF THE JARS ARE STILL FULL ON 31 DECEMBER, this is wrong and "
             "so is everything else: the deduction moves into the next year, "
             "net profit rises to "
             f"${result.get('net_profit_if_jars_stay') or 0:,.2f} and tax to "
             f"${result.get('tax_if_jars_stay') or 0:,.2f}. Empty them.")
    tab.blank()

    tab.head("Form", "Line", "What it is called on the form", "Amount",
             "Where it comes from")

    # ---- Schedule C ---------------------------------------------------
    tab.row("Schedule C", "1", "Gross receipts or sales",
            money(totals["income_usd"]),
            "every payment received, at GROSS - before platform fees")
    # THE DEDUCTIBLE AMOUNT, NOT THE GROSS. Meals go on line 24b at 50% and
    # entertainment at zero, so listing what she spent would not add up to
    # line 28 and would overstate the deduction on the face of the form.
    for row in sorted(
            connection.execute(
                "SELECT category, SUM(amount_usd) AS usd FROM expenses "
                "WHERE excluded = 0 AND tax_year = ? GROUP BY category",
                (year,)).fetchall(),
            key=lambda r: -(r["usd"] or 0)):
        line = SCHEDULE_C.get(row["category"], "review - no line assigned")
        number, _, label = line.partition(" - ")
        share = config.deductible_share(row["category"])
        deductible = round((row["usd"] or 0) * share, 2)
        source = f"everything categorised '{row['category']}'"
        if row["category"] == "refunds to clients":
            # Line 2 reduces gross receipts rather than being an expense.
            # The database carries it as a negative-effect cost, which nets
            # to the same profit - but entering it BOTH on line 2 and
            # inside line 28 would deduct it twice.
            source = ("money given back to clients. Put it on line 2 OR "
                      "leave it inside line 28 - not both.")
        elif share != 1.0:
            source = (f"${row['usd']:,.2f} spent, at {share:.0%} - "
                      f"the form wants the deductible figure")
        if row["category"] == "contractor" and pending_jars:
            tab.row("Schedule C", number, label or line,
                    money(deductible + pending_jars),
                    f"${deductible:,.2f} already withdrawn PLUS "
                    f"${pending_jars:,.2f} sitting in their jars, which is "
                    f"deductible once it leaves")
            continue
        tab.row("Schedule C", number, label or line, money(deductible),
                source)
    tab.row("Schedule C", "28", "Total expenses",
            money(totals["deductible_expenses_usd"] + pending_jars),
            "the sum above - meals halved, entertainment at zero, jars "
            "counted as paid")
    tab.row("Schedule C", "29", "Tentative profit",
            money(totals["income_usd"] - totals["deductible_expenses_usd"]
                  - pending_jars),
            "line 1 minus line 28")
    office = result.get("home_office_usd") or 0
    tab.row("Schedule C", "30", "Expenses for business use of your home",
            money(office), "from Form 8829 - the actual-cost method wins")
    tab.row("Schedule C", "31", "NET PROFIT",
            money(result.get("net_profit")),
            "line 29 minus line 30. Schedule SE starts here.")
    tab.blank()

    # ---- Schedule SE --------------------------------------------------
    net = result.get("net_profit") or 0
    tab.row("Schedule SE", "2", "Net profit from Schedule C", money(net),
            "Schedule C line 31")
    tab.row("Schedule SE", "4a", "Multiply line 2 by 92.35%",
            money(round(net * 0.9235, 2)), "IRC 1402(a)(12)")
    se_total = (result.get("self_employment_tax") or {}).get("total", 0.0)
    tab.row("Schedule SE", "12", "Self-employment tax", money(se_total),
            "15.3% - and the FEIE does NOT reduce it")
    tab.row("Schedule SE", "13", "Deductible half of it",
            money(round(se_total / 2, 2)),
            "carries to Schedule 1, reducing income tax only")
    tab.blank()

    # ---- Form 2555 and 1040 -------------------------------------------
    tab.row("Form 2555", "-", "Foreign earned income excluded",
            money(min(net, 132900)),
            "capped at $132,900 for 2026. File it to claim it.")
    tab.row("Form 2555", "YOU", "Bona fide residence dates, foreign address",
            "", "France, full year - only you can state the dates")
    tab.row("Form 1040", "YOU", "Name, SSN/ITIN, address", "",
            "and on MFS, your husband's name and SSN too")
    tab.row("Form 1040", "-", "Total tax", money(result.get("total")),
            "essentially all self-employment tax; income tax is $0")
    tab.blank()

    # ---- Form 8829 ----------------------------------------------------
    home = result.get("home_office") or {}
    if home:
        tab.row("Form 8829", "1", "Area used regularly and exclusively",
                f"{config.HOME_OFFICE['office_area']} m2",
                "the exclusive-use test is the one people fail")
        tab.row("Form 8829", "2", "Total area of home",
                f"{config.HOME_OFFICE['total_area']} m2", "")
        pct = (home.get("actual") or {}).get("business_pct")
        tab.row("Form 8829", "7", "Business percentage",
                f"{pct:.1%}" if pct else "", "line 1 divided by line 2")
        tab.row("Form 8829", "-", "Depreciation", "not applicable",
                "you rent - renters take none, which skips the hard part")
        tab.row("Form 8829", "36", "Allowable deduction", money(office),
                "carries to Schedule C line 30")
        tab.blank()

    # ---- 1040-ES, the one with a deadline ------------------------------
    tab.row("Form 1040-ES", "-", "Estimated tax for each quarter",
            money(round((result.get("total") or 0) / 4, 2)),
            "THE 2026 FORM IS PUBLISHED - the only one that is")
    for quarter in filings.quarters(year):
        tab.row("Form 1040-ES", f"Q{quarter['quarter']} voucher",
                f"due {quarter['due']}",
                money(round((result.get("total") or 0) / 4, 2)),
                quarter["period"])
    tab.row("Form 1040-ES", "YOU", "Name, SSN, address on the voucher", "",
            "or pay online at irs.gov/payments and skip the voucher")
    return tab


def tax_calendar_tab(connection, year, result, today=None):
    """
    What you owe, whether it has gone out, and every form with its date.

    TWO THINGS THIS TAB MUST NOT DO.

    It must not say "UNPAID". This tool can only see her Wise accounts. She
    may pay by card, through EFTPS, or from an account it cannot read, so
    an absent payment means NOT SEEN, never NOT PAID. Stating the stronger
    thing would be a false alarm every quarter she pays another way.

    And it must not put the tax in `expenses`. Federal income tax and
    self-employment tax are her personal liabilities, not costs of the
    business - a disregarded entity makes it irrelevant which account pays.
    """
    import datetime as _d
    from taxlib import filings

    today = today or _d.date.today()
    per_quarter = round((result.get("total") or 0.0) / 4, 2)

    paid = {}
    for row in db.tax_payments_for(connection, year):
        paid.setdefault(row["quarter"], []).append(row)

    rows = []
    for quarter in filings.quarters(year, today):
        number = quarter["quarter"]
        seen = paid.get(number, [])
        amount = sum(r["amount_usd"] or r["amount"] or 0 for r in seen)
        if seen:
            status = f"paid {seen[0]['paid_on']}"
            how = ("found in Wise" if seen[0]["detected"] == "wise"
                   else "you recorded it")
        elif quarter["overdue"]:
            status = f"NOT SEEN - was due {quarter['due']}"
            how = "check it yourself - see the note below"
        else:
            status = f"due in {quarter['days_away']} days"
            how = ""
        rows.append([
            f"Q{number}", quarter["period"], str(quarter["due"]),
            money(per_quarter), money(amount) if seen else "",
            status, how,
        ])

    quarters_tab = simple_tab(
        f"Estimated tax - {year}",
        [f"Your total estimate for {year} is "
         f"${result.get('total') or 0:,.2f}, so ${per_quarter:,.2f} a "
         f"quarter. Self-employment tax is effectively all of it.",
         "IRS QUARTERS ARE NOT THREE MONTHS EACH. Q2 is two months and Q4 "
         "is four. The periods below are the IRS's own.",
         "\"NOT SEEN\" DOES NOT MEAN UNPAID. This checks your personal "
         "Wise account. If you paid by card, through EFTPS, or from an "
         "account this tool cannot read, it will not appear here - record "
         "it with: python scripts/tax_calendar.py --paid Q3 --amount 861.59",
         "Paying 100% of last year's total tax is the SAFE HARBOUR: it "
         "protects you from underpayment penalties however this year ends."],
        ["Quarter", "Period", "Due", "You owe", "Seen paid", "Status",
         "How we know"],
        rows, money_columns=[3, 4])

    quarters_tab.blank()
    quarters_tab.title(f"Forms to file for {year}")
    deadline = filings.filing_deadline(year)
    quarters_tab.note(
        f"THE RETURN IS DUE {deadline['abroad']:%d %B %Y}, not "
        f"{deadline['normal']:%d %B %Y}. Living abroad gives you an "
        f"automatic two-month extension - nothing to request.")
    quarters_tab.note(
        f"BUT IT EXTENDS THE FILING, NOT THE PAYING. Interest runs from "
        f"{deadline['interest_from']:%d %B %Y} on anything still owed. "
        f"Form 4868 pushes filing to {deadline['with_4868']:%d %B %Y}.")
    quarters_tab.blank()
    quarters_tab.head("Form", "What it is", "Due", "Filed with", "Link",
                      "How to fill it", "Worth knowing")
    for form in filings.FORMS:
        quarters_tab.row(form["form"], form["what"], form["due"],
                         form["who"], form["url"],
                         form.get("how", "see the 'Filling the forms' tab"),
                         form["note"])
    return quarters_tab


def build_all(connection, year, built_on):
    data = collect(connection, year)

    # what is still sitting in each person's jar
    data["jar_totals"] = {}
    for jar in data["jars"]:
        if jar["person"]:
            data["jar_totals"][jar["person"]] = (
                data["jar_totals"].get(jar["person"], 0.0)
                + (jar["amount_usd"] or 0))

    tabs = {"Summary": summary_tab(data, year, built_on)}
    tabs.update(month_tabs(connection, data, year))

    _tax = tax.from_database(connection, year)
    tabs["Tax Calendar"] = tax_calendar_tab(connection, year, _tax)
    tabs["Filling the forms"] = form_lines_tab(connection, year, _tax)
    tabs["Distributions"] = distributions_tab(connection, year)

    tabs["Income"] = simple_tab(
        "Every receipt, at GROSS",
        ["Gross is what the client paid. Platform fees are separate expenses "
         "— netting them here would lose the deduction."],
        ["Date", "Source", "Business", "Client", "Amount", "Currency", "USD",
         "FX rate", "Rate from", "Review?", "Source ID"],
        [[r["date"], r["source"], r["business"], r["payer"] or "",
          money(r["amount"]), r["currency"], money(r["amount_usd"]),
          r["fx_rate"] or "", r["fx_date"] or "",
          "yes" if r["needs_review"] else "", r["source_id"]]
         for r in data["income"]], money_columns=[4, 6])

    tabs["Expenses"] = simple_tab(
        "Every cost", [],
        ["Date", "Source", "Business", "Vendor", "Category", "Schedule C",
         "Amount", "Currency", "USD", "Review?", "Source ID"],
        [[r["date"], r["source"], r["business"], r["vendor"] or "",
          r["category"], SCHEDULE_C.get(r["category"], "review"),
          money(r["amount"]), r["currency"], money(r["amount_usd"]),
          "yes" if r["needs_review"] else "", r["source_id"]]
         for r in data["expenses"]], money_columns=[6, 8])

    tabs["Excluded"] = simple_tab(
        "Money deliberately NOT counted",
        ["Each of these is the same money arriving twice — a payout of income "
         "already counted, or a transfer between your own accounts.",
         "Kept visible so every decision can be checked rather than trusted."],
        ["Date", "Kind", "Source", "Who", "Amount", "Currency", "USD", "Why"],
        [[r["date"], r["kind"], r["source"], r["who"] or "",
          money(r["amount"]), r["currency"], money(r["amount_usd"]),
          r["exclusion_reason"] or ""] for r in data["excluded"]],
        money_columns=[4, 6], empty_message="none")

    jar_total = db.total_in_jars_usd(connection)
    jars = Tab(money_columns=[2, 4])
    jars.title("Wise jars — money set aside, still yours")
    jars.note("A jar is a labelled pot inside your own account. Putting money "
              "in it pays nobody.")
    jars.note("NOT deductible · does NOT count toward $600 · DOES count "
              "toward the FBAR $10,000 test.")
    jars.blank()
    jars.head("Jar", "Person", "Amount", "Currency", "USD", "Read on")
    for r in data["jars"]:
        jars.row(r["jar_name"], r["person"] or "", money(r["amount"]),
                 r["currency"], money(r["amount_usd"]), r["observed_on"])
    jars.total("TOTAL IN JARS", "", "", "", money(jar_total))
    jars.blank()
    jars.section("WHAT DECEMBER COSTS")
    jars.note("Money still in jars on 31 December is not deductible that year, "
              "but still inflates taxable profit.")
    jars.warn(f"At 15.3% self-employment tax, ${jar_total:,.2f} left in jars "
              f"would cost about "
              f"${money(jar_total * 0.9235 * 0.153):,.2f} in real tax.")
    jars.note("Target: jars empty by about 20 December.")
    tabs["Jars"] = jars

    review = Tab(money_columns=[2])
    review.title("Everything flagged for a human")
    review.note("Nothing here is wrong. These are the things the importer "
                "would not decide on its own.")
    review.blank()
    review.head("Date", "Kind", "Amount", "Currency", "Who", "Why")
    for r in data["review"]:
        review.warn(r["date"], r["kind"], money(r["amount"]), r["currency"],
                    r["who"] or "", (r["review_note"] or "")[:250])
    if not data["review"]:
        review.row("nothing needs attention")
    tabs["Review"] = review

    # ---------------------------------------------------- Reconciliation
    # The three numbers the plan insists are never confused with each
    # other, per person, as running totals for the year.
    recon = Tab(money_columns=[1, 2, 3, 4, 5, 6])
    recon.title(f"Reconciliation {year} - earned, withdrawn, still in the jar")
    recon.note("Running totals for the whole year, not month by month. "
               "Monthly mismatches are expected: payouts lag income by a "
               "month, so a single month rarely balances and the noise "
               "hides the real gaps.")
    recon.note("EARNED (ACCOUNTING SHEET) comes from your own monthly tabs - "
               "it is read, never recalculated. WITHDRAWN and IN JAR come "
               "from Wise.")
    recon.note("EARNED (OUR CHECK) works the same figure out a second way: "
               "each client's split RATE is learned from your sheet, then "
               "applied to what actually ARRIVED in the bank. It exists so a "
               "typo in a split column shows up instead of becoming the "
               "truth.")
    recon.note("The two are not meant to match to the penny. Your sheet "
               "books income to the month it was FOR; the bank knows when it "
               "ARRIVED. A few percent is normal - a large gap is worth "
               "opening the month and looking.")
    recon.blank()

    if data["recon_error"]:
        recon.warn("Your accounting sheet could not be read, so the earned "
                   "column is missing.")
        recon.warn(data["recon_error"][:400])
        recon.note("The withdrawal and jar figures below still come from "
                   "the database and are correct.")
        recon.blank()

    recomputed = (data.get("recomputed") or {}).get("earned", {})
    recon.head("Person", "Earned (accounting sheet)", "Earned (our check)",
               "Difference", "Withdrawn", "Still in jar", "Gap")
    for row in data["reconciliation"]:
        gap = row["gap_usd"]
        ours = recomputed.get(row["person"])
        # Three people have no revenue split to recompute, for three
        # different reasons - and saying "hourly" about all of them would
        # be wrong about two. Blank rather than zero throughout: "not
        # checked" is a different fact from "checked, and it is nothing".
        difference = (round(ours - (row["earned_usd"] or 0), 2)
                      if ours is not None and row["in_sheet"] else None)
        why_not = {
            "Sunniva Texe": "hourly - no split to check",
            "Olaide Olaniyan": "subcontractor - not in the splits",
            reconcile.FOUNDER: "takes a cut, not a split",
        }.get(row["person"], "no split rule to check")
        cells = (
            row["person"],
            money(row["earned_usd"]) if row["in_sheet"] else "not in sheet",
            money(ours) if ours is not None else why_not,
            money(difference) if difference is not None else "",
            money(row["withdrawn_usd"]),
            money(row["in_jar_usd"]),
            money(gap) if gap is not None else "-",
        )
        # Flag anything that does not reconcile, anyone the sheet never
        # mentions, and any split the second calculation disagrees with by
        # more than a few percent.
        drifted = (difference is not None and row["earned_usd"]
                   and abs(difference) > max(25.0,
                                             abs(row["earned_usd"]) * 0.05))
        unusual = ((not row["in_sheet"])
                   or (gap is not None and abs(gap) >= 1) or drifted)
        (recon.warn if unusual else recon.row)(*cells)
    recon.blank()

    unattributed = (data.get("recomputed") or {}).get("unattributed") or []
    if unattributed:
        total = (data.get("recomputed") or {}).get("unattributed_usd", 0.0)
        recon.warn(f"${total:,.2f} of client income has NO split rule in "
                   f"your sheet, so the check credits it to nobody.")
        recon.note("Right if those clients are yours alone. Silently wrong "
                   "if any of them should be splitting to somebody.")
        for row in unattributed[:8]:
            recon.row(f"   {row['payer']}", "", "", "", "", "",
                      money(row["usd"]))
        recon.blank()

    recon.note("GAP = earned - withdrawn - still in jar.")
    recon.note("A POSITIVE gap means they have earned money that has "
               "neither been paid to them nor set aside for them.")
    recon.note("A NEGATIVE gap means more has been paid or reserved than "
               "the sheet says they earned.")
    recon.blank()
    recon.note("Only WITHDRAWN is a tax deduction. Money in a jar is a "
               "label inside your own Wise account - it has not been paid "
               "to anyone, and it does not count toward the $600 that "
               "triggers a 1099.")
    recon.note("Liuba is shown because she has a jar and the totals would "
               "not add up without her. Her draws are NOT a deductible "
               "expense - they are owner's draws.")
    tabs["Reconciliation"] = recon

    # ------------------------------------------------------------ Checks
    checks_data = data["checks"]
    summary = data["checks_summary"]

    checks = Tab(money_columns=[1, 2, 3])
    checks.title(f"Sheet against database - {year}")
    checks.note("Your accounting sheet against what Stripe and Wise "
                "actually reported. Neither is automatically right: the "
                "sheet holds decisions the bank cannot see, and the bank "
                "holds transactions that may not have been typed in yet.")
    checks.note("This reports disagreement. It does not resolve it - "
                "quietly overwriting one with the other would destroy the "
                "only signal that something needs looking at.")
    checks.blank()

    if data["recon_error"]:
        checks.warn("Your accounting sheet could not be read, so there is "
                    "nothing to compare against.")
        checks.warn(data["recon_error"][:400])
        checks.note("This is not a clean bill of health - the check did not "
                    "run. Fix the connection and build the sheet again.")
        checks.blank()

    checks.head("Month", "Sheet USD", "Database USD", "Difference", "Agrees?")
    for row in checks_data:
        cells = (row["month"], money(row["sheet_usd"]),
                 money(row["database_usd"]), money(row["difference_usd"]),
                 "yes" if row["agrees"] else "NO")
        (checks.row if row["agrees"] else checks.warn)(*cells)
    if summary:
        checks.total("YEAR", money(summary["sheet_usd"]),
                     money(summary["database_usd"]),
                     money(summary["difference_usd"]), "")
    checks.blank()

    checks.section("WHY THE MONTHS DISAGREE EVEN WHEN THE YEAR NEARLY AGREES")
    checks.note("The database records income in the month the money "
                "ARRIVED. Your sheet records it against the month it was "
                "for. An invoice raised in one month and paid in the next "
                "lands in different months in the two records, without "
                "either being wrong.")
    checks.note("So the year total is the meaningful comparison. A month "
                "that disagrees is worth a glance; a YEAR that disagrees "
                "means something is genuinely missing.")
    checks.blank()

    if summary and summary["unmatched_payouts"]:
        checks.section("PAYOUT ROWS THAT COULD NOT BE ATTRIBUTED")
        checks.note("Two people on the roster share the surname Olaniyan, "
                    "so a row labelled only with a surname is reported "
                    "rather than guessed. Crediting it to the wrong person "
                    "would move somebody's $600 threshold.")
        checks.head("Month", "Row in your sheet", "USD", "", "")
        for entry in summary["unmatched_payouts"]:
            checks.warn(entry["month"], entry["label"],
                        money(entry["amounts"].get("USD", 0)), "", "")
        checks.blank()
    tabs["Checks"] = checks

    return tabs, data


# ===========================================================================
#  WRITING IT
# ===========================================================================

TABS = ["Summary"]


def find_or_create(year):
    """
    Return the tax sheet's id, creating it the first time.

    The id is remembered in tax/.env so the same sheet is updated every run
    rather than a new one appearing each time.
    """
    existing = gsheets.tax_sheet_id()
    sheets = gsheets.service()

    if existing:
        try:
            gsheets.call(sheets.spreadsheets().get(
                spreadsheetId=existing, fields="properties(title)"),
                what="the tax sheet")
            return existing, False
        except Exception:
            pass          # fall through and make a new one

    title = TITLE.format(year=year)
    created = gsheets.call(sheets.spreadsheets().create(body={
        "properties": {"title": title},
        "sheets": [{"properties": {"title": name}} for name in TABS],
    }), what="a new tax sheet")
    return created["spreadsheetId"], True


def remember_id(sheet_id):
    """Write the new sheet's id into tax/.env, touching nothing else."""
    path = config.ENV_PATH
    lines = path.read_text().splitlines()
    for index, line in enumerate(lines):
        if line.startswith("GOOGLE_TAX_SHEET_ID="):
            lines[index] = f"GOOGLE_TAX_SHEET_ID={sheet_id}"
            break
    else:
        lines += ["", "# The tax sheet, created by scripts/build_tax_sheet.py",
                  f"GOOGLE_TAX_SHEET_ID={sheet_id}"]
    path.write_text("\n".join(lines) + "\n")
    path.chmod(0o600)


def formulas_present(sheets, sheet_id, tab):
    """
    Would writing here overwrite a formula somebody typed?

    This sheet is generated, so there should never be one. The check exists
    because the rule - never overwrite a formula without being asked - has to
    hold everywhere, not only on the sheet where it was promised.
    """
    try:
        result = gsheets.call(sheets.spreadsheets().values().get(
            spreadsheetId=sheet_id, range=tab,
            valueRenderOption="FORMULA"), what=f"the {tab} tab")
    except Exception:
        return []
    found = []
    for row_index, row in enumerate(result.get("values", []), start=1):
        for col_index, cell in enumerate(row, start=1):
            if isinstance(cell, str) and cell.startswith("="):
                found.append(f"{tab}!R{row_index}C{col_index}")
    return found


def write(sheet_id, tabs, force=False):
    """
    Replace each tab's contents and formatting.

    Refuses if any cell holds a formula. This sheet is generated so there
    should never be one, but the rule - never overwrite a formula without
    being asked - has to hold everywhere, not only where it was promised.
    """
    # Before anything else: is this even the right spreadsheet? Her
    # accounting sheet is read-only and this raises rather than touching it.
    gsheets.assert_writable(sheet_id, what="the tax sheet build")
    sheets = gsheets.service()

    existing = {s["properties"]["title"]: s["properties"]["sheetId"]
                for s in gsheets.call(sheets.spreadsheets().get(
                    spreadsheetId=sheet_id,
                    fields="sheets(properties(title,sheetId))"),
                    what="the tax sheet").get("sheets", [])}

    # add any tab that does not exist yet
    missing = [name for name in tabs if name not in existing]
    if missing:
        gsheets.call(sheets.spreadsheets().batchUpdate(
            spreadsheetId=sheet_id, body={"requests": [
                {"addSheet": {"properties": {"title": name}}}
                for name in missing]}), what="adding tabs")
        existing = {s["properties"]["title"]: s["properties"]["sheetId"]
                    for s in gsheets.call(sheets.spreadsheets().get(
                        spreadsheetId=sheet_id,
                        fields="sheets(properties(title,sheetId))"),
                        what="the tax sheet").get("sheets", [])}

    blocked = []
    if not force:
        for name in tabs:
            if name in existing and name not in missing:
                blocked += formulas_present(sheets, sheet_id, name)
    if blocked:
        raise gsheets.GoogleError(
            "Refusing to write - these cells contain formulas:\n  "
            + "\n  ".join(blocked[:10])
            + "\nNothing was changed.")

    # Remove tabs this build no longer produces. An earlier version had a
    # "By month" tab; leaving it behind would show stale figures beside
    # current ones, which is worse than not having it.
    stale = [name for name in existing if name not in tabs]
    if stale:
        gsheets.call(sheets.spreadsheets().batchUpdate(
            spreadsheetId=sheet_id, body={"requests": [
                {"deleteSheet": {"sheetId": existing[name]}}
                for name in stale]}), what="removing stale tabs")
        for name in stale:
            existing.pop(name)

    gsheets.call(sheets.spreadsheets().values().batchClear(
        spreadsheetId=sheet_id, body={"ranges": list(tabs)}),
        what="clearing the tabs")

    gsheets.call(sheets.spreadsheets().values().batchUpdate(
        spreadsheetId=sheet_id, body={
            "valueInputOption": "RAW",
            "data": [{"range": name, "values": tab.rows}
                     for name, tab in tabs.items()],
        }), what="writing the tabs")

    # put the tabs in a sensible order - Summary, then the months, then the
    # detail. New tabs are appended by Google, so this has to be set each run.
    requests = [{"updateSheetProperties": {
        "properties": {"sheetId": existing[name], "index": position},
        "fields": "index"}}
        for position, name in enumerate(tabs)]
    gsheets.call(sheets.spreadsheets().batchUpdate(
        spreadsheetId=sheet_id, body={"requests": requests}),
        what="ordering the tabs")

    # formatting, in one batch per tab so a big sheet stays a few calls
    requests = []
    for name, tab in tabs.items():
        requests += format_requests(existing[name], tab,
                                    freeze_row=freeze_for(tab))
    for chunk in range(0, len(requests), 60):
        gsheets.call(sheets.spreadsheets().batchUpdate(
            spreadsheetId=sheet_id,
            body={"requests": requests[chunk:chunk + 60]}),
            what="formatting")

    cap_first_column(sheets, sheet_id)
    return sheet_id


# Column A holds the titles and the explanatory notes, which are long
# sentences. Auto-resize fits the LONGEST cell, so one note stretched column
# A to 1,352 pixels on some tabs and pushed every figure off the screen.
#
# A cap rather than a fraction, because the tabs differ wildly: Checks was
# 1,352 and Expenses only 79. Scaling everything to a third would have left
# Expenses at 26 pixels, unreadable for the sake of a rule.
FIRST_COLUMN_MAX_PX = 330


def cap_first_column(sheets, sheet_id, max_px=FIRST_COLUMN_MAX_PX):
    """
    Narrow column A wherever auto-resize made it too wide to read across.

    Runs after formatting, because autoResizeDimensions would otherwise
    undo it. Only shrinks - a tab whose column A is already narrow is left
    alone, so the notes stay readable without squashing the data tabs.

    Long text still reads fine: with an empty cell beside it, Sheets spills
    it across rather than clipping it.
    """
    meta = gsheets.call(sheets.spreadsheets().get(
        spreadsheetId=sheet_id,
        fields="sheets(properties(title,sheetId),"
               "data(columnMetadata(pixelSize)))"),
        what="reading the column widths")

    requests = []
    for sheet in meta.get("sheets", []):
        columns = (sheet.get("data") or [{}])[0].get("columnMetadata") or []
        if not columns:
            continue
        if (columns[0].get("pixelSize") or 0) <= max_px:
            continue
        requests.append({"updateDimensionProperties": {
            "range": {"sheetId": sheet["properties"]["sheetId"],
                      "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1},
            "properties": {"pixelSize": max_px},
            "fields": "pixelSize"}})

    if requests:
        gsheets.call(sheets.spreadsheets().batchUpdate(
            spreadsheetId=sheet_id, body={"requests": requests}),
            what="narrowing column A")
    return len(requests)


def freeze_for(tab):
    """Freeze down to the first column-header row, so it stays visible."""
    for index, style in enumerate(tab.styles):
        if style == "head":
            return index + 1
    return 1


# Tabs that belong at the front, in this order, before the monthly ones.
# Tax Calendar sits here at her request: it carries the deadlines and what
# is owed, so it is the tab to see on opening rather than one to scroll
# twelve months past.
FRONT_TABS = ["Summary", "Tax Calendar", "Filling the forms"]


def tab_order(tabs):
    """The front tabs, then the months in order, then the detail tabs."""
    front = [n for n in FRONT_TABS if n in tabs]
    months = [n for n in tabs if n not in front and n[:3] in
              [m[:3] for m in MONTH_NAMES]]
    months.sort(key=lambda n: [m[:3] for m in MONTH_NAMES].index(n[:3]))
    rest = [n for n in tabs if n not in front and n not in months]
    return front + months + rest
