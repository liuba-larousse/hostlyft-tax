"""
google_login.py - sign in to Google, once.

    python scripts/google_login.py

Opens a browser, asks you to approve, and saves a token to
tax/google_token.json. Everything after that uses the saved token and
renews it silently - no browser, which is what lets a scheduled job run
unattended.

    --force   sign in again even if a token already exists
    --revoke  forget the saved token on this Mac
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from taxlib import gsheets   # noqa: E402

GREEN, YELLOW, RED, BOLD, OFF = (
    "\033[32m", "\033[33m", "\033[31m", "\033[1m", "\033[0m")


def main():
    parser = argparse.ArgumentParser(description="Sign in to Google.")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--revoke", action="store_true",
                        help="forget the saved sign-in on this Mac")
    args = parser.parse_args()

    print()
    print("Hostlyft Tax Tracker - Google sign-in")
    print("=" * 66)

    if args.revoke:
        path = gsheets.token_path()
        if path.exists():
            path.unlink()
            print(f"{GREEN}Forgotten.{OFF} {path} deleted.")
            print("To withdraw access at Google's end as well, visit")
            print("   myaccount.google.com/permissions")
        else:
            print("No saved sign-in to forget.")
        return 0

    if gsheets.token_path().exists() and not args.force:
        print(f"{GREEN}Already signed in.{OFF}")
        print(f"   token: {gsheets.token_path()}")
        print("   check it works:  python scripts/check_google.py")
        print("   sign in again:   python scripts/google_login.py --force")
        return 0

    try:
        gsheets.read_client_file()
    except gsheets.GoogleError as error:
        print(f"\n{RED}{error}{OFF}\n")
        return 1

    print()
    print("A browser window will open. Sign in as team@hostlyft.com and")
    print("approve the request.")
    print()
    print(f"{BOLD}What you are approving:{OFF}")
    print("   See, edit, create and delete your Google Sheets.")
    print()
    print("That is the only permission asked for. Not your documents, not")
    print("your photos, not your folders - spreadsheets only.")
    print()
    print("You can withdraw it any time at myaccount.google.com/permissions")
    print()

    try:
        gsheets.sign_in()
    except gsheets.GoogleError as error:
        print(f"\n{RED}{error}{OFF}\n")
        return 1
    except Exception as error:
        print(f"\n{RED}Sign-in did not finish: {str(error)[:300]}{OFF}\n")
        return 1

    print()
    print(f"{GREEN}{BOLD}Signed in.{OFF}")
    print(f"   token saved to {gsheets.token_path()} (locked to your account)")
    print("   now run:  python scripts/check_google.py")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
