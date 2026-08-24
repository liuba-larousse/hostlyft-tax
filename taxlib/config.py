"""
config.py - one place that knows where everything lives and who you are,
tax-wise.

Every other file in the project asks this one for:

  * file paths       - where the database and the secrets file sit
  * secrets          - your Stripe key, Wise token, Gmail app password
  * tax settings     - filing status, country, which reliefs apply

Keeping it in one file means that when something changes (you register in
France, say) you edit one line here rather than hunting through ten scripts.

You can run this file directly to get a plain-English status report:

    python3 -m taxlib.config

It uses only Python's built-in tools, so it works even before the libraries in
requirements.txt are installed.
"""

from pathlib import Path


# ===========================================================================
#  WHERE THINGS LIVE
# ===========================================================================
#
# __file__ is this file. .resolve() turns it into a full path.
# .parent is the folder containing it (taxlib/), .parent.parent is the project
# folder. Working it out this way means the project keeps working if you move
# or rename the folder.

ROOT = Path(__file__).resolve().parent.parent

# tax/ holds the two things that must never reach GitHub: your secrets and
# your financial database. Everything else in the project is just code.
DATA_DIR = ROOT / "tax"

ENV_PATH = DATA_DIR / ".env"                  # your real secrets
ENV_EXAMPLE_PATH = ROOT / ".env.example"      # the blank template
DB_PATH = DATA_DIR / "hostlyft_tax.db"        # the database (built in Stage 2)

# Where you drop the Capital One CSV export (Stage 7).
IMPORTS_DIR = DATA_DIR / "imports"

# The plain-English categorisation rules you can edit yourself (Stage 8).
RULES_PATH = ROOT / "rules.txt"


# ===========================================================================
#  YOUR TAX SITUATION
# ===========================================================================
#
# These are settings, not secrets - they are safe in GitHub. They were
# established during planning; see PLAN.md. Stage 9's calculator reads them.
#
# The one you are most likely to change is CERTIFICATE_OF_COVERAGE.

SETTINGS = {
    # --- who is filing ---
    "tax_year": 2026,

    # "Married Filing Separately". You are married to a non-US person and
    # filing alone. The IRS counts a foreign marriage as married, so filing
    # alone means MFS - NOT Single. Head of Household needs a dependent
    # living with you; there is none.
    "filing_status": "MFS",

    # --- where you live ---
    "country_of_residence": "France",

    # Bona fide residence: you live in France permanently, for the whole tax
    # year. This is what unlocks the Foreign Earned Income Exclusion below.
    "bona_fide_resident": True,

    # --- which US reliefs apply ---
    #
    # FEIE = Foreign Earned Income Exclusion (IRS Form 2555). It excludes
    # foreign earned income from US INCOME tax - up to a cap. For you it
    # very likely makes US income tax $0.
    #
    # The alternative, FTC (Foreign Tax Credit), credits foreign income tax
    # you already paid against your US bill. You pay no French income tax,
    # so there is nothing to credit - FEIE is the right choice.
    "relief_method": "FEIE",

    # THE IMPORTANT SWITCH.
    #
    # FEIE removes income tax but does NOT remove self-employment tax
    # (Social Security + Medicare, 15.3%). In your case that is essentially
    # the whole bill.
    #
    # The only thing that removes it is the US-France totalization agreement,
    # and claiming it requires a French Certificate of Coverage from the
    # agency collecting your social contributions. You currently pay into
    # nothing, so no such certificate exists -> False.
    #
    # If you ever register in France (URSSAF or similar) and receive the
    # certificate, change this to True and re-run the calculator.
    #
    #   False -> full 15.3% self-employment tax on 92.35% of net profit
    #   True  -> $0 self-employment tax
    #
    # Not automatically a saving: French self-employed contributions for a
    # service business run roughly 21-24% OF REVENUE, which can exceed 15.3%
    # of PROFIT. Registering is about being compliant where you live.
    "certificate_of_coverage": False,
}

