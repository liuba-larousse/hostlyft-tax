"""
Reconciliation - the rest of Stage 11.

TWO QUESTIONS, BOTH ANSWERED BY COMPARING TWO RECORDS THAT SHOULD AGREE

  1. Per person: what the sheet says they EARNED, against what was actually
     WITHDRAWN to them and what is still sitting in their jar.
  2. Per month: what the sheet says the business earned and spent, against
     what Stripe and Wise actually reported.

Neither record is automatically right. The sheet is maintained by hand and
carries decisions the bank knows nothing about; the database is what the
payment processors actually said. Where they disagree, this reports the
disagreement and stops. It does not pick a winner - silently overwriting one
with the other would destroy the only signal that something needs looking at.

WHERE "EARNED" COMES FROM

Not from code. The split rules - 5% off the top, 70% shared between Katerina
and Ayoka, 80% to Evgeniya, $25/hr for Sunniva - are already encoded in her
sheet's formulas, and re-implementing them here would create a second
version to drift out of step with the first. So the sheet is READ, never
recomputed, and never written to.

WHY ROWS ARE FOUND BY LABEL AND NOT BY POSITION

The monthly tabs are not identically laid out. May has an extra payout row
that July does not, which shifts everything below it. Reading row 56 because
it was "Total Payouts" in July would silently pick up a contractor's payment
in May. Every row here is located by its label.
"""

import re
import unicodedata

from taxlib import config, db, fx, gsheets


# The founder. Not a contractor: she has no form, and money paid to her is a
# draw rather than a deductible expense. She is carried through the
# reconciliation anyway because she has a jar, and leaving her out would
# make the jar totals fail to add up.
FOUNDER = "Liuba (founder)"

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# Sheet column headings in the income sections -> who they mean.
SPLIT_COLUMNS = {
    "katerina split": "Katerina Mrvova",
    "ayoka split": "Yetunde Olaniyan",
    "evgeniya split": "Evgeniya Dyatlovskaya",
    "sunniva split": "Sunniva Texe",
    "liuba cut": FOUNDER,
}

# Row labels in the payouts section -> who they mean.
PAYOUT_ROWS = {
    "katerina mrvova": "Katerina Mrvova",
    "yetunde olaniyan (ayoka)": "Yetunde Olaniyan",
    "evgeniya dyatlovskaya": "Evgeniya Dyatlovskaya",
    "sunniva texe": "Sunniva Texe",
    "liuba (founder)": FOUNDER,
}


