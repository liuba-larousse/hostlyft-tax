"""
check_forms.py - who owes a W-9 or W-8BEN, and whether it has arrived.

    python scripts/check_forms.py
        Show where everyone stands. Changes nothing.

    python scripts/check_forms.py --received "Katerina Mrvova" \
                                 --on 2026-09-10 --tin
        Record that her W-9 came back on that date, with a taxpayer ID.

    python scripts/check_forms.py --received "Yetunde Olaniyan" \
                                 --on 2026-09-10
        Record a W-8BEN. Its expiry date is worked out for you.

    python scripts/check_forms.py --not-received "Sunniva Texe"
        Undo - mark a form as no longer on file.

WHICH FORM SOMEBODY NEEDS IS NOT SET HERE. That comes from the roster in
taxlib/config.py, which records why each person is treated the way they are.
This script only records whether the form has actually arrived.
"""

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from taxlib import config, db, forms   # noqa: E402

BOLD, GREEN, YELLOW, RED, OFF = (
    "\033[1m", "\033[32m", "\033[33m", "\033[31m", "\033[0m")


def resolve_person(name):
    """
    Turn what she typed into a roster name.

    Accepts the full name, a nickname, or any unambiguous part - "Jane",
    "Katerina" and "Kateřina Mrvová" all land on the right person. A
    fragment matching two people is refused rather than guessed, because
    "Olaniyan" genuinely means either of two contractors.
    """
    person = config.contractor(name)
    if person:
        return person["name"], None

    matched = config.match_contractor(name, strict=True)
    if matched:
        return matched["name"], None

    # Say what WAS on offer, rather than only that this failed.
    known = "\n".join(f"    {row['name']}" for row in config.CONTRACTORS)
    if name.lower() in config.ambiguous_aliases():
        return None, (f"'{name}' could mean more than one person, so it will "
                      f"not be guessed. Use the full name:\n{known}")
    return None, f"No contractor matches '{name}'. The roster is:\n{known}"


def main():
    parser = argparse.ArgumentParser(
        description="Track contractor W-9 and W-8BEN forms.")
    parser.add_argument("--year", type=int,
                        default=config.SETTINGS["tax_year"])
    parser.add_argument("--received", metavar="NAME",
                        help="record that this person's form has arrived")
    parser.add_argument("--not-received", metavar="NAME",
                        help="record that this person's form is NOT on file")
    parser.add_argument("--on", metavar="YYYY-MM-DD",
                        help="the date the form was signed "
                             "(default: today)")
    parser.add_argument("--tin", action="store_true",
                        help="the W-9 includes a taxpayer ID number")
    parser.add_argument("--note", help="anything worth remembering")
    parser.add_argument("--today", metavar="YYYY-MM-DD",
                        help="pretend today is this date (for checking "
                             "expiry warnings)")
    args = parser.parse_args()

    connection = db.init_db()
    today = args.today or date.today().isoformat()

    # ------------------------------------------------------ recording one
    if args.received or args.not_received:
        raw = args.received or args.not_received
        name, problem = resolve_person(raw)
        if problem:
            print(f"\n{RED}{problem}{OFF}\n")
            return 1

        person = config.contractor(name)
        required = person["form"]

        if args.received:
            signed = args.on or today
            try:
                date.fromisoformat(signed)
            except ValueError:
                print(f"\n{RED}'{signed}' is not a date. Use YYYY-MM-DD, "
                      f"like 2026-09-10.{OFF}\n")
                return 1

            if required == "W-9" and not args.tin:
                print(f"\n{YELLOW}Recording her W-9 WITHOUT a taxpayer ID "
                      f"number.{OFF}")
                print("  A W-9 with no TIN does not do its job - 24% backup")
                print("  withholding still applies. If the number is on the")
                print("  form, re-run with  --tin  as well.\n")

            db.record_form(connection, person=name, form_type=required,
                           received=True, received_on=signed,
                           has_tin=args.tin, notes=args.note)
            connection.commit()

            row = db.get_form(connection, name)
            print(f"\n{GREEN}Recorded:{OFF} {name} - {required} signed "
                  f"{signed}")
            if row["expires_on"]:
                print(f"  Expires {row['expires_on']}. A W-8BEN is valid "
                      f"until the last day of")
                print("  the third calendar year after signing - that is the "
                      "rule, not a guess.")
            if required == "W-9":
                print(f"  Taxpayer ID number: "
                      f"{'yes' if row['has_tin'] else 'NO - 24% backup withholding applies'}")
        else:
            db.record_form(connection, person=name, form_type=required,
                           received=False, notes=args.note)
            connection.commit()
            print(f"\n{YELLOW}Recorded:{OFF} {name} - {required} is NOT on "
                  f"file.")
        print()

    # -------------------------------------------------------- the report
    rows = forms.review(connection, args.year, today=today)
    print()
    for line in forms.report(rows, args.year):
        if line.startswith("!"):
            print(f"{RED}{line}{OFF}")
        elif line.startswith("    ->"):
            print(f"{YELLOW}{line}{OFF}")
        else:
            print(line)

    outstanding = forms.outstanding(rows)
    if outstanding:
        print("-" * 70)
        print("TO RECORD A FORM ONCE IT ARRIVES")
        print('  python scripts/check_forms.py --received "Full Name" '
              '--on YYYY-MM-DD')
        print("  Add  --tin  for a W-9 that carries a taxpayer ID number.")
        print()
        print(f"{YELLOW}  Neither form is sent to the IRS. You collect them")
        print("  and keep them. They are what you produce if anyone asks why")
        print(f"  no tax was withheld.{OFF}")
        print()

    connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
