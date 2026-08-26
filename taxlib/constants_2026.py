"""
constants_2026.py - the tax figures, each with its source.

EVERY NUMBER HERE WAS READ FROM THE PRIMARY SOURCE ON 26 AUGUST 2026.

That mattered. The build plan carried figures cross-checked across secondary
sources but never read from the IRS document itself, and flagged that as the
first thing to fix. Verifying them found no errors - but it also found how
easily one could have crept in: Revenue Procedure 2025-32 puts Tables 3 and 4
on the same page with the bodies split across a page break, so a plain text
extraction interleaves them. Read carelessly, the Single 37% threshold of
$640,600 looks like the Married-Filing-Separately one, which is $384,350.

Run scripts/verify_brackets.py to see each figure beside its source.
"""

TAX_YEAR = 2026

# ===========================================================================
#  INCOME TAX - Revenue Procedure 2025-32
#  https://www.irs.gov/pub/irs-drop/rp-25-32.pdf
# ===========================================================================

RP_URL = "https://www.irs.gov/pub/irs-drop/rp-25-32.pdf"

# Table 4, section 1(j)(2)(D), page 11-12 - Married Individuals Filing
# Separate Returns. (upper_limit, rate, tax_at_start_of_band)
#
# The third figure is the PDF's own cumulative tax at the bottom of each
# band. It is not needed for the calculation, but it is kept so the bands
# can be checked against the document without arithmetic - and the tests
# recompute it, which is what caught nothing this time and would catch a
# typo next time.
MFS_BRACKETS = [
    (12_400,   0.10,          0.00),
    (50_400,   0.12,      1_240.00),
    (105_700,  0.22,      5_800.00),
    (201_775,  0.24,     17_966.00),
    (256_225,  0.32,     41_024.00),
    (384_350,  0.35,     58_448.00),
    (None,     0.37,    103_291.75),
]

# Section 3.15(1), page 9 - standard deduction. MFS and Single are both
# $16,100 for 2026; MFJ is $32,200 and Head of Household $24,150.
STANDARD_DEDUCTION_MFS = 16_100

# Section 3.39, page 21 - foreign earned income exclusion under 911(b)(2)(D)(i)
FEIE_CAP = 132_900

# ===========================================================================
#  SELF-EMPLOYMENT TAX
# ===========================================================================

# Section 1401. 12.4% Social Security + 2.9% Medicare.
SE_SOCIAL_SECURITY_RATE = 0.124
SE_MEDICARE_RATE = 0.029
SE_TAX_RATE = SE_SOCIAL_SECURITY_RATE + SE_MEDICARE_RATE      # 0.153

# Section 1402(a)(12). Only 92.35% of net profit is subject to the tax -
# the deduction standing in for the employer's half.
SE_TAXABLE_SHARE = 0.9235

# Social Security contribution and benefit base for 2026.
# Announced by SSA on 24 October 2025, up from $176,100.
#
# NOT read from ssa.gov: their site returns 403 to any automated request.
# Corroborated across independent sources including the American Payroll
# Association, and it checks out arithmetically - the widely reported
# maximum employee contribution of $11,439 is exactly 6.2% of $184,500.
# Worth confirming by eye if this is ever relied on for a large number.
SOCIAL_SECURITY_WAGE_BASE = 184_500
SOCIAL_SECURITY_WAGE_BASE_SOURCE = "https://www.ssa.gov/oact/cola/cbb.html"

# The Medicare part is uncapped, and above a threshold there is another
# 0.9% on top - sections 1401(b)(2) and 3101(b)(2).
ADDITIONAL_MEDICARE_RATE = 0.009

# $125,000 for Married Filing Separately. NOT the $200,000 quoted almost
# everywhere - that is the single-filer figure, and using it would silently
# under-tax anyone filing separately. Statutory, so it does not move with
# inflation.
ADDITIONAL_MEDICARE_THRESHOLD_MFS = 125_000
ADDITIONAL_MEDICARE_SOURCE = (
    "https://www.irs.gov/businesses/small-businesses-self-employed/"
    "questions-and-answers-for-the-additional-medicare-tax")

# When each figure was last checked against its source.
VERIFIED_ON = "2026-08-26"