# ===========================================================================
#  THE TEAM
# ===========================================================================
#
# Wise transfers may be labelled with a full name OR a nickname, so both are
# matched. "Ayoka" and "Jane" are the names used day to day; the full names
# are what appear on tax forms.
#
# WHY ONLY ONE PERSON GETS A 1099
#     A 1099-NEC reports payments to a US person. Three of the four are not
#     US persons, so they complete a W-8BEN - the form that certifies foreign
#     status - and no 1099 is issued.
#
#     Katerina is a US citizen. A US citizen is a US person for tax purposes
#     regardless of dual citizenship or where they live. No election changes
#     that, and a US citizen cannot sign a W-8BEN, because it certifies
#     exactly the thing that is not true of her.
#
#     This was raised, explained and accepted. It is deliberately written as
#     a fixed fact rather than a setting, and a test pins it, so it cannot be
#     changed by accident.
#
# WHAT COUNTS TOWARD $600
#     WITHDRAWALS ONLY. Money sitting in a Wise jar is still Liuba's money -
#     allocating it pays nobody. See taxlib/db.py.

CONTRACTORS = [
    {
        "name": "Katerina Mrvova",
        "aliases": ["Katerina", "Mrvova"],
        "us_person": True,
        "form": "W-9",
        "issues_1099": True,
        "note": ("US citizen, also Czech, living in Brazil. US citizenship "
                 "decides this - dual nationality and residence abroad do "
                 "not change it. A missing W-9 TIN triggers 24% backup "
                 "withholding."),
    },
    {
        "name": "Yetunde Olaniyan",
        "aliases": ["Ayoka", "Yetunde", "Olaniyan"],
        "us_person": False,
        "form": "W-8BEN",
        "issues_1099": False,
        "note": "Known as Ayoka. Not a US person.",
    },
    {
        "name": "Evgeniya Dyatlovskaya",
        "aliases": ["Jane", "Evgeniya", "Dyatlovskaya"],
        "us_person": False,
        "form": "W-8BEN",
        "issues_1099": False,
        "note": "Known as Jane. Not a US person.",
    },
    {
        "name": "Sunniva Texe",
        "aliases": ["Sunniva", "Texe"],
        "us_person": False,
        "form": "W-8BEN",
        "issues_1099": False,
        # Flagged every December regardless of amount, so it is a conscious
        # decision rather than something quietly forgotten.
        "always_flag_in_december": True,
        "note": "Hourly at $25.00/hr. Not a US person.",
    },
]


def contractor_names():
    """The canonical full names, in roster order."""
    return [person["name"] for person in CONTRACTORS]


def contractor(name):
    """Look one person up by their full name."""
    for person in CONTRACTORS:
        if person["name"].lower() == (name or "").lower():
            return person
    return None


def all_names_for(person):
    """
    Every label a transfer to this person might carry: their full name, and
    each nickname or surname.
    """
    return [person["name"]] + list(person.get("aliases", []))


def match_contractor(text):
    """
    Work out which contractor a transaction description refers to, if any.

    Matching is on whole words only. Without that, a short alias would match
    inside an unrelated word and quietly attribute somebody else's payment.

    Returns the contractor dictionary, or None.
    """
    import re

    if not text:
        return None

    for person in CONTRACTORS:
        for label in all_names_for(person):
            if re.search(rf"\b{re.escape(label)}\b", text, re.IGNORECASE):
                return person
    return None


# ===========================================================================
#  THE TWO BUSINESSES
# ===========================================================================
#
# Hostlyft LLC and the Marcus work are separate businesses. They are reported
# separately, so the Hostlyft profit-and-loss used for team splits stays
# honest - but they are TAXED TOGETHER, because a single-member LLC is a
# disregarded entity and both land on the same 1040.
#
# Leaving Marcus out would understate self-employment tax by roughly $6,900.

BUSINESS_HOSTLYFT = "hostlyft"
BUSINESS_MARCUS = "marcus"
BUSINESSES = (BUSINESS_HOSTLYFT, BUSINESS_MARCUS)

# What an incoming payment from Marcus looks like in the personal Wise
# account. Only credits matching this are read; everything else in that
# account is never read, stored or logged.
MARCUS_MATCH = ["Marcus"]

# The reporting currency. Everything is converted to this before it is added
# up, because the IRS wants US dollars.
BASE_CURRENCY = "USD"


# ===========================================================================
#  READING THE SECRETS FILE
# ===========================================================================

def load_env(path=None):
    """
    Read tax/.env and return its contents as a dictionary.

    The file format is one NAME=value per line. Blank lines and lines
    starting with # are ignored. Surrounding quotes, if you use any, are
    stripped.

    Returns an empty dictionary if the file doesn't exist yet, rather than
    crashing - so the project is usable before you've filled anything in.
    """
    path = Path(path) if path else ENV_PATH
    values = {}

    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()

        # Skip blank lines and comments.
        if not line or line.startswith("#"):
            continue

        # A usable line must contain "=". Anything else is ignored quietly.
        if "=" not in line:
            continue

        name, _, value = line.partition("=")
        name = name.strip()
        value = value.strip().strip('"').strip("'")

        if name:
            values[name] = value

    return values


