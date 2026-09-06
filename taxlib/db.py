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
    wise_jars       per-person Wise jar balances over time
    contractor_ledger  earned / in jar / withdrawn, per person

TWO BUSINESSES, ONE TAX RETURN
    Every income and expense row carries a `business` tag:

        hostlyft   work done through Hostlyft LLC
        marcus     separate work, paid into the personal Wise account

    They report separately - so the Hostlyft profit-and-loss used for team
    splits stays honest - but the tax calculator adds both together, because
    a single-member LLC is a "disregarded entity": both land on the same
    1040. Self-employment tax is worked out on the combined figure, and the
    FEIE and Social Security caps are combined limits too.

    Leaving Marcus out would understate self-employment tax by roughly
    $6,900.

A JAR IS NOT A PAYMENT
    A Wise jar is a labelled pot inside her own account. Moving money into
    one is not paying anybody - it is still her money. So:

      - allocating to a jar is NOT a deductible expense
      - only an actual WITHDRAWAL is deductible
      - only WITHDRAWALS count toward the $600 contractor threshold
      - jar balances still count toward the FBAR $10,000 test

    Jar balances therefore live in `wise_jars`, never in `expenses`. The
    expenses table physically cannot hold a jar allocation, which is a
    stronger guarantee than remembering not to put one there.

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
#
#   1  income, expenses, stripe_payouts, fx_rates, alerts_sent
#   2  + business column on income and expenses (hostlyft | marcus)
#      + wise_jars, contractor_ledger
#   3  + jar_movements: money moved INTO and OUT OF each jar
#   4  + contractor_forms: whether each person's W-9 or W-8BEN is on file
SCHEMA_VERSION = 4


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


BUSINESS_HOSTLYFT = config.BUSINESS_HOSTLYFT
BUSINESS_MARCUS = config.BUSINESS_MARCUS

# The category marking a payment actually transferred OUT to a team member.
# Only rows with this category count toward the $600 threshold.
CATEGORY_CONTRACTOR = "contractor"


def _checked_business(business):
    """
    Refuse an unknown business tag.

    Only 'hostlyft' and 'marcus' exist. A typo like 'Marcus' or 'marcuss'
    would silently create a third business that no report ever shows, and
    the money would vanish from every total without an error.
    """
    tag = (business or "").strip().lower()
    if tag not in config.BUSINESSES:
        raise ValueError(
            f"'{business}' is not a known business. "
            f"Use one of: {', '.join(config.BUSINESSES)}")
    return tag


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

    -- which business this belongs to. Reported separately, taxed together.
    business          TEXT    NOT NULL DEFAULT 'hostlyft',

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
CREATE INDEX IF NOT EXISTS idx_income_business ON income (business);
CREATE INDEX IF NOT EXISTS idx_income_date ON income (date);


