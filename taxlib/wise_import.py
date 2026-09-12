"""
wise_import.py - turning Wise transactions into income, expenses and jars.

Wise is the hardest source, because one account holds several different
kinds of thing that look alike:

    money arriving that IS income          a client paying you
    money arriving that is NOT income      a payout of income already
                                           counted from its invoice
    money moving that isn't money moving   a jar allocation, inside your
                                           own account
    money leaving that IS an expense       a card payment, a contractor
    money leaving that is NOT an expense   a credit-card repayment, or
                                           paying yourself

Getting any of those wrong changes the tax bill, and none of them raise an
error when they go wrong - the number is just quietly different. So this
module classifies every transaction explicitly and refuses to guess.

THE THREE ACCOUNTS
    Hostlyft LLC   read fully
    Shakti Lease   read fully; used for business until 5 June 2026, but it
                   also holds personal transactions, so nothing is
                   auto-classified as business
    Personal       INCOMING CREDITS ONLY, and only from senders known to be
                   business. Debits are dropped before they are read.

WHY A PAYOUT IS NOT INCOME
    A $2,000 invoice is income. When Stripe later sends $1,940 onward to
    Wise, that is the SAME money arriving - not new income. Counting both
    gives $3,940 and a tax bill on nearly double what was earned.

    The same is true of HubSpot and Upwork payouts, and of a client paying
    an invoice directly into the personal account.

    So every incoming payment is checked against income already recorded.
    An exact match on amount and currency within a few days is tagged as an
    internal transfer and excluded. A near-miss is flagged for review. An
    unmatched payment from an unknown sender is NEVER auto-added as income.

WHEN A PAYOUT *IS* THE ONLY RECORD
    Stripe and HubSpot have invoices behind them, so their payouts can be
    safely excluded. Upwork and Fiverr/Payoneer do not - not yet - so
    excluding those payouts would lose the income entirely.

    For those, the payout IS recorded as income, flagged to say it is NET of
    the platform's fee rather than gross. That is a known understatement,
    visible rather than silent, and it disappears once the Upwork export is
    imported.
"""

import datetime as dt

from taxlib import config, db


# ===========================================================================
#  WHO SENDS AND RECEIVES MONEY
# ===========================================================================

# Payment platforms. `has_invoice_source` says whether the income behind a
# payout is recorded somewhere else - which decides whether the payout can
# be excluded, or has to stand in as the income record itself.
PROCESSORS = [
    {"match": ["STRIPE", "Stripe Payments"], "name": "Stripe",
     "has_invoice_source": True},
    {"match": ["HUBSPOT PAYMENTS"], "name": "HubSpot",
     "has_invoice_source": True},
    # Upwork earnings are imported from its export, so a payout is the
    # arrival of income already counted. But a payout is a BATCH of several
    # earnings, so it never equals any single one - amount matching cannot
    # find it. Instead, check whether earnings from that platform exist at
    # all in the period.
    {"match": ["PAYMENT ESCROW"], "name": "Upwork",
     "has_invoice_source": True, "income_source": "upwork",
     "batched": True},
    {"match": ["PAYONEER"], "name": "Fiverr via Payoneer",
     "has_invoice_source": False},
]

# Liuba herself. Money from her own account is never income: either it is a
# client payment she forwarded (already counted from its invoice) or it is
# her own capital.
OWNER_NAMES = ["Liubov Kapitulskaya", "Liuba", "Kapitulskaya"]

# Her own businesses, moving money between each other.
OWN_BUSINESSES = ["Hostlyft LLC", "Shakti Lease", "Shakti Homes"]

# Clients who pay by bank transfer, and which business the work belongs to.
# Names come from Stripe customers and HubSpot companies - see clients.py.
CLIENT_SENDERS = {
    "Monichkirchnerhof": ("Alexandr Jaitner", config.BUSINESS_HOSTLYFT),
    "Mönichkirchnerhof": ("Alexandr Jaitner", config.BUSINESS_HOSTLYFT),
    "CLOUD9": ("Marcus Halawi", config.BUSINESS_MARCUS),
    "Cloud 9": ("Marcus Halawi", config.BUSINESS_MARCUS),
    "SETTLER VACATION": ("Timur Khabirov", config.BUSINESS_HOSTLYFT),
    "Settler Homes": ("Timur Khabirov", config.BUSINESS_HOSTLYFT),
    "BINETH": ("Chananya Bineth", config.BUSINESS_HOSTLYFT),
    "OOMPH": ("Tomasz Jagiello", config.BUSINESS_HOSTLYFT),
    "UNIQUE STAYS": ("Tyler Willey", config.BUSINESS_HOSTLYFT),
    "Airvevo": ("Shawn Ye", config.BUSINESS_HOSTLYFT),
}

# Paying your own credit card is moving money between your own accounts. The
# actual expenses come from the card statement (Stage 7); counting the
# repayment as well would double them.
CARD_REPAYMENTS = ["CAPITAL ONE", "CAPITALONE"]

