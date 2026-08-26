"""
build_tax_sheet.py - create or refresh the tax spreadsheet.

    python scripts/build_tax_sheet.py --dry-run   # show, write nothing
    python scripts/build_tax_sheet.py             # build it

This writes to a SEPARATE sheet, created the first time and updated
thereafter. Your accounting sheet is never touched.

    --dry-run   print what each tab would contain
    --year      which tax year (default: from taxlib/config.py)
    --force     write even if a tab contains formulas (it refuses otherwise)
"""

import argparse
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from taxlib import config, db, gsheets, tax_sheet   # noqa: E402

BOLD, GREEN, YELLOW, RED, OFF = (
    "\033[1m", "\033[32m", "\033[33m", "\033[31m", "\033[0m")


def main():
    parser = argparse.ArgumentParser(description="Build the tax sheet.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--year", type=int, default=config.SETTINGS["tax_year"])
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    built_on = dt.date.today().isoformat()

    print()
    print("Hostlyft Tax Tracker - tax sheet")
    print("=" * 74)
    print("A separate sheet, on a CASH RECEIVED basis.")
    print("Your accounting sheet is never written to.")

    connection = db.connect()
    tabs, data = tax_sheet.build_tabs(connection, args.year, built_on)

    print()
    print(f"{BOLD}WHAT WOULD BE WRITTEN{OFF}")
    print("-" * 74)
    for name, rows in tabs.items():
        print(f"   {name:<12} {len(rows):>4} rows")

    t = data["totals"]
    print()
    print(f"{BOLD}THE HEADLINE{OFF}")
    print("-" * 74)
    print(f"   income      ${t['income_usd']:>12,.2f}")
    print(f"   expenses    ${t['expenses_usd']:>12,.2f}")
    print(f"   net profit  ${t['net_profit_usd']:>12,.2f}")
    print(f"   in jars     ${db.total_in_jars_usd(connection):>12,.2f}"
          f"   (not deductible)")
    if t["needs_review_count"]:
        print(f"   {YELLOW}{t['needs_review_count']} entries flagged for "
              f"review — see the Review tab{OFF}")

    if args.dry_run:
        print()
        print(f"{BOLD}Summary tab preview{OFF}")
        print("-" * 74)
        for row in tabs["Summary"][:20]:
            print("   " + " | ".join(str(c) for c in row)[:88])
        print()
        print("=" * 74)
        print(f"{BOLD}DRY RUN - nothing was written.{OFF}")
        connection.close()
        return 0

    try:
        sheet_id, created = tax_sheet.find_or_create(args.year)
        if created:
            tax_sheet.remember_id(sheet_id)
        tax_sheet.write(sheet_id, tabs, force=args.force)
    except gsheets.GoogleError as error:
        print(f"\n{RED}{error}{OFF}\n")
        connection.close()
        return 1

    print()
    print("=" * 74)
    print(f"{GREEN}{BOLD}{'Created' if created else 'Updated'} the tax "
          f"sheet.{OFF}")
    print(f"   https://docs.google.com/spreadsheets/d/{sheet_id}/edit")
    if created:
        print()
        print(f"   {YELLOW}It is in the top level of My Drive. Drag it next "
              f"to your accounting{OFF}")
        print(f"   {YELLOW}sheet once — the tool only asked for Sheets "
              f"access, not Drive.{OFF}")
        print(f"   Its id is saved in tax/.env, so future runs update this "
              f"same sheet.")
    connection.close()
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
