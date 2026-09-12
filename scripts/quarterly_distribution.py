"""
quarterly_distribution.py - work out the quarterly profit split.

    python scripts/quarterly_distribution.py              # this tax quarter
    python scripts/quarterly_distribution.py --quarter 3
    python scripts/quarterly_distribution.py --dry-run    # show, save nothing
    python scripts/quarterly_distribution.py --withdrawn "Katerina Mrvova"

WHAT IT DOES NOT DO
    It does not move any money. Wise transfers are made by you, by hand.
    This works out the figures, explains the tax consequence of each, and
    records what was decided so a re-run revises rather than repeats.

WHY IT IS TIED TO THE TAX QUARTER
    US estimated tax quarters are not three months each - Q2 is two months
    and Q4 is four. You run this just before filing the quarterly estimate,
    so it uses the same periods the IRS does.
"""

import argparse
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from taxlib import config, db, distribution, fx, reconcile, wise_import  # noqa: E402

BOLD, GREEN, YELLOW, RED, CYAN, OFF = (
    "\033[1m", "\033[32m", "\033[33m", "\033[31m", "\033[36m", "\033[0m")

SE_RATE = 0.153 * 0.9235          # what a dollar of deduction is worth to her


def main():
    parser = argparse.ArgumentParser(
        description="Quarterly profit distribution.")
    parser.add_argument("--year", type=int,
                        default=config.SETTINGS["tax_year"])
    parser.add_argument("--quarter", type=int, choices=[1, 2, 3, 4])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--withdrawn", nargs="*", default=[],
                        help="mark these people as paid (makes it deductible)")
    args = parser.parse_args()

    connection = db.init_db()
    today = dt.date.today()
    # The quarter being FILED, not the one we are standing in. The estimate
    # due on 15 September covers June to August.
    default_year, default_quarter = distribution.quarter_to_distribute(today)
    quarter = args.quarter or default_quarter
    year = args.year if args.quarter or args.year != config.SETTINGS[
        "tax_year"] else default_year
    args.year = year
    months = distribution.TAX_QUARTER_MONTHS[quarter]

    print(f"{BOLD}Hostlyft - quarterly profit distribution{OFF}")
    print("=" * 74)
    print(f"Tax quarter {quarter} of {args.year}: "
          f"{BOLD}{' + '.join(months)}{OFF}, estimate due "
          f"{distribution.TAX_QUARTER_DUE[quarter]}")
    print("   US estimated tax quarters are not three months each -")
    print("   Q2 is two months and Q4 is four. These are the IRS periods.\n")

    # ---- marking money as actually paid -----------------------------------
    if args.withdrawn:
        for person in args.withdrawn:
            connection.execute(
                "UPDATE distributions SET withdrawn_on = ?, updated_at = ? "
                "WHERE tax_year = ? AND quarter = ? AND person = ?",
                (today.isoformat(), db._now(), args.year, quarter, person))
        connection.commit()
        print(f"{GREEN}Marked as withdrawn: {', '.join(args.withdrawn)}{OFF}")
        print("   Their bonus is deductible from today, not from when it was "
              "declared.\n")

    # ---- the pool ---------------------------------------------------------
    token = config.get_secret("WISE_API_TOKEN")
    # The Hostlyft profile only. Her personal account and the Shakti profile
    # are not Hostlyft's money and are not in the pool.
    hostlyft_id = int(config.get_secret("WISE_PROFILE_ID", required=True))
    standard_usd, jars_usd, lines = 0.0, 0.0, []
    for profile in wise_import.fetch_profiles(token):
        if profile.get("id") != hostlyft_id:
            continue
        for balance in wise_import.fetch_balances(token, profile["id"]):
            amount = (balance.get("amount") or {}).get("value") or 0.0
            currency = (balance.get("amount") or {}).get("currency")
            if not amount:
                continue
            converted = fx.convert(connection, amount, currency,
                                   today.isoformat())
            if balance.get("type") == "SAVINGS":
                jars_usd += converted["amount"]
            else:
                standard_usd += converted["amount"]
            lines.append((balance.get("type"), balance.get("name") or
                          "(operating)", amount, currency,
                          converted["amount"]))

    print(f"{BOLD}THE POOL{OFF}")
    print("-" * 74)
    for kind, name, amount, currency, usd in sorted(lines):
        print(f"   {kind:9s} {name:14s} {amount:>10,.2f} {currency} "
              f"= ${usd:>9,.2f}")

    pool = distribution.compute_pool(
        balances_usd=standard_usd + jars_usd, jars_usd=jars_usd)
    print(f"\n   everything in the account   ${pool['balances_usd']:>10,.2f}")
    print(f"   less every jar              ${-pool['jars_usd']:>10,.2f}   "
          f"already set aside for a person - yours too")
    print(f"   less the operating buffer   ${-pool['buffer_usd']:>10,.2f}   "
          f"kept back to run on")
    print(f"   {BOLD}DISTRIBUTABLE              ${pool['pool_usd']:>10,.2f}{OFF}")

    if pool["negative"]:
        print(f"\n{RED}   The buffer is bigger than what is left. "
              f"Nothing to distribute this quarter.{OFF}")
        return

    # ---- who earned what --------------------------------------------------
    sheet = reconcile.read_sheet(args.year)
    subset = {f"{m} {args.year}": sheet[f"{m} {args.year}"]
              for m in months if f"{m} {args.year}" in sheet}
    earned = {name: (data or {}).get("usd") or 0.0
              for name, data in reconcile.earnings_by_person(
                  connection, args.year, months=subset).items()}
    weights, gross = distribution.revenue_weights(earned)

    print(f"\n{BOLD}WHO DROVE THE REVENUE{OFF}   "
          f"{' + '.join(months)}, Marcus excluded")
    print("-" * 74)
    print(f"   Gross client revenue this quarter: ${gross:,.2f}")
    print("   Katerina and Ayoka share one client group, so it is counted")
    print("   ONCE and halved - adding both their figures would double it.")
    print("   Your own weight is the 5% you take off the top.\n")

    rows = distribution.split(pool["pool_usd"], weights)
    print(f"   {'person':<24s} {'drove':>11s} {'share':>7s} "
          f"{'even 20%':>9s} {'by revenue':>11s} {'TOTAL':>10s}")
    for row in rows:
        print(f"   {row['person']:<24s} ${row['weight_usd']:>10,.2f} "
              f"{row['weight_pct']:>6.1f}% ${row['even_usd']:>8,.2f} "
              f"${row['proportional_usd']:>10,.2f} "
              f"{BOLD}${row['total_usd']:>9,.2f}{OFF}")
    print(f"   {'':<24s} {'':>11s} {'':>7s} {'':>9s} {'':>11s} "
          f"${sum(r['total_usd'] for r in rows):>9,.2f}")

    # ---- what it costs in tax --------------------------------------------
    team = [r for r in rows if r["deductible"]]
    hers = [r for r in rows if not r["deductible"]]
    team_total = sum(r["total_usd"] for r in team)
    her_total = sum(r["total_usd"] for r in hers)

    print(f"\n{BOLD}WHAT THIS DOES TO YOUR TAX{OFF}")
    print("-" * 74)
    print(f"   Team bonuses        ${team_total:>10,.2f}   deductible - but "
          f"ONLY once withdrawn")
    print(f"   Your own share      ${her_total:>10,.2f}   "
          f"{RED}NOT deductible{OFF} - an owner draw")
    print(f"   Buffer kept back    ${pool['buffer_usd']:>10,.2f}   taxable "
          f"profit; it is still your money")
    print(f"\n   If the team withdraw it all, your profit falls "
          f"${team_total:,.2f},")
    print(f"   saving about {GREEN}${team_total * SE_RATE:,.2f}{OFF} in "
          f"self-employment tax.")
    print(f"   Left sitting in jars it saves {RED}nothing{OFF} - allocating "
          f"is not paying.")

    if quarter == 4:
        print(f"\n{YELLOW}   Q4 WARNING: this must be WITHDRAWN before 31 "
              f"December.{OFF}")
        print(f"{YELLOW}   Declared in December but paid in January, the "
              f"deduction lands in the NEXT tax year.{OFF}")

    # ---- Katerina's 1099 --------------------------------------------------
    katerina = next((r for r in rows if r["person"] == config.KATERINA), None)
    if katerina:
        ledger = connection.execute(
            "SELECT withdrawn_usd FROM contractor_ledger WHERE person = ? "
            "ORDER BY as_of DESC LIMIT 1", (config.KATERINA,)).fetchone()
        so_far = (ledger["withdrawn_usd"] if ledger else 0.0) or 0.0
        print(f"\n{BOLD}KATERINA'S 1099-NEC{OFF}")
        print("-" * 74)
        print(f"   Withdrawn so far ${so_far:,.2f}; this bonus would add "
              f"${katerina['total_usd']:,.2f}")
        print(f"   -> ${so_far + katerina['total_usd']:,.2f} once she takes it")
        if so_far + katerina["total_usd"] >= 600:
            print(f"   {YELLOW}Over the $600 threshold. She is the only one "
                  f"who gets a 1099-NEC.{OFF}")
        print("   Counts on WITHDRAWALS, not on what is allocated to her jar.")

    # ---- save -------------------------------------------------------------
    if args.dry_run:
        print(f"\n{BOLD}DRY RUN - nothing was saved.{OFF}")
        return

    for row in rows:
        db.upsert_distribution(
            connection, tax_year=args.year, quarter=quarter,
            person=row["person"], pool_usd=pool["pool_usd"],
            even_usd=row["even_usd"], weight_usd=row["weight_usd"],
            proportional_usd=row["proportional_usd"],
            total_usd=row["total_usd"], deductible=row["deductible"],
            notes=f"tax Q{quarter} {'+'.join(months)}")
    connection.commit()

    already = db.distributions_for(connection, args.year, quarter)
    paid = [r["person"] for r in already if r["withdrawn_on"]]
    print(f"\n{GREEN}Recorded for tax Q{quarter} {args.year}.{OFF} "
          f"Re-running revises these figures rather than adding to them.")
    if paid:
        print(f"   Already withdrawn: {', '.join(paid)}")
    outstanding = [r["person"] for r in already
                   if not r["withdrawn_on"] and r["deductible"]]
    if outstanding:
        print(f"   {YELLOW}Not yet withdrawn, so not yet deductible: "
              f"{', '.join(outstanding)}{OFF}")
        print(f"   Mark them paid with:  python scripts/"
              f"quarterly_distribution.py --withdrawn \"Name\"")


if __name__ == "__main__":
    main()
