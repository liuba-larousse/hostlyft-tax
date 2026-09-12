"""
meals.py - record why a meal was business, and who was at it.

    python scripts/meals.py                       # what still needs a reason
    python scripts/meals.py --id 527 \\
        --purpose "Quarterly planning with Ayoka" \\
        --with "Yetunde Olaniyan"
    python scripts/meals.py --id 527 --personal   # not business after all
    python scripts/meals.py --all                 # including ones already done

WHY THIS EXISTS
    A card row says "restaurant". It cannot say who was there or why, and
    the IRS asks for both. Nothing in Stripe, Wise or a bank export can
    supply it - only you can.

    This is the weakest part of a meal deduction, and it is weak in a
    particular way: the AMOUNT is never in doubt, because the bank recorded
    it. What is missing is the reason. An examiner does not have to prove
    the meal was personal; you have to show it was business.

    A confirmed meal with no purpose recorded is still deducted here - you
    said it was business and that is your call to make. But it is listed as
    undocumented every time this runs, because that is the honest state.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from taxlib import config, db  # noqa: E402

BOLD, GREEN, YELLOW, RED, CYAN, OFF = (
    "\033[1m", "\033[32m", "\033[33m", "\033[31m", "\033[36m", "\033[0m")


def main():
    parser = argparse.ArgumentParser(description="Document business meals.")
    parser.add_argument("--year", type=int,
                        default=config.SETTINGS["tax_year"])
    parser.add_argument("--id", type=int, help="the expense row to document")
    parser.add_argument("--purpose", help="why this was a business meal")
    parser.add_argument("--with", dest="attendees",
                        help="who was present, besides you")
    parser.add_argument("--personal", action="store_true",
                        help="not business after all - drop it")
    parser.add_argument("--all", action="store_true",
                        help="list documented meals too")
    args = parser.parse_args()

    connection = db.init_db()

    if args.id and args.personal:
        connection.execute(
            "UPDATE expenses SET excluded = 1, needs_review = 0, "
            "exclusion_reason = 'personal meal, not deductible - your "
            "decision', updated_at = ? WHERE id = ?", (db._now(), args.id))
        connection.commit()
        print(f"{GREEN}Row {args.id} dropped as personal.{OFF} It stays "
              f"visible with the reason recorded.")
        return

    if args.id:
        if not args.purpose:
            print(f"{RED}--purpose is required.{OFF} The business reason is "
                  f"the whole point - without it there is nothing to record.")
            return
        if not args.attendees:
            print(f"{YELLOW}No --with given.{OFF} Recording a meal on your "
                  f"own. That is allowed while travelling for business, but "
                  f"a meal alone near home is a personal living expense.")
        connection.execute(
            "UPDATE expenses SET business_purpose = ?, attendees = ?, "
            "needs_review = 0, updated_at = ? WHERE id = ?",
            (args.purpose, args.attendees or "(on your own)", db._now(),
             args.id))
        connection.commit()
        print(f"{GREEN}Recorded against row {args.id}.{OFF}")
        return

    # ---- the listing --------------------------------------------------
    rows = connection.execute(
        "SELECT id, date, vendor, amount, currency, amount_usd, "
        "business_purpose, attendees FROM expenses "
        "WHERE category = 'meals' AND excluded = 0 AND tax_year = ? "
        "ORDER BY date", (args.year,)).fetchall()

    documented = [r for r in rows if r["business_purpose"]]
    missing = [r for r in rows if not r["business_purpose"]]

    print(f"{BOLD}Business meals - {args.year}{OFF}")
    print("=" * 74)

    gross = sum(r["amount_usd"] or 0 for r in rows)
    share = config.deductible_share("meals")
    print(f"{len(rows)} meals, ${gross:,.2f} spent, "
          f"${gross * share:,.2f} deductible at {share:.0%}.\n")

    if missing:
        print(f"{YELLOW}{BOLD}NO BUSINESS REASON RECORDED "
              f"({len(missing)} of {len(rows)}){OFF}")
        print("-" * 74)
        for row in missing:
            print(f"   id={row['id']:<5d} {row['date']}  "
                  f"${row['amount_usd'] or 0:>8,.2f}  "
                  f"{(row['vendor'] or '')[:28]}")
        undocumented = sum(r["amount_usd"] or 0 for r in missing)
        print(f"\n   ${undocumented * share:,.2f} of deduction rests on "
              f"meals with no recorded reason.")
        print(f"   That is about ${undocumented * share * 0.1413:,.2f} of "
              f"tax - small money, but it is the")
        print(f"   part that fails if anyone asks, because the reason is "
              f"what the IRS wants\n   and the bank never recorded it.\n")
        print(f"   {CYAN}python scripts/meals.py --id {missing[0]['id']} "
              f"--purpose \"...\" --with \"...\"{OFF}")
        print(f"   {CYAN}python scripts/meals.py --id {missing[0]['id']} "
              f"--personal{OFF}   (if it was not business)")

    if documented and (args.all or not missing):
        print(f"\n{GREEN}{BOLD}DOCUMENTED ({len(documented)}){OFF}")
        print("-" * 74)
        for row in documented:
            print(f"   id={row['id']:<5d} {row['date']}  "
                  f"${row['amount_usd'] or 0:>8,.2f}  "
                  f"{(row['vendor'] or '')[:22]}")
            print(f"         {row['business_purpose']}")
            print(f"         with: {row['attendees']}")

    if not missing:
        print(f"\n{GREEN}Every meal has a business reason recorded.{OFF}")


if __name__ == "__main__":
    main()
