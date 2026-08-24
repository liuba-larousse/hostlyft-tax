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
    {"match": ["PAYMENT ESCROW"], "name": "Upwork",
     "has_invoice_source": False},
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

# How close in time a payout has to be to the income it came from.
MATCH_WINDOW_DAYS = 10


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
                         window=MATCH_WINDOW_DAYS):
    """
    Look for income already recorded that this payment is the arrival of.

    Matches on exact amount and currency within a few days. Returns
    (row, exact) - or (None, False) if nothing is close.

    Also checks stripe_payouts, because a Stripe payout is the NET of an
    invoice and so never equals the invoice amount.
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

    income = connection.execute(
        "SELECT * FROM income WHERE currency = ? AND amount = ? "
        "AND excluded = 0 AND date BETWEEN ? AND ?",
        (currency.upper(), amount, low, high)).fetchone()
    if income:
        return income, "invoice"

    return None, None


# ===========================================================================
#  CLASSIFYING ONE TRANSACTION
# ===========================================================================

def classify_credit(connection, *, description, details_type, amount,
                    currency, date, profile):
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
        matched, how = find_already_counted(connection, amount, currency, date)
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
            matched, how = find_already_counted(connection, amount, currency, date)
            if matched:
                return {"kind": "not_income", "client": client,
                        "matched": how,
                        "reason": (f"{client} paying an invoice already "
                                   f"counted - direct payment, not new income")}
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
                  personal=False):
    """
    Turn one balance's transactions into rows for the database.

    `personal=True` applies the narrow rule for the personal account:
    outgoing payments are dropped without being examined, and only incoming
    money from senders known to be business is kept.
    """
    income, expenses, jars, notes = [], [], [], []
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

        if txn.get("type") == "CREDIT":
            decision = classify_credit(
                connection, description=description, details_type=details_type,
                amount=abs(amount), currency=currency, date=date,
                profile=profile_label)

            if personal and decision["kind"] in ("unknown", "jar_move"):
                # Personal life. Dropped without being recorded anywhere.
                skipped_personal += 1
                continue

            if decision["kind"] == "jar_move":
                continue          # the jar's own balance is read separately

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
        if personal:
            skipped_personal += 1      # never read, never stored
            continue

        decision = classify_debit(
            description=description, details_type=details_type,
            amount=abs(amount), currency=currency, date=date)

        if decision["kind"] == "jar_move":
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

    return {"income": income, "expenses": expenses, "jars": jars,
            "notes": notes}
