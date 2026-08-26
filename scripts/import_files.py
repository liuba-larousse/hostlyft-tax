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

from taxlib import config, csv_import, db, manual_entry   # noqa: E402

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
    all_income, all_expenses, notes = [], [], []

    # ---- HubSpot ----
    hubspot_file = config.IMPORTS_DIR / "hubspot_invoices_2026.csv"
    if hubspot_file.exists():
        # the payments export carries the customer on each payment, which is
        # the only place the invoice's client can be found
        client_lookup = {}
        for candidate in sorted(glob.glob(str(config.IMPORTS_DIR / "*payment*.csv"))):
            if csv_import.is_payments_export(candidate):
                client_lookup = csv_import.client_lookup_from_payments(
                    csv_import.read_hubspot_payments(candidate))
        result = csv_import.build_hubspot_records(
            csv_import.read_hubspot(hubspot_file), year=args.year,
            clients=client_lookup)
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

    # ---- HubSpot fees and refunds ----
    payment_files = [f for f in sorted(glob.glob(str(config.IMPORTS_DIR / "*.csv")))
                     if "payment" in Path(f).name.lower()
                     and csv_import.is_payments_export(f)]
    if payment_files:
        newest = payment_files[-1]
        result = csv_import.build_hubspot_payment_records(
            csv_import.read_hubspot_payments(newest), year=args.year)
        all_expenses += result["expenses"]
        notes += result["notes"]
        print(f"\n{BOLD}HUBSPOT FEES AND REFUNDS{OFF}  ({Path(newest).name})")
        print(f"   USD {result['fees_total']:>12,.2f}  fees (deductible)")
        print(f"   USD {result['refunds_total']:>12,.2f}  refunds "
              f"(returns and allowances)")
        older = [f for f in sorted(glob.glob(str(config.IMPORTS_DIR / "*payment*.csv")))
                 if f not in payment_files]
        if older:
            print(f"   {YELLOW}{len(older)} earlier payments export(s) without "
                  f"fee columns ignored.{OFF}")

    # ---- Upwork ----
    candidates = [f for f in sorted(glob.glob(str(config.IMPORTS_DIR / "*.csv")))
                  if "hubspot" not in Path(f).name.lower()
                  and "manual" not in Path(f).name.lower()]
    reports = [f for f in candidates if csv_import.is_transaction_report(f)]
    summaries = [f for f in candidates if f not in reports]

    if reports:
        rows = []
        for path in reports:
            rows += csv_import.read_upwork_transactions(path)
        result = csv_import.build_upwork_records(rows, year=args.year)
        all_income += result["income"]
        all_expenses += result["expenses"]
        notes += result["notes"]

        gross = sum(r["amount"] for r in result["income"])
        fees = sum(r["amount"] for r in result["expenses"])
        print(f"\n{BOLD}UPWORK{OFF}  transaction report")
        print(f"   USD {gross:>12,.2f}  gross earnings")
        print(f"   USD {fees:>12,.2f}  fees and sales tax (deductible)")
        print(f"\n   by client:")
        for name, info in sorted(result["clients"].items(),
                                 key=lambda kv: -kv[1]["total"]):
            print(f"      ${info['total']:>10,.2f}  {info['business']:<9} "
                  f"{name[:44]}")
        if summaries:
            print(f"\n   {YELLOW}{len(summaries)} weekly-summary export(s) "
                  f"ignored - the transaction report covers the same period "
                  f"and also has the fees. Using both would double-count.{OFF}")
    elif summaries:
        print(f"\n{YELLOW}Only weekly-summary exports found. Those have no "
              f"fee column.{OFF}")
        print(f"{YELLOW}Export Upwork's TRANSACTION REPORT instead - it has "
              f"fees and client names.{OFF}")
    else:
        print(f"\n{YELLOW}No Upwork files in {config.IMPORTS_DIR}{OFF}")

    # ---- entered by hand ----
    manual_path = manual_entry.ensure_template()
    manual_rows = manual_entry.read(manual_path)
    if manual_rows:
        result = manual_entry.build_records(manual_rows, year=args.year)
        all_income += result["income"]
        all_expenses += result["expenses"]
        print(f"\n{BOLD}ENTERED BY HAND{OFF}  ({manual_path.name})")
        for row in result["income"] + result["expenses"]:
            print(f"   {row['date']}  {row['amount']:>9,.2f} {row['currency']}"
                  f"  {row['description'][:48]}")
        for problem in result["problems"]:
            print(f"   {YELLOW}{problem}{OFF}")
    else:
        print(f"\n{BOLD}ENTERED BY HAND{OFF}  none "
              f"({manual_path.relative_to(config.ROOT)} is empty)")

    for note in notes:
        print(f"\n{YELLOW}   NOTE: {note}{OFF}")

    print()
    print("=" * 74)
    if args.dry_run:
        print(f"{BOLD}DRY RUN - nothing was written.{OFF}")
        connection.close()
        return 0

    # File imports REPLACE what came from that source rather than merging.
    # The file is the whole truth for it, so a row dropped from a corrected
    # export must disappear here too - and an earlier import that used a
    # different id scheme must not linger as a duplicate.
    for source in ("hubspot", "upwork", "manual"):
        connection.execute("DELETE FROM income WHERE source = ?", (source,))
        connection.execute("DELETE FROM expenses WHERE source = ?", (source,))

    for row in all_income:
        db.upsert_income(connection, **row)
    for row in all_expenses:
        db.upsert_expense(connection, **row)
    connection.commit()

    figures = db.totals(connection, args.year)
    print(f"{GREEN}{BOLD}Imported {len(all_income)} income rows and "
          f"{len(all_expenses)} expense rows.{OFF}")
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