class MissingSecret(Exception):
    """
    Raised when a script needs a secret that isn't filled in yet.

    It exists so the error message can tell you exactly which line of
    tax/.env to fill in, instead of a confusing crash deep inside some
    library.
    """


def get_secret(name, default=None, required=False):
    """
    Fetch one secret out of tax/.env.

    name     - e.g. "STRIPE_SECRET_KEY"
    default  - what to return if it isn't set
    required - if True, raise a clear error rather than returning nothing

    Example:
        key = get_secret("STRIPE_SECRET_KEY", required=True)
    """
    value = load_env().get(name, "").strip()

    if value:
        return value

    if required:
        raise MissingSecret(
            f"{name} is not set.\n"
            f"\n"
            f"  Fix it:  open {ENV_PATH}\n"
            f"           find the line starting  {name}=\n"
            f"           put the value after the = sign, then save.\n"
            f"\n"
            f"  In Terminal:  nano {ENV_PATH}\n"
            f"                (Control+O to save, Enter, Control+X to quit)\n"
            f"\n"
            f"  {ENV_EXAMPLE_PATH.name} explains where to find this value."
        )

    return default


def ensure_data_dir():
    """
    Create tax/ if it isn't there, and make it readable only by you.

    Permission 0o700 means: the owner (you) may read, write and open the
    folder; nobody else on the machine can look inside at all.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.chmod(0o700)
    return DATA_DIR


# ===========================================================================
#  STATUS REPORT
# ===========================================================================

# Secrets we know about, and the stage that first needs each one.
_SECRET_STAGES = [
    ("STRIPE_SECRET_KEY", "Stage 4  - Stripe income"),
    ("WISE_API_TOKEN", "Stage 6  - Wise account"),
    ("WISE_PROFILE_ID", "Stage 6  - Wise account"),
    ("GMAIL_ADDRESS", "Stage 10 - email reminders"),
    ("GMAIL_APP_PASSWORD", "Stage 10 - email reminders"),
    ("GOOGLE_SHEET_ID", "Stage 11 - Google Sheet tabs"),
    ("GOOGLE_SERVICE_ACCOUNT_JSON", "Stage 11 - Google Sheet tabs"),
]


def status_report():
    """Build the plain-English status report as a list of lines."""
    env = load_env()
    lines = []

    lines.append("Hostlyft Tax Tracker - configuration check")
    lines.append("=" * 58)
    lines.append("")

    lines.append("FILES")
    lines.append(f"  project folder    {ROOT}")
    lines.append(f"  private data      {DATA_DIR}"
                 f"{'' if DATA_DIR.exists() else '   (not created yet)'}")
    lines.append(f"  secrets file      {ENV_PATH}"
                 f"{'' if ENV_PATH.exists() else '   (not created yet)'}")
    lines.append(f"  database          {DB_PATH}"
                 f"{'' if DB_PATH.exists() else '   (built in Stage 2)'}")
    lines.append("")

    lines.append("YOUR TAX SETTINGS")
    lines.append(f"  tax year                  {SETTINGS['tax_year']}")
    lines.append(f"  filing status             {SETTINGS['filing_status']}"
                 f"  (Married Filing Separately)")
    lines.append(f"  country of residence      {SETTINGS['country_of_residence']}")
    lines.append(f"  bona fide resident        {SETTINGS['bona_fide_resident']}"
                 f"   -> Foreign Earned Income Exclusion available")
    lines.append(f"  relief method             {SETTINGS['relief_method']}")
    lines.append(f"  certificate of coverage   {SETTINGS['certificate_of_coverage']}"
                 f"  -> self-employment tax "
                 f"{'is $0' if SETTINGS['certificate_of_coverage'] else 'applies in full (15.3%)'}")
    lines.append("")

    lines.append("SECRETS  (blank ones are fine until that stage arrives)")
    if not ENV_PATH.exists():
        lines.append("  tax/.env does not exist yet.")
        lines.append("  Run  ./setup_mac.command  to create it from the template.")
    else:
        for name, stage in _SECRET_STAGES:
            filled = bool(env.get(name, "").strip())
            mark = "set    " if filled else "blank  "
            lines.append(f"  [{mark}] {name:<22} {stage}")
    lines.append("")

    return lines


def main():
    for line in status_report():
        print(line)


if __name__ == "__main__":
    main()
