"""
review.py - confirm or drop the things the importer would not decide alone.

    python scripts/review.py                     # everything waiting
    python scripts/review.py --category meals    # just one category
    python scripts/review.py --keep 41 42 43     # these are business - keep
    python scripts/review.py --drop 44 45        # these are personal - drop
    python scripts/review.py --drop-vendor "Le Pacha Kebab"

NOTHING IS DELETED. Dropping a row marks it excluded: it stays visible, with
the reason, and stops reducing your profit. That way a decision is a record
rather than a disappearance.

WHY THIS EXISTS
    A card row says "restaurant" or "Uber". It cannot say who was there,
    why, or whether the trip was business. The bank does not know, and
    neither does this program - so it asks rather than guessing. A wrong
    deduction is worse than a missed one, because it is invisible.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from taxlib import config, db   # noqa: E402

BOLD, GREEN, YELLOW, RED, CYAN, OFF = (
    "\033[1m", "\033[32m", "\033[33m", "\033[31m", "\033[36m", "\033[0m")


def main():
    parser = argparse.ArgumentParser(
        description="Confirm or drop flagged expenses.")
    parser.add_argument("--year", type=int,
                        default=config.SETTINGS["tax_year"])
    parser.add_argument("--category")
    parser.add_argument("--keep", nargs="*", type=int, default=[])
    parser.add_argument("--drop", nargs="*", type=int, default=[])
    parser.add_argument("--drop-vendor")
    parser.add_argument("--reason", default="personal, not a business cost")
    args = parser.parse_args()

    connection = db.init_db()
    changed = 0

    for row_id in args.keep:
        connection.execute(
            "UPDATE expenses SET needs_review = 0, "
            "review_note = 'confirmed business by you', "
            "updated_at = ? WHERE id = ?", (db._now(), row_id))
        changed += 1

    for row_id in args.drop:
        connection.execute(
            "UPDATE expenses SET excluded = 1, needs_review = 0, "
            "exclusion_reason = ?, updated_at = ? WHERE id = ?",
            (args.reason, db._now(), row_id))
        changed += 1

    if args.drop_vendor:
        cursor = connection.execute(
            "UPDATE expenses SET excluded = 1, needs_review = 0, "
            "exclusion_reason = ?, updated_at = ? "
            "WHERE vendor = ? COLLATE NOCASE AND excluded = 0 "
            "AND tax_year = ?",
            (args.reason, db._now(), args.drop_vendor, args.year))
        changed += cursor.rowcount

    if changed:
        connection.commit()
        print(f"\n{GREEN}{changed} row(s) updated.{OFF}")

    # ------------------------------------------------------ what is left
    where = "WHERE needs_review = 1 AND excluded = 0 AND tax_year = ?"
    params = [args.year]
    if args.category:
        where += " AND category = ?"
        params.append(args.category)

    rows = connection.execute(
        f"SELECT id, date, vendor, category, amount, currency, amount_usd, "
        f"       description, review_note FROM expenses {where} "
        f"ORDER BY category, date", params).fetchall()

    if not rows:
        print(f"\n{GREEN}Nothing waiting for review.{OFF}\n")
        connection.close()
        return 0

    print(f"\n{BOLD}WAITING FOR YOUR DECISION - {args.year}{OFF}")
    print("=" * 78)

    current, subtotal = None, 0.0
    for row in rows:
        if row["category"] != current:
            if current:
                print(f"      {'':>36}{subtotal:>10,.2f}  subtotal")
            current, subtotal = row["category"], 0.0
            share = config.deductible_share(current)
            extra = f"   ({share:.0%} deductible)" if share < 1 else ""
            print(f"\n{BOLD}{current.upper()}{extra}{OFF}")
            print("-" * 78)
        subtotal += row["amount_usd"] or 0
        print(f"  {row['id']:>4}  {row['date']}  "
              f"{(row['vendor'] or '')[:30]:<30}"
              f"{row['amount_usd'] or 0:>10,.2f}")
    print(f"      {'':>36}{subtotal:>10,.2f}  subtotal")

    total = sum(r["amount_usd"] or 0 for r in rows)
    print()
    print("=" * 78)
    print(f"{BOLD}{len(rows)} rows, ${total:,.2f} gross{OFF}")
    print()
    print(f"{CYAN}  These are being deducted RIGHT NOW. Anything personal in")
    print(f"  the list is lowering your tax bill on a claim that would not")
    print(f"  survive being asked about.{OFF}")
    print()
    print("  Keep them:   python scripts/review.py --keep 41 42 43")
    print("  Drop them:   python scripts/review.py --drop 44 45")
    print('  Drop a whole vendor: '
          'python scripts/review.py --drop-vendor "Le Pacha Kebab"')
    print()

    connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
