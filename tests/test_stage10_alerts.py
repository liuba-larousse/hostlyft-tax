"""
Automatic checks for Stage 10 (the reminders).

What matters here is not the wording but the DECISIONS:

  * an alert fires on the right day and not on the wrong one
  * it fires ONCE, not every morning until it is ignored
  * the $600 alarm counts withdrawals, never jar allocations
  * a failed send is not recorded as sent, so it is retried

The last one is the quiet one. Recording an alert that never arrived would
mean the only warning she ever gets about a missed deadline is one she
never sees.
"""

import pytest

from taxlib import alerts, db, notify


@pytest.fixture
def conn():
    connection = db.init_db(":memory:")
    yield connection
    connection.close()


def pay(connection, person, amount, on="2026-06-01"):
    return db.upsert_expense(
        connection, source="wise", source_id=f"{person}-{on}-{amount}",
        date=on, amount=amount, currency="USD", amount_usd=amount,
        category="contractor", vendor=person)


def kinds(alert_list):
    return sorted({alert.kind for alert in alert_list})


# ---------------------------------------------------------------------------
#  Quarterly deadlines
# ---------------------------------------------------------------------------

def test_the_four_deadlines_are_april_june_september_and_january():
    due = alerts.quarterly_deadlines(2026)
    assert [d.isoformat() for d, _, _ in due] == [
        "2026-04-15", "2026-06-15", "2026-09-15", "2027-01-15"]


def test_the_fourth_quarter_is_due_in_the_following_january():
    """
    Easy to get wrong, and it would silently drop a quarter: the payment
    for the last quarter of 2026 is due in January 2027.
    """
    last_due, label, _ = alerts.quarterly_deadlines(2026)[-1]
    assert last_due.year == 2027
    assert label == "Q4 2026"


def test_the_reminder_arrives_a_week_before_and_not_earlier(conn):
    eight_days = alerts.quarterly_alerts(conn, _date("2026-09-07"), 2026)
    seven_days = alerts.quarterly_alerts(conn, _date("2026-09-08"), 2026)
    assert eight_days == []
    assert len(seven_days) == 1


def test_the_reminder_still_arrives_on_the_day_itself(conn):
    on_the_day = alerts.quarterly_alerts(conn, _date("2026-09-15"), 2026)
    day_after = alerts.quarterly_alerts(conn, _date("2026-09-16"), 2026)
    assert len(on_the_day) == 1
    assert day_after == []


def test_the_january_payment_is_warned_about(conn):
    """
    It belongs to the 2026 tax year but falls in 2027, so a run in January
    2027 has to look back a year to find it.
    """
    got = alerts.quarterly_alerts(conn, _date("2027-01-10"), 2027)
    assert len(got) == 1
    assert "Q4 2026" in got[0].subject


def _date(text):
    from datetime import date
    return date.fromisoformat(text)


# ---------------------------------------------------------------------------
#  FBAR
# ---------------------------------------------------------------------------

def test_fbar_fires_in_late_march_and_in_october(conn):
    assert alerts.fbar_alerts(conn, _date("2027-03-25"), 2026)
    assert alerts.fbar_alerts(conn, _date("2027-10-03"), 2026)


def test_fbar_is_quiet_the_rest_of_the_year(conn):
    for day in ["2027-01-15", "2027-05-01", "2027-07-04", "2027-12-01"]:
        assert alerts.fbar_alerts(conn, _date(day), 2026) == [], day


def test_fbar_reports_the_year_that_has_ended(conn):
    got = alerts.fbar_alerts(conn, _date("2027-03-25"), 2026)
    assert "2026" in got[0].subject


def test_fbar_does_not_claim_to_know_whether_she_is_over_the_limit(conn):
    """
    The data cannot answer it - FBAR asks for the highest combined balance
    at ANY point in the year, and only a handful of days are recorded. A
    confident "you are under $10,000" would be a wrong answer about
    something carrying criminal penalties.
    """
    db.record_jar_balance(conn, balance_id="b1", jar_name="Katerina",
                          person="Katerina Mrvova", observed_on="2026-08-26",
                          amount=200, currency="USD", amount_usd=200)
    body = alerts.fbar_alerts(conn, _date("2027-03-25"), 2026)[0].body

    assert "CANNOT" in body.upper()
    assert "Statements" in body
    # It must not tell her she is fine.
    for phrase in ["you are under", "no need to file", "not required"]:
        assert phrase not in body.lower()


