"""
reconcile_hubspot.py - cross-check the HubSpot payments export.

    python scripts/reconcile_hubspot.py

This export is NOT an income source. Income already comes from the invoices,
and importing both would count every payment twice - the mistake this project
has now hit twice, once with Stripe payouts and once with Upwork.

What it IS good for:

  * which payments actually went through HubSpot Payments, and so bore a
    processing fee - it turns out most did not
  * which payments were refunded
  * which failed, and so are not income at all
  * checking the invoice import against an independent record
"""

import csv
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from taxlib import config, db   # noqa: E402

BOLD, GREEN, YELLOW, OFF = "\033[1m", "\033[32m", "\033[33m", "\033[0m"

FEE_BEARING = "HubSpot Payments"


def find_export():
    matches = sorted(config.IMPORTS_DIR.glob("*payments*.csv"))
    return matches[-1] if matches else None


def main():
    print()
    print("Hostlyft Tax Tracker - HubSpot payments reconciliation")
    print("=" * 74)

    path = find_export()
    if not path:
        print(f"{YELLOW}No payments export found in {config.IMPORTS_DIR}{OFF}")
        print("Export it from HubSpot: Revenue -> Payments -> Export -> CSV")
        return 1
    print(f"Reading {path.name}")

    with open(path, newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))

    year = str(config.SETTINGS["tax_year"])
    this_year = [r for r in rows if (r.get("Payment date") or "").startswith(year)]

    # -- what bore a fee --
    totals = defaultdict(lambda: [0, 0.0])
    for row in this_year:
        if row["Status"] == "Failed":
            continue
        key = row["Processor"]
        totals[key][0] += 1
        totals[key][1] += float(row["Gross amount"])

    print()
    print(f"{BOLD}WHICH PAYMENTS BORE A PROCESSING FEE?{OFF}  ({year})")
    print("-" * 74)
    for processor, (count, total) in sorted(totals.items(),
                                            key=lambda kv: -kv[1][1]):
        note = ("fees apply" if processor == FEE_BEARING
                else "no HubSpot fee - the client paid you directly and the "
                     "invoice was marked paid")
        print(f"   {processor:<22} {count:>3} payments  ${total:>10,.2f}   {note}")

    fee_bearing = totals.get(FEE_BEARING, [0, 0.0])[1]
    print()
    print(f"   Only ${fee_bearing:,.2f} actually passed through HubSpot, so "
          f"only that")
    print(f"   amount bore a fee - not the full invoiced total.")

    # -- refunds --
    refunded = [r for r in this_year if "refund" in r["Status"].lower()]
    print()
    print(f"{BOLD}REFUNDS{OFF}")
    print("-" * 74)
    if refunded:
        for row in refunded:
            print(f"   {row['Payment date'][:10]}  "
                  f"${float(row['Gross amount']):>9,.2f} gross  "
                  f"{row['Customer email'][:32]:<32} {row['Status']}")
        print()
        print(f"   {YELLOW}The export does not carry the refund AMOUNT - "
              f"HubSpot leaves it out.{OFF}")
    else:
        print("   none")

    # -- failed --
    failed = [r for r in this_year if r["Status"] == "Failed"]
    print()
    print(f"{BOLD}FAILED - not income{OFF}")
    print("-" * 74)
    for row in failed:
        print(f"   {row['Payment date'][:10]}  "
              f"${float(row['Gross amount']):>9,.2f}  {row['Customer email'][:34]}")
    if not failed:
        print("   none")

    # -- against what we recorded --
    connection = db.connect()
    recorded = connection.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM income "
        "WHERE source = 'hubspot' AND excluded = 0 AND tax_year = ? "
        "AND currency = 'USD'", (config.SETTINGS["tax_year"],)).fetchone()[0]
    export_usd = sum(float(r["Gross amount"]) for r in this_year
                     if r["Status"] != "Failed")
    print()
    print(f"{BOLD}AGAINST WHAT WE RECORDED{OFF}")
    print("-" * 74)
    print(f"   payments export, all currencies mixed   ${export_usd:>11,.2f}")
    print(f"   recorded from invoices, USD rows only   ${recorded:>11,.2f}")
    print(f"   {YELLOW}These are not directly comparable - the export does "
          f"not say which{OFF}")
    print(f"   {YELLOW}currency each payment was in. Treated as a sanity "
          f"check, not a tie-out.{OFF}")
    connection.close()

    print()
    print("=" * 74)
    print("Nothing was written. This export is a cross-check, not an income")
    print("source - the invoices already provide income, and importing both")
    print("would count every payment twice.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
