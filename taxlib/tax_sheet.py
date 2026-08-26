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

def summary_rows(data, year, built_on):
    t, h, m = data["totals"], data["hostlyft"], data["marcus"]
    rows = [
        [f"Hostlyft — Tax Summary {year}"],
        ["Cash received basis: what actually arrived, in the month it arrived."],
        [f"Built from the tax database on {built_on}. Do not edit — it is "
         f"rewritten on every run."],
        [],
        ["", "Income USD", "Expenses USD", "Net profit USD"],
        ["Hostlyft LLC", money(h["income_usd"]), money(h["expenses_usd"]),
         money(h["net_profit_usd"])],
        ["Marcus (separate work)", money(m["income_usd"]),
         money(m["expenses_usd"]), money(m["net_profit_usd"])],
        ["COMBINED — what tax is worked out on", money(t["income_usd"]),
         money(t["expenses_usd"]), money(t["net_profit_usd"])],
        [],
        ["Why combined: a single-member LLC is a disregarded entity, so both "
         "land on the same 1040."],
        ["Self-employment tax is charged on combined net earnings, and the "
         "FEIE and Social Security caps are combined limits too."],
        [],
        ["EXPENSES BY SCHEDULE C LINE"],
        ["Category", "Schedule C line", "Entries", "USD"],
    ]
    for row in data["by_category"]:
        rows.append([row["category"],
                     SCHEDULE_C.get(row["category"], "review"),
                     row["n"], money(row["total"])])
    rows += [
        [],
        ["MONEY DELIBERATELY NOT COUNTED"],
        ["Entries", t["excluded_income_count"],
         "internal transfers — see the Excluded tab for each reason"],
        ["Flagged for review", t["needs_review_count"],
         "see the Review tab"],
        ["Not yet in USD", (t["unconverted_income_count"]
                            + t["unconverted_expense_count"]),
         "counted as $0 above if any"],
        [],
        ["CONTRACTOR WITHDRAWALS — what was actually paid out"],
        ["Person", "Withdrawn USD", "Payments", "Form", "1099 needed?"],
    ]
    for name, info in data["contractors"].items():
        rows.append([name, money(info["withdrawn_usd"]), info["withdrawals"],
                     info["form"], "YES" if info["needs_1099"] else "no"])
    rows += [
        [],
        ["Withdrawals only. Money sitting in a jar has not been paid to "
         "anyone — it is still yours, is not deductible, and does not count "
         "toward $600."],
    ]
    return rows


def month_rows(data):
    rows = [["Cash received and spent, by month"],
            ["The month the money moved, not the month the work was done."],
            [],
            ["Month", "Income USD", "Expenses USD", "Net USD"]]
    for row in data["by_month"]:
        rows.append([row["month"], money(row["income"]), money(row["expenses"]),
                     money((row["income"] or 0) - (row["expenses"] or 0))])
    return rows


def income_rows(data):
    rows = [["Every receipt, at GROSS"],
            ["Gross is what the client paid. Platform fees are separate "
             "expenses — netting them here would lose the deduction."],
            [],
            ["Date", "Source", "Business", "Client", "Amount", "Currency",
             "USD", "FX rate", "Rate from", "Review?", "Source ID",
             "Description"]]
    for r in data["income"]:
        rows.append([r["date"], r["source"], r["business"], r["payer"] or "",
                     money(r["amount"]), r["currency"], money(r["amount_usd"]),
                     r["fx_rate"] or "", r["fx_date"] or "",
                     "yes" if r["needs_review"] else "",
                     r["source_id"], (r["description"] or "")[:120]])
    return rows


def expense_rows(data):
    rows = [["Every cost"],
            [],
            ["Date", "Source", "Business", "Vendor", "Category",
             "Schedule C line", "Amount", "Currency", "USD", "FX rate",
             "Rate from", "Review?", "Source ID"]]
    for r in data["expenses"]:
        rows.append([r["date"], r["source"], r["business"], r["vendor"] or "",
                     r["category"], SCHEDULE_C.get(r["category"], "review"),
                     money(r["amount"]), r["currency"], money(r["amount_usd"]),
                     r["fx_rate"] or "", r["fx_date"] or "",
                     "yes" if r["needs_review"] else "", r["source_id"]])
    return rows


