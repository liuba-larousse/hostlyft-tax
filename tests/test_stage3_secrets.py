"""
Automatic checks for Stage 3 (secrets).

These test the CHECKER, using made-up keys. No real secret is used anywhere
in this file, and none is ever printed.

The point of the checker is to turn a confusing failure hours later into a
clear message now. So these tests mostly assert that the message actually
says the useful thing.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

# scripts/ isn't a package, so load check_secrets.py directly from its path.
_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_secrets.py"
_spec = importlib.util.spec_from_file_location("check_secrets", _SCRIPT)
check_secrets = importlib.util.module_from_spec(_spec)
sys.modules["check_secrets"] = check_secrets
_spec.loader.exec_module(check_secrets)

OK, WARN, BAD = check_secrets.OK, check_secrets.WARN, check_secrets.BAD


# ---------------------------------------------------------------------------
#  Stripe key - the mistakes people actually make
# ---------------------------------------------------------------------------

def test_a_good_live_key_passes():
    status, message = check_secrets.check_stripe_key("sk_live_" + "A" * 99)
    assert status == OK
    assert "sk_live_" in message


def test_the_publishable_key_is_rejected_by_name():
    """
    Both keys sit next to each other on the same Stripe page. Picking the
    wrong one is the single most common mistake, so the message must say
    exactly which one to click.
    """
    status, message = check_secrets.check_stripe_key("pk_live_" + "A" * 99)
    assert status == BAD
    assert "PUBLISHABLE" in message
    assert "Reveal" in message


def test_the_test_key_warns_that_the_data_is_pretend():
    status, message = check_secrets.check_stripe_key("sk_test_" + "A" * 99)
    assert status == WARN
    assert "pretend" in message or "TEST" in message


def test_a_webhook_secret_is_recognised():
    status, message = check_secrets.check_stripe_key("whsec_" + "A" * 40)
    assert status == BAD
    assert "webhook" in message


def test_a_half_pasted_key_is_caught():
    """Copying can stop early. The key looks plausible but is too short."""
    status, message = check_secrets.check_stripe_key("sk_live_ABC")
    assert status == BAD
    assert "cut off" in message


def test_random_text_is_rejected():
    status, _ = check_secrets.check_stripe_key("my stripe key")
    assert status == BAD


# ---------------------------------------------------------------------------
#  Invisible characters - the failure that looks like nothing is wrong
# ---------------------------------------------------------------------------

def test_a_curly_quote_from_a_web_page_is_caught():
    """
    Copying from a web page can drag along a character you cannot see. The
    key looks perfect on screen and the server rejects it, with no clue why.
    """
    problems = check_secrets.check_for_invisible_characters("sk_live_ABC”")
    assert problems
    assert "curly quote" in problems[0]


def test_a_non_breaking_space_is_caught():
    problems = check_secrets.check_for_invisible_characters("sk_live_ ABC")
    assert problems


def test_a_trailing_space_is_caught():
    problems = check_secrets.check_for_invisible_characters("sk_live_ABC ")
    assert any("space at the start or end" in p for p in problems)


def test_a_clean_value_has_no_complaints():
    assert check_secrets.check_for_invisible_characters("sk_live_ABC123") == []


# ---------------------------------------------------------------------------
#  Wise
# ---------------------------------------------------------------------------

def test_a_properly_shaped_wise_token_passes():
    status, _ = check_secrets.check_wise_token(
        "1a2b3c4d-5e6f-7a8b-9c0d-1e2f3a4b5c6d")
    assert status == OK


def test_a_wrong_looking_wise_token_is_queried_not_rejected():
    """
    Warn rather than fail: Wise could change the format, and refusing a
    working token would be worse than asking you to double-check it.
    """
    status, _ = check_secrets.check_wise_token("abc123")
    assert status == WARN


def test_the_profile_id_must_be_a_number():
    assert check_secrets.check_wise_profile("12345678")[0] == OK
    assert check_secrets.check_wise_profile("business")[0] == BAD


# ---------------------------------------------------------------------------
#  Gmail
# ---------------------------------------------------------------------------

def test_the_email_address_is_shown_partly_hidden():
    """Even an email address is only ever shown in shortened form."""
    status, message = check_secrets.check_gmail_address("help.hostlyft@gmail.com")
    assert status == OK
    assert "help.hostlyft" not in message
    assert "@gmail.com" in message


def test_a_real_gmail_password_instead_of_an_app_password_is_caught():
    """
    Google silently refuses a normal account password for this. The error it
    gives back is unhelpful, so catch it here instead.
    """
    status, message = check_secrets.check_app_password("MyRealPassword123!")
    assert status == BAD
    assert "16" in message


def test_a_correct_app_password_passes_with_or_without_spaces():
    assert check_secrets.check_app_password("abcdefghijklmnop")[0] == OK
    # Google displays it in four groups of four; pasting the spaces is fine
    assert check_secrets.check_app_password("abcd efgh ijkl mnop")[0] == OK


def test_an_email_address_in_the_password_field_is_caught():
    status, message = check_secrets.check_app_password("help@gmail.com")
    assert status == BAD
    assert "email" in message


# ---------------------------------------------------------------------------
#  Reading a filled-in file
# ---------------------------------------------------------------------------

def test_a_realistic_env_file_is_read_correctly(tmp_path, monkeypatch):
    """
    End to end on a fake file: quotes, spaces and a blank value all handled,
    and every secret the checker knows about is recognised.
    """
    from taxlib import config

    env_file = tmp_path / ".env"
    env_file.write_text(
        "# my secrets\n"
        f"STRIPE_SECRET_KEY = \"sk_live_{'A' * 99}\"\n"
        "WISE_API_TOKEN=1a2b3c4d-5e6f-7a8b-9c0d-1e2f3a4b5c6d\n"
        "WISE_PROFILE_ID=\n"
        "GMAIL_ADDRESS=help.hostlyft@gmail.com\n"
        "GMAIL_APP_PASSWORD=abcd efgh ijkl mnop\n"
    )
    monkeypatch.setattr(config, "ENV_PATH", env_file)

    values = config.load_env()
    assert values["STRIPE_SECRET_KEY"].startswith("sk_live_")
    assert check_secrets.check_stripe_key(values["STRIPE_SECRET_KEY"])[0] == OK
    assert check_secrets.check_wise_token(values["WISE_API_TOKEN"])[0] == OK
    assert values["WISE_PROFILE_ID"] == ""
    assert check_secrets.check_app_password(values["GMAIL_APP_PASSWORD"])[0] == OK


@pytest.mark.parametrize("name,_stage,_checker", check_secrets.SECRETS)
def test_every_checked_secret_is_documented_in_the_template(name, _stage, _checker):
    """If the checker knows about a secret, .env.example must explain it."""
    from taxlib import config
    assert f"{name}=" in config.ENV_EXAMPLE_PATH.read_text()
