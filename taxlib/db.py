"""
db.py - the database: creating it, writing to it, and reading totals out.

WHAT THE DATABASE IS
    One ordinary file: tax/hostlyft_tax.db

    It uses SQLite, which is a complete database that lives entirely in a
    single file. There is no server to run, no account to create, no monthly
    fee, and nothing to keep switched on. Python has it built in. Copying that
    one file is a complete backup; deleting it deletes everything.

THE FIVE TABLES
    income          money you earned
    expenses        money you spent that reduces your taxable profit
    stripe_payouts  NOT income - the reference list that stops the same
                    $2,000 being counted twice (see the note below)
    fx_rates        a saved copy of every exchange rate used
    alerts_sent     a record of reminders already sent, so they fire once

    (Plus a small `meta` table holding the schema version, so later stages can
    upgrade the database safely instead of asking you to start over.)

WHY stripe_payouts EXISTS
    A $2,000 invoice is paid through Stripe. Stripe keeps a $60 fee and sends
    $1,940 to your Wise account six days later. Stripe reports $2,000 of
    income. Wise reports $1,940 arriving. Added up naively that is $3,940 -
    tax on nearly double what you actually earned.

    Stage 6 stops this by checking every incoming Wise payment against the
    list of Stripe payouts. This table is that list. Without it there is
    nothing to compare against.

RE-RUNNING IS ALWAYS SAFE
    Every row carries a `source` (which system it came from) and a
    `source_id` (its ID in that system). Those two together must be unique.
    So importing the same Stripe invoice twice updates the existing row
    instead of adding a second one. You can re-run any import as often as you
    like and the totals will not move.

A NOTE ON MONEY AND ROUNDING
    Amounts are stored as ordinary numbers, always rounded to cents.

    Rounding is done with round_money() below rather than Python's built-in
    round(), because the built-in rounds a halfway value to the nearest EVEN
    number: round(0.125, 2) gives 0.12, not 0.13. That is correct for
    statistics and wrong for money. round_money() always rounds a half up,
    which is what tax arithmetic expects.
"""

import sqlite3
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from taxlib import config


# The version of the table layout. If a later stage needs a new column, it
# bumps this number and adds the column, rather than you rebuilding by hand.
SCHEMA_VERSION = 1


# ===========================================================================
#  MONEY
# ===========================================================================

def round_money(value):
    """
    Round to cents, with a half always going up. Returns a plain number.

        round_money(0.125)   -> 0.13   (built-in round() gives 0.12)
        round_money(1939.995) -> 1940.0

    Returns None for None, so a not-yet-converted USD amount stays empty
    rather than silently becoming 0.00.
    """
    if value is None:
        return None
    quantised = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(quantised)


def _now():
    """The current time in UTC, as text. Used for created/updated stamps."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _year_of(date_text):
    """Pull the year out of a YYYY-MM-DD date, so a year can be filtered fast."""
    if not date_text:
        return None
    try:
        return int(str(date_text)[:4])
    except ValueError:
        return None


# ===========================================================================
#  OPENING THE DATABASE
# ===========================================================================

def connect(path=None):
    """
    Open the database file and hand back a connection.

    Creates the file if it doesn't exist. Three settings are applied:

      row_factory   - rows come back labelled (row["amount"]) rather than
                      numbered (row[3]), which makes the code readable
      foreign_keys  - SQLite ignores links between tables unless asked
      journal WAL   - safer if something is interrupted mid-write
    """
    if path is None:
        config.ensure_data_dir()
        path = config.DB_PATH

    connection = sqlite3.connect(str(path))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


# ===========================================================================
#  THE TABLE LAYOUT
# ===========================================================================
#
# "CREATE TABLE IF NOT EXISTS" means running this again on an existing
# database changes nothing. It is safe to call every time.

SCHEMA = """