def excluded_rows(data):
    rows = [["Money deliberately NOT counted"],
            ["Each of these is the same money arriving twice — a payout of "
             "income already counted, or a transfer between your own "
             "accounts. Kept visible so the decision can be checked."],
            [],
            ["Date", "Kind", "Source", "Who", "Amount", "Currency", "USD",
             "Why it was excluded"]]
    for r in data["excluded"]:
        rows.append([r["date"], r["kind"], r["source"], r["who"] or "",
                     money(r["amount"]), r["currency"], money(r["amount_usd"]),
                     r["exclusion_reason"] or ""])
    return rows


def jar_rows(data, connection):
    total = db.total_in_jars_usd(connection)
    rows = [["Wise jars — money set aside, still yours"],
            ["A jar is a labelled pot inside your own account. Putting money "
             "in it pays nobody."],
            ["It is NOT deductible, does NOT count toward $600, and DOES "
             "count toward the FBAR $10,000 test."],
            [],
            ["Jar", "Person", "Amount", "Currency", "USD", "Read on"]]
    for r in data["jars"]:
        rows.append([r["jar_name"], r["person"] or "", money(r["amount"]),
                     r["currency"], money(r["amount_usd"]), r["observed_on"]])
    rows += [
        [],
        ["TOTAL IN JARS", "", "", "", money(total)],
        [],
        ["Money still in jars on 31 December is not deductible that year but "
         "still inflates taxable profit."],
        [f"At 15.3% self-employment tax, the ${money(total):,.2f} above would "
         f"cost about ${money(total * 0.9235 * 0.153):,.2f} in real tax if it "
         f"were still there at year end."],
        ["Target: jars empty by about 20 December."],
    ]
    return rows


def review_rows(data):
    rows = [["Everything flagged for a human"],
            ["Nothing here is wrong. These are the things the importer would "
             "not decide on its own."],
            [],
            ["Date", "Kind", "Amount", "Currency", "Who", "Why"]]
    for r in data["review"]:
        rows.append([r["date"], r["kind"], money(r["amount"]), r["currency"],
                     r["who"] or "", (r["review_note"] or "")[:200]])
    if len(rows) == 4:
        rows.append(["", "", "", "", "", "nothing needs attention"])
    return rows


TABS = ["Summary", "By month", "Income", "Expenses", "Excluded", "Jars",
        "Review"]


def build_tabs(connection, year, built_on):
    data = collect(connection, year)
    return {
        "Summary": summary_rows(data, year, built_on),
        "By month": month_rows(data),
        "Income": income_rows(data),
        "Expenses": expense_rows(data),
        "Excluded": excluded_rows(data),
        "Jars": jar_rows(data, connection),
        "Review": review_rows(data),
    }, data


# ===========================================================================
#  WRITING IT
# ===========================================================================

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
    """Replace each tab's contents. Refuses if a formula would be lost."""
    sheets = gsheets.service()

    existing = {s["properties"]["title"]: s["properties"]["sheetId"]
                for s in gsheets.call(sheets.spreadsheets().get(
                    spreadsheetId=sheet_id,
                    fields="sheets(properties(title,sheetId))"),
                    what="the tax sheet").get("sheets", [])}

    requests = [{"addSheet": {"properties": {"title": name}}}
                for name in tabs if name not in existing]
    if requests:
        gsheets.call(sheets.spreadsheets().batchUpdate(
            spreadsheetId=sheet_id, body={"requests": requests}),
            what="adding tabs")

    blocked = []
    if not force:
        for name in tabs:
            if name in existing:
                blocked += formulas_present(sheets, sheet_id, name)
    if blocked:
        raise gsheets.GoogleError(
            "Refusing to write - these cells contain formulas:\n  "
            + "\n  ".join(blocked[:10])
            + "\nNothing was changed.")

    gsheets.call(sheets.spreadsheets().values().batchClear(
        spreadsheetId=sheet_id, body={"ranges": list(tabs)}),
        what="clearing the tabs")

    gsheets.call(sheets.spreadsheets().values().batchUpdate(
        spreadsheetId=sheet_id, body={
            "valueInputOption": "RAW",
            "data": [{"range": name, "values": rows}
                     for name, rows in tabs.items()],
        }), what="writing the tabs")

    return sheet_id
