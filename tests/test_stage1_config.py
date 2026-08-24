"""
Automatic checks for Stage 1 (the skeleton).

A "test" here is just a small function that states something that must be
true, and fails loudly if it isn't. Together they let you change the code
later and immediately find out whether you broke something.

Run them all with:      ./run_tests.command
or from Terminal:       source .venv/bin/activate && python -m pytest
"""

import subprocess

import pytest

from taxlib import config


# ---------------------------------------------------------------------------
#  Paths
# ---------------------------------------------------------------------------

def test_project_paths_point_where_we_expect():
    """The paths are worked out from this file's location, not hard-coded."""
    assert config.ROOT.is_dir()
    assert config.DATA_DIR == config.ROOT / "tax"
    assert config.ENV_PATH == config.ROOT / "tax" / ".env"
    assert config.DB_PATH == config.ROOT / "tax" / "hostlyft_tax.db"


def test_env_example_template_exists():
    """The blank template must be present - setup copies it to make tax/.env."""
    assert config.ENV_EXAMPLE_PATH.is_file()


def test_setup_script_is_double_clickable():
    """
    A .command file only opens on double-click if it is marked executable.
    Cloning from GitHub can lose that mark, so check it.
    """
    setup = config.ROOT / "setup_mac.command"
    assert setup.is_file()
    assert setup.stat().st_mode & 0o111, "setup_mac.command is not executable"


# ---------------------------------------------------------------------------
#  Reading the secrets file
# ---------------------------------------------------------------------------

