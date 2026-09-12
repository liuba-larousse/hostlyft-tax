"""
pull_wise.py - import Wise transactions and jar balances.

    python scripts/pull_wise.py --dry-run    # show everything, write nothing
    python scripts/pull_wise.py              # import for real

Reads all three accounts:

    Hostlyft LLC   fully
    Shakti Lease   fully (business until 5 June 2026)
    Personal       INCOMING ONLY, and only from senders known to be
                   business. Outgoing payments are skipped without being
                   read - your personal spending is never stored or logged.

Safe to run repeatedly. Every row carries its Wise reference, so a repeat
updates rather than duplicates.

    --days 30      how far back to re-read (default: %(default)s)
    --since        an explicit start date, e.g. 2026-01-01
    --dry-run      show what would happen, write nothing
"""

import argparse
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from taxlib import config, db, filings, wise_import   # noqa: E402

BOLD, GREEN, YELLOW, RED, OFF = (
    "\033[1m", "\033[32m", "\033[33m", "\033[31m", "\033[0m")

# Which profile is which, and how much of it may be read.
SHAKTI_PROFILE_ID = 36576462


def profile_plan(profiles):
    """Decide how each profile should be treated."""
    business_id = int(config.get_secret("WISE_PROFILE_ID", required=True))
    personal_id = int(config.get_secret("WISE_PERSONAL_PROFILE_ID",
                                        default="0") or 0)
    plan = []
    for profile in profiles:
        pid = profile.get("id")
        if pid == business_id:
            plan.append((pid, "hostlyft", config.BUSINESS_HOSTLYFT, False))
        elif pid == personal_id:
            plan.append((pid, "personal", config.BUSINESS_HOSTLYFT, True))
        elif pid == SHAKTI_PROFILE_ID:
            plan.append((pid, "shakti", config.BUSINESS_HOSTLYFT, False))
        else:
            print(f"  {YELLOW}profile {pid} is not recognised and was "
                  f"skipped.{OFF}")
    return plan