-- ------------------------------------------------------------------ income
CREATE TABLE IF NOT EXISTS income (
    id                INTEGER PRIMARY KEY,

    -- where the row came from, and its ID over there. Together unique, so a
    -- repeated import updates rather than duplicates.
    source            TEXT    NOT NULL,      -- 'stripe' | 'wise' | 'manual'
    source_id         TEXT    NOT NULL,

    date              TEXT    NOT NULL,      -- YYYY-MM-DD
    tax_year          INTEGER,               -- filled in automatically

    -- the amount exactly as it happened, in whatever currency it happened in
    amount            REAL    NOT NULL,
    currency          TEXT    NOT NULL,

    -- the same amount in US dollars. Empty until Stage 5 converts it.
    amount_usd        REAL,
    fx_rate           REAL,                  -- the rate used
    fx_date           TEXT,                  -- the business day it came from

    description       TEXT,
    payer             TEXT,                  -- who paid you

    -- Stage 6: a Wise credit that turns out to be a Stripe payout arriving is
    -- kept for the audit trail but excluded from the totals.
    excluded          INTEGER NOT NULL DEFAULT 0,   -- 0 = counts, 1 = doesn't
    exclusion_reason  TEXT,

    -- anything the matching could not decide is surfaced, never guessed
    needs_review      INTEGER NOT NULL DEFAULT 0,
    review_note       TEXT,

    created_at        TEXT    NOT NULL,
    updated_at        TEXT    NOT NULL,

    UNIQUE (source, source_id)
);

CREATE INDEX IF NOT EXISTS idx_income_year ON income (tax_year);
CREATE INDEX IF NOT EXISTS idx_income_date ON income (date);


-- ---------------------------------------------------------------- expenses
CREATE TABLE IF NOT EXISTS expenses (
    id                INTEGER PRIMARY KEY,

    source            TEXT    NOT NULL,   -- 'stripe' | 'wise' | 'capitalone' | 'manual'
    source_id         TEXT    NOT NULL,

    date              TEXT    NOT NULL,
    tax_year          INTEGER,

    amount            REAL    NOT NULL,
    currency          TEXT    NOT NULL,
    amount_usd        REAL,
    fx_rate           REAL,
    fx_date           TEXT,

    -- Stage 8 fills this from rules you can edit yourself. Anything it can't
    -- match stays 'uncategorized' and gets listed after every run.
    category          TEXT    NOT NULL DEFAULT 'uncategorized',
    vendor            TEXT,
    description       TEXT,

    -- Stage 7: a payment to your own credit card is a transfer, not an
    -- expense. Excluded, but kept visible so it is obvious it was handled.
    excluded          INTEGER NOT NULL DEFAULT 0,
    exclusion_reason  TEXT,

    needs_review      INTEGER NOT NULL DEFAULT 0,
    review_note       TEXT,

    created_at        TEXT    NOT NULL,
    updated_at        TEXT    NOT NULL,

    UNIQUE (source, source_id)
);

CREATE INDEX IF NOT EXISTS idx_expenses_year   ON expenses (tax_year);
CREATE INDEX IF NOT EXISTS idx_expenses_vendor ON expenses (vendor);