def _plain(text):
    """Lower-case, accent-stripped, whitespace-collapsed - for matching."""
    text = unicodedata.normalize("NFKD", str(text or ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    # The sheet uses an em dash in headings; normalise every dash to a space.
    text = re.sub(r"[‐-―−-]", " ", text)
    return " ".join(text.lower().split())


def money(text):
    """
    Turn a sheet cell into a number.

    Handles "$1,234.56", "€1.060,00"-style symbols, "-" for empty, and
    "($5,461.51)" for negatives, which is how the sheet writes them.
    Anything unreadable becomes 0.0 rather than crashing a whole month.
    """
    raw = str(text or "").strip()
    if not raw or raw in {"-", "—", "–"}:
        return 0.0
    negative = raw.startswith("(") and raw.endswith(")")
    cleaned = re.sub(r"[^0-9.\-]", "", raw.strip("()"))
    if cleaned in {"", "-", "."}:
        return 0.0
    try:
        value = float(cleaned)
    except ValueError:
        return 0.0
    return -value if negative else value


def hours(text):
    """Read '20.0h' as 20.0."""
    return money(str(text or "").replace("h", ""))


# ===========================================================================
#  READING ONE MONTHLY TAB
# ===========================================================================

def _cell(rows, row_index, col_index):
    """One cell, or '' - sheets return short rows rather than padding them."""
    if 0 <= row_index < len(rows):
        row = rows[row_index]
        if 0 <= col_index < len(row):
            return row[col_index]
    return ""


def _find_row(rows, *, starts_with=None, equals=None, after=0):
    """The index of the first row whose column A matches. -1 if none."""
    for index in range(after, len(rows)):
        label = _plain(_cell(rows, index, 0))
        if equals is not None and label == _plain(equals):
            return index
        if starts_with is not None and label.startswith(_plain(starts_with)):
            return index
    return -1


def _split_columns(rows, header_index):
    """
    Which column holds which person, read from the section's own header.

    The two income sections are NOT laid out the same way - the one-time
    section has a Sunniva column and the regular section does not. Reading
    each section's own header is what stops one person's money being read
    out of another person's column.
    """
    found = {}
    header = rows[header_index] if 0 <= header_index < len(rows) else []
    for col_index, heading in enumerate(header):
        label = _plain(heading)
        for needle, person in SPLIT_COLUMNS.items():
            if label.startswith(needle):
                found[col_index] = person
    return found


def _income_section(rows, heading, total_label):
    """
    Read one income section: its per-currency totals and per-person splits.

    Returns {currency: {"amount": x, "splits": {person: y}}}.
    """
    start = _find_row(rows, starts_with=heading)
    if start < 0:
        return {}

    header_index = _find_row(rows, equals="Client", after=start)
    if header_index < 0:
        return {}
    columns = _split_columns(rows, header_index)

    out = {}
    index = header_index
    while True:
        index = _find_row(rows, starts_with=total_label, after=index + 1)
        if index < 0:
            break
        label = _cell(rows, index, 0)
        match = re.search(r"\(([A-Z]{3})\)", str(label))
        if not match:
            continue
        currency = match.group(1)
        out[currency] = {
            "amount": money(_cell(rows, index, 2)),      # column C
            "splits": {person: money(_cell(rows, index, col))
                       for col, person in columns.items()},
        }
    return out


def _payouts_section(rows):
    """
    What the sheet says was paid out, per person per currency.

    Also returns any row it could not attribute. "Olaniyan (subcontractor)"
    is the real case: two people on the roster share that surname, so it is
    reported rather than guessed - crediting it to the wrong one would move
    somebody's $600 threshold.
    """
    start = _find_row(rows, starts_with="Contractor & Founder Payouts")
    if start < 0:
        return {}, []

    # The row directly under the heading carries the currency of each column.
    currencies = {}
    for col_index, heading in enumerate(rows[start + 1]
                                        if start + 1 < len(rows) else []):
        code = _plain(heading).upper()
        if len(code) == 3 and code.isalpha():
            currencies[col_index] = code
    if not currencies:
        return {}, []

    paid, unmatched = {}, []
    for index in range(start + 2, len(rows)):
        label = _cell(rows, index, 0)
        plain = _plain(label)
        if not plain:
            continue
        if plain.startswith("total payouts"):
            break

        person = PAYOUT_ROWS.get(plain)
        amounts = {code: money(_cell(rows, index, col))
                   for col, code in currencies.items()}
        if not any(amounts.values()):
            continue

        if person is None:
            unmatched.append({"label": str(label).strip(),
                              "amounts": amounts})
            continue
        for code, value in amounts.items():
            if value:
                paid.setdefault(person, {})
                paid[person][code] = paid[person].get(code, 0.0) + value
    return paid, unmatched


def parse_month(rows):
    """Everything worth reading out of one monthly tab."""
    regular = _income_section(rows, "INCOME  Regular", "Total Regular Income")
    one_time = _income_section(rows, "INCOME  One Time",
                               "Total One Time Income")
    paid, unmatched = _payouts_section(rows)

    # Sunniva is hourly, so her earnings are not a split of anyone's client
    # revenue. The sheet records the hours and the money separately.
    hours_index = _find_row(rows, starts_with="Sunniva  Hours Worked")
    sunniva_hours = hours(_cell(rows, hours_index, 1)) if hours_index >= 0 else 0.0
    sunniva_pay = money(_cell(rows, hours_index, 3)) if hours_index >= 0 else 0.0

    # Per-person earnings, per currency, from both income sections.
    earned = {}
    for section in (regular, one_time):
        for currency, block in section.items():
            for person, amount in block["splits"].items():
                if amount:
                    earned.setdefault(person, {})
                    earned[person][currency] = (
                        earned[person].get(currency, 0.0) + amount)
    if sunniva_pay:
        earned.setdefault("Sunniva Texe", {})
        earned["Sunniva Texe"]["USD"] = (
            earned["Sunniva Texe"].get("USD", 0.0) + sunniva_pay)

    income_by_currency = {}
    for currency in set(regular) | set(one_time):
        income_by_currency[currency] = (
            regular.get(currency, {}).get("amount", 0.0)
            + one_time.get(currency, {}).get("amount", 0.0))

    return {
        "earned": earned,
        "paid": paid,
        "unmatched_payouts": unmatched,
        "income_by_currency": income_by_currency,
        "sunniva_hours": sunniva_hours,
        "sunniva_pay": sunniva_pay,
    }


# ===========================================================================
#  READING THE WHOLE YEAR
# ===========================================================================

def read_sheet(year, sheet_id=None, service=None):
    """
    Read every monthly tab of her accounting sheet. READ ONLY.

    Fetched in one batch request rather than twelve, which is both faster
    and far less likely to hit Google's rate limit mid-year.
    """
    # HER ACCOUNTING SHEET, and only ever read. The named accessor says so;
    # "GOOGLE_SHEET_ID" on its own reads like "the sheet" and is the one
    # place writing is forbidden. See the block at the top of gsheets.py.
    sheet_id = sheet_id or gsheets.accounting_sheet_id()
    if not sheet_id:
        raise gsheets.GoogleError(
            "GOOGLE_SHEET_ID is not set in tax/.env - that is her accounting "
            "sheet, which the monthly split figures are read from.")
    sheets = service or gsheets.service()
    names = [f"{month} {year}" for month in MONTHS]

    result = gsheets.call(
        sheets.spreadsheets().values().batchGet(
            spreadsheetId=sheet_id, ranges=names),
        what="the monthly tabs")

    months = {}
    for name, block in zip(names, result.get("valueRanges", [])):
        months[name] = parse_month(block.get("values", []))
    return months


def _month_end(year, month_index):
    """
    The date used to convert a month's figures into US dollars.

    The last day of the month, which the FX layer walks back to the last
    business day of. One consistent date per month means the same month
    always converts to the same number, however often this is re-run.
    """
    import calendar
    last = calendar.monthrange(year, month_index)[1]
    return f"{year}-{month_index:02d}-{last:02d}"


def earnings_by_person(connection, year, months=None, fetcher=None):
    """
    Cumulative earnings per person for the year, per currency and in USD.

    Currencies are kept separate as well as totalled. Her rule is that
    totals are never blended - but the withdrawal and jar figures this gets
    compared against are already in dollars, so a dollar column is the only
    way to compute the gap at all. Both are shown so the rule stays visible.
    """
    months = months if months is not None else read_sheet(year)

    people = {}
    for index, month in enumerate(MONTHS, start=1):
        name = f"{month} {year}"
        data = months.get(name)
        if not data:
            continue
        on_date = _month_end(year, index)

        for person, amounts in data["earned"].items():
            entry = people.setdefault(person, {"by_currency": {},
                                               "usd": 0.0, "months": {}})
            month_usd = 0.0
            for currency, amount in amounts.items():
                if not amount:
                    continue
                entry["by_currency"][currency] = (
                    entry["by_currency"].get(currency, 0.0) + amount)
                if currency == "USD":
                    usd = amount
                else:
                    usd = fx.convert(connection, amount, currency, on_date,
                                     fetcher=fetcher)["amount"]
                month_usd += usd
            entry["usd"] = db.round_money(entry["usd"] + month_usd)
            entry["months"][name] = db.round_money(month_usd)

    return people


# ===========================================================================
#  PER PERSON: EARNED vs WITHDRAWN vs STILL IN THE JAR
# ===========================================================================

def per_person(connection, year, months=None, fetcher=None):
    """
    The three numbers the plan insists are never confused, plus the gap.

        earned      what the sheet's split calculation says they earned
        withdrawn   what was actually transferred out - THE DEDUCTION
        in_jar      what is set aside but still hers

    gap = earned - withdrawn - in_jar. Positive means somebody is owed money
    that has not even been set aside yet.
    """
    earned = earnings_by_person(connection, year, months=months,
                                fetcher=fetcher)
    withdrawn = db.contractor_totals(connection, year)
    jars = db.latest_jar_balances(connection)

    in_jar = {}
    for row in jars:
        if row["person"]:
            in_jar[row["person"]] = db.round_money(
                in_jar.get(row["person"], 0.0) + (row["amount_usd"] or 0))
        else:
            # The founder's own jar is labelled by her name, not a person.
            if _plain(row["jar_name"]).startswith("liuba"):
                in_jar[FOUNDER] = db.round_money(
                    in_jar.get(FOUNDER, 0.0) + (row["amount_usd"] or 0))

    names = ([person["name"] for person in config.CONTRACTORS]
             + [FOUNDER])

    rows = []
    for name in names:
        person = config.contractor(name)
        earn = earned.get(name)
        paid_out = withdrawn.get(name, {}).get("withdrawn_usd", 0.0)
        jar = in_jar.get(name, 0.0)

        # A person the sheet never splits income to has no earned figure -
        # which is different from having earned nothing, and must not be
        # shown as 0.00 as though it had been checked and found empty.
        earned_usd = earn["usd"] if earn else None
        gap = (db.round_money(earned_usd - paid_out - jar)
               if earned_usd is not None else None)

        rows.append({
            "person": name,
            "is_contractor": person is not None,
            "form": person["form"] if person else None,
            "earned_usd": earned_usd,
            "earned_by_currency": earn["by_currency"] if earn else {},
            "withdrawn_usd": paid_out,
            "in_jar_usd": jar,
            "gap_usd": gap,
            "in_sheet": earn is not None,
        })
    return rows


def save_ledger(connection, year, rows, as_of):
    """
    Write the reconciliation into contractor_ledger.

    Built in Stage 2 for exactly this and empty until now. Dated, so the
    position at a past date stays readable rather than being overwritten.
    """
    saved = 0
    for row in rows:
        if not row["is_contractor"]:
            continue           # the founder is not a contractor
        connection.execute(
            "INSERT INTO contractor_ledger "
            "  (person, tax_year, as_of, earned_usd, in_jar_usd, "
            "   withdrawn_usd, gap_usd, notes, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(person, tax_year, as_of) DO UPDATE SET "
            "  earned_usd = excluded.earned_usd, "
            "  in_jar_usd = excluded.in_jar_usd, "
            "  withdrawn_usd = excluded.withdrawn_usd, "
            "  gap_usd = excluded.gap_usd, "
            "  notes = excluded.notes, "
            "  updated_at = excluded.updated_at",
            (row["person"], year, as_of, row["earned_usd"] or 0.0,
             row["in_jar_usd"], row["withdrawn_usd"], row["gap_usd"] or 0.0,
             None if row["in_sheet"] else "not in the sheet's split "
                                          "calculation",
             db._now(), db._now()))
        saved += 1
    return saved


# ===========================================================================
#  SHEET vs DATABASE
# ===========================================================================

# Below this, a difference is rounding or a fractionally different exchange
# rate rather than a missing transaction.
TOLERANCE_USD = 1.00


def sheet_vs_database(connection, year, months=None, fetcher=None):
    """
    Month by month: what the sheet says, against what the database says.

    Reports disagreement. Deliberately does not resolve it - the sheet holds
    decisions the bank cannot see, and the database holds transactions the
    sheet may never have had typed into it. Which is right is hers to say.
    """
    months = months if months is not None else read_sheet(year)
    out = []

    for index, month in enumerate(MONTHS, start=1):
        name = f"{month} {year}"
        data = months.get(name, {})
        on_date = _month_end(year, index)
        prefix = f"{year}-{index:02d}"

        sheet_usd = 0.0
        for currency, amount in (data.get("income_by_currency") or {}).items():
            if not amount:
                continue
            sheet_usd += (amount if currency == "USD" else
                          fx.convert(connection, amount, currency, on_date,
                                     fetcher=fetcher)["amount"])

        row = connection.execute(
            "SELECT COALESCE(SUM(amount_usd), 0) AS usd, COUNT(*) AS n "
            "FROM income WHERE excluded = 0 AND business = 'hostlyft' "
            "AND date LIKE ?", (f"{prefix}-%",)).fetchone()
        database_usd = db.round_money(row["usd"])

        difference = db.round_money(database_usd - sheet_usd)
        out.append({
            "month": name,
            "sheet_usd": db.round_money(sheet_usd),
            "database_usd": database_usd,
            "database_rows": row["n"],
            "difference_usd": difference,
            "agrees": abs(difference) <= TOLERANCE_USD,
            "unmatched_payouts": data.get("unmatched_payouts", []),
        })
    return out


def summarise(checks):
    """Totals across the year, and how many months disagree."""
    sheet = db.round_money(sum(row["sheet_usd"] for row in checks))
    database = db.round_money(sum(row["database_usd"] for row in checks))
    return {
        "sheet_usd": sheet,
        "database_usd": database,
        "difference_usd": db.round_money(database - sheet),
        "months_disagreeing": [row["month"] for row in checks
                               if not row["agrees"]],
        "unmatched_payouts": [
            {"month": row["month"], **entry}
            for row in checks for entry in row["unmatched_payouts"]],
    }


# ===========================================================================
#  THE INDEPENDENT CHECK ON THE SHEET'S SPLIT ARITHMETIC
# ===========================================================================
#
# "Earned" is the one figure in the reconciliation that does not come from a
# bank, and until now it came from one place only: her hand-maintained
# monthly tabs. A typo there propagates silently into the gap, the $600
# threshold and the quarterly distribution.
#
# This recomputes it a second way, taking only the RATES from the sheet and
# the AMOUNTS from the database - so a mistyped figure in a split column
# shows up as a divergence instead of becoming the truth.
#
# WHY THE RATES ARE LEARNED PER CLIENT RATHER THAN ASSUMED
#     The standard formulas are 0.95 x 0.70 x 0.50 for the Katerina/Ayoka
#     group and 0.95 x 0.80 for Jane. Not every client follows them:
#     Chananya splits 0.7192 to Jane and 0.2308 to Ayoka. Assuming the
#     formula would report a divergence that is really a bespoke deal.
#
# WHAT IT CANNOT DO
#     Sunniva is hourly, not a revenue split, so there is nothing to
#     recompute for her - only the sheet knows her hours. She is left out
#     rather than being reported as earning whatever she happens to have
#     been paid.

# Deliberately NOT called SPLIT_COLUMNS: that name is already taken further
# up for reading the sheet, and redefining it silently broke parse_month -
# Liuba vanished from the earnings it returns. Caught by the existing tests.
CHECK_SPLIT_COLUMNS = {
    "katerina split": "Katerina Mrvova",
    "ayoka split": "Yetunde Olaniyan",
    "evgeniya split": "Evgeniya Dyatlovskaya",
}


def client_split_rates(year, sheet_id=None):
    """
    Learn each client's split rates from the sheet's own income rows.

    Returns {client_name: {person: rate}}. A rate is that person's share of
    the invoice, read from what the sheet actually computed rather than
    from a formula it is assumed to follow.
    """
    sheet_id = sheet_id or gsheets.accounting_sheet_id()
    sheets = gsheets.service()
    rates, header = {}, None

    for month in MONTHS:
        try:
            values = gsheets.call(sheets.spreadsheets().values().get(
                spreadsheetId=sheet_id, range=f"'{month} {year}'!A1:H40"),
                what=f"the {month} tab")["values"]
        except Exception:
            continue
        for raw in values:
            cells = list(raw) + [""] * 8
            first = str(cells[0]).strip()
            if first.lower() == "client":
                header = [str(c).strip().lower() for c in cells]
                continue
            if not header or not first or first.lower().startswith("total"):
                continue
            amount = money(cells[2])
            if amount <= 0:
                continue
            for index, label in enumerate(header):
                person = CHECK_SPLIT_COLUMNS.get(label)
                if not person:
                    continue
                share = money(cells[index])
                if share:
                    rates.setdefault(first, {})[person] = share / amount
    return rates


def recomputed_earnings(connection, year, sheet_id=None):
    """
    Earned, worked out from the sheet's RATES and the database's AMOUNTS.

    The point of comparison is that the two disagree for real reasons if
    something is wrong, and agree closely if nothing is. Timing differs by
    design: the sheet books income to the month it was FOR, the database to
    the month the money ARRIVED.

    Also returns the clients whose money has no split rule at all, because
    that is a silent way to under-credit somebody.
    """
    rates = client_split_rates(year, sheet_id)
    payers = [row["payer"] for row in connection.execute(
        "SELECT DISTINCT payer FROM income WHERE excluded = 0 "
        "AND business = 'hostlyft' AND payer IS NOT NULL AND payer != ''")]

    def match(client):
        low = client.lower()
        for payer in payers:
            first = payer.split()[0].lower()
            if first.startswith(low[:4]) or low.startswith(first[:4]):
                return payer
        return None

    earned, mapped = {}, set()
    for client, person_rates in rates.items():
        payer = match(client)
        if not payer:
            continue
        mapped.add(payer)
        received = connection.execute(
            "SELECT COALESCE(SUM(amount_usd), 0) AS usd FROM income "
            "WHERE excluded = 0 AND business = 'hostlyft' AND payer = ? "
            "AND tax_year = ?", (payer, year)).fetchone()["usd"]
        for person, rate in person_rates.items():
            earned[person] = round(earned.get(person, 0.0) + received * rate, 2)

    unattributed = []
    for payer in payers:
        if payer in mapped:
            continue
        usd = connection.execute(
            "SELECT COALESCE(SUM(amount_usd), 0) AS usd FROM income "
            "WHERE excluded = 0 AND business = 'hostlyft' AND payer = ? "
            "AND tax_year = ?", (payer, year)).fetchone()["usd"]
        if usd:
            unattributed.append({"payer": payer, "usd": round(usd, 2)})

    return {
        "earned": earned,
        "unattributed": sorted(unattributed, key=lambda r: -r["usd"]),
        "unattributed_usd": round(sum(r["usd"] for r in unattributed), 2),
        "clients": len(rates),
    }
