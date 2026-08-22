"""
pull_stripe.py - import your Stripe income and fees into the database.

    cd ~/Documents/hostlyft-tax
    source .venv/bin/activate
    python scripts/pull_stripe.py --dry-run     # look, change nothing
    python scripts/pull_stripe.py               # actually import

Safe to run as often as you like. Every row is matched on its Stripe ID, so
re-running updates what's there instead of adding it again. Your totals will
not move.

    --dry-run    show exactly what would happen, write nothing
    --year 2026  which tax year (default: from taxlib/config.py)
    --all        every year Stripe has, ignoring --year
"""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from taxlib import config, db, stripe_import   # noqa: E402

BOLD, GREEN, YELLOW, OFF = "\033[1m", "\033[32m", "\033[33m", "\033[0m"


def money(amount, currency):
    return f"{amount:>10,.2f} {currency}"


def totals_by_currency(rows):
    """Add rows up per currency, since they can't be added across currencies."""
    result = {}
    for row in rows:
        result[row["currency"]] = result.get(row["currency"], 0) + row["amount"]
    return result


def show(records, tax_year):
    """Print what was found, in plain English."""
    income = records["income"]
    expenses = records["expenses"]

    print()
    print(f"{BOLD}INCOME - paid invoices, at gross{OFF}")
    print("-" * 70)
    if not income:
        print("  nothing found in this period")
    for row in sorted(income, key=lambda r: r["date"]):
        flag = "  <- REVIEW" if row.get("needs_review") else ""
        print(f"  {row['date']}  {money(row['amount'], row['currency'])}"
              f"  {(row['description'] or '')[:34]}{flag}")

    print()
    print(f"{BOLD}EXPENSES - Stripe's fees, all three kinds{OFF}")
    print("-" * 70)
    if not expenses:
        print("  nothing found in this period")
    for row in sorted(expenses, key=lambda r: r["date"]):
        print(f"  {row['date']}  {money(row['amount'], row['currency'])}"
              f"  {(row['description'] or '')[:44]}")

    print()
    print(f"{BOLD}TOTALS, per currency{OFF}")
    print("-" * 70)
    income_totals = totals_by_currency(income)
    expense_totals = totals_by_currency(expenses)
    for currency in sorted(set(income_totals) | set(expense_totals)):
        got = income_totals.get(currency, 0)
        paid = expense_totals.get(currency, 0)
        print(f"  {currency}   income {got:>12,.2f}   fees {paid:>10,.2f}"
              f"   net {got - paid:>12,.2f}")
    if len(set(income_totals) | set(expense_totals)) > 1:
        print()
        print("  Different currencies cannot be added together. Stage 5")
        print("  converts them all to US dollars using the rate on the day.")

    print()
    print(f"{BOLD}PAYOUTS - money Stripe sent to your bank{OFF}")
    print("-" * 70)
    print("  These are NOT income. They are the reference list Stage 6 uses")
    print("  to recognise the same money arriving in Wise and refuse to")
    print("  count it twice.")
    print()
    for row in sorted(records["payouts"], key=lambda r: r["arrival_date"]):
        print(f"  arrives {row['arrival_date']}  "
              f"{money(row['amount'], row['currency'])}  ({row['status']})")

    if records["outstanding"]:
        print()
        print(f"{BOLD}NOT income - invoices sent but not paid yet{OFF}")
        print("-" * 70)
        print("  Money owed to you is not income until it arrives.")
        print()
        for row in sorted(records["outstanding"], key=lambda r: -r["amount"]):
            print(f"  {money(row['amount'], row['currency'])}  "
                  f"{row['status']:<6} invoice {row['number'] or row['id']}")

    review = [r for r in income + expenses if r.get("needs_review")]
    if review:
        print()
        print(f"{YELLOW}{BOLD}NEEDS YOUR EYES{OFF}")
        print("-" * 70)
        for row in review:
            print(f"  {row['date']}  {money(row['amount'], row['currency'])}")
            print(f"      {row['review_note']}")

    for note in records["notes"]:
        print()
        print(f"{YELLOW}  NOTE: {note}{OFF}")


def write(records):
    """Put the rows in the database. Re-running updates, never duplicates."""
    connection = db.init_db()

    for row in records["income"]:
        db.upsert_income(connection, **row)
    for row in records["expenses"]:
        db.upsert_expense(connection, **row)
    for row in records["payouts"]:
        db.upsert_payout(connection, **row)

    connection.commit()
    return connection


def main():
    parser = argparse.ArgumentParser(
        description="Import Stripe income and fees into the tax database.")
    parser.add_argument("--dry-run", action="store_true",
                        help="show what would happen, write nothing")
    parser.add_argument("--year", type=int,
                        default=config.SETTINGS["tax_year"],
                        help="tax year to import (default: %(default)s)")
    parser.add_argument("--all", action="store_true",
                        help="every year Stripe has, ignoring --year")
    args = parser.parse_args()

    print()
    print("Hostlyft Tax Tracker - Stripe import")
    print("=" * 70)

    try:
        import stripe
        stripe.api_key = config.get_secret("STRIPE_SECRET_KEY", required=True)
    except config.MissingSecret as error:
        print()
        print(error)
        return 1

    if args.all:
        since = until = None
        since_timestamp = None
        print("Period: everything Stripe has")
    else:
        since = f"{args.year}-01-01"
        until = f"{args.year}-12-31"
        since_timestamp = int(datetime(args.year, 1, 1,
                                       tzinfo=timezone.utc).timestamp())
        print(f"Period: {since} to {until}")

    print("Reading from Stripe (read-only - nothing is changed or moved) ...")
    try:
        invoices, charges, ledger, payouts = stripe_import.fetch_everything(
            stripe, created_since=since_timestamp)
    except Exception as error:
        print()
        print(f"  Stripe refused the request: {str(error).splitlines()[0][:200]}")
        print("  Check the key with:  python scripts/check_secrets.py --connect")
        return 1

    print(f"  {len(invoices)} invoices, {len(charges)} payments, "
          f"{len(ledger)} ledger entries, {len(payouts)} payouts")

    records = stripe_import.build_records(
        invoices, charges, ledger, payouts, since=since, until=until)

    show(records, args.year)

    print()
    print("=" * 70)
    if args.dry_run:
        print(f"{BOLD}DRY RUN - nothing was written.{OFF}")
        print("Run it without --dry-run to import for real.")
        return 0

    connection = write(records)
    figures = db.totals(connection, args.year)

    print(f"{GREEN}{BOLD}Imported.{OFF}")
    print(f"  {len(records['income'])} income entries, "
          f"{len(records['expenses'])} expenses, "
          f"{len(records['payouts'])} payouts recorded")
    print()
    print(f"  In the database for {args.year}, converted to USD so far:")
    print(f"    income      ${figures['income_usd']:>12,.2f}")
    print(f"    expenses    ${figures['expenses_usd']:>12,.2f}")
    print(f"    net profit  ${figures['net_profit_usd']:>12,.2f}")

    if figures["unconverted_income_count"] or figures["unconverted_expense_count"]:
        total_unconverted = (figures["unconverted_income_count"]
                             + figures["unconverted_expense_count"])
        print()
        print(f"  {YELLOW}{total_unconverted} entries are not in US dollars yet,"
              f" so they count as $0 above.{OFF}")
        print(f"  {YELLOW}Those totals are incomplete until Stage 5 converts"
              f" them.{OFF}")

    connection.close()
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
