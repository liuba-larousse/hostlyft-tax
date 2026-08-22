"""
fx.py - converting foreign currency into US dollars.

WHY THIS EXISTS
    The IRS wants US dollars. Your income arrives in USD, EUR and GBP, and
    those cannot simply be added together - EUR 900 and GBP 3,798 are not
    4,698 of anything.

WHERE THE RATES COME FROM
    The Frankfurter API (api.frankfurter.dev). Free, with no key, no signup,
    no quota and no card, because it is a thin public wrapper over the
    reference exchange rates the European Central Bank publishes every day as
    a public service. History goes back to 1999.

THE THREE THINGS THAT CAN GO WRONG, AND WHAT IS DONE ABOUT THEM

  1. The ECB only publishes on BUSINESS DAYS.
     There is no rate for a Saturday, a Sunday, Christmas Day or Easter
     Monday. The rate from the previous business day is used instead, and
     BOTH dates are recorded - the date of the transaction and the date the
     rate actually came from. You can always see which rate was really used.

  2. A future date silently returns a STALE rate.
     Asking the API for a date a week from now returns 200 OK with last
     Friday's rate and no warning at all. A mistyped year would quietly
     produce a wrong but plausible number. So future dates are refused here,
     before the request is ever made.

  3. Only about 30 currencies exist.
     Anything else must fail loudly. Inventing a rate would be far worse
     than saying "I don't know" - it would put a wrong number on a tax
     return with nothing to show it was a guess.

EVERY RATE IS SAVED
    Once fetched, a rate is stored in the fx_rates table. Re-running a report
    next month gives the identical figure rather than today's rate, and the
    service isn't asked the same question twice.

THE SIMPLER OFFICIAL ALTERNATIVE
    The IRS also publishes a single yearly average rate per currency, and
    accepts it. It is less precise but much less to maintain. See the README.
    This module does daily rates; the yearly average is the documented
    fallback if daily ever becomes a burden.
"""

import datetime as dt

import requests

from taxlib import db


API_BASE = "https://api.frankfurter.dev/v1"

# The ECB's reference rates start here.
EARLIEST_DATE = "1999-01-04"

# A gap longer than this between a transaction and the rate used is not a
# normal weekend or public holiday, and is worth a human looking at.
# The longest ordinary gap is about four days (Christmas, Easter).
MAX_REASONABLE_GAP_DAYS = 7

# The currencies the ECB publishes, as of the last check. Kept here so the
# tests and the error messages work without an internet connection. If the
# list ever grows, an unknown currency is still tried against the API before
# being rejected - see get_rate().
KNOWN_CURRENCIES = {
    "AUD", "BRL", "CAD", "CHF", "CNY", "CZK", "DKK", "EUR", "GBP", "HKD",
    "HUF", "IDR", "ILS", "INR", "ISK", "JPY", "KRW", "MXN", "MYR", "NOK",
    "NZD", "PHP", "PLN", "RON", "SEK", "SGD", "THB", "TRY", "USD", "ZAR",
}


class FxError(Exception):
    """Something went wrong converting a currency."""


class UnsupportedCurrency(FxError):
    """A currency the European Central Bank does not publish a rate for."""


class RateUnavailable(FxError):
    """No rate could be obtained for this date."""


def _today():
    """Today's date. Separate function so tests can pin it."""
    return dt.date.today()


# ===========================================================================
#  FETCHING ONE RATE
# ===========================================================================

def fetch_rate(date, base_currency, quote_currency="USD", timeout=25):
    """
    Ask the service for one rate. Returns (rate, actual_date).

    `actual_date` is the business day the rate really came from, which may be
    earlier than the date asked for.

    This is the only function that touches the internet, which keeps
    everything else testable offline.
    """
    response = requests.get(
        f"{API_BASE}/{date}",
        params={"base": base_currency.upper(), "symbols": quote_currency.upper()},
        timeout=timeout,
    )

    if response.status_code == 404:
        raise RateUnavailable(
            f"No rate published for {base_currency.upper()} on {date}.")
    if not response.ok:
        raise RateUnavailable(
            f"The exchange rate service replied {response.status_code} "
            f"for {base_currency.upper()} on {date}.")

    body = response.json()
    rate = (body.get("rates") or {}).get(quote_currency.upper())
    if rate is None:
        raise RateUnavailable(
            f"The service gave no {quote_currency.upper()} rate for "
            f"{base_currency.upper()} on {date}.")

    return float(rate), body.get("date", date)


# ===========================================================================
#  GETTING A RATE, WITH ALL THE CHECKS
# ===========================================================================

