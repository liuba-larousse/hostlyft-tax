"""
check_google.py - is the Google connection working?

    python scripts/check_google.py

Checks each step in order, stops at the first problem, and says what to do.
Only reads - it never writes to your sheet.
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
    print("Hostlyft Tax Tracker - Google check")
    print("=" * 70)

    # -- 1. the OAuth client file --
    print(f"\n{BOLD}1. THE APP REGISTRATION{OFF}")
    print("-" * 70)
    try:
        gsheets.read_client_file()
    except gsheets.GoogleError as error:
        print(f"[{BAD}] {error}")
        return 1
    print(f"[{OK}] Desktop OAuth client found at {gsheets.client_path()}")

    # -- 2. signed in? --
    print(f"\n{BOLD}2. ARE YOU SIGNED IN?{OFF}")
    print("-" * 70)
    try:
        creds = gsheets.credentials()
    except gsheets.GoogleError as error:
        print(f"[{BAD}] {error}")
        return 1
    print(f"[{OK}] signed in, token saved at {gsheets.token_path()}")
    print(f"       scopes: {', '.join(s.rsplit('/', 1)[-1] for s in creds.scopes or [])}")
    print(f"       (spreadsheets only - not Drive, not documents)")

    import subprocess
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", str(gsheets.token_path())],
        cwd=config.ROOT, capture_output=True).returncode == 0
    print(f"[{OK if ignored else BAD}] git "
          f"{'refuses to upload the token' if ignored else 'WOULD UPLOAD IT - stop'}")

    # -- 3. THE TWO SHEETS, SIDE BY SIDE --
    #
    # Both are shown together, every time, because the one failure this has
    # actually produced was looking in the wrong one. On 2026-09-12 a review
    # opened the accounting sheet hunting for the generated tabs, found her
    # original 16, and reported Stage 11 as never done. It had been done -
    # in the other sheet. Showing one sheet alone is what made that possible.
    print(f"\n{BOLD}3. THE TWO SHEETS - WHICH IS WHICH{OFF}")
    print("-" * 70)
    sheets = gsheets.service()

    def describe(label, sheet_id, rule, key):
        if not sheet_id:
            print(f"[{BAD}] {label}: {key} is not set in tax/.env")
            return None, []
        try:
            info = sheets.spreadsheets().get(
                spreadsheetId=sheet_id,
                fields="properties(title),sheets(properties(title))").execute()
        except Exception as error:
            print(f"[{BAD}] {label}: "
                  f"{gsheets.describe_error(error, label)}")
            return None, []
        titles = [x["properties"]["title"] for x in info.get("sheets", [])]
        print(f"[{OK}] {label}  \"{info['properties']['title']}\"")
        print(f"       {key}")
        print(f"       {rule}")
        print(f"       {len(titles)} tabs: {', '.join(titles[:6])}"
              f"{' ...' if len(titles) > 6 else ''}")
        return info, titles

    info, titles = describe(
        "ACCOUNTING", gsheets.accounting_sheet_id(),
        f"{YELLOW}READ ONLY - hers. Generated tabs are NOT here and never "
        f"will be.{OFF}", "GOOGLE_SHEET_ID")
    if info is None:
        return 1
    sheet_id = gsheets.accounting_sheet_id()

    print()
    tax_info, tax_titles = describe(
        "TAX", gsheets.tax_sheet_id(),
        f"WRITTEN TO - generated, rewritten every run. Look for Summary, "
        f"Income, Expenses,\n       Distributions, Reconciliation HERE.",
        "GOOGLE_TAX_SHEET_ID")
    if tax_info is None:
        print(f"       {YELLOW}Not built yet - run "
              f"scripts/build_tax_sheet.py{OFF}")

    # The guard that makes a wrong write impossible, exercised for real.
    try:
        gsheets.assert_writable(gsheets.accounting_sheet_id(),
                                what="a write to the accounting sheet")
        print(f"\n[{BAD}] THE GUARD IS NOT WORKING - a write to her "
              f"accounting sheet was allowed")
        return 1
    except gsheets.WroteToTheWrongSheet:
        print(f"\n[{OK}] the guard refuses any write aimed at her "
              f"accounting sheet")

    # -- 4. can it read cell notes --
    print(f"\n{BOLD}4. CAN IT READ THE NOTES IN YOUR TABS?{OFF}")
    print("-" * 70)
    target = next((t for t in titles if t.lower().startswith("jul")), titles[0])
    try:
        data = sheets.spreadsheets().get(
            spreadsheetId=sheet_id, ranges=[target], includeGridData=True,
            fields="sheets(data(rowData(values(note))))").execute()
    except Exception as error:
        print(f"[{BAD}] {gsheets.describe_error(error, 'cell notes')}")
        return 1

    notes = 0
    for sheet in data.get("sheets", []):
        for block in sheet.get("data", []):
            for row in block.get("rowData", []):
                for cell in row.get("values", []):
                    if cell.get("note"):
                        notes += 1
    print(f"[{OK}] read the \"{target}\" tab - {notes} cell notes found")
    if notes == 0:
        print(f"       (none on that tab; they may be on another)")

    print()
    print("=" * 70)
    print(f"{GREEN}{BOLD}Google is connected.{OFF}")
    print("Nothing was written - this only reads.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
