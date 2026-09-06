"""
The home office deduction - Stage 12b.

TWO WAYS TO WORK IT OUT, AND THE TOOL COMPUTES BOTH

  ACTUAL      the share of your home that is the office, applied to rent,
              utilities and insurance
  SIMPLIFIED  a flat rate per square foot, capped at 300 sq ft

You may use either. Which one wins is a matter of arithmetic, not
principle, so both are calculated and the better one is named rather than
chosen quietly. For a renter the actual method usually wins by a lot,
because rent is the largest number in the calculation and the simplified
cap is low - but "usually" is not "always", so it is computed each time.

THREE THINGS THAT DECIDE WHETHER THERE IS A DEDUCTION AT ALL

  EXCLUSIVE USE   the space must be used ONLY for work. A dining table
                  cleared away each evening does not qualify. This is the
                  condition people fail, and no arithmetic here rescues it.
  REGULAR USE     and it must be your principal place of business.
  NET PROFIT      the deduction cannot create or deepen a loss. Anything
                  above net profit carries forward to next year instead.

WHAT IT IS WORTH

Her income tax is already $0 under the Foreign Earned Income Exclusion, so
this reduces SELF-EMPLOYMENT tax only - about 14 cents in the dollar. The
figure is reported honestly rather than dressed up.

NO DEPRECIATION. She rents. Depreciation applies to a home you own, and it
is the hardest part of Form 8829. It simply does not arise here.
"""

from taxlib import config, constants_2026 as k, db, fx


class HomeOfficeNotClaimed(Exception):
    """Raised when the conditions are not met, with the reason in plain words."""


def business_share(settings=None):
    """
    The fraction of the home that is the office.

    Both areas must be in the same unit; only the ratio is used, so square
    metres and square feet give the same answer.
    """
    settings = settings or config.HOME_OFFICE
    total = float(settings.get("total_area") or 0)
    office = float(settings.get("office_area") or 0)

    if total <= 0 or office <= 0:
        raise HomeOfficeNotClaimed(
            "The home office needs both a total home area and an office "
            "area. Set them in taxlib/config.py under HOME_OFFICE.")
    if office > total:
        raise HomeOfficeNotClaimed(
            f"The office ({office}) is larger than the whole home "
            f"({total}). One of the two numbers is wrong.")
    return office / total


def office_sqft(settings=None):
    """The office area in square feet, whatever unit it was given in."""
    settings = settings or config.HOME_OFFICE
    area = float(settings.get("office_area") or 0)
    unit = str(settings.get("area_unit", "m2")).lower()
    if unit in {"m2", "sqm", "m^2", "sq m"}:
        return area * config.SQFT_PER_SQM
    return area


def simplified(settings=None, months_counted=None):
    """
    The flat-rate method: a fixed amount per square foot, capped.

    The cap is on the AREA, not the money - the first 300 square feet count
    and anything beyond that adds nothing.
    """
    settings = settings or config.HOME_OFFICE
    sqft = office_sqft(settings)
    counted = min(sqft, config.SIMPLIFIED_HOME_OFFICE_MAX_SQFT)
    amount = counted * config.SIMPLIFIED_HOME_OFFICE_RATE_PER_SQFT

    # Pro-rated on the same number of months the actual method counted,
    # or the two would not be comparable and the "better" one would be
    # decided by the calendar rather than the arithmetic.
    months = float(months_counted if months_counted is not None
                   else settings.get("months", 12) or 12)
    amount = amount * min(months, 12) / 12

    return {
        "method": "simplified",
        "office_sqft": round(sqft, 2),
        "counted_sqft": round(counted, 2),
        "capped": sqft > config.SIMPLIFIED_HOME_OFFICE_MAX_SQFT,
        "rate": config.SIMPLIFIED_HOME_OFFICE_RATE_PER_SQFT,
        "months": months,
        "amount_usd": db.round_money(amount),
    }