-- ---------------------------------------------------------------- expenses
CREATE TABLE IF NOT EXISTS expenses (
    id                INTEGER PRIMARY KEY,

    source            TEXT    NOT NULL,   -- 'stripe' | 'wise' | 'capitalone' | 'manual'
    source_id         TEXT    NOT NULL,

    business          TEXT    NOT NULL DEFAULT 'hostlyft',

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
CREATE INDEX IF NOT EXISTS idx_expenses_business ON expenses (business);
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

-- -------------------------------------------------------------- wise_jars
-- A Wise "jar" is a labelled savings pot inside her own account, used to set
-- money aside for each team member.
--
-- MONEY IN A JAR IS STILL HER MONEY. Putting it there pays nobody. So a jar
-- balance is recorded here as an observation - what was in the pot on a given
-- day - and never as an expense. Only the withdrawal out of the jar is a
-- payment, and that goes in `expenses`.
--
-- One row per jar per observation date, so the balance can be tracked over
-- time and re-reading the same day updates rather than duplicates.
CREATE TABLE IF NOT EXISTS wise_jars (
    id                INTEGER PRIMARY KEY,

    balance_id        TEXT    NOT NULL,      -- Wise's id for the jar
    jar_name          TEXT    NOT NULL,      -- what she called it in Wise
    person            TEXT,                  -- who it is for, once matched

    observed_on       TEXT    NOT NULL,      -- YYYY-MM-DD this was read
    amount            REAL    NOT NULL,      -- balance in its own currency
    currency          TEXT    NOT NULL,
    amount_usd        REAL,
    fx_rate           REAL,
    fx_date           TEXT,

    created_at        TEXT    NOT NULL,
    updated_at        TEXT    NOT NULL,

    UNIQUE (balance_id, observed_on)
);

CREATE INDEX IF NOT EXISTS idx_jars_person ON wise_jars (person);


-- ---------------------------------------------------------- jar_movements
-- Money moved into or out of a jar.
--
-- STILL NOT A PAYMENT. Moving money into Ayoka's jar does not pay Ayoka -
-- it is Liuba's money, relabelled inside her own account. It is not
-- deductible and does not count toward $600. Only a transfer OUT of Wise
-- to the person is.
--
-- So why record it? Because it is the best available ESTIMATE of what the
-- deduction will become. The team withdraw before year end, so this month's
-- allocation is next quarter's deduction. Kept in its own table, never in
-- `expenses`, so the two can be shown side by side without any chance of
-- one being added to the other.
CREATE TABLE IF NOT EXISTS jar_movements (
    id                INTEGER PRIMARY KEY,

    source_id         TEXT    NOT NULL UNIQUE,   -- the Wise reference
    date              TEXT    NOT NULL,
    tax_year          INTEGER,

    jar_name          TEXT    NOT NULL,
    person            TEXT,                      -- once matched to the roster

    -- 'in'  money allocated to the jar
    -- 'out' money taken back out of the jar into the operating balance
    direction         TEXT    NOT NULL,

    amount            REAL    NOT NULL,
    currency          TEXT    NOT NULL,
    amount_usd        REAL,
    fx_rate           REAL,
    fx_date           TEXT,

    description       TEXT,
    created_at        TEXT    NOT NULL,
    updated_at        TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_jarmoves_person ON jar_movements (person);
CREATE INDEX IF NOT EXISTS idx_jarmoves_year ON jar_movements (tax_year);


-- ------------------------------------------------------- contractor_ledger
-- The three numbers per person that must never be confused with each other:
--
--   earned_usd     what the Google Sheet's split calculation says they earned
--   in_jar_usd     what is sitting in their Wise jar right now
--   withdrawn_usd  what has actually been transferred out to them
--
-- ONLY `withdrawn_usd` IS THE TAX DEDUCTION, and only it counts toward the
-- $600 threshold that triggers a W-9 and a 1099-NEC.
--
-- They are stored side by side precisely so the gap between them is visible.
-- Someone who earned $5,000 and withdrew $3,200 has $1,800 still owed to
-- them, and that gap is a fact she should see rather than a rounding error.
CREATE TABLE IF NOT EXISTS contractor_ledger (
    id                INTEGER PRIMARY KEY,

    person            TEXT    NOT NULL,      -- the canonical full name
    tax_year          INTEGER NOT NULL,
    as_of             TEXT    NOT NULL,      -- YYYY-MM-DD this was worked out

    earned_usd        REAL    NOT NULL DEFAULT 0,
    in_jar_usd        REAL    NOT NULL DEFAULT 0,
    withdrawn_usd     REAL    NOT NULL DEFAULT 0,

    -- withdrawn minus earned. Negative means money is still owed.
    gap_usd           REAL    NOT NULL DEFAULT 0,

    notes             TEXT,

    created_at        TEXT    NOT NULL,
    updated_at        TEXT    NOT NULL,

    UNIQUE (person, tax_year, as_of)
);


-- -------------------------------------------------------- contractor_forms
-- Whether the tax form each team member owes has actually been RECEIVED.
--
-- The roster in config.py knows which form each person NEEDS. That is a
-- different fact from whether it is sitting in a folder, and only this
-- table records the second one. Keeping them apart matters: the roster is
-- a decision about someone's tax status and should not be edited casually,
-- while this table changes every time a form arrives.
--
-- WHY `expires_on` EXISTS
--   A W-9 does not expire. A W-8BEN does: it is valid from the day it is
--   signed until the last day of the THIRD following calendar year. One
--   signed in June 2026 lapses on 31 December 2029. An expired W-8BEN is
--   worth no more than a missing one, and nothing else in this system
--   would ever notice, which is exactly why it is stored rather than
--   remembered.
--
-- WHY `has_tin` EXISTS SEPARATELY FROM `received`
--   A W-9 that arrives without a taxpayer ID number does not do its job:
--   payments become subject to 24% backup withholding. So "the form came
--   back" and "the form is usable" are two different questions.
CREATE TABLE IF NOT EXISTS contractor_forms (
    id                INTEGER PRIMARY KEY,

    -- the canonical full name, matching the roster in config.py
    person            TEXT    NOT NULL UNIQUE,

    -- 'W-9' or 'W-8BEN'. Stored as well as looked up, so the record shows
    -- which form was actually collected rather than which one is owed now.
    form_type         TEXT    NOT NULL,

    received          INTEGER NOT NULL DEFAULT 0,   -- 0 = no, 1 = yes
    received_on       TEXT,                          -- YYYY-MM-DD
    expires_on        TEXT,                          -- W-8BEN only; NULL for W-9

    -- W-9 only. 0 on a received W-9 means backup withholding applies.
    has_tin           INTEGER NOT NULL DEFAULT 0,

    notes             TEXT,

    created_at        TEXT    NOT NULL,
    updated_at        TEXT    NOT NULL
);


-- ------------------------------------------------------------------- meta
-- Internal bookkeeping: which version of the layout above this file uses.
CREATE TABLE IF NOT EXISTS meta (
    key               TEXT PRIMARY KEY,
    value             TEXT NOT NULL
);
"""


# ===========================================================================
#  UPGRADING AN EXISTING DATABASE
# ===========================================================================
#
# "CREATE TABLE IF NOT EXISTS" adds tables that are missing, but it will not
# add a COLUMN to a table that already exists. So when a later stage needs a
# new column, the database already holding real financial records has to be
# altered in place.
#
# The alternative - deleting and rebuilding - would throw away every
# transaction, every categorisation decision and the record of which alerts
# have already fired. That is never the right trade.
#
# Each step below is written so running it twice is harmless.

def _columns(connection, table):
    return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}


def _add_column_if_missing(connection, table, column, definition):
    """ALTER TABLE, but only if the column isn't already there."""
    if column in _columns(connection, table):
        return False
    connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    return True


def _migrate_2_to_3(connection):
    """
    Version 2 -> 3.

    Adds jar_movements. Nothing to alter - the CREATE TABLE above makes it -
    but the step exists so the version is recorded and the intent is on file.
    """
    return ["added jar_movements (allocations into and out of each jar)"]


def _migrate_1_to_2(connection):
    """
    Version 1 -> 2.

    Adds the `business` column to income and expenses so the two income
    streams - Hostlyft LLC and the separate Marcus work - report separately
    while still being taxed together.

    Everything already in the database predates the Marcus work being
    tracked, and is Hostlyft. The column defaults to 'hostlyft', so existing
    rows are correct without being touched.

    wise_jars and contractor_ledger are new tables, so the CREATE TABLE
    statements above have already made them.
    """
    changes = []
    for table in ("income", "expenses"):
        if _add_column_if_missing(connection, table, "business",
                                  "TEXT NOT NULL DEFAULT 'hostlyft'"):
            changes.append(f"added `business` to {table}, existing rows set "
                           f"to 'hostlyft'")

    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_income_business ON income (business)")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_expenses_business ON expenses (business)")
    return changes


def _migrate_3_to_4(connection):
    """
    Version 3 -> 4.

    Adds contractor_forms. It is a brand new table, so the CREATE TABLE in
    the schema above has already built it by the time anything reads it -
    there is nothing to copy across and no existing row to change.

    Deliberately NOT pre-filled with a row per person. An empty table means
    "no form has been recorded for anybody", which is the truthful starting
    position. Writing rows here that say `received = 0` would look identical
    but invites the opposite reading - that someone checked and found them
    missing.
    """
    return ["added contractor_forms (whether each W-9 / W-8BEN is on file)"]


# version to reach -> the function that gets there
MIGRATIONS = {
    2: _migrate_1_to_2,
    3: _migrate_2_to_3,
    4: _migrate_3_to_4,
}


def migrate(connection, verbose=False):
    """
    Bring an older database up to the current layout, in place.

    Returns the list of changes made - empty if it was already current.
    """
    current = schema_version(connection)
    if current is None:          # brand new; SCHEMA already built it correctly
        return []

    changes = []
    for version in sorted(MIGRATIONS):
        if current < version:
            step_changes = MIGRATIONS[version](connection)
            for change in step_changes:
                changes.append(f"v{version}: {change}")
                if verbose:
                    print(f"  {change}")
            current = version

    return changes


def init_db(path=None, verbose=False):
    """
    Create the database if it isn't there, or bring an older one up to date.

    Safe to call any number of times - it never deletes or overwrites data.
    Returns the open connection.
    """
    connection = connect(path)

    # What version is this file on? Read it BEFORE creating anything, since
    # creating the meta table would otherwise hide the answer.
    existing_version = None
    has_meta = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'"
    ).fetchone()
    if has_meta:
        existing_version = schema_version(connection)

    # ORDER MATTERS. Migrations run FIRST, on the tables as they currently
    # are. The create-script below includes an index on income(business), and
    # that index cannot be built until the migration has added the column -
    # so running the create-script first fails with "no such column".
    if existing_version is not None and existing_version < SCHEMA_VERSION:
        migrate(connection, verbose=verbose)

    # Then add anything still missing: new tables, new indexes. Harmless if
    # they all already exist.
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
                  business=BUSINESS_HOSTLYFT,
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
            "business": _checked_business(business),
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
                   business=BUSINESS_HOSTLYFT,
                   amount_usd=None, fx_rate=None, fx_date=None,
                   category="uncategorized", vendor=None, description=None,
                   excluded=False, exclusion_reason=None,
                   needs_review=False, review_note=None):
    """
    Record one expense. Same re-run behaviour as income.

    NEVER used for a Wise jar allocation. Moving money into a jar pays
    nobody - it is still her money. Jar balances go in `wise_jars`; only the
    withdrawal out of a jar is an expense.

    An owner's draw is not an expense either. Record it with excluded=True
    and a reason, so it stays visible without reducing taxable profit.
    """
    return _upsert(
        connection,
        "expenses",
        {"source": source, "source_id": str(source_id)},
        {
            "business": _checked_business(business),
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

def totals(connection, tax_year=None, business=None):
    """
    Add everything up for a year and return it as a dictionary.

    `business` filters to one stream ('hostlyft' or 'marcus'). Left out, it
    covers BOTH - which is what the tax calculation needs, because
    self-employment tax is worked out on combined net earnings.

    Rows marked `excluded` are left out of the totals - that is exactly what
    the flag is for. They stay in the database so you can see the decision was
    made, rather than a transaction quietly vanishing.

    Amounts that haven't been converted to USD yet count as 0 in the USD
    totals, and are reported separately as `unconverted_*` so an incomplete
    picture is never mistaken for a complete one.
    """
    conditions, params = [], []
    if tax_year:
        conditions.append("AND tax_year = ?")
        params.append(tax_year)
    if business:
        conditions.append("AND business = ?")
        params.append(_checked_business(business))
    where_year = " ".join(conditions)
    params = tuple(params)

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

    # How much of each category actually reduces taxable profit. Meals are
    # the only one below 100% today; the table lives in config.py so the
    # rule can change without touching this query.
    by_category = connection.execute(
        f"SELECT category, COALESCE(SUM(amount_usd), 0) AS usd "
        f"FROM expenses WHERE excluded = 0 {where_year} GROUP BY category",
        params).fetchall()
    deductible = round_money(sum(
        (row["usd"] or 0) * config.deductible_share(row["category"])
        for row in by_category))

    income_usd = round_money(income_row["usd"])
    expenses_usd = round_money(expense_row["usd"])

    return {
        "tax_year": tax_year,
        "business": business,
        "income_count": income_row["n"],
        "income_usd": income_usd,
        "expense_count": expense_row["n"],
        "expenses_usd": expenses_usd,

        # WHAT YOU SPENT, AND WHAT YOU MAY DEDUCT, ARE NOT THE SAME NUMBER.
        #
        # Almost every category is deductible in full. Business meals are
        # 50%. Reporting only the deductible figure would leave the sheet
        # disagreeing with her bank for no visible reason, so both are
        # carried and the difference is shown as its own line.
        "deductible_expenses_usd": deductible,
        "non_deductible_usd": round_money(expenses_usd - deductible),

        # Net profit is what the tax calculator in Stage 9 starts from, and
        # it uses the DEDUCTIBLE figure - that is the whole point of it.
        "net_profit_usd": round_money(income_usd - deductible),
        "net_profit_before_limits_usd": round_money(income_usd - expenses_usd),
        "excluded_income_count": excluded_income["n"],
        "needs_review_count": review_income["n"] + review_expenses["n"],
        "uncategorized_expense_count": uncategorized["n"],
        "unconverted_income_count": income_row["unconverted"] or 0,
        "unconverted_expense_count": expense_row["unconverted"] or 0,
    }


def contractor_totals(connection, tax_year, people=None):
    """
    How much has actually been WITHDRAWN by each team member this year.

    THIS COUNTS WITHDRAWALS, NOT ALLOCATIONS.

    Money moved into someone's Wise jar has not been paid to them - it is
    still Liuba's money, sitting in her own account under a label. It is not
    deductible and it does not count toward the $600 threshold that triggers
    a W-9 and a 1099-NEC.

    Two things enforce that here:

      1. jar balances are physically stored in `wise_jars`, never in
         `expenses`, so there is no row for this query to pick up by mistake
      2. only rows categorised as an actual transfer out are counted

    Matching uses full names AND nicknames, since a Wise transfer may be
    labelled either way - "Ayoka" and "Yetunde Olaniyan" are one person.

    Owner's draws are excluded rows, so they never appear here either.
    """
    people = people or config.CONTRACTORS
    result = {}

    for person in people:
        labels = config.all_names_for(person)

        # vendor matches exactly; description matches loosely, because Wise
        # writes things like "Transfer to Ayoka - September".
        clauses = " OR ".join(
            ["vendor = ? COLLATE NOCASE"] * len(labels)
            + ["description LIKE ?"] * len(labels))
        values = list(labels) + [f"%{label}%" for label in labels]

        row = connection.execute(
            f"SELECT COALESCE(SUM(amount_usd), 0) AS usd, COUNT(*) AS n, "
            f"       MAX(date) AS latest "
            f"FROM expenses "
            f"WHERE excluded = 0 AND category = ? AND tax_year = ? "
            f"  AND ({clauses})",
            [CATEGORY_CONTRACTOR, tax_year] + values,
        ).fetchone()

        withdrawn = round_money(row["usd"])

        # THE $600 THRESHOLD ONLY EXISTS FOR A US PERSON.
        #
        # It is the Form 1099-NEC filing threshold, and 1099-NEC reports
        # payments to US persons. For a non-US person doing the work
        # outside the United States, the payment is foreign-source income
        # (IRC 861(a)(3) sources personal services by WHERE THE WORK IS
        # DONE). Foreign-source income paid to a foreign person is not
        # reportable on a 1099-NEC, is not reportable on a 1042-S, and is
        # not subject to withholding - so there is no dollar threshold of
        # any kind to cross.
        #
        # Tracking "$600" against them would invent an obligation that
        # does not exist and imply a deadline that is not real. What they
        # need is a W-8BEN on file, from the first dollar, which Stage 12
        # tracks separately and without any threshold.
        #
        # None, not False: the question does not apply, which is a
        # different fact from the answer being no. Someone paid $5,470
        # showing "over_600: False" would be actively misleading.
        threshold_applies = bool(person["issues_1099"])
        result[person["name"]] = {
            "person": person,
            "withdrawn_usd": withdrawn,
            "withdrawals": row["n"],
            "latest_withdrawal": row["latest"],
            "threshold_applies": threshold_applies,
            "over_600": (withdrawn >= 600) if threshold_applies else None,
            "needs_1099": threshold_applies and withdrawn >= 600,
            "form": person["form"],
        }

    return result


# ===========================================================================
#  CONTRACTOR FORMS  -  the W-9 / W-8BEN paperwork
# ===========================================================================

def w8ben_expires_on(received_on):
    """
    When a W-8BEN signed on this date stops being valid.

    The rule: valid from the day it is signed until the last day of the
    THIRD following calendar year. Signed any day in 2026 -> expires
    2029-12-31. The day and month of signing make no difference, which is
    why this only reads the year.

    (There is an exception for a W-8BEN carrying a US taxpayer ID number,
    which can stay valid indefinitely. None of the four foreign contractors
    here has one, so the plain rule is what gets applied - and the
    conservative direction of the error is to re-collect a form that was
    still valid, not to rely on one that lapsed.)
    """
    if not received_on:
        return None
    year = int(str(received_on)[:4])
    return f"{year + 3}-12-31"


def record_form(connection, *, person, form_type, received=True,
                received_on=None, has_tin=False, notes=None):
    """
    Record that someone's form has come back - or un-record it.

    Re-running with the same person updates that one row rather than adding
    a second, so this is safe to repeat.

    `expires_on` is worked out here rather than being asked for, because it
    follows from the signing date by a fixed rule and a hand-typed date
    would just be somewhere else for it to be wrong.
    """
    form_type = (form_type or "").strip()
    expires_on = (w8ben_expires_on(received_on)
                  if received and form_type == "W-8BEN" else None)

    # has_tin is only meaningful for a W-9. Forcing it to 0 elsewhere stops
    # a stray True on a W-8BEN row reading as though a TIN was collected.
    tin = 1 if (received and form_type == "W-9" and has_tin) else 0

    now = _now()
    connection.execute(
        "INSERT INTO contractor_forms "
        "  (person, form_type, received, received_on, expires_on, has_tin, "
        "   notes, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(person) DO UPDATE SET "
        "  form_type = excluded.form_type, "
        "  received = excluded.received, "
        "  received_on = excluded.received_on, "
        "  expires_on = excluded.expires_on, "
        "  has_tin = excluded.has_tin, "
        "  notes = excluded.notes, "
        "  updated_at = excluded.updated_at",
        (person, form_type, 1 if received else 0, received_on, expires_on,
         tin, notes, now, now),
    )
    return connection.execute(
        "SELECT * FROM contractor_forms WHERE person = ?", (person,)
    ).fetchone()


def get_form(connection, person):
    """The stored form record for one person, or None if nothing recorded."""
    return connection.execute(
        "SELECT * FROM contractor_forms WHERE person = ? COLLATE NOCASE",
        (person,),
    ).fetchone()


def all_forms(connection):
    """Every stored form record, keyed by person."""
    return {row["person"]: row for row in
            connection.execute("SELECT * FROM contractor_forms").fetchall()}


# ===========================================================================
#  WISE JARS  -  money set aside, but NOT yet paid to anyone
# ===========================================================================

def record_jar_balance(connection, *, balance_id, jar_name, observed_on,
                       amount, currency, person=None, amount_usd=None,
                       fx_rate=None, fx_date=None):
    """
    Record what was sitting in one jar on one day.

    This is an OBSERVATION, not a transaction. Nothing here is an expense and
    nothing here counts toward anybody's $600 threshold. Re-reading the same
    jar on the same day updates the row rather than adding another.

    Jar balances DO count toward the FBAR $10,000 test, because the money is
    still hers, held in a foreign account.
    """
    return _upsert(
        connection,
        "wise_jars",
        {"balance_id": str(balance_id), "observed_on": observed_on},
        {
            "jar_name": jar_name,
            "person": person,
            "amount": round_money(amount),
            "currency": currency.upper(),
            "amount_usd": round_money(amount_usd),
            "fx_rate": fx_rate,
            "fx_date": fx_date,
        },
        protect_conversion=True,
    )


def latest_jar_balances(connection, on_or_before=None):
    """
    The most recent reading for each jar, one row per jar.

    A jar is read repeatedly over time, so this picks the newest observation
    of each - optionally as it stood on a given date, which is how the
    "still in jars on 31 December" check works.
    """
    params = []
    date_filter = ""
    if on_or_before:
        date_filter = "WHERE observed_on <= ?"
        params.append(on_or_before)

    # Group by jar, keep only the newest observation of each.
    return connection.execute(
        f"""
        SELECT * FROM wise_jars
        WHERE id IN (
            SELECT id FROM wise_jars
            {date_filter}
            GROUP BY balance_id
            HAVING observed_on = MAX(observed_on)
        )
        ORDER BY person, jar_name
        """,
        params,
    ).fetchall()


def total_in_jars_usd(connection, on_or_before=None):
    """
    Everything sitting in jars, in US dollars.

    Money still in jars on 31 December is not deductible that year, but it is
    still her money - so it inflates taxable profit. At 15.3% self-employment
    tax, $8,000 left in jars costs about $1,224 in real tax. That is what the
    1 December reminder is for.
    """
    rows = latest_jar_balances(connection, on_or_before)
    return round_money(sum(row["amount_usd"] or 0 for row in rows))


# ===========================================================================
#  CONTRACTOR LEDGER  -  the three numbers, side by side
# ===========================================================================

def record_jar_movement(connection, *, source_id, date, jar_name, direction,
                        amount, currency, person=None, amount_usd=None,
                        fx_rate=None, fx_date=None, description=None):
    """
    Record money moving into or out of a jar.

    NOT an expense and never counted as one. See the table comment.
    """
    if direction not in ("in", "out"):
        raise ValueError(f"direction must be 'in' or 'out', not '{direction}'")

    return _upsert(
        connection, "jar_movements", {"source_id": str(source_id)},
        {
            "date": date, "tax_year": _year_of(date),
            "jar_name": jar_name, "person": person, "direction": direction,
            "amount": round_money(amount), "currency": currency.upper(),
            "amount_usd": round_money(amount_usd),
            "fx_rate": fx_rate, "fx_date": fx_date,
            "description": description,
        },
        protect_conversion=True,
    )


def jar_allocations_by_month(connection, tax_year, person=None):
    """
    How much was set aside for each person, month by month.

    This is an ESTIMATE of a future deduction, not a deduction. The team
    withdraw before year end, so what is allocated now becomes deductible
    when it leaves. Shown beside the actual withdrawals so the gap is
    visible; never added to them.
    """
    where = "AND person = ?" if person else ""
    params = [tax_year] + ([person] if person else [])
    return connection.execute(
        f"SELECT substr(date, 1, 7) AS month, person, "
        f"       SUM(CASE WHEN direction = 'in' THEN amount_usd ELSE 0 END) "
        f"           AS allocated, "
        f"       SUM(CASE WHEN direction = 'out' THEN amount_usd ELSE 0 END) "
        f"           AS returned "
        f"FROM jar_movements WHERE tax_year = ? AND person IS NOT NULL {where} "
        f"GROUP BY month, person ORDER BY month, person", params).fetchall()


def contractor_withdrawals_by_month(connection, tax_year):
    """Actual payments out, month by month - the real deduction."""
    rows = {}
    for person in config.CONTRACTORS:
        labels = config.all_names_for(person)
        clauses = " OR ".join(["vendor = ? COLLATE NOCASE"] * len(labels)
                              + ["description LIKE ?"] * len(labels))
        values = list(labels) + [f"%{label}%" for label in labels]
        for row in connection.execute(
                f"SELECT substr(date, 1, 7) AS month, "
                f"       COALESCE(SUM(amount_usd), 0) AS withdrawn "
                f"FROM expenses WHERE excluded = 0 AND category = ? "
                f"AND tax_year = ? AND ({clauses}) GROUP BY month",
                [CATEGORY_CONTRACTOR, tax_year] + values):
            rows[(row["month"], person["name"])] = round_money(row["withdrawn"])
    return rows


def record_contractor_ledger(connection, *, person, tax_year, as_of,
                             earned_usd=0, in_jar_usd=0, withdrawn_usd=0,
                             notes=None):
    """
    Store the three numbers for one person on one day.

        earned      what the Google Sheet's split calculation says
        in_jar      what is sitting in their jar
        withdrawn   what has actually been transferred to them

    Only `withdrawn` is the tax deduction. They are kept side by side so the
    gap is visible: someone who earned $5,000 and withdrew $3,200 is still
    owed $1,800, and that should be plain to see rather than buried.
    """
    earned = round_money(earned_usd) or 0
    withdrawn = round_money(withdrawn_usd) or 0

    return _upsert(
        connection,
        "contractor_ledger",
        {"person": person, "tax_year": tax_year, "as_of": as_of},
        {
            "earned_usd": earned,
            "in_jar_usd": round_money(in_jar_usd) or 0,
            "withdrawn_usd": withdrawn,
            "gap_usd": round_money(withdrawn - earned),
            "notes": notes,
        },
    )
