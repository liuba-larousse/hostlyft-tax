"""
categorize.py - deciding which expense is which kind of cost.

The rules live in rules.txt, in plain English, so they can be changed
without touching code. See that file for the format.

TWO PRINCIPLES

  1. Nothing is ever guessed into a category. Anything that matches no rule
     stays "uncategorized" and is listed after every run. A wrong category
     is a wrong deduction, and unlike a crash it is completely invisible.

  2. Contractors are NOT matched here. They are matched by name, nickname
     and payment alias in config.py, which also knows who needs a W-9 and
     who needs a W-8BEN. Splitting that across two files would let the two
     drift apart.
"""

import re

from taxlib import config


DEFAULT_CATEGORY = "uncategorized"


def load_rules(path=None):
    """
    Read rules.txt into a list of (category, [words]) in file order.

    Order matters: the first rule that matches wins, so more specific rules
    belong higher up the file.
    """
    path = path or config.RULES_PATH
    rules, current, words = [], None, []

    for raw in open(path, encoding="utf-8"):
        line = raw.split("#")[0].rstrip()
        if not line.strip():
            continue

        if "=" in line:
            if current:
                rules.append((current, words))
            name, _, rest = line.partition("=")
            current, words = name.strip(), []
            line = rest

        words += [w.strip() for w in line.split(",") if w.strip()]

    if current:
        rules.append((current, words))
    return rules


def categorize(text, rules=None, vendor=None):
    """
    Work out the category for one expense.

    Returns (category, matched_word). The matched word is kept so the run
    can show WHY something was categorised, rather than asking for trust.
    """
    rules = rules if rules is not None else load_rules()
    haystack = config._plain(f"{vendor or ''} {text or ''}").lower()

    for category, words in rules:
        for word in words:
            needle = config._plain(word).lower()
            # whole-word for short words, substring for longer distinctive
            # ones - "Quo" must not match "quote", but "Multicurrency
            # Settlement" should match inside a longer description.
            if len(needle) <= 4:
                if re.search(rf"\b{re.escape(needle)}\b", haystack):
                    return category, word
            elif needle in haystack:
                return category, word

    return DEFAULT_CATEGORY, None


# ===========================================================================
#  CLEANING UP VENDOR NAMES
# ===========================================================================

def merchant_from_card(description):
    """
    Pull the shop's name out of a Wise card description.

    Wise writes:
        "Card transaction of 108.00 USD issued by Anthropic* Claude"

    Taking the first 30 characters of that gives "Card transaction of 108.00
    USD iss", which is the same for every purchase and useless for both
    categorising and reading. The merchant is the part after "issued by".
    """
    found = re.search(r"issued by\s+(.+?)\s*$", description or "",
                      re.IGNORECASE)
    if not found:
        return None
    name = found.group(1)
    # trim the noise card networks add: "Anthropic* Claude" -> "Anthropic",
    # "Clickup SAN DIEGO" -> "Clickup"
    name = re.split(r"[*#]", name)[0]
    # Card networks append the merchant's town: "Clickup SAN DIEGO".
    return _trim_noise(name) or None


def _trim_noise(name):
    """Strip the town and reference numbers card networks append."""
    name = re.sub(r"\s+\d{4,}.*$", "", name or "").strip()
    if name[:1].isupper() and name.split() and not name.split()[0].isupper():
        name = re.sub(r"(\s+[A-Z0-9.]{2,}){1,3}\s*$", "", name)
    return name.strip()


def tidy_vendor(vendor, description, matched_word=None):
    """
    The best available name for whoever was paid.

    Card descriptions often name a reseller before the real merchant:
    "Dnh*Godaddy#4049716694" is GoDaddy, billed through DNH. Taking the part
    before the asterisk gives "Dnh", which is right for "Anthropic* Claude"
    and wrong here.

    Where a rule matched, the segment containing that word is the better
    name - the thing that made it recognisable is the thing to call it.
    """
    merchant = merchant_from_card(description)
    if merchant and matched_word:
        raw = re.search(r"issued by\s+(.+?)\s*$", description or "",
                        re.IGNORECASE)
        if raw:
            plain_word = config._plain(matched_word).lower()
            for segment in re.split(r"[*]", raw.group(1)):
                if plain_word in config._plain(segment).lower():
                    cleaned = _trim_noise(re.split(r"[#]", segment)[0])
                    if cleaned:
                        return cleaned
    if merchant:
        return merchant
    if vendor and vendor.lower().startswith("card transaction"):
        return None
    return vendor


# ===========================================================================
#  APPLYING IT
# ===========================================================================

def recategorize(connection, tax_year=None, dry_run=False, rules=None):
    """
    Go through the expenses and categorise anything not yet categorised.

    Only touches rows still on the default category, so a category set by
    hand is never overwritten. Vendor names are tidied at the same time,
    since a card row's vendor is unusable until the merchant is extracted.
    """
    rules = rules if rules is not None else load_rules()

    where_year = "AND tax_year = ?" if tax_year else ""
    params = (tax_year,) if tax_year else ()
    rows = connection.execute(
        f"SELECT id, vendor, description, category, amount_usd "
        f"FROM expenses WHERE excluded = 0 {where_year}", params).fetchall()

    changed, still_unknown = [], []

    for row in rows:
        _, preview = categorize(row["description"], rules,
                                merchant_from_card(row["description"]))
        vendor = tidy_vendor(row["vendor"], row["description"], preview)
        if row["category"] != DEFAULT_CATEGORY:
            if vendor and vendor != row["vendor"] and not dry_run:
                connection.execute(
                    "UPDATE expenses SET vendor = ? WHERE id = ?",
                    (vendor, row["id"]))
            continue

        category, matched = categorize(row["description"], rules, vendor)

        if category == DEFAULT_CATEGORY:
            still_unknown.append({
                "id": row["id"], "vendor": vendor or row["vendor"],
                "description": row["description"],
                "amount_usd": row["amount_usd"]})
            if vendor and vendor != row["vendor"] and not dry_run:
                connection.execute(
                    "UPDATE expenses SET vendor = ? WHERE id = ?",
                    (vendor, row["id"]))
            continue

        changed.append({"id": row["id"], "vendor": vendor or row["vendor"],
                        "category": category, "matched": matched,
                        "amount_usd": row["amount_usd"]})
        if not dry_run:
            connection.execute(
                "UPDATE expenses SET category = ?, vendor = ?, "
                "updated_at = ? WHERE id = ?",
                (category, vendor or row["vendor"], db_now(), row["id"]))

    if not dry_run:
        connection.commit()

    return {"categorized": changed, "uncategorized": still_unknown}


def db_now():
    from taxlib import db
    return db._now()