def get_rate(connection, date, currency, quote_currency="USD", fetcher=None):
    """
    The rate to turn one unit of `currency` into `quote_currency` on `date`.

    Checks the saved rates first, so the same question is never asked twice
    and a re-run gives the identical number.

    Returns a dictionary:
        rate        the number to multiply by
        rate_date   the business day the rate came from
        days_back   how many days earlier that was (0 on a normal weekday)
        cached      True if it came from the database
        warning     set when something is worth a human look
    """
    currency = (currency or "").upper()
    quote_currency = (quote_currency or "USD").upper()
    fetcher = fetcher or fetch_rate

    # -- same currency: no conversion, and never ask the service ------------
    # (Asking for USD->USD actually returns an error, so this matters.)
    if currency == quote_currency:
        return {"rate": 1.0, "rate_date": date, "days_back": 0,
                "cached": False, "warning": None}

    # -- is the date sane? --------------------------------------------------
    try:
        requested = dt.date.fromisoformat(date)
    except (TypeError, ValueError):
        raise FxError(f"'{date}' is not a date in YYYY-MM-DD form.")

    # A future date returns a stale rate with no warning, so it is refused.
    if requested > _today():
        raise RateUnavailable(
            f"{date} is in the future. There is no exchange rate for a day "
            f"that hasn't happened yet.\n"
            f"The service would quietly hand back an old rate instead of "
            f"refusing, so this check exists here.\n"
            f"Most likely the date on that transaction is wrong.")

    if date < EARLIEST_DATE:
        raise RateUnavailable(
            f"{date} is before {EARLIEST_DATE}, which is as far back as "
            f"European Central Bank rates go.")

    # -- already saved? -----------------------------------------------------
    cached = db.get_cached_fx_rate(connection, requested_date=date,
                                   base_currency=currency,
                                   quote_currency=quote_currency)
    if cached:
        gap = (requested - dt.date.fromisoformat(cached["rate_date"])).days
        return {"rate": cached["rate"], "rate_date": cached["rate_date"],
                "days_back": gap, "cached": True, "warning": None}

    # -- a currency nobody publishes a rate for -----------------------------
    # Unknown currencies are still tried once, in case the list has grown
    # since this was written. What is never done is guessing a number.
    if currency not in KNOWN_CURRENCIES:
        try:
            rate, actual_date = fetcher(date, currency, quote_currency)
        except RateUnavailable:
            raise UnsupportedCurrency(
                f"No exchange rate is published for {currency}.\n"
                f"\n"
                f"The European Central Bank covers about 30 currencies:\n"
                f"  {', '.join(sorted(KNOWN_CURRENCIES))}\n"
                f"\n"
                f"Nothing has been guessed. Options:\n"
                f"  - enter the US dollar amount for that transaction by hand\n"
                f"  - or use the IRS yearly average rate (see the README)")
    else:
        rate, actual_date = fetcher(date, currency, quote_currency)

    # -- sanity-check what came back ----------------------------------------
    actual = dt.date.fromisoformat(actual_date)
    if actual > requested:
        raise RateUnavailable(
            f"The service returned a rate dated {actual_date}, which is "
            f"AFTER the transaction on {date}. Refusing to use it.")

    days_back = (requested - actual).days
    warning = None
    if days_back > MAX_REASONABLE_GAP_DAYS:
        warning = (f"the rate used is {days_back} days older than the "
                   f"transaction ({actual_date} for a transaction on {date}). "
                   f"A weekend or public holiday is 1-4 days; this is longer, "
                   f"so it is worth checking.")

    db.cache_fx_rate(connection, requested_date=date, rate_date=actual_date,
                     base_currency=currency, quote_currency=quote_currency,
                     rate=rate)

    return {"rate": rate, "rate_date": actual_date, "days_back": days_back,
            "cached": False, "warning": warning}


def convert(connection, amount, currency, date, quote_currency="USD",
            fetcher=None):
    """
    Convert an amount into US dollars.

    Returns the converted amount plus the rate and the date it came from, so
    the working is always visible rather than just a final number.
    """
    info = get_rate(connection, date, currency, quote_currency, fetcher=fetcher)
    converted = db.round_money(amount * info["rate"])
    return {"amount": converted, **info}


# ===========================================================================
#  FILLING IN THE DATABASE
# ===========================================================================

def rows_needing_conversion(connection, table, tax_year=None):
    """Everything that has no US dollar figure yet."""
    where_year = "AND tax_year = ?" if tax_year else ""
    params = (tax_year,) if tax_year else ()
    return connection.execute(
        f"SELECT id, date, amount, currency, description FROM {table} "
        f"WHERE amount_usd IS NULL {where_year} ORDER BY date",
        params,
    ).fetchall()


def set_usd_amount(connection, table, row_id, amount_usd, rate, rate_date):
    """Store the dollar figure alongside the original - never replacing it."""
    connection.execute(
        f"UPDATE {table} SET amount_usd = ?, fx_rate = ?, fx_date = ?, "
        f"updated_at = ? WHERE id = ?",
        (amount_usd, rate, rate_date, db._now(), row_id),
    )


def convert_pending(connection, tax_year=None, dry_run=False, fetcher=None):
    """
    Convert everything that still has no dollar figure.

    The original amount and currency are never touched. The dollar figure is
    stored next to them, along with the rate and the date it came from, so
    the working can always be checked.

    Returns a summary: what was converted, what failed, and any warnings.
    """
    converted, failed, warnings = [], [], []

    for table in ("income", "expenses"):
        for row in rows_needing_conversion(connection, table, tax_year):
            try:
                result = convert(connection, row["amount"], row["currency"],
                                 row["date"], fetcher=fetcher)
            except FxError as error:
                failed.append({
                    "table": table, "id": row["id"], "date": row["date"],
                    "amount": row["amount"], "currency": row["currency"],
                    "description": row["description"], "reason": str(error),
                })
                continue

            if result["warning"]:
                warnings.append({
                    "table": table, "date": row["date"],
                    "currency": row["currency"], "note": result["warning"],
                })

            if not dry_run:
                set_usd_amount(connection, table, row["id"], result["amount"],
                               result["rate"], result["rate_date"])

            converted.append({
                "table": table, "id": row["id"], "date": row["date"],
                "amount": row["amount"], "currency": row["currency"],
                "amount_usd": result["amount"], "rate": result["rate"],
                "rate_date": result["rate_date"],
                "days_back": result["days_back"],
                "description": row["description"],
            })

    if not dry_run:
        connection.commit()

    return {"converted": converted, "failed": failed, "warnings": warnings}
