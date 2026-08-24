"""
Automatic checks for Stage 8 (expense categories).

The rules live in a plain-English file, so most of what matters here is
that the file is read correctly and that nothing is ever guessed.
"""

import pytest

from taxlib import categorize, db


@pytest.fixture
def rules(tmp_path):
    path = tmp_path / "rules.txt"
    path.write_text(
        "# a note, ignored\n"
        "software = PriceLabs, ClickUp, Anthropic, Google Workspace\n"
        "phone and internet = Quo, OpenPhone\n"
        "payment processing = Stripe, Service Fee\n"
    )
    return categorize.load_rules(path)


# ---------------------------------------------------------------------------
#  Reading the rules file
# ---------------------------------------------------------------------------

def test_rules_are_read_in_file_order(rules):
    """Order matters: the first match wins, so specific rules go first."""
    assert [name for name, _ in rules] == [
        "software", "phone and internet", "payment processing"]


def test_a_rule_can_wrap_onto_several_lines(tmp_path):
    path = tmp_path / "rules.txt"
    path.write_text("software = PriceLabs, ClickUp,\n"
                    "           Anthropic, Supabase\n")
    rules = categorize.load_rules(path)
    assert rules[0][1] == ["PriceLabs", "ClickUp", "Anthropic", "Supabase"]


def test_the_real_rules_file_loads():
    loaded = categorize.load_rules()
    assert loaded
    names = [name for name, _ in loaded]
    for expected in ["software", "payment processing", "compliance and admin"]:
        assert expected in names


# ---------------------------------------------------------------------------
#  Matching
# ---------------------------------------------------------------------------

def test_a_vendor_is_matched_whatever_the_capitals(rules):
    for text in ["CLICKUP", "clickup", "Clickup SAN DIEGO"]:
        assert categorize.categorize(text, rules)[0] == "software"


def test_a_short_word_only_matches_whole(rules):
    """
    "Quo" must not match inside "quote" or "status quo report" - a
    three-letter substring would otherwise capture unrelated expenses.
    """
    assert categorize.categorize("Quo openphone", rules)[0] == "phone and internet"
    assert categorize.categorize("quotation for services", rules)[0] == \
        categorize.DEFAULT_CATEGORY


def test_a_longer_phrase_matches_inside_a_description(rules):
    assert categorize.categorize(
        "Service Fee - OTA Optimization", rules)[0] == "payment processing"


def test_nothing_is_ever_guessed(rules):
    """
    An unknown vendor stays uncategorized and gets listed. A wrong category
    is a wrong deduction, and unlike a crash it is invisible.
    """
    category, matched = categorize.categorize("Bloggs & Sons Ltd", rules)
    assert category == categorize.DEFAULT_CATEGORY
    assert matched is None


def test_the_matched_word_is_reported(rules):
    """So a run can show WHY, rather than asking to be trusted."""
    _, matched = categorize.categorize("Anthropic* Claude", rules)
    assert matched == "Anthropic"


# ---------------------------------------------------------------------------
#  Card descriptions
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("description,expected", [
    ("Card transaction of 108.00 USD issued by Anthropic* Claude", "Anthropic"),
    ("Card transaction of 64.80 USD issued by Clickup SAN DIEGO", "Clickup"),
    ("Card transaction of 25.00 USD issued by Supabase SINGAPORE", "Supabase"),
    ("Card transaction of 6.38 EUR issued by Godaddy#41237", "Godaddy"),
])
def test_the_merchant_is_pulled_out_of_a_card_description(description, expected):
    """
    Wise writes the whole sentence. Taking the first 30 characters gives
    "Card transaction of 108.00 USD iss" - identical for every purchase, and
    useless both for categorising and for reading.
    """
    assert categorize.merchant_from_card(description) == expected


def test_a_description_that_is_not_a_card_payment_gives_nothing():
    assert categorize.merchant_from_card("Sent money to Ayoka") is None
    assert categorize.merchant_from_card("") is None


# ---------------------------------------------------------------------------
#  Applying it to the database
# ---------------------------------------------------------------------------

def test_categories_are_applied_and_vendors_tidied(rules):
    conn = db.init_db(":memory:")
    db.upsert_expense(conn, source="wise", source_id="c1", date="2026-08-10",
                      amount=64.80, currency="USD", amount_usd=64.80,
                      vendor="Card transaction of 64.80 USD iss",
                      description="Card transaction of 64.80 USD issued by "
                                  "Clickup SAN DIEGO")
    conn.commit()

    result = categorize.recategorize(conn, tax_year=2026, rules=rules)

    assert len(result["categorized"]) == 1
    row = conn.execute("SELECT * FROM expenses").fetchone()
    assert row["category"] == "software"
    assert row["vendor"] == "Clickup"
    conn.close()


def test_a_category_set_by_hand_is_never_overwritten(rules):
    conn = db.init_db(":memory:")
    db.upsert_expense(conn, source="wise", source_id="c1", date="2026-08-10",
                      amount=64.80, currency="USD", amount_usd=64.80,
                      category="professional services", vendor="ClickUp")
    conn.commit()

    categorize.recategorize(conn, tax_year=2026, rules=rules)

    assert conn.execute(
        "SELECT category FROM expenses").fetchone()[0] == "professional services"
    conn.close()


def test_an_unknown_vendor_is_returned_for_listing(rules):
    conn = db.init_db(":memory:")
    db.upsert_expense(conn, source="wise", source_id="x", date="2026-08-10",
                      amount=98.00, currency="USD", amount_usd=98.00,
                      vendor="My Data Value Limited")
    conn.commit()

    result = categorize.recategorize(conn, tax_year=2026, rules=rules)

    assert result["categorized"] == []
    assert len(result["uncategorized"]) == 1
    assert result["uncategorized"][0]["vendor"] == "My Data Value Limited"
    conn.close()


def test_a_dry_run_changes_nothing(rules):
    conn = db.init_db(":memory:")
    db.upsert_expense(conn, source="wise", source_id="c1", date="2026-08-10",
                      amount=64.80, currency="USD", amount_usd=64.80,
                      vendor="ClickUp")
    conn.commit()

    result = categorize.recategorize(conn, tax_year=2026, dry_run=True,
                                     rules=rules)

    assert len(result["categorized"]) == 1        # says what it would do
    assert conn.execute(
        "SELECT category FROM expenses").fetchone()[0] == "uncategorized"
    conn.close()


def test_running_twice_changes_nothing_the_second_time(rules):
    conn = db.init_db(":memory:")
    db.upsert_expense(conn, source="wise", source_id="c1", date="2026-08-10",
                      amount=64.80, currency="USD", amount_usd=64.80,
                      vendor="ClickUp")
    conn.commit()

    first = categorize.recategorize(conn, tax_year=2026, rules=rules)
    second = categorize.recategorize(conn, tax_year=2026, rules=rules)

    assert len(first["categorized"]) == 1
    assert second["categorized"] == []
    conn.close()
