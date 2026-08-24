"""
import_files.py - one-time imports from files in tax/imports/.

    python scripts/import_files.py --dry-run
    python scripts/import_files.py

Two sources with no live connection:

    HubSpot   invoices Jan-Jul 2026. Hostlyft left the platform after
              30 July, so this is a fixed historical record.
    Upwork    earnings exported from Upwork's reports page.

Both record income GROSS. Safe to re-run - every row carries a stable id.
"""

import argparse
import glob
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from taxlib import config, csv_import, db   # noqa: E402

BOLD, GREEN, YELLOW, OFF = "\033[1m", "\033[32m", "\033[33m", "\033[0m"


def main():
    parser = argparse.ArgumentParser(description="Import HubSpot and Upwork files.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--year", type=int, default=config.SETTINGS["tax_year"])
    args = parser.parse_args()

    print()
    print("Hostlyft Tax Tracker - file imports")
    print("=" * 74)

    connection = db.init_db()
    all_income, notes = [], []

    # ---- HubSpot ----
    hubspot_file = config.IMPORTS_DIR / "hubspot_invoices_2026.csv"
    if hubspot_file.exists():
        result = csv_import.build_hubspot_records(
            csv_import.read_hubspot(hubspot_file), year=args.year)
        all_income += result["income"]
        notes += result["notes"]
        by_currency = {}
        for row in result["income"]:
            by_currency[row["currency"]] = by_currency.get(row["currency"], 0) + row["amount"]
        print(f"\n{BOLD}HUBSPOT{OFF}  {len(result['income'])} paid invoices")
        for currency, total in sorted(by_currency.items()):
            print(f"   {currency} {total:>12,.2f}  gross")
        for row in result["outstanding"]:
            print(f"   {YELLOW}outstanding: {row['invoice']} "
                  f"{row['amount']:,.2f} {row['currency']} ({row['status']}) "
                  f"- not income{OFF}")
    else:
        print(f"\n{YELLOW}No HubSpot file at {hubspot_file}{OFF}")

    # ---- Upwork ----
    upwork_files = sorted(
        f for f in glob.glob(str(config.IMPORTS_DIR / "*.csv"))
        if "hubspot" not in Path(f).name.lower())
    if upwork_files:
        result = csv_import.build_upwork_records(
            csv_import.read_upwork(upwork_files), year=args.year)
        all_income += result["income"]
        notes += result["notes"]
        gross = sum(r["amount"] for r in result["income"])
        print(f"\n{BOLD}UPWORK{OFF}  {len(result['income'])} earnings from "
              f"{len(upwork_files)} file(s)")
        print(f"   USD {gross:>12,.2f}  gross")
        if result["unmapped"]:
            print(f"\n   {YELLOW}contracts with no client yet - counted under "
                  f"Hostlyft, flagged for review:{OFF}")
            for name, total in sorted(result["unmapped"].items(),
                                      key=lambda kv: -kv[1]):
                print(f"      ${total:>9,.2f}  {name[:60]}")
    else:
        print(f"\n{YELLOW}No Upwork files in {config.IMPORTS_DIR}{OFF}")

    for note in notes:
        print(f"\n{YELLOW}   NOTE: {note}{OFF}")

    print()
    print("=" * 74)
    if args.dry_run:
        print(f"{BOLD}DRY RUN - nothing was written.{OFF}")
        connection.close()
        return 0

    for row in all_income:
        db.upsert_income(connection, **row)
    connection.commit()

    figures = db.totals(connection, args.year)
    print(f"{GREEN}{BOLD}Imported {len(all_income)} income rows.{OFF}")
    print(f"\n   income      ${figures['income_usd']:>12,.2f}")
    print(f"   expenses    ${figures['expenses_usd']:>12,.2f}")
    print(f"   net profit  ${figures['net_profit_usd']:>12,.2f}")
    unconverted = (figures["unconverted_income_count"]
                   + figures["unconverted_expense_count"])
    if unconverted:
        print(f"\n   {YELLOW}{unconverted} entries need converting - run "
              f"scripts/convert_currency.py{OFF}")
    connection.close()
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
