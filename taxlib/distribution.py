"""
Stage 14 - the quarterly profit distribution.

At each quarter end the Hostlyft account is shared between Liuba and the
three revenue managers - Katerina, Ayoka and Jane. Sunniva is not in it: she
is hourly, not a revenue manager.

TIMED TO THE TAX QUARTER, NOT THE CALENDAR QUARTER
    Her choice, and it matters. US estimated tax quarters are NOT three
    months each:

        Q1  Jan - Mar   (3 months)  due 15 April
        Q2  Apr - May   (2 MONTHS)  due 15 June
        Q3  Jun - Aug   (3 months)  due 15 September
        Q4  Sep - Dec   (4 MONTHS)  due 15 January

    She runs the distribution just before filing the quarterly estimate, so
    the two line up. Using calendar quarters would put the distribution in a
    different period from the tax it is being computed alongside.

WHAT IS ACTUALLY DEDUCTIBLE - THE PART THAT IS EASY TO GET WRONG
    1. A team bonus is deductible only when WITHDRAWN, not when allocated.
       The same jar rule as everywhere else: money sitting in a jar at the
       quarter end is still hers.
    2. HER OWN SHARE IS NOT DEDUCTIBLE AT ALL. A single-member LLC is a
       disregarded entity, so paying herself is an owner draw, not a cost.
    3. The operating buffer is taxable profit too - retained business cash
       is still hers. Roughly $141 of SE tax per $1,000 left behind.
    4. Q4 timing: the December distribution must be WITHDRAWN before 31
       December or the deduction lands in the following year.
"""

from taxlib import config

# month -> which US estimated tax quarter it belongs to
TAX_QUARTER_MONTHS = {
    1: ["Jan", "Feb", "Mar"],
    2: ["Apr", "May"],
    3: ["Jun", "Jul", "Aug"],
    4: ["Sep", "Oct", "Nov", "Dec"],
}

TAX_QUARTER_DUE = {1: "15 April", 2: "15 June",
                   3: "15 September", 4: "15 January (following year)"}


def quarter_of(month_number):
    """Which tax quarter a calendar month falls in."""
    for quarter, months in TAX_QUARTER_MONTHS.items():
        if config.MONTH_ABBR[month_number - 1] in months:
            return quarter
    raise ValueError(f"no quarter for month {month_number}")


def quarter_to_distribute(today):
    """
    Which quarter a distribution run on `today` is actually FOR.

    Not the quarter we are standing in - the one being filed. She runs this
    just before paying the quarterly estimate, and the estimate due on 15
    September covers June to August, not September.

    So it is the most recently COMPLETED tax quarter:

        12 Sep -> Q3 (Jun-Aug), filed 15 Sep        <- the common case
        5 Jan  -> Q4 (Sep-Dec), filed 15 Jan
        20 Apr -> Q1 (Jan-Mar)

    Returns (year, quarter), because in January the quarter being filed
    belongs to the PREVIOUS year.
    """
    starts = {1: (1, 1), 2: (4, 1), 3: (6, 1), 4: (9, 1)}
    for quarter in (4, 3, 2, 1):
        month, day = starts[quarter]
        if quarter == 4:
            # Q4 runs Sep-Dec, so it only completes at the year end.
            if today.month == 1 or (today.month == 12 and today.day == 31):
                return (today.year - 1 if today.month == 1 else today.year), 4
            continue
        end_month = {1: 3, 2: 5, 3: 8}[quarter]
        if today.month > end_month:
            return today.year, quarter
    return today.year - 1, 4


def compute_pool(*, balances_usd, jars_usd, buffer_usd=None):
    """
    What there is to share.

        pool = every Hostlyft balance, all currencies, converted to USD
             - every jar        (money already set aside for a person)
             - the buffer       (kept back to run on)

    The jars are inside the account total, so subtracting them leaves the
    operating money. Her own jar is subtracted too - she confirmed on
    2026-09-12 that money in her jar is already hers, exactly as the team's
    jars are already theirs.

    A jar is NOT deductible just for being allocated, so nothing here is an
    expense yet. This only says what is available to distribute.
    """
    buffer_usd = (config.DISTRIBUTION["operating_buffer_usd"]
                  if buffer_usd is None else buffer_usd)
    pool = balances_usd - jars_usd - buffer_usd
    return {
        "balances_usd": round(balances_usd, 2),
        "jars_usd": round(jars_usd, 2),
        "buffer_usd": round(buffer_usd, 2),
        "pool_usd": round(max(0.0, pool), 2),
        "negative": pool < 0,
    }


