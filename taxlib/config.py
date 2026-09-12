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

MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# Names used in one place so a typo cannot quietly drop somebody from a split.
FOUNDER = "Liubov Kapitulskaya"
KATERINA = "Katerina Mrvova"
AYOKA = "Yetunde Olaniyan"
JANE = "Evgeniya Dyatlovskaya"


# ===========================================================================
#  STAGE 14 - THE QUARTERLY PROFIT DISTRIBUTION
# ===========================================================================
#
# CHANGE THESE FREELY. They decide who receives what, and nothing else -
# not one figure on the tax return moves when you edit them. What IS
# deductible is fixed by law and lives in distribution.py, not here.
#
# Her rule, given 2026-09-12, replacing an earlier flat 25% founder share:
#     20% shared EVENLY between the four of them
#     80% in proportion to who drove the revenue, with Marcus left out
#
# Marcus is excluded because that work is hers alone, done outside Hostlyft.
# Including it would hand the team a share of income they had no part in.
#
# Sunniva is not a participant. She is hourly, not a revenue manager, and is
# paid for her time rather than out of profit.
#
# WHAT COUNTS AS REVENUE SHE DROVE: the 5% she takes off the top of every
# client payment - her own answer when asked. It makes the weights a true
# partition of gross client revenue: her 5%, and the 95% the managers split.