# ---------------------------------------------------------------------------
#  The December jars warning
# ---------------------------------------------------------------------------

def jar(connection, person, amount, on="2026-11-30"):
    db.record_jar_balance(connection, balance_id=f"jar-{person}",
                          jar_name=person.split()[0], person=person,
                          observed_on=on, amount=amount, currency="USD",
                          amount_usd=amount)


def test_the_jars_warning_starts_on_1_december_and_not_before(conn):
    jar(conn, "Katerina Mrvova", 8000)
    assert alerts.jar_alerts(conn, _date("2026-11-30"), 2026) == []
    assert len(alerts.jar_alerts(conn, _date("2026-12-01"), 2026)) == 1


def test_the_jars_warning_prices_the_cost_correctly(conn):
    """
    $8,000 left in jars costs 15.3% of 92.35% of it - about $1,130 - in
    self-employment tax. Not the flat 15.3% ($1,224) that a rough estimate
    gives: only 92.35% of profit is subject to the tax.
    """
    jar(conn, "Katerina Mrvova", 8000)
    body = alerts.jar_alerts(conn, _date("2026-12-01"), 2026)[0].body
    assert "$8,000.00" in body
    assert "$1,130.36" in body


def test_only_team_jars_count_not_her_own(conn):
    """
    Her ADMIN and TAX jars are hers whatever happens. Withdrawing from them
    changes nothing, so they must not inflate the warning.
    """
    jar(conn, "Katerina Mrvova", 1000)
    db.record_jar_balance(conn, balance_id="admin", jar_name="ADMIN 30%",
                          person=None, observed_on="2026-11-30",
                          amount=99999, currency="USD", amount_usd=99999)

    body = alerts.jar_alerts(conn, _date("2026-12-01"), 2026)[0].body
    assert "$1,000.00" in body
    assert "99,999" not in body


def test_no_warning_when_the_jars_are_empty(conn):
    jar(conn, "Katerina Mrvova", 0)
    assert alerts.jar_alerts(conn, _date("2026-12-05"), 2026) == []


# ---------------------------------------------------------------------------
#  The $600 contractor alarm
# ---------------------------------------------------------------------------

def test_the_600_alarm_fires_for_katerina(conn):
    pay(conn, "Katerina Mrvova", 3102.05)
    got = alerts.contractor_600_alerts(conn, _date("2026-09-06"), 2026)
    assert len(got) == 1
    assert "Katerina" in got[0].subject
    assert "$3,102.05" in got[0].body


def test_the_600_alarm_does_not_fire_for_the_foreign_contractors(conn):
    """They are over $600 and still get no 1099 - they are not US persons."""
    for name in ["Yetunde Olaniyan", "Olaide Olaniyan",
                 "Evgeniya Dyatlovskaya"]:
        pay(conn, name, 5000)
    assert alerts.contractor_600_alerts(conn, _date("2026-09-06"), 2026) == []


def test_the_600_alarm_ignores_jar_allocations(conn):
    """The plan's test 11, at the alert level."""
    jar(conn, "Katerina Mrvova", 9000, on="2026-06-01")
    db.record_jar_movement(conn, source_id="mv", date="2026-06-01",
                           jar_name="Katerina", person="Katerina Mrvova",
                           direction="in", amount=9000, currency="USD",
                           amount_usd=9000)
    assert alerts.contractor_600_alerts(conn, _date("2026-09-06"), 2026) == []


def test_the_600_alarm_says_whether_the_w9_is_on_file(conn):
    pay(conn, "Katerina Mrvova", 3102.05)

    without = alerts.contractor_600_alerts(conn, _date("2026-09-06"), 2026)[0]
    assert "NOT ON FILE" in without.body.upper()
    assert without.urgent is True

    db.record_form(conn, person="Katerina Mrvova", form_type="W-9",
                   received_on="2026-09-01", has_tin=True)
    with_form = alerts.contractor_600_alerts(conn, _date("2026-09-06"),
                                             2026)[0]
    assert "on file with a taxpayer ID" in with_form.body
    assert with_form.urgent is False


# ---------------------------------------------------------------------------
#  Firing once, not every morning
# ---------------------------------------------------------------------------