def main():
    parser = argparse.ArgumentParser(
        description="Import Wise transactions and jar balances.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--days", type=int, default=30,
                        help="trailing window to re-read (default: %(default)s)")
    parser.add_argument("--since", help="explicit start date YYYY-MM-DD")
    args = parser.parse_args()

    today = dt.date.today()
    start = args.since or (today - dt.timedelta(days=args.days)).isoformat()
    end = today.isoformat()

    print()
    print("Hostlyft Tax Tracker - Wise import")
    print("=" * 74)
    print(f"Window: {start} to {end}")
    print("A trailing window, not 'since last run' - so a missed day is not a")
    print("lost day, and corrections to older transactions are picked up too.")
    print()

    try:
        token = config.get_secret("WISE_API_TOKEN", required=True)
        profiles = wise_import.fetch_profiles(token)
    except (config.MissingSecret, wise_import.WiseError) as error:
        print(f"{RED}{error}{OFF}")
        return 1

    connection = db.init_db()
    totals = {"income": [], "expenses": [], "jars": [], "notes": []}

    for pid, label, business, personal in profile_plan(profiles):
        scope = "INCOMING ONLY" if personal else "full"
        print(f"{BOLD}{label}{OFF} (profile {pid}) - {scope}")

        balances = wise_import.fetch_balances(token, pid)
        for balance in balances:
            currency = (balance.get("amount") or {}).get("currency")
            kind = balance["_kind"]
            jar = balance.get("name")

            # A jar's balance is an observation, never an expense.
            if kind == "SAVINGS" and not personal:
                totals["jars"].append({
                    "balance_id": balance["id"], "jar_name": jar or "(unnamed)",
                    "observed_on": end,
                    "amount": (balance.get("amount") or {}).get("value") or 0,
                    "currency": currency,
                    "amount_usd": ((balance.get("amount") or {}).get("value")
                                   if currency == "USD" else None),
                    "person": (config.match_contractor(jar or "", strict=False)
                               or {}).get("name"),
                })

            try:
                txns = wise_import.fetch_statement(token, pid, balance["id"],
                                                   currency, start, end)
            except wise_import.WiseError as error:
                print(f"   {RED}{currency} {kind}: {error}{OFF}")
                continue

            records = wise_import.build_records(
                connection, txns, profile_label=label, business=business,
                personal=personal, balance_kind=kind, jar_name=jar)
            for key in ("income", "expenses", "notes"):
                totals[key].extend(records[key])
            totals.setdefault("tax_payments", []).extend(
                records.get("tax_payments", []))
            totals.setdefault("movements", []).extend(records["jars"])

            label_jar = f" ({jar})" if jar else ""
            print(f"   {currency} {kind}{label_jar:<18} {len(txns):>3} txns")

    # Estimated tax paid to the IRS. Recorded, never as an expense - it is
    # her personal liability, not a cost of the business.
    for payment in totals.get("tax_payments", []):
        year, quarter = filings.quarter_for_payment(payment["paid_on"])
        db.record_tax_payment(
            connection, tax_year=year, quarter=quarter,
            paid_on=payment["paid_on"], amount=payment["amount"],
            currency=payment["currency"], amount_usd=payment["amount_usd"],
            detected="wise", source_id=payment["source_id"],
            note=payment["note"])
    if totals.get("tax_payments"):
        connection.commit()
        print(f"   {GREEN}{len(totals['tax_payments'])} estimated tax "
              f"payment(s) found{OFF}")

    # ---- report ----
    counted = [r for r in totals["income"] if not r.get("excluded")]
    excluded = [r for r in totals["income"] if r.get("excluded")]
    real_expenses = [r for r in totals["expenses"] if not r.get("excluded")]

    print()
    print(f"{BOLD}INCOME COUNTED{OFF}")
    print("-" * 74)
    for r in sorted(counted, key=lambda r: r["date"]):
        flag = "  <- REVIEW" if r.get("needs_review") else ""
        print(f"   {r['date']}  {r['amount']:>10,.2f} {r['currency']}  "
              f"{str(r.get('payer'))[:32]:<32}{flag}")
    if not counted:
        print("   none in this window")

    print()
    print(f"{BOLD}MONEY IN, DELIBERATELY NOT COUNTED{OFF}  "
          f"(recorded so the decision is visible)")
    print("-" * 74)
    for r in sorted(excluded, key=lambda r: r["date"]):
        print(f"   {r['date']}  {r['amount']:>10,.2f} {r['currency']}  "
              f"{str(r.get('payer'))[:26]:<26} {r['exclusion_reason'][:60]}")
    if not excluded:
        print("   none")

    print()
    print(f"{BOLD}EXPENSES{OFF}")
    print("-" * 74)
    for r in sorted(real_expenses, key=lambda r: r["date"]):
        flag = "  <- REVIEW" if r.get("needs_review") else ""
        print(f"   {r['date']}  {r['amount']:>10,.2f} {r['currency']}  "
              f"{r['category']:<18} {str(r.get('vendor'))[:24]:<24}{flag}")
    if not real_expenses:
        print("   none in this window")

    if totals["jars"]:
        print()
        print(f"{BOLD}JARS{OFF}  - money set aside, still yours, NOT an expense")
        print("-" * 74)
        for j in sorted(totals["jars"], key=lambda j: -abs(j["amount"])):
            who = f"  ({j['person']})" if j.get("person") else ""
            print(f"   {j['jar_name']:<14} {j['amount']:>10,.2f} "
                  f"{j['currency']}{who}")

    for note in totals["notes"]:
        print(f"\n{YELLOW}   NOTE: {note}{OFF}")

    print()
    print("=" * 74)
    if args.dry_run:
        print(f"{BOLD}DRY RUN - nothing was written.{OFF}")
        connection.close()
        return 0

    for row in totals["income"]:
        db.upsert_income(connection, **row)
    for row in totals["expenses"]:
        db.upsert_expense(connection, **row)
    for jar in totals["jars"]:
        db.record_jar_balance(connection, **jar)
    for movement in totals.get("movements", []):
        db.record_jar_movement(connection, **movement)
    connection.commit()

    figures = db.totals(connection, config.SETTINGS["tax_year"])
    print(f"{GREEN}{BOLD}Imported.{OFF}  "
          f"{len(counted)} income, {len(excluded)} excluded, "
          f"{len(real_expenses)} expenses, {len(totals['jars'])} jars, "
          f"{len(totals.get('movements', []))} jar movements")
    print()
    print(f"   income      ${figures['income_usd']:>12,.2f}")
    print(f"   expenses    ${figures['expenses_usd']:>12,.2f}")
    print(f"   net profit  ${figures['net_profit_usd']:>12,.2f}")
    jars_usd = db.total_in_jars_usd(connection)
    unconverted_jars = connection.execute(
        "SELECT COUNT(*) FROM wise_jars WHERE amount_usd IS NULL").fetchone()[0]
    note = " (some not yet converted)" if unconverted_jars else ""
    print(f"   in jars     ${jars_usd:>12,.2f}   <- still yours, "
          f"not deductible{note}")
    unconverted = (figures["unconverted_income_count"]
                   + figures["unconverted_expense_count"])
    if unconverted:
        print(f"\n   {YELLOW}{unconverted} entries need converting to USD - "
              f"run scripts/convert_currency.py{OFF}")
    if figures["needs_review_count"]:
        print(f"   {YELLOW}{figures['needs_review_count']} entries flagged "
              f"for review{OFF}")
    connection.close()
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
