"""
Automatic checks for Stage 12 (the contractor forms tracker).

The one the plan named explicitly:

  * Katerina's row produces a 1099-NEC alert; the other four produce
    W-8BEN reminders and no 1099 at all.

Plus the things that would otherwise be silently wrong: a W-8BEN's expiry
date, an expired form counting as no form, and a W-9 that arrived without a
taxpayer ID number.
"""

import pytest

from taxlib import config, db, forms


@pytest.fixture
def conn():
    """A fresh in-memory database. The real one is never touched."""
    connection = db.init_db(":memory:")
    yield connection
    connection.close()


def pay(connection, person, amount, on="2026-06-01", **kwargs):
    """A real transfer OUT to somebody - the kind that counts."""
    return db.upsert_expense(
        connection, source="wise", source_id=f"{person}-{on}-{amount}",
        date=on, amount=amount, currency="USD", amount_usd=amount,
        category="contractor", vendor=person, **kwargs)


def row_for(rows, name):
    return next(row for row in rows if row["person"] == name)


# ---------------------------------------------------------------------------
#  The roster
# ---------------------------------------------------------------------------

def test_the_roster_has_five_people_not_four():
    """
    Olaide Olaniyan was added during the build, after the plan first listed
    four. Any code or document naming only four is out of date.
    """
    assert len(config.CONTRACTORS) == 5
    assert "Olaide Olaniyan" in config.contractor_names()


def test_only_katerina_is_a_us_person_and_only_she_gets_a_1099():
    us = [p["name"] for p in config.CONTRACTORS if p["us_person"]]
    issuing = [p["name"] for p in config.CONTRACTORS if p["issues_1099"]]
    assert us == ["Katerina Mrvova"]
    assert issuing == ["Katerina Mrvova"]


def test_katerina_needs_a_w9_and_everyone_else_a_w8ben():
    for person in config.CONTRACTORS:
        expected = "W-9" if person["us_person"] else "W-8BEN"
        assert person["form"] == expected, person["name"]


# ---------------------------------------------------------------------------
#  Test 12 from the plan
# ---------------------------------------------------------------------------

def test_katerina_alerts_for_a_1099_and_the_other_four_do_not(conn):
    """
    The plan's test 12, in full: everyone is paid well over $600, and only
    the US citizen produces a 1099 obligation.
    """
    for name in config.contractor_names():
        pay(conn, name, 5000)

    rows = forms.review(conn, 2026, today="2026-09-06")

    katerina = row_for(rows, "Katerina Mrvova")
    assert katerina["needs_1099"] is True
    assert katerina["required_form"] == "W-9"

    for name in ["Yetunde Olaniyan", "Olaide Olaniyan",
                 "Evgeniya Dyatlovskaya", "Sunniva Texe"]:
        row = row_for(rows, name)
        assert row["needs_1099"] is False, f"{name} must not get a 1099"
        assert row["required_form"] == "W-8BEN"

    assert [row["person"] for row in forms.needs_1099(rows)] == \
        ["Katerina Mrvova"]


def test_a_missing_form_is_flagged_for_everyone_even_under_600(conn):
    """
    The form is owed from the first dollar. Being under $600 removes the
    1099, never the W-8BEN - it is what establishes no 1099 is owed.
    """
    pay(conn, "Evgeniya Dyatlovskaya", 100)
    rows = forms.review(conn, 2026, today="2026-09-06")

    row = row_for(rows, "Evgeniya Dyatlovskaya")
    assert row["needs_1099"] is False
    assert row["ok"] is False
    assert "No W-8BEN on file" in " ".join(row["problems"])


# ---------------------------------------------------------------------------
#  Test 11 from the plan - the $600 counts WITHDRAWALS
# ---------------------------------------------------------------------------

def test_jar_allocations_do_not_count_toward_the_600(conn):
    """
    The plan's test 11. $5,000 moved into Katerina's jar is still Liuba's
    money. It is not a deduction and it must not trigger a 1099.
    """
    db.record_jar_balance(conn, balance_id="jar-kat", jar_name="Katerina",
                          person="Katerina Mrvova", observed_on="2026-06-01",
                          amount=5000, currency="USD", amount_usd=5000)
    db.record_jar_movement(conn, source_id="mv-1", date="2026-06-01",
                           jar_name="Katerina", person="Katerina Mrvova",
                           direction="in", amount=5000, currency="USD",
                           amount_usd=5000)

    rows = forms.review(conn, 2026, today="2026-09-06")
    row = row_for(rows, "Katerina Mrvova")

    assert row["withdrawn_usd"] == 0
    assert row["needs_1099"] is False


def test_paying_the_jar_out_does_trigger_it(conn):
    """The withdrawal is what crosses the line - and it must."""
    pay(conn, "Katerina Mrvova", 5000)
    rows = forms.review(conn, 2026, today="2026-09-06")
    assert row_for(rows, "Katerina Mrvova")["needs_1099"] is True


def test_exactly_600_crosses_the_line(conn):
    """The threshold is $600 or more, not more than $600."""
    pay(conn, "Katerina Mrvova", 599.99, on="2026-03-01")
    assert row_for(forms.review(conn, 2026, today="2026-09-06"),
                   "Katerina Mrvova")["needs_1099"] is False

    pay(conn, "Katerina Mrvova", 0.01, on="2026-03-02")
    assert row_for(forms.review(conn, 2026, today="2026-09-06"),
                   "Katerina Mrvova")["needs_1099"] is True