# How close in time a bank credit has to be to the income it settles.
#
# 45 days, not 10. Several HubSpot invoices carry a payment date of
# 2026-02-01 - a batch marked paid in one go, weeks after the money actually
# arrived. A 10-day window missed all of them, so Monichkirchnerhof's
# EUR 1,195, Settler's $1,326 and Unique Stays' $300 were each counted twice:
# once from the invoice, once from the bank credit that paid it.
MATCH_WINDOW_DAYS = 45


# Categories in rules.txt that may be read from the PERSONAL account.
#
# This is a whitelist, and it is deliberately short. Everything not named
# here is discarded before it is stored, printed or logged - which is what
# keeps ordinary personal spending out of the database entirely.
#
# TRAVEL AND MEALS WERE ADDED ON 6 SEPTEMBER 2026, AT HER EXPLICIT REQUEST.
# They were excluded before, on the reasoning that a flight or a restaurant
# on a personal card is more likely to be personal than business. She has
# said that all travel and all restaurant charges on both accounts are
# business, so they are now read.
#
# That instruction decides what gets READ. It cannot decide what is
# DEDUCTIBLE, because two of the tests are things no bank row can answer:
#   - travel is deductible only when away from her tax home (France);
#     commuting never is, and a mixed trip counts only for the business part
#   - a meal needs a business purpose and the people present recorded, and
#     is 50% deductible at most
# So every row from here lands with needs_review set, and is confirmed one
# at a time rather than by a blanket rule.
PERSONAL_ALLOWED_CATEGORIES = {
    "software", "phone and internet", "compliance and admin",
    "professional services", "advertising", "payment processing",
    "travel", "meals",
}

# The subset that cannot be taken at face value even once it is read, and
# why - shown to her on each row rather than assumed to be remembered.
PERSONAL_NEEDS_CONFIRMING = {
    "travel": ("deductible only if this trip was away from your tax home "
               "in France on business - commuting and the personal part of "
               "a mixed trip do not count"),
    "meals": ("a business meal needs the business purpose and who was "
              "present; only 50% is deductible, and a meal on your own "
              "near home is personal"),
}


# WHO THE IRS LOOKS LIKE ON A BANK STATEMENT.
#
# A THIRD NARROW EXTENSION TO THE PERSONAL ACCOUNT, at her request on
# 2026-09-12: she wants to see whether the quarterly estimate has actually
# been paid, and she pays it from the personal account.
#
# Only payments to the US tax authorities are kept. Everything else in that
# account is still discarded unread, exactly as before.
#
# "IRS" is matched as a WHOLE WORD. As a substring it hits "Airside", which
# is what a Costa Coffee at an airport is called - found on the first run of
# this search. The same trap as "Uber" matching "Uber Eats".
TAX_AUTHORITY_PATTERNS = (
    r"\birs\b", r"internal revenue", r"united states treasury",
    r"\bus treasury\b", r"usataxpymt", r"eftps", r"\birs\s*usa\b",
)


def looks_like_tax_payment(description):
    """Is this outgoing money a payment of US tax?"""
    import re
    text = (description or "").lower()
    return any(re.search(pattern, text) for pattern in TAX_AUTHORITY_PATTERNS)


def _business_subscription(description):
    """(category, matched word) if this is a recognised business vendor."""
    from taxlib import categorize

    category, word = categorize.categorize(
        description, vendor=categorize.merchant_from_card(description))
    if category in PERSONAL_ALLOWED_CATEGORIES:
        return category, word
    return None, None


def _refund_of_claimed_spending(connection, *, description, amount, currency):
    """
    Is this incoming money a refund of spending already in the database?

    Returns {"vendor", "category"} when the sender matches a merchant this
    database already holds PERSONAL-account spending for, else None.

    Why it is scoped that narrowly: her instruction is that ordinary
    personal income must never be read. A refund from a merchant whose
    charge is already being deducted is not ordinary personal income - it
    is the reversal of a number already on her return. Anything else is
    still dropped unread.
    """
    from taxlib import categorize

    candidates = [c for c in (categorize.merchant_from_card(description),
                              sender_of(description)) if c]
    if not candidates:
        return None

    # A MERCHANT, NEVER A PERSON.
    #
    # Contractors are sometimes paid from the personal account, so Olaide,
    # Katerina and Yetunde all appear as vendors on personal rows. Without
    # this guard, money arriving from her HUSBAND read as a merchant refund
    # - a EUR 3,689 transfer on 2026-06-03 among them. That is household
    # money between spouses, which her rule says is never read, and calling
    # it a refund would both breach that and silently alter a deduction.
    #
    # Returned contractor payments are a real thing, but they are a question
    # for the contractor ledger and for her, not something to infer from the
    # direction of a transfer.
    for candidate in candidates:
        try:
            if config.match_contractor(candidate):
                return None
        except config.AmbiguousContractor:
            return None

    rows = connection.execute(
        "SELECT DISTINCT vendor, category FROM expenses "
        "WHERE source_id LIKE 'personal:%' AND vendor IS NOT NULL "
        "AND vendor != '' AND amount > 0 "
        "AND category NOT IN ('contractor', 'bank fees')").fetchall()

    for candidate in candidates:
        flat = categorize._match_text(candidate)
        if len(flat) < 4:
            continue
        for row in rows:
            vendor = categorize._match_text(row["vendor"])
            if len(vendor) < 4:
                continue
            if vendor in flat or flat in vendor:
                return {"vendor": row["vendor"], "category": row["category"]}
    return None


