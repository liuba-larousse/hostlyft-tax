"""
Automatic checks for Stage 5 (currency conversion).

These use a stand-in for the rate service, so they run without an internet
connection and always give the same answer.

The two that matter most:

  * test_a_saturday_uses_fridays_rate_and_says_so
        the European Central Bank doesn't publish at weekends

  * test_a_future_date_is_refused
        the real service returns 200 OK with a STALE rate for a future date,
        which would put a wrong but plausible number on a tax return
"""

import datetime as dt

import pytest

from taxlib import db, fx


# ---------------------------------------------------------------------------
#  A stand-in for the rate service
# ---------------------------------------------------------------------------

# Rates on real business days. 2026-08-08 and 08-09 are a weekend.
FAKE_RATES = {
    "2026-08-03": 1.3470,
    "2026-08-04": 1.3446,
    "2026-08-05": 1.3500,
    "2026-08-06": 1.3510,
    "2026-08-07": 1.1535,
}


def fake_fetcher(date, base_currency, quote_currency="USD"):
    """
    Behaves like the real service: walks BACK to the last date it has, and
    reports which date that was.
    """
    if base_currency.upper() not in fx.KNOWN_CURRENCIES:
        raise fx.RateUnavailable(f"No rate published for {base_currency}.")

    asked = dt.date.fromisoformat(date)
    for step in range(0, 30):
        candidate = (asked - dt.timedelta(days=step)).isoformat()
        if candidate in FAKE_RATES:
            return FAKE_RATES[candidate], candidate
    raise fx.RateUnavailable(f"No rate published on {date}.")


def counting_fetcher():
    """A fetcher that records how many times it was called."""
    calls = []

    def fetcher(date, base_currency, quote_currency="USD"):
        calls.append((date, base_currency))
        return fake_fetcher(date, base_currency, quote_currency)

    fetcher.calls = calls
    return fetcher


@pytest.fixture
def conn():
    connection = db.init_db(":memory:")
    yield connection
    connection.close()


@pytest.fixture(autouse=True)
def pin_today(monkeypatch):
    """Pin "today" so the tests give the same answer in a year's time."""
    monkeypatch.setattr(fx, "_today", lambda: dt.date(2026, 8, 22))


# ---------------------------------------------------------------------------
#  Business days
# ---------------------------------------------------------------------------

def test_an_ordinary_weekday_uses_that_days_rate(conn):
    result = fx.get_rate(conn, "2026-08-03", "GBP", fetcher=fake_fetcher)
    assert result["rate"] == 1.3470
    assert result["rate_date"] == "2026-08-03"
    assert result["days_back"] == 0


def test_a_saturday_uses_fridays_rate_and_says_so(conn):
    """
    The ECB publishes on business days only. A Saturday transaction has no
    rate of its own, so Friday's is used - and BOTH dates are recorded, so
    it is always clear which rate was really applied.
    """
    result = fx.get_rate(conn, "2026-08-08", "EUR", fetcher=fake_fetcher)

    assert result["rate"] == 1.1535
    assert result["rate_date"] == "2026-08-07"     # the Friday
    assert result["days_back"] == 1
    assert result["warning"] is None               # a weekend is normal


def test_a_sunday_walks_back_two_days(conn):
    result = fx.get_rate(conn, "2026-08-09", "EUR", fetcher=fake_fetcher)
    assert result["rate_date"] == "2026-08-07"
    assert result["days_back"] == 2


def test_the_date_actually_used_is_stored_alongside_the_transaction_date(conn):
    fx.get_rate(conn, "2026-08-08", "EUR", fetcher=fake_fetcher)
    row = db.get_cached_fx_rate(conn, requested_date="2026-08-08",
                                base_currency="EUR", quote_currency="USD")
    assert row["requested_date"] == "2026-08-08"   # the transaction
    assert row["rate_date"] == "2026-08-07"        # the rate


def test_an_unusually_old_rate_is_flagged(conn, monkeypatch):
    """
    A weekend or public holiday is one to four days. Anything longer means
    something odd, and a human should look.
    """
    def stale(date, base_currency, quote_currency="USD"):
        return 1.10, "2026-07-01"

    result = fx.get_rate(conn, "2026-08-03", "EUR", fetcher=stale)
    assert result["days_back"] > fx.MAX_REASONABLE_GAP_DAYS
    assert result["warning"] is not None
    assert "worth checking" in result["warning"]


