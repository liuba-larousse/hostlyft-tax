"""
categorize.py - sort expenses into categories, and list what it could not.

    python scripts/categorize.py --dry-run    # show, change nothing
    python scripts/categorize.py              # apply

The rules live in rules.txt, in plain English. Edit that file and run this
again - no code involved.

Anything matching no rule stays "uncategorized" and is listed below. That
list is the point of this script: a wrong category is a wrong deduction,
and unlike a crash it is completely invisible.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from taxlib import categorize, config, db   # noqa: E402

BOLD, GREEN, YELLOW, OFF = "\033[1m", "\033[32m", "\033[33m", "\033[0m"


def main():
    parser = argparse.ArgumentParser(description="Categorise expenses.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--year", type=int, default=config.SETTINGS["tax_year"])
    args = parser.parse_args()

    print()
    print("Hostlyft Tax Tracker - expense categories")
    print("=" * 72)
    rules = categorize.load_rules()
    print(f"Rules: {config.RULES_PATH.name}  "
          f"({len(rules)} categories, "
          f"{sum(len(w) for _, w in rules)} matching words)")

    connection = db.init_db()
    result = categorize.recategorize(connection, tax_year=args.year,
                                     dry_run=args.dry_run, rules=rules)

    if result["categorized"]:
        print()
        print(f"{BOLD}CATEGORISED{OFF}")
        print("-" * 72)
        for row in sorted(result["categorized"],
                          key=lambda r: -(r["amount_usd"] or 0)):
            print(f"   ${row['amount_usd'] or 0:>9,.2f}  "
                  f"{str(row['vendor'])[:26]:<26} -> {row['category']:<22} "
                  f"(matched \"{row['matched']}\")")

    if result["uncategorized"]:
        print()
        print(f"{YELLOW}{BOLD}NOT CATEGORISED - these need a rule{OFF}")
        print("-" * 72)
        total = 0
        for row in sorted(result["uncategorized"],
                          key=lambda r: -(r["amount_usd"] or 0)):
            total += row["amount_usd"] or 0
            print(f"   ${row['amount_usd'] or 0:>9,.2f}  "
                  f"{str(row['vendor'])[:30]:<30} "
                  f"{str(row['description'])[:34]}")
        print(f"\n   ${total:,.2f} across {len(result['uncategorized'])} "
              f"entries has no category.")
        print(f"   Add a line to {config.RULES_PATH.name} and run this again,")
        print(f"   or tell Claude what they are and it will add the rule.")
    else:
        print()
        print(f"{GREEN}Everything has a category.{OFF}")

    # what the totals look like now
    print()
    print(f"{BOLD}EXPENSES BY CATEGORY{OFF}  ({args.year})")
    print("-" * 72)
    for row in connection.execute(
            "SELECT category, COUNT(*) n, SUM(amount_usd) s FROM expenses "
            "WHERE excluded = 0 AND tax_year = ? GROUP BY category "
            "ORDER BY s DESC", (args.year,)):
        print(f"   {row['category'][:28]:<30} {row['n']:>3} "
              f"${row['s'] or 0:>10,.2f}")

    print()
    print("=" * 72)
    if args.dry_run:
        print(f"{BOLD}DRY RUN - nothing was written.{OFF}")
    else:
        print(f"{GREEN}{BOLD}Done.{OFF} "
              f"{len(result['categorized'])} categorised, "
              f"{len(result['uncategorized'])} still without a category.")
    connection.close()
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