def _contains(text, needles):
    low = (text or "").lower()
    return any(n.lower() in low for n in needles)


def sender_of(description):
    """Pull the counterparty out of a Wise description."""
    import re
    text = description or ""
    for pattern in (r"Received money from (.+?) with reference",
                    r"Received money from (.+)",
                    r"Sent money to (.+)",
                    r"Paid to (.+)"):
        found = re.search(pattern, text, re.IGNORECASE)
        if found:
            return found.group(1).strip()
    return text.strip()


def jar_name_of(description):
    """"Moved 1,172.00 USD to Ayoka" -> "Ayoka"."""
    import re
    found = re.search(r"Moved [\d,.]+ [A-Z]{3} (?:to|from) (.+)", description or "")
    return found.group(1).strip() if found else None


# ===========================================================================
#  HAS THIS MONEY ALREADY BEEN COUNTED?
# ===========================================================================

def find_already_counted(connection, amount, currency, date,
                         window=MATCH_WINDOW_DAYS, ignore_source_id=None):
    """
    Look for income already recorded that this payment is the arrival of.

    Matches on exact amount and currency within a few days. Returns
    (row, how) - or (None, None) if nothing is close.

    Also checks stripe_payouts, because a Stripe payout is the NET of an
    invoice and so never equals the invoice amount.

    `ignore_source_id` MUST be the row being classified.

    Without it, the second run of the importer finds the row the FIRST run
    created, concludes the money was already counted, and excludes it. The
    totals then quietly collapse to the Stripe-only figure - no error, just
    a smaller number every time you re-run. Found exactly that way.
    """
    day = dt.date.fromisoformat(date)
    low = (day - dt.timedelta(days=window)).isoformat()
    high = (day + dt.timedelta(days=window)).isoformat()
    amount = db.round_money(amount)

    payout = connection.execute(
        "SELECT * FROM stripe_payouts WHERE currency = ? AND amount = ? "
        "AND arrival_date BETWEEN ? AND ?",
        (currency.upper(), amount, low, high)).fetchone()
    if payout:
        return payout, "stripe_payout"

    candidates = connection.execute(
        "SELECT * FROM income WHERE currency = ? AND amount = ? "
        "AND excluded = 0 AND date BETWEEN ? AND ? "
        "AND (source_id IS NULL OR source_id != ?) "
        "AND source != 'wise'",
        (currency.upper(), amount, low, high,
         ignore_source_id or "")).fetchall()

    if not candidates:
        return None, None

    # With a window this wide a recurring client can have two invoices of the
    # same amount in range. Take the nearest in time - but say so, because
    # picking between two identical figures is a guess even when it is the
    # best one available.
    if len(candidates) == 1:
        return candidates[0], "invoice"

    nearest = min(candidates,
                  key=lambda row: abs((dt.date.fromisoformat(row["date"])
                                       - day).days))
    return nearest, "invoice (one of several the same size)"


# A credit within this much of an invoice is probably the same money, minus
# a wire fee - but "probably" is not good enough to exclude income on.
NEAR_MISS_TOLERANCE = 0.03


def find_near_miss(connection, amount, currency, date,
                   window=MATCH_WINDOW_DAYS, ignore_source_id=None):
    """
    An invoice that is CLOSE to this credit but not equal to it.

    A client wires an invoice and their bank takes a fee, so $1,689.25
    invoiced arrives as $1,683.14. Excluding it would silently drop real
    income; counting it doubles the invoice. Neither can be chosen safely
    from the numbers alone.

    So this finds the candidate and the caller flags it for a human. Counted,
    but visibly uncertain - which is the honest position.
    """
    day = dt.date.fromisoformat(date)
    low = (day - dt.timedelta(days=window)).isoformat()
    high = (day + dt.timedelta(days=window)).isoformat()
    span = amount * NEAR_MISS_TOLERANCE

    return connection.execute(
        "SELECT * FROM income WHERE currency = ? AND excluded = 0 "
        "AND amount BETWEEN ? AND ? AND amount != ? "
        "AND date BETWEEN ? AND ? "
        "AND (source_id IS NULL OR source_id != ?) AND source != 'wise' "
        "ORDER BY ABS(amount - ?) LIMIT 1",
        (currency.upper(), amount - span, amount + span, db.round_money(amount),
         low, high, ignore_source_id or "", amount)).fetchone()


# ===========================================================================
#  CLASSIFYING ONE TRANSACTION
# ===========================================================================