def test_a_rate_dated_after_the_transaction_is_refused(conn):
    """Using tomorrow's rate for today's transaction is never right."""
    def from_the_future(date, base_currency, quote_currency="USD"):
        return 1.50, "2026-08-20"

    with pytest.raises(fx.RateUnavailable) as caught:
        fx.get_rate(conn, "2026-08-03", "EUR", fetcher=from_the_future)
    assert "AFTER the transaction" in str(caught.value)


# ---------------------------------------------------------------------------
#  The stale-rate trap
# ---------------------------------------------------------------------------

def test_a_future_date_is_refused(conn):
    """
    THE TRAP.

    Asked for a date a week from now, the real service returns 200 OK with
    last Friday's rate and no warning whatsoever. A mistyped year would
    quietly produce a wrong but entirely plausible number.

    So future dates are refused here, before the request is ever made.
    """
    with pytest.raises(fx.RateUnavailable) as caught:
        fx.get_rate(conn, "2026-09-30", "EUR", fetcher=fake_fetcher)

    message = str(caught.value)
    assert "in the future" in message
    assert "date on that transaction is wrong" in message


def test_today_is_allowed(conn):
    """Today is not the future. It must still work."""
    result = fx.get_rate(conn, "2026-08-22", "EUR", fetcher=fake_fetcher)
    assert result["rate"] == 1.1535
    assert result["rate_date"] == "2026-08-07"


def test_a_date_before_the_records_begin_is_refused(conn):
    with pytest.raises(fx.RateUnavailable) as caught:
        fx.get_rate(conn, "1990-01-02", "EUR", fetcher=fake_fetcher)
    assert "1999" in str(caught.value)


def test_nonsense_instead_of_a_date_is_refused(conn):
    with pytest.raises(fx.FxError):
        fx.get_rate(conn, "last Tuesday", "EUR", fetcher=fake_fetcher)


# ---------------------------------------------------------------------------
#  Currencies
# ---------------------------------------------------------------------------

def test_dollars_to_dollars_never_touches_the_network(conn):
    """
    The rate is 1. Asking the real service for USD to USD actually returns
    an error, so this shortcut is required, not just an optimisation.
    """
    fetcher = counting_fetcher()
    result = fx.get_rate(conn, "2026-08-08", "USD", fetcher=fetcher)

    assert result["rate"] == 1.0
    assert fetcher.calls == []


def test_an_unsupported_currency_fails_loudly(conn):
    """
    Only about 30 currencies exist. Inventing a rate would be far worse than
    admitting it isn't known - it would put a wrong number on a tax return
    with nothing to show it was a guess.
    """
    with pytest.raises(fx.UnsupportedCurrency) as caught:
        fx.get_rate(conn, "2026-08-03", "AED", fetcher=fake_fetcher)

    message = str(caught.value)
    assert "Nothing has been guessed" in message
    assert "IRS yearly average" in message      # the sanctioned alternative
    assert "EUR" in message                     # lists what does work


def test_the_three_currencies_actually_used_are_all_supported():
    for currency in ["USD", "EUR", "GBP"]:
        assert currency in fx.KNOWN_CURRENCIES


# ---------------------------------------------------------------------------
#  Saved rates
# ---------------------------------------------------------------------------

def test_a_rate_is_only_fetched_once(conn):
    """
    Saved rates mean a report run next month gives the identical figure,
    rather than quietly re-pricing everything at today's rate.
    """
    fetcher = counting_fetcher()

    first = fx.get_rate(conn, "2026-08-03", "GBP", fetcher=fetcher)
    second = fx.get_rate(conn, "2026-08-03", "GBP", fetcher=fetcher)
    third = fx.get_rate(conn, "2026-08-03", "GBP", fetcher=fetcher)

    assert len(fetcher.calls) == 1, "asked the service more than once"
    assert first["cached"] is False
    assert second["cached"] is True
    assert first["rate"] == second["rate"] == third["rate"]


