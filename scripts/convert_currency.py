"""
convert_currency.py - put a US dollar figure on every foreign entry.

    cd ~/Documents/hostlyft-tax
    source .venv/bin/activate
    python scripts/convert_currency.py --dry-run   # show, change nothing
    python scripts/convert_currency.py             # convert for real

The original amount and currency are never changed. The dollar figure is
stored NEXT to them, together with the rate used and the date that rate came
from, so the working can always be checked.

Safe to run repeatedly - anything already converted is skipped, and saved
rates mean the same answer every time.

    --dry-run     show what would happen, write nothing
    --year 2026   which tax year (default: from taxlib/config.py)
    --rates       just list the rates already saved
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from taxlib import config, db, fx   # noqa: E402

BOLD, GREEN, YELLOW, RED, OFF = (
    "\033[1m", "\033[32m", "\033[33m", "\033[31m", "\033[0m")


def show_saved_rates(connection):
    rows = connection.execute(
        "SELECT * FROM fx_rates ORDER BY requested_date, base_currency"
    ).fetchall()
    print()
    print(f"{BOLD}RATES ALREADY SAVED{OFF}")
    print("-" * 70)
    if not rows:
        print("  none yet")
        return
    print("  transaction  rate from    pair       rate")
    for row in rows:
        note = ""
        if row["rate_date"] != row["requested_date"]:
            note = "  <- weekend or holiday, walked back"
        print(f"  {row['requested_date']}   {row['rate_date']}   "
              f"{row['base_currency']}->{row['quote_currency']}   "
              f"{row['rate']:<10}{note}")


def main():
    parser = argparse.ArgumentParser(
        description="Convert foreign amounts in the database into US dollars.")
    parser.add_argument("--dry-run", action="store_true",
                        help="show what would happen, write nothing")
    parser.add_argument("--year", type=int,
                        default=config.SETTINGS["tax_year"],
                        help="tax year to convert (default: %(default)s)")
    parser.add_argument("--rates", action="store_true",
                        help="just list the rates already saved")
    args = parser.parse_args()

    print()
    print("Hostlyft Tax Tracker - currency conversion")
    print("=" * 70)
    print("Rates: European Central Bank, via api.frankfurter.dev (free, no key)")

    connection = db.init_db()

    if args.rates:
        show_saved_rates(connection)
        connection.close()
        print()
        return 0

    pending = (fx.rows_needing_conversion(connection, "income", args.year)
               + fx.rows_needing_conversion(connection, "expenses", args.year))

    if not pending:
        print()
        print(f"{GREEN}Everything already has a US dollar figure.{OFF}")
        figures = db.totals(connection, args.year)
        print(f"  income      ${figures['income_usd']:>12,.2f}")
        print(f"  expenses    ${figures['expenses_usd']:>12,.2f}")
        print(f"  net profit  ${figures['net_profit_usd']:>12,.2f}")
        connection.close()
        print()
        return 0

    print(f"{len(pending)} entries need converting for {args.year}.")

    result = fx.convert_pending(connection, tax_year=args.year,
                                dry_run=args.dry_run)

    if result["converted"]:
        print()
        print(f"{BOLD}CONVERTED{OFF}")
        print("-" * 70)
        print("  date        amount        ->  US dollars   rate     rate from")
        for row in result["converted"]:
            note = ""
            if row["days_back"] > 0:
                note = f"  <- {row['days_back']}d earlier (weekend/holiday)"
            print(f"  {row['date']}  {row['amount']:>9,.2f} {row['currency']}"
                  f"  ->  ${row['amount_usd']:>10,.2f}"
                  f"   {row['rate']:<8} {row['rate_date']}{note}")

    if result["warnings"]:
        print()
        print(f"{YELLOW}{BOLD}WORTH CHECKING{OFF}")
        print("-" * 70)
        for row in result["warnings"]:
            print(f"  {row['date']} {row['currency']}: {row['note']}")

    if result["failed"]:
        print()
        print(f"{RED}{BOLD}COULD NOT CONVERT - nothing was guessed{OFF}")
        print("-" * 70)
        for row in result["failed"]:
            print(f"  {row['date']}  {row['amount']:,.2f} {row['currency']}"
                  f"  ({row['description'] or 'no description'})")
            for line in row["reason"].splitlines():
                print(f"      {line}")

    print()
    print("=" * 70)
    if args.dry_run:
        print(f"{BOLD}DRY RUN - nothing was written.{OFF}")
        print("Run it without --dry-run to convert for real.")
        connection.close()
        print()
        return 0

    figures = db.totals(connection, args.year)
    print(f"{GREEN}{BOLD}Converted {len(result['converted'])} entries.{OFF}")
    print()
    print(f"  Totals for {args.year}, all in US dollars:")
    print(f"    income      ${figures['income_usd']:>12,.2f}")
    print(f"    expenses    ${figures['expenses_usd']:>12,.2f}")
    print(f"    {'-' * 26}")
    print(f"    net profit  ${figures['net_profit_usd']:>12,.2f}"
          f"   <- what tax is worked out from")

    still_pending = (figures["unconverted_income_count"]
                     + figures["unconverted_expense_count"])
    if still_pending:
        print()
        print(f"  {RED}{still_pending} entries still have no dollar figure and"
              f" count as $0 above.{OFF}")
        print(f"  {RED}Those totals are incomplete. See the failures"
              f" listed.{OFF}")
        connection.close()
        print()
        return 1

    connection.close()
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