def has_income_from(connection, source, on_or_before, window_days=120):
    """
    Is there income recorded from this platform, covering this payout?

    Needed because a platform payout is a BATCH - Upwork withdraws several
    earnings at once, so the payout equals no single earning and amount
    matching can never find it. What CAN be established is whether the
    earnings behind it were imported at all.
    """
    day = dt.date.fromisoformat(on_or_before)
    since = (day - dt.timedelta(days=window_days)).isoformat()
    row = connection.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(amount_usd), 0) AS total "
        "FROM income WHERE source = ? AND excluded = 0 "
        "AND date BETWEEN ? AND ?",
        (source, since, on_or_before)).fetchone()
    return row["n"] > 0, row["total"]


def classify_credit(connection, *, description, details_type, amount,
                    currency, date, profile, source_id=None):
    """
    Decide what an incoming payment is. Returns a dictionary describing the
    decision, always including `kind` and `reason`.
    """
    sender = sender_of(description)

    if details_type == "CONVERSION":
        return {"kind": "jar_move", "reason": "moved between own balances",
                "jar": jar_name_of(description)}

    if details_type == "MONEY_ADDED":
        return {"kind": "not_income",
                "reason": "account top-up - your own money, not earnings"}

    if _contains(sender, OWNER_NAMES):
        return {"kind": "not_income", "needs_review": True,
                "reason": ("transfer from your own personal account. Either a "
                           "client payment you forwarded - already counted "
                           "from its invoice - or your own capital. Confirm "
                           "no invoice is missing.")}

    if _contains(sender, OWN_BUSINESSES):
        return {"kind": "not_income",
                "reason": "transfer between your own business accounts"}

    for processor in PROCESSORS:
        if not _contains(sender, processor["match"]):
            continue
        if processor.get("batched"):
            found, total = has_income_from(connection,
                                           processor["income_source"], date)
            if found:
                return {"kind": "not_income", "processor": processor["name"],
                        "matched": "batched earnings",
                        "reason": (f"{processor['name']} payout. The earnings "
                                   f"behind it are already counted from the "
                                   f"{processor['name']} export "
                                   f"(${total:,.2f} in the period), and a "
                                   f"payout batches several earnings so it "
                                   f"matches no single one.")}
            return {"kind": "income", "needs_review": True,
                    "processor": processor["name"],
                    "business": config.BUSINESS_HOSTLYFT,
                    "reason": (f"{processor['name']} payout, and no "
                               f"{processor['name']} earnings are imported "
                               f"for this period. Counted so the income is "
                               f"not lost - but it is NET of their fee.")}

        matched, how = find_already_counted(connection, amount, currency, date,
                                            ignore_source_id=source_id)
        if matched:
            return {"kind": "not_income", "processor": processor["name"],
                    "matched": how,
                    "reason": (f"{processor['name']} payout of income already "
                               f"counted from its {how.replace('_', ' ')}")}
        if processor["has_invoice_source"]:
            return {"kind": "not_income", "needs_review": True,
                    "processor": processor["name"],
                    "reason": (f"{processor['name']} payout with no matching "
                               f"invoice found. Excluded to avoid double "
                               f"counting - check the invoice was imported.")}
        return {"kind": "income", "needs_review": True,
                "processor": processor["name"],
                "business": config.BUSINESS_HOSTLYFT,
                "reason": (f"{processor['name']} payout. Counted as income "
                           f"because no invoice source exists yet - but this "
                           f"is NET of their fee, so gross is understated "
                           f"and the fee deduction is missing.")}

    for pattern, (client, business) in CLIENT_SENDERS.items():
        if _contains(sender, [pattern]):
            matched, how = find_already_counted(connection, amount, currency,
                                                date, ignore_source_id=source_id)
            if matched:
                return {"kind": "not_income", "client": client,
                        "matched": how,
                        "reason": (f"{client} paying an invoice already "
                                   f"counted - direct payment, not new income")}
            near = find_near_miss(connection, amount, currency, date,
                                  ignore_source_id=source_id)
            if near is not None:
                difference = abs(db.round_money(near["amount"]) - amount)
                return {
                    "kind": "income", "client": client, "business": business,
                    "needs_review": True,
                    "reason": (f"payment from {client}, counted as income - "
                               f"but it is within {difference:,.2f} "
                               f"{currency} of an invoice already counted "
                               f"({near['amount']:,.2f} on {near['date']}). "
                               f"If it is the same money arriving after a "
                               f"wire fee, this is a duplicate; if it is a "
                               f"separate payment, it is correct. Not "
                               f"guessed either way."),
                }
            return {"kind": "income", "client": client, "business": business,
                    "reason": f"payment from {client}"}

    return {"kind": "unknown", "needs_review": True,
            "reason": (f"unrecognised sender '{sender[:40]}'. Not counted as "
                       f"income - tell Claude what it is and it will be "
                       f"classified from then on.")}