def test_a_saved_weekend_rate_remembers_the_walk_back(conn):
    fetcher = counting_fetcher()
    fx.get_rate(conn, "2026-08-08", "EUR", fetcher=fetcher)
    again = fx.get_rate(conn, "2026-08-08", "EUR", fetcher=fetcher)

    assert again["cached"] is True
    assert again["rate_date"] == "2026-08-07"
    assert again["days_back"] == 1


# ---------------------------------------------------------------------------
#  Converting amounts
# ---------------------------------------------------------------------------

def test_an_amount_is_converted_and_rounded_to_cents(conn):
    result = fx.convert(conn, 900.00, "EUR", "2026-08-07", fetcher=fake_fetcher)
    assert result["amount"] == 1038.15          # 900 * 1.1535
    assert result["rate"] == 1.1535
    assert result["rate_date"] == "2026-08-07"


def test_the_original_amount_and_currency_are_never_changed(conn):
    """
    Both figures are kept. The original is what actually happened; the dollar
    figure is a calculation, and you can always check the working.
    """
    db.upsert_income(conn, source="stripe", source_id="in_1",
                     date="2026-08-07", amount=900, currency="EUR")
    conn.commit()

    fx.convert_pending(conn, tax_year=2026, fetcher=fake_fetcher)

    row = conn.execute("SELECT * FROM income").fetchone()
    assert row["amount"] == 900.00        # untouched
    assert row["currency"] == "EUR"       # untouched
    assert row["amount_usd"] == 1038.15   # added
    assert row["fx_rate"] == 1.1535       # the working
    assert row["fx_date"] == "2026-08-07"


def test_converting_fills_in_income_and_expenses_together(conn):
    db.upsert_income(conn, source="stripe", source_id="in_1",
                     date="2026-08-03", amount=3798, currency="GBP")
    db.upsert_expense(conn, source="stripe", source_id="fee_1",
                      date="2026-08-03", amount=167.31, currency="GBP")
    conn.commit()

    result = fx.convert_pending(conn, tax_year=2026, fetcher=fake_fetcher)

    assert len(result["converted"]) == 2
    figures = db.totals(conn, 2026)
    assert figures["income_usd"] == 5115.91      # 3798 * 1.3470
    assert figures["expenses_usd"] == 225.37     # 167.31 * 1.3470
    assert figures["unconverted_income_count"] == 0


def test_a_dry_run_changes_nothing(conn):
    db.upsert_income(conn, source="stripe", source_id="in_1",
                     date="2026-08-03", amount=3798, currency="GBP")
    conn.commit()

    result = fx.convert_pending(conn, tax_year=2026, dry_run=True,
                                fetcher=fake_fetcher)

    assert len(result["converted"]) == 1        # it says what it would do
    row = conn.execute("SELECT * FROM income").fetchone()
    assert row["amount_usd"] is None            # but did not do it


def test_converting_twice_changes_nothing(conn):
    db.upsert_income(conn, source="stripe", source_id="in_1",
                     date="2026-08-03", amount=3798, currency="GBP")
    conn.commit()

    fx.convert_pending(conn, tax_year=2026, fetcher=fake_fetcher)
    first = db.totals(conn, 2026)

    second_run = fx.convert_pending(conn, tax_year=2026, fetcher=fake_fetcher)
    second = db.totals(conn, 2026)

    assert second_run["converted"] == []        # nothing left to do
    assert first == second


def test_dollars_already_in_dollars_are_left_alone(conn):
    """They were given a dollar figure at import, so there is nothing to do."""
    db.upsert_income(conn, source="stripe", source_id="in_1",
                     date="2026-08-03", amount=225, currency="USD",
                     amount_usd=225)
    conn.commit()

    result = fx.convert_pending(conn, tax_year=2026, fetcher=fake_fetcher)
    assert result["converted"] == []


def test_one_currency_failing_does_not_block_the_others(conn):
    """
    A currency with no published rate is reported, and everything else is
    still converted. One awkward transaction must not stop the whole thing.
    """
    db.upsert_income(conn, source="manual", source_id="ok",
                     date="2026-08-03", amount=100, currency="GBP")
    db.upsert_income(conn, source="manual", source_id="bad",
                     date="2026-08-03", amount=100, currency="AED")
    conn.commit()

    result = fx.convert_pending(conn, tax_year=2026, fetcher=fake_fetcher)

    assert len(result["converted"]) == 1
    assert len(result["failed"]) == 1
    assert result["failed"][0]["currency"] == "AED"
    assert "Nothing has been guessed" in result["failed"][0]["reason"]

    # and the failed one still has no dollar figure - not a guessed zero
    row = conn.execute(
        "SELECT * FROM income WHERE source_id = 'bad'").fetchone()
    assert row["amount_usd"] is None


