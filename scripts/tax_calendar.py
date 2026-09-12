"""
tax_calendar.py - what you owe, what has gone out, and what to file.

    python scripts/tax_calendar.py                      # show everything
    python scripts/tax_calendar.py --paid Q2 --amount 861.59
    python scripts/tax_calendar.py --paid Q2 --amount 861.59 --on 2026-06-14

WHY --paid EXISTS
    This tool can only see your Wise accounts. Pay the IRS by card, through
    EFTPS, or from anywhere else, and nothing will show up here. So a
    missing payment means NOT SEEN, never NOT PAID - and you can tell it
    what it could not see.
"""

import argparse
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from taxlib import config, db, filings, tax  # noqa: E402

BOLD, GREEN, YELLOW, RED, CYAN, OFF = (
    "\033[1m", "\033[32m", "\033[33m", "\033[31m", "\033[36m", "\033[0m")


def main():
    parser = argparse.ArgumentParser(description="Estimated tax and filings.")
    parser.add_argument("--year", type=int,
                        default=config.SETTINGS["tax_year"])
    parser.add_argument("--paid", help="mark a quarter paid, e.g. Q2")
    parser.add_argument("--amount", type=float)
    parser.add_argument("--on", help="the date it was paid, YYYY-MM-DD")
    parser.add_argument("--forms", action="store_true",
                        help="show the forms list only")
    args = parser.parse_args()

    connection = db.init_db()
    today = dt.date.today()

    if args.paid:
        quarter = int(str(args.paid).upper().lstrip("Q"))
        if not args.amount:
            print(f"{RED}--amount is required with --paid.{OFF}")
            return 1
        when = args.on or today.isoformat()
        db.record_tax_payment(
            connection, tax_year=args.year, quarter=quarter, paid_on=when,
            amount=args.amount, currency="USD", amount_usd=args.amount,
            detected="manual",
            note="recorded by you - this tool could not see it")
        connection.commit()
        print(f"{GREEN}Recorded ${args.amount:,.2f} against Q{quarter} "
              f"{args.year}, paid {when}.{OFF}")
        return 0

    result = tax.from_database(connection, args.year)
    per_quarter = round((result.get("total") or 0.0) / 4, 2)

    paid = {}
    for row in db.tax_payments_for(connection, args.year):
        paid.setdefault(row["quarter"], []).append(row)

    if not args.forms:
        print(f"{BOLD}Estimated tax - {args.year}{OFF}")
        print("=" * 74)
        print(f"   Total estimate ${result.get('total') or 0:,.2f}, so "
              f"${per_quarter:,.2f} a quarter.\n")
        print(f"   {'':<3} {'period':<11} {'due':<12} {'you owe':>10} "
              f"{'status'}")
        unseen = []
        for quarter in filings.quarters(args.year, today):
            number = quarter["quarter"]
            seen = paid.get(number, [])
            if seen:
                status = (f"{GREEN}paid {seen[0]['paid_on']} "
                          f"(${seen[0]['amount_usd'] or seen[0]['amount']:,.2f})"
                          f"{OFF}")
            elif quarter["overdue"]:
                status = f"{RED}NOT SEEN - was due {quarter['due']}{OFF}"
                unseen.append(quarter)
            elif quarter["days_away"] <= 30:
                status = f"{YELLOW}due in {quarter['days_away']} days{OFF}"
            else:
                status = f"due in {quarter['days_away']} days"
            print(f"   Q{number}  {quarter['period']:<11} "
                  f"{str(quarter['due']):<12} ${per_quarter:>9,.2f} {status}")

        if unseen:
            print(f"\n   {YELLOW}\"NOT SEEN\" IS NOT \"UNPAID\".{OFF} This "
                  f"checks your personal Wise account only.")
            print(f"   Paid by card, through EFTPS, or from another "
                  f"account? Tell it so:")
            print(f"   {CYAN}python scripts/tax_calendar.py --paid "
                  f"Q{unseen[0]['quarter']} --amount {per_quarter:,.2f}{OFF}")
            print(f"\n   If they genuinely were not paid: the safe harbour "
                  f"rule means paying 100%")
            print(f"   of LAST year's total tax protects you from "
                  f"underpayment penalties.")

    deadline = filings.filing_deadline(args.year)
    print(f"\n{BOLD}Forms to file for {args.year}{OFF}")
    print("=" * 74)
    print(f"   The return is due {GREEN}{deadline['abroad']:%d %B %Y}{OFF}, "
          f"not {deadline['normal']:%d %B %Y} -")
    print(f"   living abroad gives an automatic two-month extension, with "
          f"nothing to request.")
    print(f"   {YELLOW}It extends the FILING, not the PAYING.{OFF} Interest "
          f"runs from "
          f"{deadline['interest_from']:%d %B %Y}.\n")
    for form in filings.FORMS:
        print(f"   {BOLD}{form['form']}{OFF} - {form['what']}")
        print(f"      due {form['due']}   |   {form['who']}")
        print(f"      {CYAN}{form['url']}{OFF}")
        print(f"      {form['note']}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