def actual(connection, tax_year, settings=None, fetcher=None, today=None):
    """
    The share-of-costs method.

    CONVERTED MONTH BY MONTH, NOT ONCE FOR THE YEAR. Rent is paid every
    month at whatever the rate was that month, so twelve conversions is
    both more accurate than one and the way the rest of this system already
    treats foreign amounts.

    It also settles a question a single year-end rate cannot: months that
    have not happened yet have no exchange rate, and inventing one would be
    a guess. Only ELAPSED months are counted, and how many were counted is
    reported so a part-year figure is never mistaken for a full one.
    """
    import calendar
    import datetime as dt

    settings = settings or config.HOME_OFFICE
    share = business_share(settings)
    wanted = int(min(float(settings.get("months", 12) or 12), 12))

    monthly = (float(settings.get("monthly_rent") or 0)
               + float(settings.get("monthly_utilities") or 0)
               + float(settings.get("monthly_insurance") or 0))
    currency = str(settings.get("currency", "USD")).upper()

    today = today or dt.date.today()
    if isinstance(today, str):
        today = dt.date.fromisoformat(today)

    business_monthly = monthly * share
    total_usd, counted, rates = 0.0, 0, []

    for month in range(1, wanted + 1):
        last_day = calendar.monthrange(tax_year, month)[1]
        month_end = dt.date(tax_year, month, last_day)
        # A month still running, or still to come, has no rate yet.
        if month_end > today:
            break

        if currency == "USD":
            total_usd += business_monthly
        else:
            converted = fx.convert(connection, business_monthly, currency,
                                   month_end.isoformat(), fetcher=fetcher)
            total_usd += converted["amount"]
            rates.append((month_end.isoformat(), converted["rate"]))
        counted += 1

    return {
        "method": "actual",
        "share": share,
        "share_percent": round(share * 100, 2),
        "monthly_cost_native": db.round_money(monthly),
        "monthly_business_native": db.round_money(business_monthly),
        "total_cost_native": db.round_money(monthly * counted),
        "business_cost_native": db.round_money(business_monthly * counted),
        "currency": currency,
        "months_wanted": wanted,
        "months_counted": counted,
        "part_year": counted < wanted,
        "rates": rates,
        "amount_usd": db.round_money(total_usd),
    }


def best(connection, tax_year, net_profit=None, settings=None,
         fetcher=None, today=None):
    """
    Both methods, the better one named, and the net-profit limit applied.

    Returns a dictionary rather than a single number, because a figure with
    no working behind it cannot be checked - and this one rests on a test
    (exclusive use) that no arithmetic can verify.
    """
    settings = settings or config.HOME_OFFICE

    if not settings.get("exclusive_use", False):
        raise HomeOfficeNotClaimed(
            "EXCLUSIVE_USE is set to False, so no home office deduction is "
            "claimed.\n"
            "  The space has to be used ONLY for work - not a room that is "
            "also a guest room,\n"
            "  and not a desk in the corner of a room used for other "
            "things. If it genuinely\n"
            "  is used only for work, set exclusive_use to True in "
            "taxlib/config.py.")

    by_actual = actual(connection, tax_year, settings, fetcher=fetcher,
                       today=today)
    by_simplified = simplified(settings, by_actual["months_counted"])

    winner = (by_actual if by_actual["amount_usd"] >= by_simplified["amount_usd"]
              else by_simplified)
    claimed = winner["amount_usd"]

    # The deduction cannot create or deepen a loss. Anything above net
    # profit is not lost - it carries forward to next year.
    limited, carried = claimed, 0.0
    if net_profit is not None and claimed > max(0.0, net_profit):
        limited = db.round_money(max(0.0, net_profit))
        carried = db.round_money(claimed - limited)

    return {
        "actual": by_actual,
        "simplified": by_simplified,
        "better_method": winner["method"],
        "difference_usd": db.round_money(abs(by_actual["amount_usd"]
                                             - by_simplified["amount_usd"])),
        "claimed_usd": limited,
        "before_limit_usd": claimed,
        "carried_forward_usd": carried,
        "limited_by_profit": carried > 0,
        # What it is actually worth: it reduces self-employment tax only.
        "tax_saved_usd": db.round_money(
            limited * k.SE_TAXABLE_SHARE * k.SE_TAX_RATE),
    }