def classify_debit(*, description, details_type, amount, currency, date):
    """Decide what an outgoing payment is."""
    recipient = sender_of(description)

    if details_type == "CONVERSION":
        return {"kind": "jar_move", "reason": "moved between own balances",
                "jar": jar_name_of(description)}

    if details_type == "PAYOUT" or _contains(description, ["STRIPE PAYOUT"]):
        return {"kind": "not_expense", "reason": "payout to your own bank"}

    if _contains(recipient, CARD_REPAYMENTS):
        return {"kind": "not_expense",
                "reason": ("credit-card repayment - moving your own money. "
                           "The actual expenses come from the card "
                           "statement; counting this too would double them.")}

    if _contains(recipient, OWNER_NAMES + OWN_BUSINESSES):
        return {"kind": "owner_draw",
                "reason": ("paying yourself. Not a business expense and it "
                           "does not reduce taxable profit.")}

    try:
        person = config.match_contractor(recipient)
    except config.AmbiguousContractor as clash:
        return {"kind": "expense", "category": "contractor",
                "needs_review": True,
                "reason": str(clash)}
    if person:
        return {"kind": "expense", "category": db.CATEGORY_CONTRACTOR,
                "vendor": person["name"], "person": person,
                "reason": f"withdrawal to {person['name']}"}

    if details_type == "CARD":
        return {"kind": "expense", "category": "uncategorized",
                "vendor": recipient,
                "reason": "card payment - business expense"}

    if details_type in ("UNKNOWN", "FEE"):
        return {"kind": "expense", "category": "bank fees", "vendor": "Wise",
                "reason": description or "Wise fee"}

    return {"kind": "expense", "category": "uncategorized",
            "vendor": recipient, "needs_review": True,
            "reason": f"payment to '{recipient[:40]}' - needs a category"}


# ===========================================================================
#  TALKING TO WISE
# ===========================================================================

API = "https://api.transferwise.com"


class WiseError(Exception):
    """Wise refused a request, with a plain-English explanation."""


def _headers(token):
    return {"Authorization": f"Bearer {token}", "User-Agent": "hostlyft-tax"}


def fetch_profiles(token):
    """Every profile on this login - personal and business."""
    import requests
    response = requests.get(f"{API}/v2/profiles", headers=_headers(token),
                            timeout=30)
    if response.status_code == 401:
        raise WiseError(
            "Wise rejected the API token (401).\n"
            "It has expired or been deleted. Make a new read-only token at\n"
            "wise.com -> Settings -> API tokens, and put it in tax/.env")
    if not response.ok:
        raise WiseError(f"Wise replied {response.status_code} listing profiles")
    return response.json()


def fetch_balances(token, profile_id, kinds=("STANDARD", "SAVINGS")):
    """
    Every balance on a profile.

    STANDARD is operating money. SAVINGS are the jars - each one comes back
    with the name you gave it in Wise, which is how they get matched to
    people.
    """
    import requests
    balances = []
    for kind in kinds:
        response = requests.get(f"{API}/v4/profiles/{profile_id}/balances",
                                headers=_headers(token),
                                params={"types": kind}, timeout=30)
        if not response.ok:
            continue
        for balance in response.json():
            balance["_kind"] = kind
            balances.append(balance)
    return balances


def fetch_statement(token, profile_id, balance_id, currency, start, end,
                    private_key_path=None):
    """
    One balance's transactions between two dates.

    HANDLES THE SCA CHALLENGE. Wise protects statements under European
    banking rules: the first request comes back 403 with a one-time code in
    the `x-2fa-approval` header. That code is signed with the private key and
    the request is retried with the signature attached.

    The challenge only appears every 90 days or so - viewing a statement in
    the Wise app resets the clock - so most runs never see it. That is
    exactly why it must be handled: the day it appears, an unprepared sync
    simply starts failing.
    """
    import requests
    from taxlib import wise_sca

    url = (f"{API}/v1/profiles/{profile_id}/balance-statements/"
           f"{balance_id}/statement.json")
    params = {"currency": currency, "type": "COMPACT",
              "intervalStart": f"{start}T00:00:00.000Z",
              "intervalEnd": f"{end}T23:59:59.999Z"}

    response = requests.get(url, headers=_headers(token), params=params,
                            timeout=60)

    if response.status_code == 403 and response.headers.get("x-2fa-approval"):
        one_time_code = response.headers["x-2fa-approval"]
        key_path = private_key_path or (config.DATA_DIR / "wise_private_key.pem")
        try:
            private_key = wise_sca.load_private_key(key_path)
            signature = wise_sca.sign_token(private_key, one_time_code)
        except wise_sca.WiseSigningError as error:
            raise WiseError(
                f"Wise asked for a signature and it could not be produced.\n"
                f"{error}\n"
                f"The public half must also be uploaded at\n"
                f"wise.com -> Settings -> API tokens -> Manage public keys")

        signed = dict(_headers(token))
        signed["x-2fa-approval"] = one_time_code
        signed["X-Signature"] = signature
        response = requests.get(url, headers=signed, params=params, timeout=60)

        if response.status_code == 403:
            raise WiseError(
                "Wise rejected the signature.\n"
                "Usually this means the public key in your Wise settings does "
                "not match the private key on this Mac.\n"
                "Check with:  python scripts/wise_keys.py --check\n"
                "then re-upload tax/wise_public_key.pem to Wise.")

    if not response.ok:
        raise WiseError(f"Wise replied {response.status_code} for the "
                        f"{currency} statement: {response.text[:160]}")

    return response.json().get("transactions", [])