# ---------------------------------------------------------------------------
#  Re-importing must not undo the conversion
# ---------------------------------------------------------------------------

def test_reimporting_does_not_erase_the_conversion(conn):
    """
    Stage 4 imports a EUR 900 invoice with no dollar figure - it doesn't know
    the rate. Stage 5 works it out. Then Stage 4 runs again, once more
    offering no dollar figure.

    Handled naively that erases the conversion, and the totals silently drop
    back to counting the invoice as $0. Nothing errors; the number is just
    quietly wrong.
    """
    db.upsert_income(conn, source="stripe", source_id="in_1",
                     date="2026-08-07", amount=900, currency="EUR")
    conn.commit()
    fx.convert_pending(conn, tax_year=2026, fetcher=fake_fetcher)
    assert db.totals(conn, 2026)["income_usd"] == 1038.15

    # Stage 4 runs again, exactly as before
    db.upsert_income(conn, source="stripe", source_id="in_1",
                     date="2026-08-07", amount=900, currency="EUR")
    conn.commit()

    assert db.totals(conn, 2026)["income_usd"] == 1038.15, \
        "the conversion was erased by the re-import"
    assert db.totals(conn, 2026)["unconverted_income_count"] == 0


def test_a_corrected_amount_clears_the_stale_conversion(conn):
    """
    The other half of the rule. If Stripe corrects an invoice from EUR 900 to
    EUR 1,000, the old dollar figure is now wrong. Keeping it would be worse
    than having none, so it is cleared and worked out again.
    """
    db.upsert_income(conn, source="stripe", source_id="in_1",
                     date="2026-08-07", amount=900, currency="EUR")
    conn.commit()
    fx.convert_pending(conn, tax_year=2026, fetcher=fake_fetcher)

    db.upsert_income(conn, source="stripe", source_id="in_1",
                     date="2026-08-07", amount=1000, currency="EUR")
    conn.commit()

    row = conn.execute("SELECT * FROM income").fetchone()
    assert row["amount_usd"] is None, "a stale dollar figure was kept"

    fx.convert_pending(conn, tax_year=2026, fetcher=fake_fetcher)
    assert db.totals(conn, 2026)["income_usd"] == 1153.50    # 1000 * 1.1535


def test_a_currency_change_also_clears_the_conversion(conn):
    db.upsert_income(conn, source="manual", source_id="x",
                     date="2026-08-03", amount=100, currency="GBP")
    conn.commit()
    fx.convert_pending(conn, tax_year=2026, fetcher=fake_fetcher)

    db.upsert_income(conn, source="manual", source_id="x",
                     date="2026-08-03", amount=100, currency="EUR")
    conn.commit()

    assert conn.execute("SELECT amount_usd FROM income").fetchone()[0] is None


def test_the_full_import_then_convert_cycle_is_stable(conn):
    """
    Import, convert, import, convert, import... the totals must settle and
    stay put. This is the cycle that actually happens month to month.
    """
    def import_stripe():
        db.upsert_income(conn, source="stripe", source_id="in_gbp",
                         date="2026-08-03", amount=3798, currency="GBP")
        db.upsert_income(conn, source="stripe", source_id="in_usd",
                         date="2026-08-03", amount=225, currency="USD",
                         amount_usd=225)
        db.upsert_expense(conn, source="stripe", source_id="fee_gbp",
                          date="2026-08-03", amount=167.31, currency="GBP")
        conn.commit()

    import_stripe()
    fx.convert_pending(conn, tax_year=2026, fetcher=fake_fetcher)
    settled = db.totals(conn, 2026)

    for _ in range(3):
        import_stripe()
        fx.convert_pending(conn, tax_year=2026, fetcher=fake_fetcher)
        assert db.totals(conn, 2026) == settled

    assert settled["income_usd"] == 5340.91       # 3798*1.3470 + 225
    assert settled["unconverted_income_count"] == 0
