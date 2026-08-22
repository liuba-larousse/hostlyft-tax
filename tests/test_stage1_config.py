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


def test_all_four_contractors_are_watched():
    """The $600 W-9 / 1099-NEC alarm can only fire for people on this list."""
    assert set(config.CONTRACTORS) == {"Ayoka", "Katerina", "Jane", "Sunniva"}
    assert "Sunniva" in config.CONTRACTORS_ALWAYS_FLAG_IN_DECEMBER


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
