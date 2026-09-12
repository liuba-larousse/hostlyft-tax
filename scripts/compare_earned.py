"""
compare_earned.py - three ways to measure what each contractor earned.

    python scripts/compare_earned.py

"Earned" is the one number in the reconciliation that does not come from a
bank. It has to come from somewhere, and there are three candidates:

  A  THE SHEET'S OWN SPLIT CALCULATION  (what is used today)
     Her hand-maintained monthly tabs. Independent of the money, which is
     what makes reconciliation work at all.

  B  WHAT WENT INTO AND OUT OF EACH JAR
     The truest record of what she has actually set aside. But see the
     warning this prints: it is computed from the same money movements as
     "withdrawn" and "in jar", so the gap between them collapses to zero
     by construction. It cannot detect a discrepancy, because it IS the
     thing it would be checking.

  C  OUR OWN CALCULATION
     The split RATES are learned from the sheet per client - including the
     bespoke ones - and applied to the money that ACTUALLY ARRIVED, from
     the database. Cash basis, which is what tax runs on.

Sunniva is hourly, not a revenue split, so B and C can only report what she
was paid. Only A knows what she is owed.
"""

import sys, re
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
from taxlib import gsheets, db, fx, config, reconcile
import collections

MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
NAMES = {"Katerina Split":"Katerina Mrvova","Ayoka Split":"Yetunde Olaniyan",
         "Evgeniya Split":"Evgeniya Dyatlovskaya","Sunniva Split":"Sunniva Texe"}

def money(x):
    if x is None: return 0.0
    s = str(x).strip()
    if s in ("","-","—"): return 0.0
    s = re.sub(r"[^\d.\-]", "", s.replace(",",""))
    try: return float(s)
    except: return 0.0

svc = gsheets.service(); sid = gsheets.accounting_sheet_id()
conn = db.init_db()

# ---- learn each client's split RATES from the sheet -------------------
rates = collections.defaultdict(dict)   # client -> person -> rate
cur_of = {}
for m in MONTHS:
    try:
        vals = gsheets.call(svc.spreadsheets().values().get(
            spreadsheetId=sid, range=f"'{m} 2026'!A1:H40"))["values"]
    except Exception:
        continue
    header = None
    for row in vals:
        cells = list(row) + [""]*8
        if str(cells[0]).strip() == "Client":
            header = [str(c).strip() for c in cells]
            continue
        if header and str(cells[0]).strip() and not str(cells[0]).startswith("Total"):
            client = str(cells[0]).strip()
            amount = money(cells[2])
            if amount <= 0: continue
            cur_of[client] = str(cells[1]).strip()
            for idx, label in enumerate(header):
                if label in NAMES:
                    share = money(cells[idx])
                    if share:
                        rates[client][NAMES[label]] = share/amount
print("CLIENT SPLIT RATES LEARNED FROM THE SHEET")
for client, r in sorted(rates.items()):
    print(f"   {client:<14s} " + "  ".join(f"{p.split()[0]}={v:.4f}" for p,v in r.items()))

# ---- map sheet client names to database payers ------------------------
payers = [r["payer"] for r in conn.execute(
    "SELECT DISTINCT payer FROM income WHERE excluded=0 AND business='hostlyft' "
    "AND payer IS NOT NULL AND payer!=''")]
def match(client):
    c = client.lower()
    for p in payers:
        first = p.split()[0].lower()
        if first.startswith(c[:4]) or c.startswith(first[:4]):
            return p
    return None
mapping = {c: match(c) for c in rates}
print("\nCLIENT -> PAYER IN THE DATABASE")
for c, p in sorted(mapping.items()):
    print(f"   {c:<14s} -> {p or '*** NO MATCH ***'}")

matched = {p for p in mapping.values() if p}
orphans = [(p, conn.execute("SELECT ROUND(SUM(amount_usd),2) FROM income WHERE excluded=0 "
            "AND business='hostlyft' AND payer=?", (p,)).fetchone()[0]) for p in payers if p not in matched]
