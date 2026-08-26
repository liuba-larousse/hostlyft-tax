"""
verify_receipts.py - only count invoices whose money can be traced.

    python scripts/verify_receipts.py --dry-run
    python scripts/verify_receipts.py

An invoice marked "paid" is a status somebody set, not evidence money
arrived. On a cash basis the money is the test. Run this after every import.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from taxlib import config, db, receipts   # noqa: E402

BOLD, GREEN, YELLOW, RED, OFF = (
    "\033[1m", "\033[32m", "\033[33m", "\033[31m", "\033[0m")


def main():
    parser = argparse.ArgumentParser(description="Trace invoices to receipts.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--year", type=int, default=config.SETTINGS["tax_year"])
    args = parser.parse_args()

    print()
    print("Hostlyft Tax Tracker - tracing invoices to money")
    print("=" * 74)

    connection = db.init_db()
    result = receipts.reconcile(connection, args.year, dry_run=args.dry_run)

    print(f"\n{BOLD}PAID THROUGH A PROCESSOR{OFF}  — arrives batched, "
          f"payout already excluded")
    print("-" * 74)
    print(f"   {len(result['verified'])} invoices  "
          f"${sum(r['amount_usd'] or 0 for r in result['verified']):,.2f}")

    print(f"\n{BOLD}MATCHED TO A BANK CREDIT{OFF}")
    print("-" * 74)
    for invoice, credits, difference in result["matched"]:
        note = f"  (bank took {difference:,.2f})" if difference else ""
        parts = " + ".join(f"{c['amount']:,.2f} on {c['date']}"
                           for c in credits)
        split = "  [split payment]" if len(credits) > 1 else ""
        print(f"   {invoice['date']}  {invoice['amount']:>9,.2f} "
              f"{invoice['currency']}  <-  {parts}{note}{split}")
    if not result["matched"]:
        print("   none")

    if result.get("other_year"):
        print(f"\n{BOLD}PAID IN A DIFFERENT YEAR — not {args.year} income{OFF}")
        print("-" * 74)
        for invoice, credit in result["other_year"]:
            print(f"   {invoice['date']}  {invoice['amount']:>9,.2f} "
                  f"{invoice['currency']}  marked paid — but the money "
                  f"arrived {credit['date']}")
        print()
        print("   On a cash basis these belong to the year the money "
              "arrived, not the")
        print("   year the invoice was marked paid.")

    print(f"\n{RED}{BOLD}NOT COUNTED — no money found{OFF}")
    print("-" * 74)
    for invoice in result["unverified"]:
        print(f"   {invoice['date']}  {invoice['amount']:>9,.2f} "
              f"{invoice['currency']}  ${invoice['amount_usd'] or 0:>9,.2f}  "
              f"{str(invoice['payer'])[:20]:<22} "
              f"{(invoice['description'] or '')[:32]}")
    if result["unverified"]:
        total = sum(r["amount_usd"] or 0 for r in result["unverified"])
        print(f"\n   ${total:,.2f} of invoices marked paid cannot be traced "
              f"to money arriving.")
        print(f"   They are flagged, not counted. If the money did arrive "
              f"somewhere not")
        print(f"   being read, tell Claude and it will be added back.")
    else:
        print("   none — every invoice traces to money")

    if result["fees"]:
        print(f"\n{BOLD}WIRE FEES RECOVERED{OFF}  — deducted in transit, "
              f"now deductible")
        print("-" * 74)
        for invoice, difference in result["fees"]:
            print(f"   {difference:>8,.2f} {invoice['currency']}  on "
                  f"{(invoice['description'] or '')[:44]}")

    figures = db.totals(connection, args.year)
    print()
    print("=" * 74)
    if args.dry_run:
        print(f"{BOLD}DRY RUN - nothing was written.{OFF}")
    else:
        print(f"{GREEN}{BOLD}Done.{OFF}")
        print(f"   income      ${figures['income_usd']:>12,.2f}")
        print(f"   expenses    ${figures['expenses_usd']:>12,.2f}")
        print(f"   net profit  ${figures['net_profit_usd']:>12,.2f}")
    connection.close()
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