def test_an_alert_is_not_repeated_once_sent(conn):
    pay(conn, "Katerina Mrvova", 3102.05)

    first = alerts.due(conn, today="2026-09-06", tax_year=2026)
    assert alerts.unsent(conn, first) == first

    for alert in first:
        db.record_alert(conn, alert_key=alert.key, alert_type=alert.kind)

    second = alerts.due(conn, today="2026-09-06", tax_year=2026)
    assert second != []                       # still due...
    assert alerts.unsent(conn, second) == []  # ...but not sent again


def test_each_person_and_year_gets_its_own_key(conn):
    """
    Katerina crossing $600 again next year is a new obligation and must
    alert again, not be silenced by this year's record.
    """
    pay(conn, "Katerina Mrvova", 3102.05, on="2026-06-01")
    pay(conn, "Katerina Mrvova", 3000, on="2027-06-01")

    this_year = alerts.contractor_600_alerts(conn, _date("2026-09-06"), 2026)
    next_year = alerts.contractor_600_alerts(conn, _date("2027-09-06"), 2027)
    assert this_year[0].key != next_year[0].key


# ---------------------------------------------------------------------------
#  Delivery
# ---------------------------------------------------------------------------

def test_a_dry_run_sends_nothing(capsys):
    delivery = notify.send("Subject", "Body", short="Short", dry_run=True)
    assert delivery.desktop_ok and delivery.email_ok
    printed = capsys.readouterr().out
    assert "dry run" in printed


def test_one_channel_failing_does_not_stop_the_other(monkeypatch):
    """
    Being offline should not also cost her the desktop notification.
    """
    def broken_email(*args, **kwargs):
        raise notify.NotifyError("Gmail is unreachable")

    monkeypatch.setattr(notify, "email", broken_email)
    monkeypatch.setattr(notify, "desktop", lambda *a, **k: True)

    delivery = notify.send("Subject", "Body")
    assert delivery.desktop_ok is True
    assert delivery.email_ok is False
    assert delivery.anything_arrived is True
    assert "unreachable" in delivery.problems[0]


def test_nothing_arriving_is_reported_as_nothing_arriving(monkeypatch):
    def broken(*args, **kwargs):
        raise notify.NotifyError("no")

    monkeypatch.setattr(notify, "email", broken)
    monkeypatch.setattr(notify, "desktop", broken)

    delivery = notify.send("Subject", "Body")
    assert delivery.anything_arrived is False
    assert len(delivery.problems) == 2


def test_applescript_quotes_are_escaped():
    """
    An unescaped quote would end the AppleScript string early and turn the
    rest of the message into broken code.
    """
    escaped = notify._applescript_quote('She said "no" \\ then left')
    assert '\\"no\\"' in escaped
    assert "\\\\" in escaped


def test_newlines_do_not_break_the_notification():
    assert "\n" not in notify._applescript_quote("line one\nline two")


def test_a_missing_app_password_names_the_setting(monkeypatch):
    """
    The failure she is most likely to hit. It must name GMAIL_APP_PASSWORD,
    not produce an SMTP error code.
    """
    monkeypatch.setattr("taxlib.config.get_secret", lambda name, *a, **k: "")
    with pytest.raises(notify.NotifyError) as problem:
        notify.email("Subject", "Body")
    assert "GMAIL_APP_PASSWORD" in str(problem.value)
    assert "app password" in str(problem.value).lower()


# ---------------------------------------------------------------------------
#  Everything together
# ---------------------------------------------------------------------------

def test_a_quiet_day_produces_nothing(conn):
    """
    Every form on file, nobody over $600, no deadline near. Silence is the
    correct answer and is what makes a noisy day worth reading.
    """
    from taxlib import config
    for person in config.CONTRACTORS:
        db.record_form(conn, person=person["name"], form_type=person["form"],
                       received_on="2026-01-15", has_tin=True)

    assert alerts.due(conn, today="2026-07-04", tax_year=2026) == []


def test_a_busy_day_produces_everything(conn):
    """1 December, with a deadline, jars full and no forms collected."""
    pay(conn, "Katerina Mrvova", 3102.05)
    jar(conn, "Katerina Mrvova", 4000)

    got = alerts.due(conn, today="2026-12-01", tax_year=2026)
    assert kinds(got) == ["contractor600", "forms", "jars"]