DISTRIBUTION = {
    "even_share": 0.20,          # split equally between the participants
    "proportional_share": 0.80,  # split by revenue driven (must total 1.0)
    "operating_buffer_usd": 1000.00,   # kept back, ~a quarter of subscriptions
    "founder_off_the_top": 0.05,       # her cut before the group percentages
    "participants": [FOUNDER, KATERINA, AYOKA, JANE],
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

# ===========================================================================
#  HOME OFFICE  -  Stage 12b
# ===========================================================================
#
# Edit these; do not edit the code that uses them.
#
# WHAT THIS IS WORTH, so you can judge the paperwork against the payoff.
# Your US income tax is already $0 because the Foreign Earned Income
# Exclusion covers all of your profit. So a deduction saves you nothing in
# income tax - it only reduces SELF-EMPLOYMENT tax, at about 14 cents in
# the dollar. Worth having; not the 30-40% people assume.
#
# THE TEST YOU MUST ACTUALLY MEET - "exclusive and regular use".
# The 12 m2 must be used ONLY for work. Not a spare room that is also a
# guest room; not a desk in the corner of the living room. A dining table
# you clear away in the evening does NOT qualify, and this is the
# condition people fail. If the room is not exclusively an office, set
# EXCLUSIVE_USE to False and the deduction is not claimed.
#
# A foreign home is fine - nothing requires the office to be in the US.
# And because you RENT, there is no depreciation to work out, which is the
# hardest part of Form 8829. That does not apply to you at all.

HOME_OFFICE = {
    # Is it used exclusively and regularly for business? If not, no claim.
    "exclusive_use": True,

    # Areas. Any unit, as long as both are the SAME unit - only the ratio
    # matters for the actual-cost method.
    "total_area": 60.0,
    "office_area": 12.0,
    "area_unit": "m2",

    # What you pay for the whole home, per month, in this currency.
    #
    # UTILITIES SHOULD NOT INCLUDE INTERNET. Internet is already deducted
    # in full under "phone and internet" in rules.txt. Counting it here as
    # well would deduct part of it twice. If your 120 includes internet,
    # take it out here.
    "monthly_rent": 720.0,
    "monthly_utilities": 120.0,
    "monthly_insurance": 0.0,          # renter's / contents insurance
    "currency": "EUR",

    # How many months of the year the office was used this way.
    "months": 12,
}

# The simplified alternative the IRS offers: a flat rate per square foot,
# capped. VERIFY BOTH FIGURES against
# https://www.irs.gov/businesses/small-businesses-self-employed/simplified-option-for-home-office-deduction
# before relying on them - they were not read from the IRS site.
SIMPLIFIED_HOME_OFFICE_RATE_PER_SQFT = 5.00
SIMPLIFIED_HOME_OFFICE_MAX_SQFT = 300
SQFT_PER_SQM = 10.7639


# ===========================================================================
#  HOW MUCH OF EACH CATEGORY IS DEDUCTIBLE
# ===========================================================================
#
# Almost everything a business spends is deductible in full. Meals are the
# exception, and they are the reason this table exists.
#
# BUSINESS MEALS ARE 50% DEDUCTIBLE. The temporary 100% allowance for
# restaurant meals ran in 2021 and 2022 only and has expired - do not
# reintroduce it. IRS Publication 463.
#
# Anything not listed here is treated as 100% deductible.

CATEGORY_DEDUCTIBLE_SHARE = {
    "meals": 0.50,
}


def deductible_share(category):
    """How much of this category actually reduces taxable profit."""
    return CATEGORY_DEDUCTIBLE_SHARE.get((category or "").strip().lower(), 1.0)


# HER RULE, GIVEN 2026-09-12: MONEY SENT STRAIGHT OUT OF A CONTRACTOR'S JAR
# IS THAT CONTRACTOR'S PAYOUT, WHOEVER THE CHEQUE IS MADE OUT TO.
#
# She pays some people through a third party - Ayoka through her brother
# Olatunbosun, Jane through Dmitry Kapitulskiy or Vadim Snitserev. Matching
# on the recipient's name alone misses those, and a missed one is not a small
# error: it drops a deductible contractor cost AND understates that person's
# withdrawals, which is what the $600 threshold and the reconciliation gap
# are both measured on.
#
# The named payment_aliases below catch the cases we know about. The general
# rule she stated is stronger and is NOT yet automated: an outgoing transfer
# that matches money just released from someone's jar belongs to that person,
# even when the name has never been seen before. The evidence is already in
# the database - jar_movements records what left each jar and when - so this
# is a matching job, not a data problem.
#
# TODO, agreed with her: implement jar-sourced attribution in wise_import so
# a new payee is recognised from the jar it came out of rather than waiting
# to be added here by hand.

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
        # "Olaniyan" is deliberately NOT an alias: Olaide Olaniyan is a
        # different person on this same roster. See the ambiguity check below.
        "aliases": ["Ayoka", "Yetunde"],
        # Someone else who receives money on her behalf. Her brother.
        "payment_aliases": ["Olatunbosun"],
        "us_person": False,
        "form": "W-8BEN",
        "issues_1099": False,
        "note": ("Known as Ayoka. Not a US person. Some payments go to her "
                 "brother Olatunbosun Olaniyan on her behalf - the work is "
                 "hers, so the deduction and the W-8BEN are hers too."),
    },
    {
        "name": "Olaide Olaniyan",
        "aliases": ["Olaide"],
        "us_person": False,
        "form": "W-8BEN",
        "issues_1099": False,
        "note": ("Liuba's husband, and a foreign contractor. Shares a surname "
                 "with Yetunde Olaniyan, so surname-only matching is refused "
                 "rather than guessed. Payments to a spouse are deductible on "
                 "the same terms as any contractor - genuine work at a "
                 "reasonable rate - but being a related party, the "
                 "substantiation (a contract, invoices) carries more weight."),
    },
    {
        "name": "Evgeniya Dyatlovskaya",
        "aliases": ["Jane", "Evgeniya", "Dyatlovskaya"],
        # Receives on her behalf.
        "payment_aliases": ["Dmitry Kapitulskiy", "Kapitulskiy",
                            "Snitserev Vadim", "Snitserev"],
        "us_person": False,
        "form": "W-8BEN",
        "issues_1099": False,
        "note": ("Known as Jane. Not a US person. Some payments go to Dmitry "
                 "Kapitulskiy or Vadim Snitserev on her behalf - the work is "
                 "hers, so the deduction and the W-8BEN are hers too. The "
                 "$505.06 to Snitserev on 2026-09-10 emptied Jane's jar: "
                 "$248.00 + $256.88 released plus the $0.18 left in it comes "
                 "to exactly $505.06. See JAR_PAYOUT_RULE below."),
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


def _plain(text):
    """
    Strip accents so names match however they are spelled.

    Wise writes "Kateřina Mrvová"; the roster says "Katerina Mrvova". Without
    this they are different strings, and payments to the one person who
    needs a 1099 would never count toward her $600 threshold.

    NFKD splits an accented letter into the letter plus a combining mark;
    dropping the marks leaves plain ASCII.
    """
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", text or "")
                   if not unicodedata.combining(c))


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
    Every label a transfer to this person might carry.

    Three kinds:
      the full name        "Yetunde Olaniyan"
      nicknames            "Ayoka"
      payment aliases      somebody else who receives money on their behalf

    That last kind matters for tax as well as matching. Paying a
    contractor's relative instead of the contractor does not move who earned
    it: the deduction, the $600 threshold and the tax form all still belong
    to the person who did the work.
    """
    return ([person["name"]]
            + list(person.get("aliases", []))
            + list(person.get("payment_aliases", [])))


def ambiguous_aliases():
    """
    Name fragments that could mean more than one person on the roster.

    Two people share the surname Olaniyan - Yetunde (known as Ayoka) and
    Olaide (Liuba's husband). A payment labelled only "Olaniyan" genuinely
    cannot be attributed, so it must never be guessed: crediting it to the
    wrong person would push someone over the $600 threshold who is not there,
    or hide someone who is.

    Every word of every name is considered, not just the nicknames listed
    above - the collision here is between two SURNAMES, and neither is
    written as an alias. Working it out from the roster means adding another
    person with a colliding name is caught automatically rather than
    remembered.
    """
    from collections import defaultdict

    owners = defaultdict(set)
    for person in CONTRACTORS:
        # every distinct word across their full name and every alias
        for label in all_names_for(person):
            for word in _plain(label).split():
                if len(word) > 2:
                    owners[word.lower()].add(person["name"])

    return {word for word, people in owners.items() if len(people) > 1}


class AmbiguousContractor(Exception):
    """A transaction names someone, but more than one person could match."""

    def __init__(self, label, candidates):
        self.label = label
        self.candidates = candidates
        super().__init__(
            f"'{label}' could be {' or '.join(candidates)}. "
            f"Refusing to guess - it is flagged for review instead.")


def match_contractor(text, strict=True):
    """
    Work out which contractor a transaction description refers to.

    Matching is on whole words only. Without that, a short alias would match
    inside an unrelated word and quietly attribute somebody else's payment -
    "Janet" would become Jane.

    Returns the contractor dictionary, or None.

    Raises AmbiguousContractor when the only thing matched is a name shared
    by two people. That is deliberately an error rather than a best guess:
    the caller flags it for review. With strict=False it returns None
    instead, for callers that just want a yes/no.
    """
    import re

    if not text:
        return None

    ambiguous = ambiguous_aliases()

    # A full-name match always wins - it is unambiguous by definition.
    plain_text = _plain(text)
    for person in CONTRACTORS:
        if re.search(rf"\b{re.escape(_plain(person['name']))}\b",
                     plain_text, re.IGNORECASE):
            return person

    # Then nicknames and first names, skipping anything shared.
    matched, shared = [], []
    for person in CONTRACTORS:
        for label in all_names_for(person):
            if not re.search(rf"\b{re.escape(_plain(label))}\b",
                             plain_text, re.IGNORECASE):
                continue
            if label.lower() in ambiguous:
                shared.append((label, person["name"]))
            elif person not in matched:
                matched.append(person)

    if len(matched) == 1:
        return matched[0]
    if len(matched) > 1:
        if strict:
            raise AmbiguousContractor(
                text, sorted(person["name"] for person in matched))
        return None

    if shared:
        if strict:
            label = shared[0][0]
            raise AmbiguousContractor(
                label, sorted({name for _, name in shared}))
        return None

    # Nothing matched by name or nickname. Before giving up, check for a
    # fragment shared by two people - a bare surname, typically. That is not
    # "no match", it is "cannot tell which", and the two need different
    # handling: one becomes an ordinary expense, the other must be reviewed.
    for word in ambiguous:
        if re.search(rf"\b{re.escape(word)}\b", plain_text, re.IGNORECASE):
            candidates = sorted(
                person["name"] for person in CONTRACTORS
                if re.search(rf"\b{re.escape(word)}\b",
                             _plain(" ".join(all_names_for(person))),
                             re.IGNORECASE))
            if strict:
                raise AmbiguousContractor(word, candidates)
            return None

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