def earned_weights(earned_by_person):
    """
    How many dollars each person EARNED in the quarter - the weights for the
    80% share.

    WEIGHTED BY DOLLARS EARNED, NOT BY REVENUE DRIVEN. Her instruction, to
    match the method worked out in the "Accounting spreadsheet" chat. The two
    are not the same thing and give different answers, so it is worth being
    explicit about which this is.

    Take one $1,000 payment from a Katerina/Ayoka client:

        Liuba  5% off the top                        $   50
        K + A  70% of the remaining $950             $  665   ($332.50 each)
        retained business profit                     $  285

    Her 5% is a rate on revenue; the 80% share is divided on dollars earned.
    Measured in dollars she takes $50 where the pair take $665, so she lands
    near 7% of the combined earned pool rather than the 5% the rate might
    suggest. Those two numbers measure different things, and the gap between
    them is by design rather than an error.

    Each manager's weight is simply what the sheet already says they earned.
    Liuba's is the 5% off the top, which has to be recovered from gross
    client revenue - and THAT is where the one trap lives:

    KATERINA AND AYOKA SHARE ONE CLIENT GROUP. Inverting both their formulas
    recovers the SAME pot twice, so the group is recovered once and averaged.
    Adding them would put gross revenue near $34,250 against a true $18,952,
    and inflate her 5% to match.
    """
    ka_share = 0.95 * 0.70 * 0.50
    jane_share = 0.95 * 0.80

    katerina = earned_by_person.get(config.KATERINA, 0.0)
    ayoka = earned_by_person.get(config.AYOKA, 0.0)
    jane = earned_by_person.get(config.JANE, 0.0)

    derivations = [x / ka_share for x in (katerina, ayoka) if x]
    group_revenue = sum(derivations) / len(derivations) if derivations else 0.0
    jane_revenue = jane / jane_share if jane else 0.0
    gross = group_revenue + jane_revenue

    if not gross:
        return {}, 0.0

    weights = {
        config.FOUNDER: round(gross * config.DISTRIBUTION[
            "founder_off_the_top"], 2),
        config.KATERINA: round(katerina, 2),
        config.AYOKA: round(ayoka, 2),
        config.JANE: round(jane, 2),
    }
    return weights, round(gross, 2)


# The name it had while weights were revenue-driven rather than earned.
revenue_weights = earned_weights


def split(pool_usd, weights):
    """
    Divide the pool: a flat part shared equally, the rest by revenue driven.

    Her rule, given 2026-09-12, replacing the earlier 25% founder share:
        20% split EVENLY between the four of them
        80% in proportion to who drove the revenue, Marcus excluded
    Both percentages live in config.DISTRIBUTION so she can change them
    without touching code.
    """
    even_fraction = config.DISTRIBUTION["even_share"]
    people = list(config.DISTRIBUTION["participants"])

    even_pot = pool_usd * even_fraction
    proportional_pot = pool_usd - even_pot
    each_even = even_pot / len(people) if people else 0.0
    total_weight = sum(weights.get(p, 0.0) for p in people)

    rows = []
    for person in people:
        weight = weights.get(person, 0.0)
        proportional = (proportional_pot * weight / total_weight
                        if total_weight else 0.0)
        rows.append({
            "person": person,
            "even_usd": round(each_even, 2),
            "weight_usd": round(weight, 2),
            "weight_pct": round(100 * weight / total_weight, 2) if total_weight else 0.0,
            "proportional_usd": round(proportional, 2),
            "total_usd": round(each_even + proportional, 2),
            # THE WHOLE POINT OF THE STAGE. Her share is an owner draw from a
            # disregarded entity and reduces taxable profit by nothing. The
            # team's bonuses are real costs - but only once withdrawn.
            "deductible": person != config.FOUNDER,
            "deductible_when": ("not deductible - owner draw"
                                if person == config.FOUNDER
                                else "deductible WHEN WITHDRAWN, not now"),
        })
    return rows
