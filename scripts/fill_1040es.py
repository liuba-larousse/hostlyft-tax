"""
fill_1040es.py - fill in Form 1040-ES with your estimated tax.

    python scripts/fill_1040es.py
    python scripts/fill_1040es.py --out ~/Desktop

WHAT IT FILLS AND WHAT IT DOES NOT
    The AMOUNT OF PAYMENT box on each voucher, from the calculator.

    Not your name, SSN or address - those are not ours to invent, and on
    Married Filing Separately the form wants your husband's details too.
    The form is left fillable, so you type those in and it saves normally.

WHY ONLY THIS FORM
    It is the only 2026 one that exists. Checked against irs.gov:
    f1040es.pdf is the 2026 edition, but Form 1040, Schedule C, Schedule
    SE, Form 2555 and Form 8829 are all still the 2025 editions and will be
    until around January. Filling a 2025 form with 2026 figures produces a
    document that is wrong on its face while looking official.

    For those, the "Filling the forms" tab in your tax sheet says which
    number goes on which line.

WHERE TO SEND IT
    You file Form 2555, so your vouchers go to a DIFFERENT address from the
    one most people use:

        Internal Revenue Service
        P.O. Box 1303
        Charlotte, NC 28201-1303

    Or skip the voucher entirely and pay at irs.gov/payments.
"""

import argparse
import datetime as dt
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from taxlib import config, db, filings, tax  # noqa: E402

BOLD, GREEN, YELLOW, CYAN, OFF = (
    "\033[1m", "\033[32m", "\033[33m", "\033[36m", "\033[0m")

FORM_URL = "https://www.irs.gov/pub/irs-pdf/f1040es.pdf"
ABROAD_ADDRESS = ("Internal Revenue Service\n"
                  "P.O. Box 1303\n"
                  "Charlotte, NC 28201-1303")


DUE_TEXT = {
    1: r"April\s*15,\s*%(y)s", 2: r"June\s*15,\s*%(y)s",
    3: r"Sept[.]?\s*15,\s*%(y)s", 4: r"Jan[.]?\s*15,\s*%(next)s",
}


def voucher_amount_fields(page, year):
    """
    Map each voucher number to its "Amount of payment" box.

    BY THE DUE DATE PRINTED ON THE VOUCHER, not by guessing.

    The field names are opaque - f15_1[0] and so on - and the four vouchers
    are spread two to a page in an order that is not 1,2,3,4. While every
    quarter happened to be the same amount this did not matter; now that
    each voucher carries its own figure, putting the wrong number on a real
    form is a real error.

    So each voucher is identified by the date it prints - "Calendar
    year-Due Sept. 15, 2026" - and paired with the amount box directly
    beneath it, which is consistently about 40 points below. A voucher
    whose date cannot be read is left blank rather than guessed at.
    """
    labels = []

    def visit(text, cm, tm, font, size):
        stripped = text.strip()
        if stripped:
            labels.append((round(tm[5]), stripped))

    page.extract_text(visitor_text=visit)

    boxes = []
    for annot in (page.get("/Annots") or []):
        obj = annot.get_object()
        name = obj.get("/T")
        if not name and obj.get("/Parent"):
            name = obj.get("/Parent").get_object().get("/T")
        rect = obj.get("/Rect")
        if name and rect:
            x0, y0, x1, y1 = [float(v) for v in rect]
            if x0 >= 460 and 70 <= (x1 - x0) <= 110:
                boxes.append((round(y0), str(name)))

    found = {}
    for quarter, pattern in DUE_TEXT.items():
        wanted = pattern % {"y": year, "next": year + 1}
        for y, text in labels:
            if not re.search(wanted, text, re.I):
                continue
            # the amount box just below this label, nearest first
            below = sorted((y - by, name) for by, name in boxes if by < y)
            if below and below[0][0] < 80:
                found[quarter] = below[0][1]
            break
    return found