-- ---------------------------------------------------------- stripe_payouts
-- NOT income. This is the reference list Stage 6 compares Wise credits
-- against, so the same money is never counted twice.
CREATE TABLE IF NOT EXISTS stripe_payouts (
    id                INTEGER PRIMARY KEY,

    payout_id         TEXT    NOT NULL UNIQUE,  -- Stripe's own ID, e.g. po_1A2B
    arrival_date      TEXT    NOT NULL,         -- when it lands in Wise
    amount            REAL    NOT NULL,
    currency          TEXT    NOT NULL,
    status            TEXT,                     -- 'paid', 'in_transit', ...

    -- filled in by Stage 6 once a Wise credit is matched to this payout
    matched_source    TEXT,
    matched_source_id TEXT,
    matched_at        TEXT,

    created_at        TEXT    NOT NULL,
    updated_at        TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_payouts_arrival ON stripe_payouts (arrival_date);


-- --------------------------------------------------------------- fx_rates
-- Saved exchange rates. Two reasons this matters:
--   1. re-running a report gives exactly the same numbers as last time
--   2. the rate service isn't asked for something it already answered
--
-- requested_date is the date of the transaction. rate_date is the date the
-- rate actually came from - the European Central Bank only publishes on
-- business days, so a Saturday transaction uses Friday's rate, and this
-- records that honestly rather than hiding it.
CREATE TABLE IF NOT EXISTS fx_rates (
    id                INTEGER PRIMARY KEY,

    requested_date    TEXT    NOT NULL,
    rate_date         TEXT    NOT NULL,
    base_currency     TEXT    NOT NULL,       -- converting FROM
    quote_currency    TEXT    NOT NULL,       -- converting TO (normally USD)
    rate              REAL    NOT NULL,

    source            TEXT    NOT NULL DEFAULT 'frankfurter/ECB',

    -- created_at doubles as "when this rate was fetched"
    created_at        TEXT    NOT NULL,
    updated_at        TEXT    NOT NULL,

    UNIQUE (requested_date, base_currency, quote_currency)
);


-- ------------------------------------------------------------ alerts_sent
-- One row per reminder already sent. alert_key is unique, so the $600
-- contractor alarm rings once and not every morning for the rest of the year.
CREATE TABLE IF NOT EXISTS alerts_sent (
    id                INTEGER PRIMARY KEY,
    alert_key         TEXT    NOT NULL UNIQUE,  -- e.g. 'contractor600:Ayoka:2026'
    alert_type        TEXT    NOT NULL,         -- 'contractor600' | 'quarterly' | 'fbar'
    subject           TEXT,
    detail            TEXT,
    sent_at           TEXT    NOT NULL
);


-- ------------------------------------------------------------------- meta
-- Internal bookkeeping: which version of the layout above this file uses.
CREATE TABLE IF NOT EXISTS meta (
    key               TEXT PRIMARY KEY,
    value             TEXT NOT NULL
);
"""


def init_db(path=None):
    """
    Create the database and its tables if they aren't there yet.

    Safe to call any number of times - it never deletes or overwrites data.
    Returns the open connection.
    """
    connection = connect(path)
    connection.executescript(SCHEMA)
    connection.execute(
        "INSERT INTO meta (key, value) VALUES ('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(SCHEMA_VERSION),),
    )
    connection.commit()
    return connection


def schema_version(connection):
    """Which layout version this database file is on."""
    row = connection.execute(
        "SELECT value FROM meta WHERE key = 'schema_version'"
    ).fetchone()
    return int(row["value"]) if row else None


def table_names(connection):
    """The tables that exist, in alphabetical order."""
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [row["name"] for row in rows]


# ===========================================================================
#  WRITING ROWS
# ===========================================================================
#
# These are "upserts": update if the row already exists, insert if it doesn't.
# That single behaviour is what makes re-running an import harmless.

# Columns holding the result of a currency conversion. They need special
# handling on a re-import - see _upsert() below.
_CONVERSION_COLUMNS = ("amount_usd", "fx_rate", "fx_date")


def _upsert(connection, table, keys, values, protect_conversion=False):
    """
    Shared machinery behind the three upsert functions below.

    keys   - the columns that identify the row (what must be unique)
    values - everything else to store

    On a repeat, every value column is refreshed and updated_at is stamped,
    but created_at keeps its original time so you can still see when a
    transaction first appeared.

    PROTECTING THE CURRENCY CONVERSION
        Stage 4 imports a EUR 900 invoice with no dollar figure - it doesn't
        know the rate. Stage 5 works the rate out and fills it in. Then
        Stage 4 runs again, once more offering no dollar figure.

        Handled naively, that second import erases the conversion, and the
        totals silently drop back to counting that invoice as $0.

        So on a re-import the conversion is kept - but ONLY while the amount
        and currency are unchanged. If Stripe ever corrects an invoice from
        EUR 900 to EUR 1,000, the old dollar figure is now wrong, so it is
        cleared and Stage 5 works it out again. Keeping a stale conversion
        would be worse than having none.
    """
    now = _now()
    all_columns = {**keys, **values, "created_at": now, "updated_at": now}

    column_list = ", ".join(all_columns)
    placeholders = ", ".join("?" for _ in all_columns)
    conflict_columns = ", ".join(keys)

    # On a clash, refresh the value columns - but never created_at.
    assignments = []
    for column in values:
        if protect_conversion and column in _CONVERSION_COLUMNS:
            assignments.append(
                f"{column} = CASE"
                f" WHEN excluded.{column} IS NOT NULL THEN excluded.{column}"
                f" WHEN {table}.amount = excluded.amount"
                f"  AND {table}.currency = excluded.currency"
                f"  THEN {table}.{column}"
                f" ELSE NULL END"
            )
        else:
            assignments.append(f"{column} = excluded.{column}")
    assignments.append("updated_at = excluded.updated_at")

    connection.execute(
        f"INSERT INTO {table} ({column_list}) VALUES ({placeholders}) "
        f"ON CONFLICT({conflict_columns}) DO UPDATE SET {', '.join(assignments)}",
        tuple(all_columns.values()),
    )
    return connection


def upsert_income(connection, *, source, source_id, date, amount, currency,
                  amount_usd=None, fx_rate=None, fx_date=None,
                  description=None, payer=None,
                  excluded=False, exclusion_reason=None,
                  needs_review=False, review_note=None):
    """
    Record one piece of income. Re-recording the same source + source_id
    updates that row instead of adding another.

    IMPORTANT - record income GROSS.
    A $2,000 invoice with a $60 Stripe fee is income of $2,000 plus a
    deductible expense of $60. It is never income of $1,940. Schedule C asks
    for gross receipts, and netting silently throws away the fee deduction.
    """
    return _upsert(
        connection,
        "income",
        {"source": source, "source_id": str(source_id)},
        {
            "date": date,
            "tax_year": _year_of(date),
            "amount": round_money(amount),
            "currency": currency.upper(),
            "amount_usd": round_money(amount_usd),
            "fx_rate": fx_rate,
            "fx_date": fx_date,
            "description": description,
            "payer": payer,
            "excluded": 1 if excluded else 0,
            "exclusion_reason": exclusion_reason,
            "needs_review": 1 if needs_review else 0,
            "review_note": review_note,
        },
        protect_conversion=True,
    )


def upsert_expense(connection, *, source, source_id, date, amount, currency,
                   amount_usd=None, fx_rate=None, fx_date=None,
                   category="uncategorized", vendor=None, description=None,
                   excluded=False, exclusion_reason=None,
                   needs_review=False, review_note=None):
    """Record one expense. Same re-run behaviour as income."""
    return _upsert(
        connection,
        "expenses",
        {"source": source, "source_id": str(source_id)},
        {
            "date": date,
            "tax_year": _year_of(date),
            "amount": round_money(amount),
            "currency": currency.upper(),
            "amount_usd": round_money(amount_usd),
            "fx_rate": fx_rate,
            "fx_date": fx_date,
            "category": category,
            "vendor": vendor,
            "description": description,
            "excluded": 1 if excluded else 0,
            "exclusion_reason": exclusion_reason,
            "needs_review": 1 if needs_review else 0,
            "review_note": review_note,
        },
        protect_conversion=True,
    )


def upsert_payout(connection, *, payout_id, arrival_date, amount, currency,
                  status=None):
    """
    Record a Stripe payout - money Stripe sent onward to your bank.

    This is NOT income and is deliberately kept out of the income table. It
    exists purely so Stage 6 can recognise the same money arriving in Wise and
    refuse to count it twice.
    """
    return _upsert(
        connection,
        "stripe_payouts",
        {"payout_id": str(payout_id)},
        {
            "arrival_date": arrival_date,
            "amount": round_money(amount),
            "currency": currency.upper(),
            "status": status,
        },
    )


def mark_payout_matched(connection, *, payout_id, matched_source,
                        matched_source_id):
    """Note that a Wise credit has been identified as this payout arriving."""
    connection.execute(
        "UPDATE stripe_payouts SET matched_source = ?, matched_source_id = ?, "
        "matched_at = ?, updated_at = ? WHERE payout_id = ?",
        (matched_source, str(matched_source_id), _now(), _now(), str(payout_id)),
    )
    return connection


# ===========================================================================
#  EXCHANGE RATE CACHE
# ===========================================================================

def cache_fx_rate(connection, *, requested_date, rate_date, base_currency,
                  quote_currency, rate, source="frankfurter/ECB"):
    """Save a rate so the same question is never asked twice."""
    return _upsert(
        connection,
        "fx_rates",
        {
            "requested_date": requested_date,
            "base_currency": base_currency.upper(),
            "quote_currency": quote_currency.upper(),
        },
        {
            "rate_date": rate_date,
            "rate": rate,
            "source": source,
        },
    )


def get_cached_fx_rate(connection, *, requested_date, base_currency,
                       quote_currency):
    """
    Look up a saved rate. Returns the row, or None if it was never fetched.
    Stage 5 checks here before going to the internet.
    """
    return connection.execute(
        "SELECT * FROM fx_rates WHERE requested_date = ? "
        "AND base_currency = ? AND quote_currency = ?",
        (requested_date, base_currency.upper(), quote_currency.upper()),
    ).fetchone()


# ===========================================================================
#  ALERTS
# ===========================================================================

def alert_already_sent(connection, alert_key):
    """True if this exact reminder has gone out before."""
    row = connection.execute(
        "SELECT 1 FROM alerts_sent WHERE alert_key = ?", (alert_key,)
    ).fetchone()
    return row is not None


def record_alert(connection, *, alert_key, alert_type, subject=None,
                 detail=None):
    """
    Remember that a reminder was sent.

    Returns True if this was the first time (so it counted as sending), and
    False if it had already gone out - which is how the $600 alarm rings once
    rather than every morning.
    """
    if alert_already_sent(connection, alert_key):
        return False

    connection.execute(
        "INSERT INTO alerts_sent (alert_key, alert_type, subject, detail, sent_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (alert_key, alert_type, subject, detail, _now()),
    )
    return True


# ===========================================================================
#  READING TOTALS
# ===========================================================================

def totals(connection, tax_year=None):
    """
    Add everything up for a year and return it as a dictionary.

    Rows marked `excluded` are left out of the totals - that is exactly what
    the flag is for. They stay in the database so you can see the decision was
    made, rather than a transaction quietly vanishing.

    Amounts that haven't been converted to USD yet count as 0 in the USD
    totals, and are reported separately as `unconverted_*` so an incomplete
    picture is never mistaken for a complete one.
    """
    where_year = "AND tax_year = ?" if tax_year else ""
    params = (tax_year,) if tax_year else ()

    def one(sql):
        return connection.execute(sql, params).fetchone()

    income_row = one(
        f"SELECT COUNT(*) AS n, "
        f"       COALESCE(SUM(amount_usd), 0) AS usd, "
        f"       SUM(amount_usd IS NULL) AS unconverted "
        f"FROM income WHERE excluded = 0 {where_year}"
    )
    expense_row = one(
        f"SELECT COUNT(*) AS n, "
        f"       COALESCE(SUM(amount_usd), 0) AS usd, "
        f"       SUM(amount_usd IS NULL) AS unconverted "
        f"FROM expenses WHERE excluded = 0 {where_year}"
    )
    excluded_income = one(
        f"SELECT COUNT(*) AS n FROM income WHERE excluded = 1 {where_year}"
    )
    review_income = one(
        f"SELECT COUNT(*) AS n FROM income WHERE needs_review = 1 {where_year}"
    )
    review_expenses = one(
        f"SELECT COUNT(*) AS n FROM expenses WHERE needs_review = 1 {where_year}"
    )
    uncategorized = one(
        f"SELECT COUNT(*) AS n FROM expenses "
        f"WHERE excluded = 0 AND category = 'uncategorized' {where_year}"
    )

    income_usd = round_money(income_row["usd"])
    expenses_usd = round_money(expense_row["usd"])

    return {
        "tax_year": tax_year,
        "income_count": income_row["n"],
        "income_usd": income_usd,
        "expense_count": expense_row["n"],
        "expenses_usd": expenses_usd,
        # Net profit is what the tax calculator in Stage 9 starts from.
        "net_profit_usd": round_money(income_usd - expenses_usd),
        "excluded_income_count": excluded_income["n"],
        "needs_review_count": review_income["n"] + review_expenses["n"],
        "uncategorized_expense_count": uncategorized["n"],
        "unconverted_income_count": income_row["unconverted"] or 0,
        "unconverted_expense_count": expense_row["unconverted"] or 0,
    }


def contractor_totals(connection, tax_year, names=None):
    """
    Total paid to each contractor this year, in USD.

    Used by Stage 10's daily check: crossing $600 means a W-9 and a 1099-NEC
    are required. Only counts what is actually in this database.
    """
    names = names or config.CONTRACTORS
    result = {}
    for name in names:
        row = connection.execute(
            "SELECT COALESCE(SUM(amount_usd), 0) AS usd, COUNT(*) AS n "
            "FROM expenses WHERE excluded = 0 AND tax_year = ? "
            "AND (vendor = ? COLLATE NOCASE OR description LIKE ?)",
            (tax_year, name, f"%{name}%"),
        ).fetchone()
        result[name] = {"usd": round_money(row["usd"]), "payments": row["n"]}
    return result
