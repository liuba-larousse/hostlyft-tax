"""
init_db.py - create the database, or show what's currently in it.

Run it from Terminal:

    cd ~/Documents/hostlyft-tax
    source .venv/bin/activate
    python scripts/init_db.py

Running it again is safe. It never deletes or overwrites anything - it only
adds tables that aren't there yet, then prints a summary.

    python scripts/init_db.py --show    just report, don't create anything
    python scripts/init_db.py --year 2026   totals for one tax year
"""

import argparse
import sys
from pathlib import Path

# Make the project's own code importable no matter which folder you run this
# from. Without this line, Python looks for `taxlib` next to THIS file (in
# scripts/) rather than one level up, and gives up.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from taxlib import config, db   # noqa: E402  (must come after the line above)


def human_money(value):
    """Format a number the way money is normally written: $1,940.00"""
    if value is None:
        return "-"
    return f"${value:,.2f}"


def describe(connection, tax_year):
    """Print a plain-English summary of what the database holds."""
    counts = {
        name: connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        for name in db.table_names(connection)
        if name != "meta"
    }

    print()
    print("WHAT'S IN THE DATABASE")
    print("-" * 58)
    labels = {
        "income": "income          money you earned",
        "expenses": "expenses        money you spent",
        "stripe_payouts": "stripe_payouts  NOT income - the double-count check list",
        "fx_rates": "fx_rates        saved exchange rates",
        "alerts_sent": "alerts_sent     reminders already sent",
    }
    for name in ["income", "expenses", "stripe_payouts", "fx_rates", "alerts_sent"]:
        print(f"  {counts.get(name, 0):>6} rows   {labels[name]}")

    if counts.get("income", 0) == 0 and counts.get("expenses", 0) == 0:
        print()
        print("  All empty, which is correct - nothing has been imported yet.")
        print("  Stage 4 fills income from Stripe; Stage 7 adds Capital One.")
        return

    figures = db.totals(connection, tax_year)

    print()
    print(f"TOTALS FOR {tax_year}")
    print("-" * 58)
    print(f"  income            {human_money(figures['income_usd']):>14}"
          f"   ({figures['income_count']} entries)")
    print(f"  expenses          {human_money(figures['expenses_usd']):>14}"
          f"   ({figures['expense_count']} entries)")
    print(f"  {'-' * 54}")
    print(f"  net profit        {human_money(figures['net_profit_usd']):>14}"
          f"   <- what tax is worked out from")

    # Anything that could make those totals misleading gets said out loud.
    warnings = []
    if figures["unconverted_income_count"] or figures["unconverted_expense_count"]:
        warnings.append(
            f"{figures['unconverted_income_count'] + figures['unconverted_expense_count']}"
            f" entries have no US dollar amount yet, so they are counted as $0"
            f" above. Stage 5 converts them."
        )
    if figures["needs_review_count"]:
        warnings.append(
            f"{figures['needs_review_count']} entries are flagged for review -"
            f" the importer was unsure and refused to guess."
        )
    if figures["uncategorized_expense_count"]:
        warnings.append(
            f"{figures['uncategorized_expense_count']} expenses have no"
            f" category yet (Stage 8)."
        )
    if figures["excluded_income_count"]:
        warnings.append(
            f"{figures['excluded_income_count']} incoming payments were"
            f" excluded as internal transfers already counted via Stripe."
            f" That is the double-count protection working."
        )

    if warnings:
        print()
        print("WORTH KNOWING")
        print("-" * 58)
        for note in warnings:
            print(f"  - {note}")


def main():
    parser = argparse.ArgumentParser(
        description="Create the tax database, or show what it contains."
    )
    parser.add_argument(
        "--show", action="store_true",
        help="only report on the existing database, create nothing",
    )
    parser.add_argument(
        "--year", type=int, default=config.SETTINGS["tax_year"],
        help="which tax year to total up (default: %(default)s)",
    )
    args = parser.parse_args()

    print()
    print("Hostlyft Tax Tracker - database")
    print("=" * 58)
    print(f"File: {config.DB_PATH}")

    already_existed = config.DB_PATH.exists()

    if args.show:
        if not already_existed:
            print()
            print("  That file doesn't exist yet.")
            print("  Run  python scripts/init_db.py  to create it.")
            return 1
        connection = db.connect()
    else:
        connection = db.init_db()
        print()
        if already_existed:
            print("  Already existed - checked, nothing changed.")
        else:
            print("  Created. This one file now holds everything.")
            print("  It lives in tax/, which git refuses to upload.")
            print("  Copying that file is a complete backup.")

    print(f"  Layout version {db.schema_version(connection)}")

    describe(connection, args.year)

    connection.commit()
    connection.close()

    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