def test_load_env_reads_a_normal_file(tmp_path):
    """Names and values are picked up; comments and blank lines are ignored."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# a comment\n"
        "\n"
        "STRIPE_SECRET_KEY=sk_live_example\n"
        "GMAIL_ADDRESS=help.hostlyft@gmail.com\n"
        "EMPTY=\n"
    )

    values = config.load_env(env_file)

    assert values["STRIPE_SECRET_KEY"] == "sk_live_example"
    assert values["GMAIL_ADDRESS"] == "help.hostlyft@gmail.com"
    assert values["EMPTY"] == ""
    assert "# a comment" not in values


def test_load_env_tolerates_quotes_spaces_and_equals_signs(tmp_path):
    """
    People add quotes and spaces out of habit, and some passwords contain an
    "=" sign. None of that should change the value we read.
    """
    env_file = tmp_path / ".env"
    env_file.write_text(
        '  WISE_API_TOKEN = "abc123"  \n'
        "GMAIL_APP_PASSWORD='pw=with=equals'\n"
        "not a setting line\n"
    )

    values = config.load_env(env_file)

    assert values["WISE_API_TOKEN"] == "abc123"
    assert values["GMAIL_APP_PASSWORD"] == "pw=with=equals"


def test_load_env_returns_empty_when_file_is_missing(tmp_path):
    """Before setup runs there is no .env. That must not crash anything."""
    assert config.load_env(tmp_path / "nope.env") == {}


def test_missing_required_secret_gives_a_useful_message(monkeypatch):
    """
    The error must name the setting and say which file to edit - not produce
    a confusing crash somewhere deep inside a library.
    """
    monkeypatch.setattr(config, "load_env", lambda path=None: {})

    with pytest.raises(config.MissingSecret) as caught:
        config.get_secret("STRIPE_SECRET_KEY", required=True)

    message = str(caught.value)
    assert "STRIPE_SECRET_KEY" in message
    assert "tax/.env" in message
    assert "nano" in message


def test_optional_secret_returns_the_default(monkeypatch):
    """A blank secret is fine until the stage that needs it arrives."""
    monkeypatch.setattr(config, "load_env", lambda path=None: {})
    assert config.get_secret("WISE_API_TOKEN") is None
    assert config.get_secret("WISE_API_TOKEN", default="none yet") == "none yet"


# ---------------------------------------------------------------------------
#  The template and the code must agree
# ---------------------------------------------------------------------------

def test_every_secret_the_code_expects_is_in_the_template():
    """
    Catches drift: if a later stage starts needing a new secret, this fails
    until .env.example documents where to get it.
    """
    template = config.ENV_EXAMPLE_PATH.read_text()
    for name, _stage in config._SECRET_STAGES:
        assert f"{name}=" in template, f"{name} is missing from .env.example"


# ---------------------------------------------------------------------------
#  Tax settings
# ---------------------------------------------------------------------------

def test_tax_settings_match_the_established_situation():
    """
    These were established during planning (see PLAN.md) and drive Stage 9's
    calculator. If one is ever changed by accident, the tax number changes
    silently - so pin them here.
    """
    s = config.SETTINGS
    assert s["filing_status"] == "MFS", "Married Filing Separately, not Single"
    assert s["country_of_residence"] == "France"
    assert s["bona_fide_resident"] is True
    assert s["relief_method"] == "FEIE"
    assert s["certificate_of_coverage"] is False, (
        "Flip this to True only once a French Certificate of Coverage exists"
    )
    assert config.BASE_CURRENCY == "USD"


def test_everyone_paid_as_a_contractor_is_on_the_roster():
    """Alerts can only fire for people on this list."""
    assert set(config.contractor_names()) == {
        "Katerina Mrvova", "Yetunde Olaniyan", "Olaide Olaniyan",
        "Evgeniya Dyatlovskaya", "Sunniva Texe",
    }


def test_only_katerina_gets_a_1099():
    """
    A 1099-NEC reports payments to a US person. Katerina is a US citizen, so
    she gets a W-9 and a 1099 at $600. The other three are not US persons,
    complete a W-8BEN instead, and get no 1099.
    """
    katerina = config.contractor("Katerina Mrvova")
    assert katerina["us_person"] is True
    assert katerina["form"] == "W-9"
    assert katerina["issues_1099"] is True

    for name in ["Yetunde Olaniyan", "Olaide Olaniyan",
                 "Evgeniya Dyatlovskaya", "Sunniva Texe"]:
        person = config.contractor(name)
        assert person["us_person"] is False
        assert person["form"] == "W-8BEN"
        assert person["issues_1099"] is False


def test_katerina_cannot_be_recorded_as_a_non_us_person():
    """
    Pinned deliberately.

    US citizenship decides this. Dual nationality and living abroad do not
    change it, and a US citizen cannot sign a W-8BEN because that form
    certifies foreign status. This was raised, explained and accepted.

    If anyone ever edits that flag, this test fails loudly rather than the
    change passing quietly and a required 1099 never being issued. A missing
    W-9 TIN also triggers 24% backup withholding.
    """
    katerina = config.contractor("Katerina Mrvova")
    assert katerina["us_person"] is True, (
        "Katerina is a US citizen and must not be recorded otherwise")
    assert katerina["form"] != "W-8BEN"


def test_sunniva_is_flagged_every_december_regardless_of_amount():
    """Asked for explicitly, so it is a decision rather than an oversight."""
    assert config.contractor("Sunniva Texe").get("always_flag_in_december")


def test_nicknames_and_full_names_both_match():
    """
    A Wise transfer may be labelled either way - "Ayoka" and "Yetunde
    Olaniyan" are one person. Missing one form would split their total and
    hide a $600 crossing.
    """
    for text, expected in [
        ("Transfer to Ayoka", "Yetunde Olaniyan"),
        ("Payment to Yetunde Olaniyan", "Yetunde Olaniyan"),
        ("wise transfer Jane", "Evgeniya Dyatlovskaya"),
        ("Evgeniya Dyatlovskaya September", "Evgeniya Dyatlovskaya"),
        ("KATERINA payout", "Katerina Mrvova"),
        ("Sunniva Texe hours", "Sunniva Texe"),
    ]:
        assert config.match_contractor(text)["name"] == expected, text


def test_a_name_inside_another_word_is_not_a_match():
    """
    Matching is on whole words. Without that, "Jane" would match "Janet" and
    quietly attribute a stranger's payment to a contractor.
    """
    for text in ["Janet Smith invoice", "Sunnivale Ltd", "Katerinaburg Hotel"]:
        assert config.match_contractor(text) is None, text


def test_the_two_businesses_are_named_consistently():
    assert config.BUSINESSES == ("hostlyft", "marcus")


# ---------------------------------------------------------------------------
#  Secrets must never reach GitHub
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "path",
    [
        "tax/.env",
        "tax/hostlyft_tax.db",
        "tax/hostlyft_tax.db-wal",   # SQLite's working side-files
        "tax/hostlyft_tax.db-shm",
        "tax/wise_private_key.pem",
        "tax/imports/capitalone.csv",
        ".venv/x",
    ],
)
def test_git_refuses_to_track_private_files(path):
    """
    Asks git directly: would you ignore this file? Anything other than "yes"
    means a real risk of publishing financial data or an API key.
    """
    result = subprocess.run(
        ["git", "check-ignore", "-q", path],
        cwd=config.ROOT,
        capture_output=True,
    )
    assert result.returncode == 0, f"git would NOT ignore {path}"


def test_the_blank_template_is_not_ignored():
    """.env.example carries no secrets and must stay in the repo."""
    result = subprocess.run(
        ["git", "check-ignore", "-q", ".env.example"],
        cwd=config.ROOT,
        capture_output=True,
    )
    assert result.returncode != 0, ".env.example should be tracked by git"


# ---------------------------------------------------------------------------
#  Two people, one surname
# ---------------------------------------------------------------------------

def test_a_shared_surname_is_detected_automatically():
    """
    Yetunde Olaniyan (Ayoka) and Olaide Olaniyan are different people.
    Neither has "Olaniyan" written as an alias - the clash is between their
    SURNAMES - so it has to be worked out from the roster rather than
    remembered.
    """
    assert "olaniyan" in config.ambiguous_aliases()


def test_full_names_still_match_exactly_despite_the_shared_surname():
    assert config.match_contractor(
        "Sent money to Olaide Olaniyan")["name"] == "Olaide Olaniyan"
    assert config.match_contractor(
        "Sent money to Yetunde Olaniyan")["name"] == "Yetunde Olaniyan"
    assert config.match_contractor(
        "Transfer to Ayoka")["name"] == "Yetunde Olaniyan"


def test_a_bare_shared_surname_is_refused_not_guessed():
    """
    THE ONE THIS EXISTS FOR.

    A payment labelled only "Olaniyan" cannot be attributed. Guessing would
    either push someone over the $600 threshold who is not there, or hide
    someone who is. So it raises, and the caller flags it for review.
    """
    with pytest.raises(config.AmbiguousContractor) as caught:
        config.match_contractor("Payment to Olaniyan")

    message = str(caught.value)
    assert "Olaide Olaniyan" in message
    assert "Yetunde Olaniyan" in message
    assert "Refusing to guess" in message


def test_a_caller_that_only_wants_a_yes_or_no_gets_none():
    assert config.match_contractor("Payment to Olaniyan", strict=False) is None


def test_adding_a_colliding_name_would_be_caught_automatically(monkeypatch):
    """
    The clash list is derived, not hand-written. Someone joining with a name
    that collides is detected without anyone remembering to update a list.
    """
    roster = config.CONTRACTORS + [{
        "name": "Katerina Nowak", "aliases": [], "us_person": False,
        "form": "W-8BEN", "issues_1099": False,
    }]
    monkeypatch.setattr(config, "CONTRACTORS", roster)

    assert "katerina" in config.ambiguous_aliases()
    with pytest.raises(config.AmbiguousContractor):
        config.match_contractor("payment to Katerina")
