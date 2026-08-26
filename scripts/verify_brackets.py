"""
verify_brackets.py - print every tax figure beside where it came from.

    python scripts/verify_brackets.py

So the numbers can be checked by eye against the source, without reading any
code. Run it once a year when the new figures come out.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from taxlib import constants_2026 as k   # noqa: E402

BOLD, GREEN, YELLOW, OFF = "\033[1m", "\033[32m", "\033[33m", "\033[0m"


def main():
    print()
    print(f"Tax figures for {k.TAX_YEAR} — Married Filing Separately")
    print("=" * 74)
    print(f"Last checked against the sources: {k.VERIFIED_ON}")

    print(f"\n{BOLD}INCOME TAX BRACKETS{OFF}")
    print(f"{k.RP_URL}")
    print("Table 4, section 1(j)(2)(D) — Married Individuals Filing Separate "
          "Returns")
    print("-" * 74)
    print(f"   {'band':<34} {'rate':>6}   {'tax at start of band':>22}")
    low = 0
    for limit, rate, base in k.MFS_BRACKETS:
        band = (f"over ${low:,} up to ${limit:,}" if limit
                else f"over ${low:,}")
        print(f"   {band:<34} {rate:>5.0%}   ${base:>21,.2f}")
        low = limit or low

    print(f"\n   Check: each band's starting tax equals the one below it plus")
    print(f"   the band's width times its rate. The tests recompute this, so a")
    print(f"   mistyped figure fails rather than quietly changing the answer.")

    print(f"\n{BOLD}OTHER FIGURES{OFF}")
    print("-" * 74)
    rows = [
        ("Standard deduction (MFS)", f"${k.STANDARD_DEDUCTION_MFS:,}",
         "Rev. Proc. 2025-32 §3.15(1)"),
        ("Foreign earned income exclusion", f"${k.FEIE_CAP:,}",
         "Rev. Proc. 2025-32 §3.39, IRC §911(b)(2)(D)(i)"),
        ("Self-employment tax rate", f"{k.SE_TAX_RATE:.1%}",
         f"IRC §1401 — {k.SE_SOCIAL_SECURITY_RATE:.1%} Social Security "
         f"+ {k.SE_MEDICARE_RATE:.1%} Medicare"),
        ("Share of profit it applies to", f"{k.SE_TAXABLE_SHARE:.2%}",
         "IRC §1402(a)(12)"),
        ("Social Security wage base", f"${k.SOCIAL_SECURITY_WAGE_BASE:,}",
         "SSA, announced 24 Oct 2025"),
        ("Additional Medicare Tax", f"{k.ADDITIONAL_MEDICARE_RATE:.1%}",
         "IRC §1401(b)(2)"),
        ("  its threshold (MFS)",
         f"${k.ADDITIONAL_MEDICARE_THRESHOLD_MFS:,}",
         "NOT $200,000 — that is the single-filer figure"),
    ]
    for label, value, source in rows:
        print(f"   {label:<32} {value:>12}   {source}")

    print(f"\n{YELLOW}   One figure was not read from its primary source:{OFF}")
    print(f"   the Social Security wage base. ssa.gov returns 403 to any")
    print(f"   automated request, so it is corroborated across independent")
    print(f"   sources instead, and checks out arithmetically — the widely")
    print(f"   reported maximum contribution of $11,439 is exactly 6.2% of")
    print(f"   ${k.SOCIAL_SECURITY_WAGE_BASE:,}.")
    print(f"   {k.SOCIAL_SECURITY_WAGE_BASE_SOURCE}")

    print(f"\n{BOLD}A TRAP WORTH KNOWING{OFF}")
    print("-" * 74)
    print("   Revenue Procedure 2025-32 puts Tables 3 and 4 on the same page,")
    print("   with their bodies split across a page break. Extracted as plain")
    print("   text they interleave, and the Single 37% threshold of $640,600")
    print("   reads as though it belongs to Married Filing Separately.")
    print(f"   It does not. The MFS figure is $384,350 — half the $768,700")
    print("   joint threshold, which is the relationship to sanity-check.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