orphans = sorted([o for o in orphans if o[1]], key=lambda x: -x[1])
print("\nCLIENTS PAYING MONEY THAT THE SHEET HAS NO SPLIT RULE FOR")
for p, usd in orphans:
    print(f"   {p:<28s} ${usd:>9,.2f}")
print(f"   {'TOTAL':<28s} ${sum(u for _,u in orphans):>9,.2f}")

PEOPLE = ["Katerina Mrvova","Yetunde Olaniyan","Evgeniya Dyatlovskaya","Sunniva Texe"]

# ---- OPTION A: the sheet's own split calculation ----------------------
sheet_earned = reconcile.earnings_by_person(conn, 2026)
A = {p: (sheet_earned.get(p) or {}).get("usd") or 0.0 for p in PEOPLE}

# ---- OPTION B: what actually went into and out of each jar ------------
def usd(amount, currency, date):
    if currency == "USD": return amount
    return fx.convert(conn, amount, currency, date)["amount"]

B = {p: 0.0 for p in PEOPLE}
for r in conn.execute("SELECT person, direction, amount, currency, date, amount_usd "
                      "FROM jar_movements WHERE person IS NOT NULL AND tax_year=2026"):
    v = r["amount_usd"] if r["amount_usd"] is not None else usd(r["amount"], r["currency"], r["date"])
    if r["person"] in B:
        B[r["person"]] += v if r["direction"] == "in" else -v
# Sunniva has no jar - money goes straight to her bank
sun = conn.execute("SELECT ROUND(SUM(amount_usd),2) FROM expenses WHERE excluded=0 "
                   "AND category='contractor' AND vendor='Sunniva Texe' AND tax_year=2026").fetchone()[0] or 0.0
B["Sunniva Texe"] = sun

# ---- OPTION C: our own split rates x money actually received ----------
C = {p: 0.0 for p in PEOPLE}
for client, person_rates in rates.items():
    payer = mapping.get(client)
    if not payer: continue
    received = conn.execute("SELECT COALESCE(SUM(amount_usd),0) FROM income WHERE excluded=0 "
                            "AND business='hostlyft' AND payer=? AND tax_year=2026", (payer,)).fetchone()[0]
    for person, rate in person_rates.items():
        if person in C: C[person] += received * rate
C["Sunniva Texe"] = sun   # hourly, not a revenue split

print("\n" + "="*78)
print("THREE WAYS TO MEASURE 'EARNED' - 2026")
print("="*78)
print(f"{'person':<24s} {'A sheet':>12s} {'B jars':>12s} {'C our calc':>12s}   {'B vs A':>10s} {'C vs A':>10s}")
for p in PEOPLE:
    print(f"{p:<24s} {A[p]:>12,.2f} {B[p]:>12,.2f} {C[p]:>12,.2f}   "
          f"{B[p]-A[p]:>+10,.2f} {C[p]-A[p]:>+10,.2f}")
print(f"{'TOTAL':<24s} {sum(A.values()):>12,.2f} {sum(B.values()):>12,.2f} {sum(C.values()):>12,.2f}   "
      f"{sum(B.values())-sum(A.values()):>+10,.2f} {sum(C.values())-sum(A.values()):>+10,.2f}")

print("\nWHAT EACH ONE IMPLIES FOR THE RECONCILIATION GAP (earned - withdrawn - in jar)")
print(f"{'person':<24s} {'withdrawn':>11s} {'in jar':>10s} {'gap A':>10s} {'gap B':>10s} {'gap C':>10s}")
for p in PEOPLE:
    w = conn.execute("SELECT COALESCE(SUM(amount_usd),0) FROM expenses WHERE excluded=0 "
                     "AND category='contractor' AND vendor=? AND tax_year=2026",(p,)).fetchone()[0]
    j = conn.execute("SELECT COALESCE(SUM(amount_usd),0) FROM wise_jars WHERE person=? "
                     "AND observed_on=(SELECT MAX(observed_on) FROM wise_jars)",(p,)).fetchone()[0]
    print(f"{p:<24s} {w:>11,.2f} {j:>10,.2f} {A[p]-w-j:>10,.2f} {B[p]-w-j:>10,.2f} {C[p]-w-j:>10,.2f}")