# ===========================================================================
#  BUILDING THE ROWS
# ===========================================================================

def build_records(connection, transactions, *, profile_label, business,
                  personal=False, balance_kind="STANDARD", jar_name=None):
    """
    Turn one balance's transactions into rows for the database.

    `personal=True` applies the narrow rule for the personal account:
    outgoing payments are dropped without being examined, and only incoming
    money from senders known to be business is kept.

    `balance_kind` decides whether jar movements are recorded here.

    EVERY JAR MOVEMENT APPEARS TWICE - once on the operating balance and once
    on the jar itself - and the two describe it differently:

        from the operating balance   "Moved 1,172.00 USD to Ayoka"
        from Ayoka's jar             "Moved 1,172.00 USD to USD"

    Only the first names the jar. So movements are recorded from STANDARD
    balances only. Reading both would double every allocation and label half
    of them with a currency code.
    """
    income, expenses, jars, notes = [], [], [], []
    tax_payments = []
    skipped_personal = 0

    for txn in transactions:
        amount = txn.get("amount", {}).get("value")
        currency = (txn.get("amount", {}).get("currency") or "").upper()
        date = (txn.get("date") or "")[:10]
        details = txn.get("details") or {}
        details_type = details.get("type")
        description = details.get("description") or ""
        reference = txn.get("referenceNumber") or txn.get("id") or ""
        source_id = f"{profile_label}:{reference}"

        # Wise takes a fee out of an INCOMING transfer, so what is credited
        # is less than what the client sent. The client sent the invoice
        # amount; Wise kept a cut of it.
        #
        # Recording the credited figure would understate income AND lose the
        # fee, which is deductible - the same netting trap as Stripe and
        # Upwork. It also breaks matching: $1,689.25 invoiced shows up as
        # $1,683.14 and looks like a different payment.
        incoming_fee = 0.0
        if txn.get("type") == "CREDIT":
            incoming_fee = abs((txn.get("totalFees") or {}).get("value") or 0)
            if incoming_fee:
                amount = abs(amount) + incoming_fee

        if txn.get("type") == "CREDIT":
            decision = classify_credit(
                connection, description=description, details_type=details_type,
                amount=abs(amount), currency=currency, date=date,
                profile=profile_label, source_id=source_id)

            if personal and decision["kind"] in ("unknown", "jar_move"):
                # A REFUND OF SOMETHING ALREADY BEING CLAIMED IS NOT
                # PERSONAL LIFE, AND MUST NOT BE DROPPED HERE.
                #
                # Opening the personal account let travel and meals be READ,
                # but only money going OUT. Money coming back in still fell
                # through this filter, because a refund's sender matches no
                # client. So the charge was deducted and the refund was
                # invisible - and travel and meals are precisely the two
                # categories that get cancelled and refunded.
                #
                # Three were found by hand on 2026-09-12: an Airbnb booking,
                # a cancelled Blablacar seat, and AirHelp compensation on a
                # delayed business flight. Each one overstated a deduction.
                #
                # The test stays inside her privacy rule: a credit is kept
                # ONLY when it comes from a merchant this database already
                # has personal-account spending for. An unrelated credit is
                # still dropped unread.
                refund = _refund_of_claimed_spending(
                    connection, description=description, amount=abs(amount),
                    currency=currency)
                if refund:
                    expenses.append({
                        # ":refund" MATTERS - IT IS NOT DECORATION.
                        #
                        # Wise reverses a card transaction under the SAME
                        # referenceNumber as the original:
                        #   2026-08-16 CREDIT  25.50 EUR CARD-4200064313
                        #   2026-08-16 DEBIT  -25.50 EUR CARD-4200064313
                        # Rows are keyed on "profile:reference", so without
                        # a suffix the refund and the charge are the same
                        # key and one silently overwrites the other. Six of
                        # seven refunds were lost that way on the first run.
                        "source": "wise",
                        "source_id": f"{source_id}:refund",
                        "date": date, "amount": -abs(amount),
                        "currency": currency, "business": business,
                        "amount_usd": (-abs(amount) if currency == "USD"
                                       else None),
                        "category": refund["category"],
                        "vendor": refund["vendor"],
                        "description": (f"Refund from {refund['vendor']} - "
                                        f"reduces the deduction"),
                        "needs_review": True,
                        "review_note": (
                            f"money back from {refund['vendor']}, who you "
                            f"have {refund['category']} charges with. Netted "
                            f"off so the deduction is what you actually bore. "
                            f"Confirm it refunds a charge being claimed and "
                            f"is not unrelated personal money."),
                    })
                    continue
                # Personal life. Dropped without being recorded anywhere.
                skipped_personal += 1
                continue

            if decision["kind"] == "jar_move":
                if balance_kind != "STANDARD":
                    continue      # the same movement, seen from the jar side
                jars.append({
                    "source_id": source_id, "date": date,
                    "jar_name": decision.get("jar") or "(unnamed)",
                    "direction": "out",     # money coming BACK out of the jar
                    "amount": abs(amount), "currency": currency,
                    "amount_usd": abs(amount) if currency == "USD" else None,
                    "description": description[:200],
                })
                continue

            if decision["kind"] == "income":
                income.append({
                    "source": "wise", "source_id": source_id, "date": date,
                    "amount": abs(amount), "currency": currency,
                    "business": decision.get("business", business),
                    "amount_usd": abs(amount) if currency == "USD" else None,
                    "description": description[:200],
                    "payer": decision.get("client") or sender_of(description),
                    "needs_review": bool(decision.get("needs_review")),
                    "review_note": decision["reason"] if decision.get("needs_review") else None,
                })
                if incoming_fee:
                    expenses.append({
                        "source": "wise", "source_id": f"{source_id}:infee",
                        "date": date, "amount": incoming_fee,
                        "currency": currency, "business": business,
                        "amount_usd": (incoming_fee if currency == "USD"
                                       else None),
                        "category": "bank fees", "vendor": "Wise",
                        "description": "Wise fee on an incoming transfer",
                    })
            else:
                # Recorded but excluded, so the decision stays auditable
                # instead of the transaction silently vanishing.
                income.append({
                    "source": "wise", "source_id": source_id, "date": date,
                    "amount": abs(amount), "currency": currency,
                    "business": business,
                    "amount_usd": abs(amount) if currency == "USD" else None,
                    "description": description[:200],
                    "payer": sender_of(description),
                    "excluded": True, "exclusion_reason": decision["reason"],
                    "needs_review": bool(decision.get("needs_review")),
                    "review_note": decision["reason"] if decision.get("needs_review") else None,
                })
            continue

        # ---- outgoing ----
        if personal and looks_like_tax_payment(description):
            # Recorded, but NEVER as an expense. Federal income tax and
            # self-employment tax are her personal liabilities, not costs of
            # the business - and a disregarded entity makes it irrelevant
            # which account pays. An expense row here would reduce the very
            # profit the tax is computed on.
            tax_payments.append({
                "paid_on": date, "amount": abs(amount), "currency": currency,
                "amount_usd": abs(amount) if currency == "USD" else None,
                "source_id": source_id, "detected": "wise",
                "note": description[:200],
            })
            continue

        if personal:
            # NARROW EXTENSION, authorised explicitly: contractors are
            # sometimes paid from the personal account, and those are real
            # deductible business costs that are otherwise invisible.
            #
            # Only payments to somebody ON THE ROSTER are kept. Everything
            # else - which is all ordinary personal spending - is discarded
            # here, before it is stored, printed or logged. The test is a
            # whitelist of named people, not a filter on categories, so
            # nothing unrelated can slip through.
            recipient = sender_of(description)
            try:
                person = config.match_contractor(recipient)
            except config.AmbiguousContractor as clash:
                person, ambiguous = None, str(clash)
            else:
                ambiguous = None

            if person is None and ambiguous is None:
                # Second whitelist: business subscriptions paid from the
                # personal card, which happened before the Hostlyft account
                # existed. Only vendors named in rules.txt under an
                # unambiguously business category count - travel and taxes
                # are deliberately left out, being too easily personal.
                category, matched_word = _business_subscription(description)
                if not category:
                    skipped_personal += 1
                    continue
                from taxlib import categorize as _cat
                expenses.append({
                    "source": "wise", "source_id": source_id, "date": date,
                    "amount": abs(amount), "currency": currency,
                    "business": business,
                    "amount_usd": abs(amount) if currency == "USD" else None,
                    "category": category,
                    "vendor": _cat.tidy_vendor(None, description, matched_word),
                    "description": description[:200],
                    "needs_review": True,
                    "review_note": (
                        f"personal account, matched on '{matched_word}' - "
                        f"{PERSONAL_NEEDS_CONFIRMING[category]}"
                        if category in PERSONAL_NEEDS_CONFIRMING else
                        f"business subscription paid from the personal "
                        f"card, matched on '{matched_word}' - confirm it "
                        f"was for Hostlyft and not personal use"),
                })
                continue

            expenses.append({
                "source": "wise", "source_id": source_id, "date": date,
                "amount": abs(amount), "currency": currency,
                "business": business,
                "amount_usd": abs(amount) if currency == "USD" else None,
                "category": db.CATEGORY_CONTRACTOR,
                "vendor": person["name"] if person else recipient,
                "description": description[:200],
                "needs_review": bool(ambiguous),
                "review_note": (ambiguous or
                                f"paid from the personal account, not the "
                                f"business one - confirm it was for Hostlyft "
                                f"work"),
            })
            fee = (txn.get("totalFees") or {}).get("value") or 0
            if fee:
                expenses.append({
                    "source": "wise", "source_id": f"{source_id}:fee",
                    "date": date, "amount": abs(fee), "currency": currency,
                    "business": business,
                    "amount_usd": abs(fee) if currency == "USD" else None,
                    "category": "bank fees", "vendor": "Wise",
                    "description": "Wise transfer fee",
                })
            continue

        # MONEY SENT STRAIGHT OUT OF A JAR IS THAT PERSON'S PAYOUT.
        #
        # Her rule, given 2026-09-12, and it needs no guessing: a transfer
        # made from a jar appears in THAT JAR'S OWN statement. Jane's jar
        # shows
        #     2026-09-10 DEBIT -505.06 TRANSFER-...  Sent money to Snitserev
        # so the payee's name never has to be recognised at all. Vadim
        # Snitserev had never been seen before and landed as "uncategorized"
        # - a lost deduction AND $505.06 missing from Jane's withdrawals,
        # which is what the $600 threshold and the reconciliation gap are
        # measured on.
        #
        # Matching on the recipient's name can only ever catch people
        # somebody already added by hand. The jar knows who it belongs to.
        jar_person = (config.match_contractor(jar_name, strict=False)
                      if balance_kind == "SAVINGS" and jar_name else None)
        if jar_person and abs(amount) and (txn.get("type") == "DEBIT"):
            probe = classify_debit(
                description=description, details_type=details_type,
                amount=abs(amount), currency=currency, date=date)
            if probe["kind"] != "jar_move":
                expenses.append({
                    "source": "wise", "source_id": source_id, "date": date,
                    "amount": abs(amount), "currency": currency,
                    "business": business,
                    "amount_usd": abs(amount) if currency == "USD" else None,
                    "category": db.CATEGORY_CONTRACTOR,
                    "vendor": jar_person["name"],
                    "description": description[:200],
                    "review_note": (
                        f"paid straight out of the '{jar_name}' jar, so it is "
                        f"{jar_person['name']}'s payout whoever the transfer "
                        f"names. Deductible now - it has actually left - and "
                        f"it counts toward her withdrawals."),
                })
                fee = (txn.get("totalFees") or {}).get("value") or 0
                if fee:
                    expenses.append({
                        "source": "wise", "source_id": f"{source_id}:fee",
                        "date": date, "amount": abs(fee), "currency": currency,
                        "business": business,
                        "amount_usd": abs(fee) if currency == "USD" else None,
                        "category": "bank fees", "vendor": "Wise",
                        "description": "Wise transfer fee",
                    })
                continue

        decision = classify_debit(
            description=description, details_type=details_type,
            amount=abs(amount), currency=currency, date=date)

        if decision["kind"] == "jar_move":
            if balance_kind != "STANDARD":
                continue          # the same movement, seen from the jar side
            jars.append({
                "source_id": source_id, "date": date,
                "jar_name": decision.get("jar") or "(unnamed)",
                "direction": "in",          # money set aside INTO the jar
                "amount": abs(amount), "currency": currency,
                "amount_usd": abs(amount) if currency == "USD" else None,
                "description": description[:200],
            })
            continue
        if decision["kind"] == "not_expense":
            expenses.append({
                "source": "wise", "source_id": source_id, "date": date,
                "amount": abs(amount), "currency": currency,
                "business": business,
                "amount_usd": abs(amount) if currency == "USD" else None,
                "category": "internal transfer", "vendor": sender_of(description),
                "description": description[:200],
                "excluded": True, "exclusion_reason": decision["reason"],
            })
            continue
        if decision["kind"] == "owner_draw":
            expenses.append({
                "source": "wise", "source_id": source_id, "date": date,
                "amount": abs(amount), "currency": currency,
                "business": business,
                "amount_usd": abs(amount) if currency == "USD" else None,
                "category": "owner draw", "vendor": "Liuba",
                "description": description[:200],
                "excluded": True, "exclusion_reason": decision["reason"],
            })
            continue

        expenses.append({
            "source": "wise", "source_id": source_id, "date": date,
            "amount": abs(amount), "currency": currency,
            "business": business,
            "amount_usd": abs(amount) if currency == "USD" else None,
            "category": decision.get("category", "uncategorized"),
            "vendor": decision.get("vendor") or sender_of(description),
            "description": description[:200],
            "needs_review": bool(decision.get("needs_review")),
            "review_note": decision["reason"] if decision.get("needs_review") else None,
        })

        # a per-transaction Wise fee is a separate deductible cost
        fee = (txn.get("totalFees") or {}).get("value") or 0
        if fee:
            expenses.append({
                "source": "wise", "source_id": f"{source_id}:fee", "date": date,
                "amount": abs(fee), "currency": currency, "business": business,
                "amount_usd": abs(fee) if currency == "USD" else None,
                "category": "bank fees", "vendor": "Wise",
                "description": "Wise transfer fee",
            })

    if skipped_personal:
        notes.append(f"{skipped_personal} personal transactions in "
                     f"{profile_label} were skipped without being stored")

    # attach a person to each jar movement where the name is recognised
    for movement in jars:
        person = config.match_contractor(movement["jar_name"], strict=False)
        movement["person"] = person["name"] if person else None

    return {"income": income, "expenses": expenses, "jars": jars,
            "notes": notes, "tax_payments": tax_payments}
