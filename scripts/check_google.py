"""
check_google.py - is the Google setup working?

    python scripts/check_google.py

Checks each step in order and stops at the first thing that is wrong,
saying what to do about it. Run it after every step of GOOGLE-SETUP.md.

Never prints the key.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from taxlib import config, gsheets   # noqa: E402

GREEN, YELLOW, RED, BOLD, OFF = (
    "\033[32m", "\033[33m", "\033[31m", "\033[1m", "\033[0m")
OK, BAD = f"{GREEN}  ok  {OFF}", f"{RED} fail {OFF}"


def main():
    print()
    print("Hostlyft Tax Tracker - Google setup check")
    print("=" * 70)

    # -- 1. the key file --
    print(f"\n{BOLD}1. THE KEY FILE{OFF}")
    print("-" * 70)
    try:
        data = gsheets.read_key_file()
    except gsheets.GoogleError as error:
        print(f"[{BAD}] {error}")
        return 1

    path = gsheets.key_path()
    print(f"[{OK}] found at {path}")
    print(f"[{OK}] it is a service-account key")
    print(f"       project   {data['project_id']}")
    print(f"       robot     {data['client_email']}")

    permissions = oct(path.stat().st_mode & 0o777)[2:]
    if permissions == "600":
        print(f"[{OK}] locked to your account (600)")
    else:
        path.chmod(0o600)
        print(f"[{OK}] was {permissions}, changed to 600")

    import subprocess
    ignored = subprocess.run(["git", "check-ignore", "-q", str(path)],
                             cwd=config.ROOT, capture_output=True).returncode == 0
    print(f"[{OK if ignored else BAD}] git "
          f"{'refuses to upload it' if ignored else 'WOULD UPLOAD IT - stop'}")

    # -- 2. does Google accept it --
    print(f"\n{BOLD}2. DOES GOOGLE ACCEPT IT?{OFF}")
    print("-" * 70)
    try:
        drive = gsheets.service("drive", "v3")
        print(f"[{OK}] signed in to Drive")
    except Exception as error:
        print(f"[{BAD}] {gsheets.describe_error(error, 'Drive')}")
        return 1

    # -- 3. can it see the sheet --
    print(f"\n{BOLD}3. CAN IT SEE YOUR ACCOUNTING SHEET?{OFF}")
    print("-" * 70)
    sheet_id = config.get_secret("GOOGLE_SHEET_ID")
    if not sheet_id:
        print(f"[{BAD}] GOOGLE_SHEET_ID is not set in tax/.env")
        return 1
    try:
        info = drive.files().get(
            fileId=sheet_id,
            fields="id,name,parents,capabilities(canEdit)").execute()
        print(f"[{OK}] can see \"{info['name']}\"")
        print(f"       can edit it: {info.get('capabilities', {}).get('canEdit')}")
        folder = (info.get("parents") or [None])[0]
    except Exception as error:
        print(f"[{BAD}] {gsheets.describe_error(error, 'your accounting sheet')}")
        print(f"\n       Share it with:  {data['client_email']}")
        return 1

    # -- 4. can it write in the folder --
    print(f"\n{BOLD}4. CAN IT CREATE THE TAX SHEET ALONGSIDE?{OFF}")
    print("-" * 70)
    if not folder:
        print(f"[{YELLOW} note {OFF}] the sheet is not in a folder - the tax "
              f"sheet will go to the robot's own Drive instead")
    else:
        try:
            meta = drive.files().get(
                fileId=folder,
                fields="id,name,capabilities(canAddChildren)").execute()
            can_add = meta.get("capabilities", {}).get("canAddChildren")
            print(f"[{OK if can_add else BAD}] folder \"{meta['name']}\" - "
                  f"{'can create files in it' if can_add else 'CANNOT create files'}")
            if not can_add:
                print(f"       Share the FOLDER with {data['client_email']} "
                      f"as Editor.")
                return 1
        except Exception as error:
            print(f"[{BAD}] {gsheets.describe_error(error, 'the folder')}")
            print(f"\n       Share the folder with: {data['client_email']}")
            return 1

    # -- 5. can it read cell notes --
    print(f"\n{BOLD}5. CAN IT READ THE NOTES IN YOUR TABS?{OFF}")
    print("-" * 70)
    try:
        sheets = gsheets.service("sheets", "v4")
        result = sheets.spreadsheets().get(
            spreadsheetId=sheet_id, includeGridData=False,
            fields="sheets(properties(title))").execute()
        titles = [s["properties"]["title"] for s in result.get("sheets", [])]
        print(f"[{OK}] Sheets API works - {len(titles)} tabs")
        print(f"       {', '.join(titles[:8])}{' ...' if len(titles) > 8 else ''}")
    except Exception as error:
        print(f"[{BAD}] {gsheets.describe_error(error, 'the Sheets API')}")
        return 1

    print()
    print("=" * 70)
    print(f"{GREEN}{BOLD}Google setup is working.{OFF}")
    print("Nothing has been written to your sheet - this only reads.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
