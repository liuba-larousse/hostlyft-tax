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

from taxlib import config, db, gsheets
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
    "taxes and licences": "23 - Taxes and licenses",
    "refunds to clients": "2 - Returns and allowances",
    "uncategorized": "NEEDS A CATEGORY",
}


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

    return {"totals": totals, "hostlyft": hostlyft, "marcus": marcus,
            "income": income, "expenses": expenses, "excluded": excluded,
            "review": review, "by_category": by_category, "by_month": by_month,
            "jars": jars, "contractors": contractors}


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

        tab.section("NET FOR THE MONTH")
        income_total = sum(r["amount_usd"] or 0 for r in income)
        expense_total = sum(r["amount_usd"] or 0 for r in expenses)
        tab.head("", "", "", "", "Income", "Expenses", "Net")
        tab.total("", "", "", "", money(income_total), money(expense_total),
                  money(income_total - expense_total))

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
    existing = config.get_secret("GOOGLE_TAX_SHEET_ID")
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

    return sheet_id


def freeze_for(tab):
    """Freeze down to the first column-header row, so it stays visible."""
    for index, style in enumerate(tab.styles):
        if style == "head":
            return index + 1
    return 1


def tab_order(tabs):
    """Summary first, then months in order, then the detail tabs."""
    months = [n for n in tabs if n[:3] in
              [m[:3] for m in MONTH_NAMES]]
    months.sort(key=lambda n: [m[:3] for m in MONTH_NAMES].index(n[:3]))
    rest = [n for n in tabs if n not in months and n != "Summary"]
    return ["Summary"] + months + rest