def main():
    parser = argparse.ArgumentParser(description="Fill Form 1040-ES.")
    parser.add_argument("--year", type=int,
                        default=config.SETTINGS["tax_year"])
    parser.add_argument("--out", default=str(config.ROOT / "tax" / "forms"))
    args = parser.parse_args()

    try:
        from pypdf import PdfReader, PdfWriter
        from pypdf.generic import NameObject, BooleanObject
    except ImportError:
        print("pypdf is not installed.  pip install pypdf")
        return 1

    connection = db.init_db()
    result = tax.from_database(connection, args.year)

    paid = {}
    for row in db.tax_payments_for(connection, args.year):
        paid[row["quarter"]] = (paid.get(row["quarter"], 0.0)
                                + (row["amount_usd"] or row["amount"] or 0.0))
    plan = filings.quarterly_plan(connection, args.year, paid)
    amounts = {row["quarter"]: row["voucher"] for row in plan["quarters"]}

    print(f"{BOLD}Form 1040-ES {args.year}{OFF}")
    print("=" * 74)
    print(f"   Tax accrued for the full year   "
          f"${plan['year_tax']:>9,.2f}")
    print(f"   {YELLOW}Each quarter is computed on ITS OWN period - Q3 ends "
          f"31 August, not today.{OFF}")
    print(f"   {YELLOW}Each voucher is the tax accrued by that cut-off, "
          f"less what has been paid.{OFF}")
    print()

    print("   downloading the form from irs.gov ...")
    request = urllib.request.Request(FORM_URL,
                                     headers={"User-Agent": "Mozilla/5.0"})
    data = urllib.request.urlopen(request, timeout=60).read()

    out_dir = Path(args.out).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    source = out_dir / f"f1040es-{args.year}-blank.pdf"
    source.write_bytes(data)

    reader = PdfReader(str(source))
    writer = PdfWriter()
    writer.append(reader)

    filled, wrote = 0, {}
    for index, page in enumerate(writer.pages):
        # VOUCHER PAGES ONLY, and this is not belt-and-braces - without it
        # the geometry filter also matched 19 fields on the Estimated Tax
        # Worksheet and wrote the quarterly amount into lines meant for
        # adjusted gross income, deductions and credits. A form filled with
        # the same number nineteen times is worse than an empty one.
        # NORMALISE THE WHITESPACE BEFORE MATCHING. The extracted text
        # carries line breaks inside the phrase, so a plain `"Payment
        # Voucher" in text` finds nothing and every page is skipped. Same
        # trap as "Uber   * Eats" not matching "Uber Eats".
        text = re.sub(r"\s+", " ", reader.pages[index].extract_text() or "")
        if "Payment Voucher" not in text:
            continue
        names = voucher_amount_fields(reader.pages[index], args.year)
        if not names:
            continue
        values = {field: f"{amounts[quarter]:,.2f}"
                  for quarter, field in names.items()
                  if amounts.get(quarter)}
        if values:
            writer.update_page_form_field_values(page, values)
            filled += len(values)
            wrote.update({q: amounts[q] for q in names if amounts.get(q)})

    if filled != 4:
        print(f"{YELLOW}   Expected 4 vouchers, filled {filled}. The form's "
              f"layout may have changed - check the PDF before using it."
              f"{OFF}")

    # Without this, Acrobat shows the values only after a click.
    writer._root_object["/AcroForm"][NameObject("/NeedAppearances")] = \
        BooleanObject(True)

    target = out_dir / f"f1040es-{args.year}-filled.pdf"
    with open(target, "wb") as handle:
        writer.write(handle)

    print(f"{GREEN}   Filled {filled} voucher(s):{OFF}")
    for quarter in sorted(wrote):
        print(f"      Voucher {quarter}  ${wrote[quarter]:>9,.2f}")
    print(f"   {target}")
    print()
    print(f"{BOLD}STILL TO DO BY HAND{OFF}")
    print("   Your name, SSN and address on the voucher you send.")
    print("   On Married Filing Separately the form asks for your "
          "husband's details too.")
    print()
    print(f"{BOLD}WHERE IT GOES{OFF}   (you file Form 2555, so NOT the "
          f"usual address)")
    for line in ABROAD_ADDRESS.splitlines():
        print(f"   {line}")
    print(f"   {CYAN}Or pay online at irs.gov/payments and skip the voucher "
          f"entirely.{OFF}")
    print()
    for quarter in filings.quarters(args.year):
        number = quarter["quarter"]
        marker = ("  <- due in "
                  f"{quarter['days_away']} days") if 0 <= quarter[
                      "days_away"] <= 30 else ""
        overdue = "  <- OVERDUE" if quarter["overdue"] else ""
        print(f"   Voucher {number}  {quarter['period']:<11} "
              f"due {quarter['due']}  ${amounts.get(number, 0):>9,.2f}"
              f"{marker}{overdue}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
