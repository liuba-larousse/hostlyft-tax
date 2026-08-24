"""
wise_keys.py - create the key pair Wise needs before it will show statements.

    cd ~/Documents/hostlyft-tax
    source .venv/bin/activate
    python scripts/wise_keys.py

Run once. It makes two files in tax/ and then prints exactly what to do with
them.

    --check          prove the pair works, without making a new one
    --show-public    print the public key again, ready to copy
    --replace        make a NEW pair (the old one stops working)

WHY THIS IS NEEDED
    Wise refuses to hand statements to an ordinary API token. Every request
    comes back 403 Forbidden, even with a perfectly valid token. That is
    European banking regulation, not a fault.

    The way through is a pair of matched keys - one kept here, one given to
    Wise. See taxlib/wise_sca.py for how the exchange works.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from taxlib import config, wise_sca   # noqa: E402

BOLD, GREEN, YELLOW, RED, OFF = (
    "\033[1m", "\033[32m", "\033[33m", "\033[31m", "\033[0m")

PRIVATE_KEY_PATH = config.DATA_DIR / "wise_private_key.pem"
PUBLIC_KEY_PATH = config.DATA_DIR / "wise_public_key.pem"


def make_keys(replace=False):
    """Create the pair and write both files with the right permissions."""
    config.ensure_data_dir()

    if PRIVATE_KEY_PATH.exists() and not replace:
        print(f"{YELLOW}A key pair already exists.{OFF}")
        print(f"  private  {PRIVATE_KEY_PATH}")
        print(f"  public   {PUBLIC_KEY_PATH}")
        print()
        print("Nothing was changed. Your options:")
        print("  python scripts/wise_keys.py --check         is it working?")
        print("  python scripts/wise_keys.py --show-public   print it again")
        print("  python scripts/wise_keys.py --replace       start over")
        print()
        print(f"{YELLOW}Only use --replace if you are going to upload the new"
              f" public key to Wise as well.{OFF}")
        print("The old one stops working the moment it is replaced.")
        return False

    print("Creating a 2048-bit RSA key pair ...")
    private_pem, public_pem = wise_sca.generate_keypair()

    PRIVATE_KEY_PATH.write_bytes(private_pem)
    PRIVATE_KEY_PATH.chmod(0o600)      # only your account can read it

    PUBLIC_KEY_PATH.write_bytes(public_pem)
    PUBLIC_KEY_PATH.chmod(0o644)       # harmless to share - that is the point

    print(f"{GREEN}  done.{OFF}")
    print(f"  private key  {PRIVATE_KEY_PATH}   (stays on this Mac, locked to you)")
    print(f"  public key   {PUBLIC_KEY_PATH}    (this is the one you upload)")
    return True


def check_keys():
    """
    Prove the two files really are a matched pair, by signing a made-up
    code and checking the signature against the public key - which is
    exactly what Wise does at their end.

    Better to find a broken pair here than as a baffling 403 later.
    """
    print(f"{BOLD}CHECKING THE KEY PAIR{OFF}")
    print("-" * 62)

    if not PRIVATE_KEY_PATH.exists():
        print(f"{RED}  No private key yet.{OFF}")
        print("  Run:  python scripts/wise_keys.py")
        return False

    try:
        private_key = wise_sca.load_private_key(PRIVATE_KEY_PATH)
    except wise_sca.WiseSigningError as error:
        print(f"{RED}  {error}{OFF}")
        return False
    print("  private key loads")

    if not PUBLIC_KEY_PATH.exists():
        print(f"{RED}  The public key file is missing.{OFF}")
        print("  Run:  python scripts/wise_keys.py --replace")
        return False
    print("  public key loads")

    # The real test: sign something, then verify it the way Wise will.
    pretend_token = "a-pretend-one-time-code-from-wise-0123456789"
    signature = wise_sca.sign_token(private_key, pretend_token)

    if not wise_sca.verify_signature(PUBLIC_KEY_PATH.read_bytes(),
                                     pretend_token, signature):
        print(f"{RED}  The two keys do NOT match.{OFF}")
        print("  Make a fresh pair:  python scripts/wise_keys.py --replace")
        print("  then upload the new public key to Wise.")
        return False
    print("  a signature made with the private key verifies against the public one")

    # And prove a tampered code is rejected, so the check means something.
    if wise_sca.verify_signature(PUBLIC_KEY_PATH.read_bytes(),
                                 "a-different-code", signature):
        print(f"{RED}  A wrong code was accepted. Something is badly wrong.{OFF}")
        return False
    print("  a different code is correctly rejected")

    permissions = oct(PRIVATE_KEY_PATH.stat().st_mode & 0o777)[2:]
    if permissions == "600":
        print(f"  private key is {permissions} - only your account can read it")
    else:
        print(f"{YELLOW}  private key is {permissions}, should be 600{OFF}")
        PRIVATE_KEY_PATH.chmod(0o600)
        print("  fixed.")

    print()
    print(f"{GREEN}The key pair is sound.{OFF}")
    return True


def show_public_key():
    if not PUBLIC_KEY_PATH.exists():
        print(f"{RED}No public key yet. Run:  python scripts/wise_keys.py{OFF}")
        return False
    print(PUBLIC_KEY_PATH.read_text().strip())
    return True


def print_upload_instructions():
    print()
    print("=" * 62)
    print(f"{BOLD}WHAT TO DO NEXT - about 5 minutes on the Wise website{OFF}")
    print("=" * 62)
    print()
    print(f"{BOLD}1. Open your Wise API settings{OFF}")
    print("   wise.com -> your name, top right -> Settings -> API tokens")
    print()
    print(f"{BOLD}2. Create a token, if you haven't already{OFF}")
    print("   Create token -> choose READ ONLY -> copy it")
    print()
    print("   Read-only is correct and important. This project only ever")
    print("   reads transactions. It should not be able to send money.")
    print()
    print("   Put it in tax/.env on the line  WISE_API_TOKEN=")
    print()
    print(f"{BOLD}3. Upload the public key{OFF}")
    print("   On the same page: Manage public keys -> Add public key")
    print()
    print("   It wants the CONTENTS of the file, not the file itself.")
    print("   Copy them to your clipboard with:")
    print()
    print(f"      {BOLD}pbcopy < {PUBLIC_KEY_PATH}{OFF}")
    print()
    print("   then paste into the box. It starts with")
    print("      -----BEGIN PUBLIC KEY-----")
    print("   and ends with")
    print("      -----END PUBLIC KEY-----")
    print("   Include both of those lines.")
    print()
    print(f"{BOLD}4. Come back and check it worked{OFF}")
    print()
    print("      python scripts/check_secrets.py --connect")
    print()
    print("   That lists your Wise profiles and tells you which number to")
    print("   put in WISE_PROFILE_ID.")
    print()
    print(f"{YELLOW}Never upload the PRIVATE key. It never leaves this Mac.{OFF}")
    print("Only wise_public_key.pem is meant to be shared - that is the whole")
    print("point of it. .gitignore blocks both from GitHub either way.")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Create the key pair Wise needs for statements.")
    parser.add_argument("--check", action="store_true",
                        help="prove the existing pair works")
    parser.add_argument("--show-public", action="store_true",
                        help="print the public key, ready to copy")
    parser.add_argument("--replace", action="store_true",
                        help="make a NEW pair (the old one stops working)")
    args = parser.parse_args()

    if args.show_public:
        return 0 if show_public_key() else 1

    print()
    print("Hostlyft Tax Tracker - Wise keys")
    print("=" * 62)

    if args.check:
        print()
        return 0 if check_keys() else 1

    created = make_keys(replace=args.replace)
    if created:
        print()
        if not check_keys():
            return 1
        print_upload_instructions()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
