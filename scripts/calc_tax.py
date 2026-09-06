"""
calc_tax.py - what to set aside, and why.

    python scripts/calc_tax.py               # from your actual records
    python scripts/calc_tax.py --profit 80000    # try a figure
    python scripts/calc_tax.py --certificate     # if you register in France

Explains every step as it goes. A single number with no working behind it
cannot be checked, and this is the number the whole tool exists to produce.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from taxlib import config, constants_2026 as k, db, tax   # noqa: E402

BOLD, GREEN, YELLOW, CYAN, OFF = (
    "\033[1m", "\033[32m", "\033[33m", "\033[36m", "\033[0m")


def main():
    parser = argparse.ArgumentParser(description="Estimate US federal tax.")
    parser.add_argument("--profit", type=float,
                        help="try a net profit figure instead of your records")
    parser.add_argument("--year", type=int, default=config.SETTINGS["tax_year"])
    parser.add_argument("--certificate", action="store_true",
                        help="model having a French Certificate of Coverage")
    parser.add_argument("--paid", type=float, default=0.0,
                        help="tax already paid this year")
    args = parser.parse_args()

    settings = dict(config.SETTINGS)
    if args.certificate:
        settings["certificate_of_coverage"] = True

    print()
    print(f"Hostlyft Tax Tracker - {args.year} federal tax estimate")
    print("=" * 74)

    connection = None
    if args.profit is not None:
        net_profit = args.profit
        print(f"Using a figure you gave: ${net_profit:,.2f} net profit")
        result = tax.estimate(net_profit, settings)
    else:
        connection = db.connect()
        result = tax.from_database(connection, args.year, settings)
        t = result["totals"]
        h = db.totals(connection, args.year, business="hostlyft")
        m = db.totals(connection, args.year, business="marcus")
        print("From your records:")
        print(f"   Hostlyft LLC          income ${h['income_usd']:>11,.2f}"
              f"   expenses ${h['expenses_usd']:>10,.2f}")
        print(f"   Marcus (separate)     income ${m['income_usd']:>11,.2f}"
              f"   expenses ${m['expenses_usd']:>10,.2f}")
        print(f"   {'-' * 66}")
        print(f"   COMBINED              income ${t['income_usd']:>11,.2f}"
              f"   expenses ${t['expenses_usd']:>10,.2f}")
        print(f"   NET PROFIT            ${t['net_profit_usd']:,.2f}")
        print()
        print("   Combined because a single-member LLC is a disregarded")
        print("   entity - both land on the same 1040, and self-employment")
        print("   tax is charged on the combined figure.")

        if t["non_deductible_usd"]:
            print()
            print(f"   Of those expenses, ${t['non_deductible_usd']:,.2f} is "
                  f"NOT deductible.")
            print("   Business meals count at 50%, not 100%. What you spent")
            print("   and what you may deduct are different numbers.")
            print(f"   Deductible expenses: "
                  f"${t['deductible_expenses_usd']:,.2f}")

        office = result.get("home_office")
        if office:
            actual_m, simple_m = office["actual"], office["simplified"]
            print()
            print(f"{BOLD}   HOME OFFICE{OFF}")
            print(f"   Actual costs:  {actual_m['share_percent']}% of "
                  f"{actual_m['currency']} "
                  f"{actual_m['monthly_cost_native']:,.2f}/month "
                  f"x {actual_m['months_counted']} months"
                  f"  = ${actual_m['amount_usd']:,.2f}")
            print(f"   Simplified:    {simple_m['office_sqft']:,.0f} sq ft "
                  f"x ${simple_m['rate']:.2f}"
                  f"                       = "
                  f"${simple_m['amount_usd']:,.2f}")
            print(f"   {GREEN}Using the {office['better_method']} method - "
                  f"${office['difference_usd']:,.2f} better.{OFF}")
            if actual_m["part_year"]:
                print(f"   {YELLOW}Only {actual_m['months_counted']} months "
                      f"have finished, so this is a part-year figure and "
                      f"will grow.{OFF}")
            if office["limited_by_profit"]:
                print(f"   {YELLOW}Capped at your net profit; "
                      f"${office['carried_forward_usd']:,.2f} carries "
                      f"forward to next year.{OFF}")
            print(f"   Deduction: ${office['claimed_usd']:,.2f}"
                  f"   -> saves about ${office['tax_saved_usd']:,.2f} in "
                  f"self-employment tax")
            print(f"   {YELLOW}This relies on the 12 m2 being used ONLY for "
                  f"work. That is the test people fail.{OFF}")
            print(f"   NET PROFIT AFTER HOME OFFICE   "
                  f"${result['net_profit']:,.2f}")
        elif result.get("home_office_problem"):
            print()
            print(f"{YELLOW}   HOME OFFICE NOT CLAIMED{OFF}")
            for line in result["home_office_problem"].splitlines():
                print(f"   {line}")

    net_profit = result["net_profit"]

    print(f"\n{BOLD}SELF-EMPLOYMENT TAX{OFF}   — in your case, nearly the "
          f"whole bill")
    print("-" * 74)
    for step in result["self_employment_tax"]["steps"]:
        print(f"   {step}")

    print(f"\n{BOLD}INCOME TAX{OFF}")
    print("-" * 74)
    for step in result["income_tax"]["steps"]:
        print(f"   {step}")

    print(f"\n{BOLD}{CYAN}WHAT TO SET ASIDE{OFF}")
    print("=" * 74)
    se = result["self_employment_tax"]["total"]
    it = result["income_tax"]["total"]
    print(f"   self-employment tax     ${se:>12,.2f}")
    print(f"   income tax              ${it:>12,.2f}")
    print(f"   {'-' * 38}")
    print(f"   {BOLD}TOTAL                   ${result['total']:>12,.2f}{OFF}")
    if net_profit > 0:
        print(f"\n   That is {result['effective_rate']:.1%} of "
              f"${net_profit:,.2f} of profit.")

    remaining = max(0.0, result["total"] - args.paid)
    if args.paid:
        print(f"   Already paid ${args.paid:,.2f}, leaving ${remaining:,.2f}.")
    print(f"   Per quarter: ${tax.quarterly(result['total'], args.paid):,.2f}")

    if not settings.get("certificate_of_coverage"):
        other = tax.estimate(net_profit,
                             {**settings, "certificate_of_coverage": True})
        print(f"\n{BOLD}IF YOU REGISTERED IN FRANCE{OFF}")
        print("-" * 74)
        print(f"   With a French Certificate of Coverage the US bill would be "
              f"${other['total']:,.2f},")
        print(f"   a difference of ${result['total'] - other['total']:,.2f}.")
        print()
        print("   Not a saving to reach for. French self-employed")
        print("   contributions for a service business run roughly 21-24% OF")
        print("   REVENUE, which can exceed 15.3% of PROFIT. Registering is")
        print("   about being compliant where you live, not about paying less.")

    print(f"\n{BOLD}SAFE HARBOUR{OFF}")
    print("-" * 74)
    print("   Paying 100% of LAST year's total tax shields you from")
    print("   underpayment penalties however this year turns out. If 2026 ends")
    print("   bigger than expected, you are not penalised for having estimated")
    print("   from last year's figure.")

    print(f"\n{YELLOW}   This estimates US FEDERAL tax only. It is not tax")
    print(f"   advice, and does not cover your French obligations - which,")
    print(f"   living and working in France, are likely the larger exposure.")
    print(f"   Figures verified against the IRS publication on "
          f"{k.VERIFIED_ON};")
    print(f"   run scripts/verify_brackets.py to see each one.{OFF}")

    if connection:
        t = result["totals"]
        if t["needs_review_count"]:
            print(f"\n   {YELLOW}{t['needs_review_count']} entries are still "
                  f"flagged for review - the figure above could move.{OFF}")
        connection.close()
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