# ---------------------------------------------------------------------------
#  Recording a form
# ---------------------------------------------------------------------------

def test_a_w8ben_expires_at_the_end_of_the_third_following_year():
    """
    Signed any day in 2026 -> valid to 31 December 2029. The day and month
    of signing make no difference.
    """
    assert db.w8ben_expires_on("2026-01-01") == "2029-12-31"
    assert db.w8ben_expires_on("2026-12-31") == "2029-12-31"
    assert db.w8ben_expires_on("2027-06-15") == "2030-12-31"


def test_a_w9_never_expires(conn):
    db.record_form(conn, person="Katerina Mrvova", form_type="W-9",
                   received_on="2026-09-01", has_tin=True)
    assert db.get_form(conn, "Katerina Mrvova")["expires_on"] is None


def test_recording_a_form_clears_the_problem(conn):
    pay(conn, "Yetunde Olaniyan", 4000)
    assert row_for(forms.review(conn, 2026, today="2026-09-06"),
                   "Yetunde Olaniyan")["ok"] is False

    db.record_form(conn, person="Yetunde Olaniyan", form_type="W-8BEN",
                   received_on="2026-09-01")
    row = row_for(forms.review(conn, 2026, today="2026-09-06"),
                  "Yetunde Olaniyan")
    assert row["ok"] is True
    assert row["expires_on"] == "2029-12-31"


def test_an_expired_w8ben_is_as_bad_as_a_missing_one(conn):
    db.record_form(conn, person="Sunniva Texe", form_type="W-8BEN",
                   received_on="2020-05-01")     # expired 2023-12-31
    row = row_for(forms.review(conn, 2026, today="2026-09-06"), "Sunniva Texe")
    assert row["ok"] is False
    assert row["status"] == "expired"


def test_a_w8ben_about_to_lapse_is_warned_about(conn):
    db.record_form(conn, person="Sunniva Texe", form_type="W-8BEN",
                   received_on="2023-05-01")     # expires 2026-12-31
    row = row_for(forms.review(conn, 2026, today="2026-06-01"), "Sunniva Texe")
    assert row["status"] == "expiring"
    assert row["ok"] is False


def test_a_w9_without_a_tin_is_not_good_enough(conn):
    """A W-9 with no taxpayer ID leaves 24% backup withholding in place."""
    pay(conn, "Katerina Mrvova", 5000)
    db.record_form(conn, person="Katerina Mrvova", form_type="W-9",
                   received_on="2026-09-01", has_tin=False)

    row = row_for(forms.review(conn, 2026, today="2026-09-06"),
                  "Katerina Mrvova")
    assert row["ok"] is False
    assert row["status"] == "no_tin"
    assert "backup withholding" in " ".join(row["problems"])


def test_a_w9_with_a_tin_is_fine(conn):
    pay(conn, "Katerina Mrvova", 5000)
    db.record_form(conn, person="Katerina Mrvova", form_type="W-9",
                   received_on="2026-09-01", has_tin=True)
    row = row_for(forms.review(conn, 2026, today="2026-09-06"),
                  "Katerina Mrvova")
    assert row["ok"] is True
    assert row["needs_1099"] is True     # still owed, just now possible


def test_the_wrong_form_is_caught(conn):
    """
    A W-8BEN certifies foreign status. A US citizen signing one is not
    merely unhelpful - it is a false certification.
    """
    db.record_form(conn, person="Katerina Mrvova", form_type="W-8BEN",
                   received_on="2026-09-01")
    row = row_for(forms.review(conn, 2026, today="2026-09-06"),
                  "Katerina Mrvova")
    assert row["ok"] is False
    assert "W-9" in " ".join(row["problems"])


def test_recording_the_same_person_twice_updates_rather_than_duplicates(conn):
    db.record_form(conn, person="Sunniva Texe", form_type="W-8BEN",
                   received_on="2026-01-01")
    db.record_form(conn, person="Sunniva Texe", form_type="W-8BEN",
                   received_on="2026-08-01")
    rows = conn.execute("SELECT * FROM contractor_forms").fetchall()
    assert len(rows) == 1
    assert rows[0]["received_on"] == "2026-08-01"


def test_sunniva_is_flagged_in_december_even_on_zero(conn):
    """
    She asked for this explicitly: a year of no payments should be a
    decision, not an oversight.
    """
    db.record_form(conn, person="Sunniva Texe", form_type="W-8BEN",
                   received_on="2026-01-01")

    september = row_for(forms.review(conn, 2026, today="2026-09-06"),
                        "Sunniva Texe")
    assert september["ok"] is True

    december = row_for(forms.review(conn, 2026, today="2026-12-01"),
                       "Sunniva Texe")
    assert december["ok"] is False
    assert december["status"] == "december_check"


def test_the_worst_problem_is_listed_first(conn):
    """Someone over $600 with no form outranks someone under it."""
    pay(conn, "Katerina Mrvova", 5000)
    pay(conn, "Sunniva Texe", 10)
    rows = forms.review(conn, 2026, today="2026-09-06")
    assert rows[0]["person"] == "Katerina Mrvova"
