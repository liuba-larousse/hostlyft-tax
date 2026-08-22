"""
check_secrets.py - is everything in tax/.env filled in correctly?

Run it any time:

    cd ~/Documents/hostlyft-tax
    source .venv/bin/activate
    python scripts/check_secrets.py

It checks three separate things:

  1. Is the file locked down, so only your Mac account can read it?
  2. Is each value present and the right SHAPE? (catches nearly every
     copy-and-paste mistake without needing the internet)
  3. Optionally, does the key actually work?  --connect

IT NEVER PRINTS YOUR SECRETS.
Only their shape, e.g. "starts with sk_live_, 107 characters". That is
deliberate: this output is safe to show to anyone, including in a chat window.

    python scripts/check_secrets.py --connect       also test the keys live
    python scripts/check_secrets.py --fix-permissions   re-lock the file
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from taxlib import config   # noqa: E402


GREEN, YELLOW, RED, BOLD, OFF = (
    "\033[32m", "\033[33m", "\033[31m", "\033[1m", "\033[0m")

OK, WARN, BAD, BLANK = "ok", "warn", "bad", "blank"

MARK = {
    OK:    f"{GREEN}  ok   {OFF}",
    WARN:  f"{YELLOW} check {OFF}",
    BAD:   f"{RED} wrong {OFF}",
    BLANK: "       ",
}


# ===========================================================================
#  SHAPE CHECKS
# ===========================================================================
#
# Each function gets the value and returns (status, message).
# They are deliberately picky, because a wrong key produces a confusing
# error deep inside a library hours later, while a wrong SHAPE can be caught
# here in a second.

def check_stripe_key(value):
    if value.startswith("pk_"):
        return BAD, ("that is the PUBLISHABLE key. You need the one labelled "
                     "Secret key - click 'Reveal' next to it")
    if value.startswith("whsec_"):
        return BAD, "that is a webhook signing secret, not the API key"
    if value.startswith("rk_"):
        return WARN, ("that is a restricted key. It works if you gave it read "
                      "access to Invoices, Charges, Balance transactions and "
                      "Payouts")
    if value.startswith("sk_test_"):
        return WARN, ("that is the TEST key - it only sees pretend "
                      "transactions. For real figures use the one starting "
                      "sk_live_")
    if not value.startswith("sk_live_"):
        return BAD, "a Stripe secret key starts with sk_live_ (or sk_test_)"
    if len(value) < 30:
        return BAD, f"only {len(value)} characters - looks cut off mid-paste"
    return OK, f"starts with sk_live_, {len(value)} characters"


def check_wise_token(value):
    # Wise API tokens are UUIDs: 8-4-4-4-12 hexadecimal characters.
    if re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
                    r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", value):
        return OK, "correct format (36 characters, dashes in the right places)"
    return WARN, (f"{len(value)} characters - a Wise token normally looks like "
                  f"8-4-4-4-12 letters and numbers separated by dashes")


def check_wise_profile(value):
    if not value.isdigit():
        return BAD, "this should be digits only - Stage 6 looks it up for you"
    return OK, f"{len(value)}-digit number"


def check_gmail_address(value):
    if "@" not in value or "." not in value.split("@")[-1]:
        return BAD, "that doesn't look like an email address"
    user, _, domain = value.partition("@")
    return OK, f"{user[:2]}...@{domain}"


def check_app_password(value):
    stripped = value.replace(" ", "")
    if "@" in value:
        return BAD, "that looks like an email address, not an app password"
    if len(stripped) != 16:
        return BAD, (f"{len(stripped)} characters - a Google app password is "
                     f"exactly 16 letters. If you typed your normal Gmail "
                     f"password, that will not work; Google blocks it")
    if not stripped.isalpha():
        return WARN, "app passwords are normally 16 lower-case letters only"
    return OK, "16 characters, correct shape"


SECRETS = [
    # name, stage that needs it, checker, required-by-now
    ("STRIPE_SECRET_KEY",  "Stage 4  Stripe income",    check_stripe_key),
    ("WISE_API_TOKEN",     "Stage 6  Wise account",     check_wise_token),
    ("WISE_PROFILE_ID",    "Stage 6  Wise account",     check_wise_profile),
    ("GMAIL_ADDRESS",      "Stage 10 email reminders",  check_gmail_address),
    ("GMAIL_APP_PASSWORD", "Stage 10 email reminders",  check_app_password),
]


def check_for_invisible_characters(value):
    """
    Copying from a web page can drag along characters you cannot see - a
    curly quote, a non-breaking space, a zero-width space. The key then looks
    perfect on screen and is rejected by the server.
    """
    problems = []
    if any(ord(character) > 127 for character in value):
        problems.append("contains a character that isn't a plain letter, "
                        "digit or symbol - most likely a curly quote or an "
                        "odd space picked up from a web page")
    if value != value.strip():
        problems.append("has a space at the start or end")
    return problems


# ===========================================================================
#  FILE SAFETY
# ===========================================================================

def check_file_safety(fix=False):
    """Is the secrets file locked down, and will git refuse to upload it?"""
    print(f"{BOLD}1. IS THE FILE SAFE?{OFF}")
    print("-" * 62)
    everything_fine = True

    # -- does it exist --
    if not config.ENV_PATH.exists():
        print(f"[{MARK[BAD]}] tax/.env does not exist")
        print("        Run  ./setup_mac.command  to create it, then come back.")
        return False
    print(f"[{MARK[OK]}] tax/.env exists")

    # -- permissions --
    # A file's permission is three digits. 600 means: the owner (you) can read
    # and write it, and nobody else on this Mac can even open it.
    for path, wanted, label in [
        (config.DATA_DIR, 0o700, "tax/ folder"),
        (config.ENV_PATH, 0o600, "tax/.env"),
    ]:
        actual = path.stat().st_mode & 0o777
        if actual == wanted:
            print(f"[{MARK[OK]}] {label} is {oct(actual)[2:]} - only your "
                  f"account can read it")
        elif fix:
            path.chmod(wanted)
            print(f"[{MARK[OK]}] {label} was {oct(actual)[2:]}, changed to "
                  f"{oct(wanted)[2:]}")
        else:
            everything_fine = False
            print(f"[{MARK[WARN]}] {label} is {oct(actual)[2:]}, should be "
                  f"{oct(wanted)[2:]}")
            print(f"        Fix it:  python scripts/check_secrets.py "
                  f"--fix-permissions")

    # -- would git upload it? --
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "tax/.env"],
        cwd=config.ROOT, capture_output=True).returncode == 0
    if ignored:
        print(f"[{MARK[OK]}] git refuses to upload tax/.env")
    else:
        everything_fine = False
        print(f"[{MARK[BAD]}] git WOULD upload tax/.env - stop and fix "
              f".gitignore before committing anything")

    # -- is it already in git history? --
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "tax/.env"],
        cwd=config.ROOT, capture_output=True).returncode == 0
    if tracked:
        everything_fine = False
        print(f"[{MARK[BAD]}] tax/.env is already tracked by git. "
              f"Run:  git rm --cached tax/.env")
    else:
        print(f"[{MARK[OK]}] tax/.env is not in git's history")

    print()
    return everything_fine


# ===========================================================================
#  VALUE CHECKS
# ===========================================================================

def check_values():
    """Check the shape of each secret. Returns the list of ones that are set."""
    print(f"{BOLD}2. IS EACH VALUE THE RIGHT SHAPE?{OFF}")
    print("-" * 62)
    print("(blank is fine until that stage arrives)")
    print()

    values = config.load_env()
    filled = []
    problems = 0

    for name, stage, checker in SECRETS:
        raw = values.get(name, "")
        value = raw.strip()

        if not value:
            print(f"[{MARK[BLANK]}] {name}")
            print(f"        blank - needed for {stage}")
            continue

        # invisible-character check first, since it explains weird failures
        invisible = check_for_invisible_characters(raw)
        if invisible:
            problems += 1
            print(f"[{MARK[BAD]}] {name}")
            for note in invisible:
                print(f"        {note}")
            print(f"        Fix: delete the line and retype or re-paste it")
            continue

        status, message = checker(value)
        if status == BAD:
            problems += 1
        print(f"[{MARK[status]}] {name}")
        print(f"        {message}")
        if status != BAD:
            filled.append(name)

    print()
    return filled, problems


# ===========================================================================
#  LIVE CONNECTION TEST
# ===========================================================================

def test_connections(filled):
    """
    Actually use the keys. This is the difference between "I typed something"
    and "it works". Both calls are read-only - nothing is changed or moved.
    """
    print(f"{BOLD}3. DO THE KEYS ACTUALLY WORK?{OFF}")
    print("-" * 62)

    # ---- Stripe ----
    if "STRIPE_SECRET_KEY" in filled:
        try:
            import stripe
            stripe.api_key = config.get_secret("STRIPE_SECRET_KEY")
            account = stripe.Account.retrieve()
            name = (account.get("settings", {})
                           .get("dashboard", {})
                           .get("display_name")) or account.get("id")
            live = "LIVE data" if not str(stripe.api_key).startswith("sk_test_") \
                else "TEST data only"
            print(f"[{MARK[OK]}] Stripe connected - account '{name}' ({live})")
        except Exception as error:
            message = str(error).split("\n")[0][:150]
            print(f"[{MARK[BAD]}] Stripe refused the key")
            print(f"        {message}")
            print(f"        Usually: the key was copied incompletely, or it "
                  f"has been rolled/deleted in the dashboard.")
    else:
        print(f"[{MARK[BLANK]}] Stripe - no key set yet, skipped")

    # ---- Wise ----
    if "WISE_API_TOKEN" in filled:
        try:
            import requests
            response = requests.get(
                "https://api.transferwise.com/v2/profiles",
                headers={"Authorization":
                         f"Bearer {config.get_secret('WISE_API_TOKEN')}"},
                timeout=20)
            if response.status_code == 200:
                profiles = response.json()
                print(f"[{MARK[OK]}] Wise connected - "
                      f"{len(profiles)} profile(s) found")
                for profile in profiles:
                    kind = profile.get("type", "?")
                    label = "<- this is the one you want" \
                        if kind == "BUSINESS" else ""
                    print(f"        {kind:<9} id {profile.get('id')} {label}")
                print(f"        Put the BUSINESS id in WISE_PROFILE_ID")
            elif response.status_code == 401:
                print(f"[{MARK[BAD]}] Wise rejected the token (401) - "
                      f"wrong or expired")
            else:
                print(f"[{MARK[WARN]}] Wise replied {response.status_code}")
        except Exception as error:
            print(f"[{MARK[BAD]}] Could not reach Wise: {str(error)[:120]}")
    else:
        print(f"[{MARK[BLANK]}] Wise - no token set yet, skipped")

    print()
    print("        (Gmail is tested in Stage 10, when reminders are built.)")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Check tax/.env is safe and correctly filled in.")
    parser.add_argument("--connect", action="store_true",
                        help="also test the keys against the real services")
    parser.add_argument("--fix-permissions", action="store_true",
                        help="re-lock tax/ and tax/.env to your account only")
    args = parser.parse_args()

    print()
    print("Hostlyft Tax Tracker - secrets check")
    print("=" * 62)
    print(f"File: {config.ENV_PATH}")
    print("Your actual secrets are never printed below - only their shape.")
    print()

    safe = check_file_safety(fix=args.fix_permissions)
    filled, problems = check_values()

    if args.connect:
        test_connections(filled)

    print("=" * 62)
    if not safe:
        print(f"{RED}Fix the file safety problems above first.{OFF}")
        return 1
    if problems:
        print(f"{RED}{problems} value(s) look wrong.{OFF} "
              f"Each one says what to do.")
        return 1
    if not filled:
        print("File is safe. Nothing filled in yet - that's expected.")
    else:
        print(f"{GREEN}All good.{OFF} {len(filled)} secret(s) set and "
              f"correctly shaped.")
        if not args.connect:
            print("Prove they actually work:  "
                  "python scripts/check_secrets.py --connect")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
