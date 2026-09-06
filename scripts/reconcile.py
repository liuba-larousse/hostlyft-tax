"""
reconcile.py - what each person earned, against what they were actually paid.

    python scripts/reconcile.py
        Read your accounting sheet, compare it with the database, print
        both. Writes the result into the database's audit record.

    python scripts/reconcile.py --no-save
        Just look. Changes nothing at all.

YOUR ACCOUNTING SHEET IS ONLY EVER READ. Nothing here writes to it. The
tax sheet, which this system does own, is built by build_tax_sheet.py.
"""

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from taxlib import config, db, reconcile   # noqa: E402

BOLD, GREEN, YELLOW, RED, CYAN, OFF = (
    "\033[1m", "\033[32m", "\033[33m", "\033[31m", "\033[36m", "\033[0m")


def main():
    parser = argparse.ArgumentParser(
        description="Reconcile the sheet against the database.")
    parser.add_argument("--year", type=int,
                        default=config.SETTINGS["tax_year"])
    parser.add_argument("--no-save", action="store_true",
                        help="print only; do not record the result")
    args = parser.parse_args()

    connection = db.init_db()
    year = args.year

    print(f"\n{BOLD}Reconciliation {year}{OFF}")
    print("=" * 74)
    print("Reading your accounting sheet...")
    months = reconcile.read_sheet(year)

    rows = reconcile.per_person(connection, year, months=months)

    print()
    print(f"{BOLD}PER PERSON{OFF}   (US dollars)")
    print("-" * 74)
    print(f"{'Person':<24}{'earned':>12}{'withdrawn':>12}"
          f"{'in jar':>11}{'gap':>12}")
    for row in rows:
        earned = (f"{row['earned_usd']:,.2f}" if row["in_sheet"]
                  else "not in sheet")
        gap = f"{row['gap_usd']:,.2f}" if row["gap_usd"] is not None else "-"
        colour = ""
        if not row["in_sheet"]:
            colour = YELLOW
        elif row["gap_usd"] is not None and abs(row["gap_usd"]) >= 1:
            colour = YELLOW
        print(f"{colour}{row['person']:<24}{earned:>12}"
              f"{row['withdrawn_usd']:>12,.2f}{row['in_jar_usd']:>11,.2f}"
              f"{gap:>12}{OFF}")

    print()
    print("  gap = earned - withdrawn - still in jar")
    print("  POSITIVE  they have earned money neither paid to them nor set")
    print("            aside for them")
    print("  NEGATIVE  more has been paid or reserved than the sheet says")
    print("            they earned")
    print()
    print(f"{CYAN}  Only WITHDRAWN is a tax deduction. Money in a jar is a")
    print("  label inside your own Wise account - it has not been paid to")
    print(f"  anyone.{OFF}")

    missing = [row for row in rows if not row["in_sheet"]]
    if missing:
        print()
        for row in missing:
            print(f"{YELLOW}  {row['person']} was paid "
                  f"${row['withdrawn_usd']:,.2f} but never appears in your")
            print(f"  sheet's split calculation, so there is no earned")
            print(f"  figure to check it against.{OFF}")

    # ------------------------------------------------------ sheet vs db
    checks = reconcile.sheet_vs_database(connection, year, months=months)
    summary = reconcile.summarise(checks)

    print()
    print(f"{BOLD}YOUR SHEET AGAINST THE DATABASE{OFF}   (Hostlyft income, USD)")
    print("-" * 74)
    print(f"{'Month':<14}{'sheet':>13}{'database':>13}{'difference':>13}")
    for row in checks:
        if row["sheet_usd"] == 0 and row["database_usd"] == 0:
            continue
        colour = GREEN if row["agrees"] else YELLOW
        print(f"{colour}{row['month']:<14}{row['sheet_usd']:>13,.2f}"
              f"{row['database_usd']:>13,.2f}"
              f"{row['difference_usd']:>13,.2f}{OFF}")
    print("-" * 74)
    print(f"{BOLD}{'YEAR':<14}{summary['sheet_usd']:>13,.2f}"
          f"{summary['database_usd']:>13,.2f}"
          f"{summary['difference_usd']:>13,.2f}{OFF}")

    print()
    print("  The database records income in the month the money ARRIVED.")
    print("  Your sheet records it against the month it was for. So single")
    print("  months differ without either being wrong - the YEAR total is")
    print("  the comparison that means something.")

    if summary["unmatched_payouts"]:
        print()
        print(f"{YELLOW}{BOLD}PAYOUT ROWS THAT COULD NOT BE ATTRIBUTED{OFF}")
        print("-" * 74)
        total = 0.0
        for entry in summary["unmatched_payouts"]:
            usd = entry["amounts"].get("USD", 0)
            total += usd
            print(f"  {entry['month']:<12} {entry['label']:<34} "
                  f"${usd:>10,.2f}")
        print(f"  {'':<12} {'total':<34} ${total:>10,.2f}")
        print()
        print(f"{YELLOW}  Two people on your roster share the surname")
        print("  Olaniyan, so a row labelled only with a surname is not")
        print("  guessed - crediting it to the wrong person would move")
        print(f"  somebody's $600 threshold.{OFF}")

    # ---------------------------------------------------------- saving
    if not args.no_save:
        as_of = date.today().isoformat()
        saved = reconcile.save_ledger(connection, year, rows, as_of)
        connection.commit()
        print()
        print(f"{GREEN}Recorded {saved} contractors in the audit record, "
              f"dated {as_of}.{OFF}")
        print("  Past reconciliations are kept rather than overwritten, so "
              "you can see how the position moved.")

    print()
    connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
