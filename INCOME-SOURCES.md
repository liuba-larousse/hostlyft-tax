# Where the money actually comes from

Written 24 August 2026, after reading the live Stripe, Wise and HubSpot
accounts. The build plan assumed two income streams; there are seven, arriving
in three different accounts.

This page exists because that took a long time to establish and none of it is
obvious from the code.

---

## The headline

| | |
|---|---:|
| Recorded before this investigation | $6,559.06 |
| Actually visible for 2026 | **$57,250.72** |
| Newly found | $50,691.66 |

Self-employment tax on the newly found income, before offsetting expenses:
roughly **$7,160**.

---

## The seven streams

| # | Source | Lands in | Business | 2026 |
|---|---|---|---|---:|
| 1 | **Stripe** invoices | Hostlyft Wise | hostlyft | $6,559.06 |
| 2 | **HubSpot** invoices | mixed (see below) | hostlyft | $29,791.83 |
| 3 | **Upwork** (`PAYMENT ESCROW I`) | personal Wise | **mixed** | $11,797.31 |
| 4 | **CLOUD9 WINDY CITY** | personal Wise | marcus | $5,200.00 |
| 5 | **SETTLER VACATION HOMES** | personal Wise | hostlyft | $2,860.92 |
| 6 | **Payoneer** (Fiverr) | personal Wise | hostlyft | $807.60 |
| 7 | Direct client payments | personal Wise | hostlyft | matched to #2 |

### 1. Stripe — August onward

Clean. Invoices are the source of truth, recorded gross, with all three kinds
of Stripe fee as separate expenses. See the README.

### 2. HubSpot — January to July

Hostlyft moved off HubSpot after 30 July 2026, so this is **historical only**.
No ongoing API connection is needed or wanted. The invoices were extracted once
and saved to `tax/imports/hubspot_invoices_2026.csv`.

**Clean handover:** last HubSpot payment 30 July, first Stripe invoice 3 August.
No overlap, so nothing can be double-counted between them.

Only about $12,361 of the $29,792 invoiced actually arrived via HubSpot
Payments. **The rest was paid straight into the personal account** — fifteen
payments matched to invoices by amount, currency and date.

`amount_billed` differing from `subtotal` is a **discount**, not a fee.
`amount_paid` always equals `amount_billed`, so gross receipts are what the
client paid.

**Unresolved:** HubSpot's own processing fee is not recoverable. The
`COMMERCE_PAYMENT` object is not readable through the available connection.
Those fees are deductible and are currently missing.

### 3. Upwork — arrives as `PAYMENT ESCROW I`

Ten payouts, irregular amounts, matching no invoice. **Mixes two businesses**:
payments from Brian and some of the Marcus work, aggregated into single
payouts.

A Wise description cannot be split between the two, so these are recorded
`needs_review` rather than guessed. Splitting them needs Upwork's own reports.

### 4. CLOUD9 WINDY CITY — the Marcus work

Confirmed. Includes exactly $4,000.00 on 5 August, matching the $4,000/month
the plan describes. Tagged `marcus`.

Nothing is ever labelled "Marcus" in the bank data — the money arrives under
the company name.

### 5–7. Other client payments

SETTLER VACATION HOMES is an older client. Payoneer is Fiverr, one-time
clients. Monichkirchnerhof, OOMPH, BINETH, UNIQUE STAYS and Airvevo all match
HubSpot invoices.

---

## Four invoices marked unpaid that were actually paid

Money arrived directly instead of through the processor, so the invoice was
never marked paid.

| Invoice | Amount | Actually paid by |
|---|---:|---|
| Stripe `LEJEMVG3-0001` | $4,000.00 | CLOUD9 WINDY CITY, 5 Aug |
| Stripe `AOMSXKBZ-0001` | $234.00 | BINETH AND GROUP, 10 Aug |
| HubSpot `INV-1051` | $288.00 | BINETH AND GROUP, 10 Aug |

On a cash basis these are income — the money is in the account. Stripe's $180
invoice appears genuinely unpaid.

**This is a recurring pattern, not a one-off.** Any "outstanding invoices"
figure must be checked against actual receipts before being believed.

---

## The three accounts

| Account | Wise profile | What it holds |
|---|---|---|
| **Hostlyft LLC** | 93461311 | operating balances + the per-person jars |
| **Personal** | 17549462 | most client income, plus personal life |
| **Shakti Lease LLC** | 36576462 | business account used until 5 June |

### Shakti Lease LLC

Used for business until the Hostlyft LLC account opened on 30 May 2026. The
work at the time was done **as an independent contractor**, not under Shakti —
the account was simply an outdated container.

It is also **mixed**: some transactions are personal (a payment from Sunniva
Texe sent to the wrong account; AirHelp flight compensation after personal
travel). Nothing from this account is auto-classified as business.

### The personal account — scope

The original plan said to read this account narrowly, for Marcus payments only.
**That turned out to be far too narrow**: most 2026 client income arrives here,
and Marcus never appears by name.

Authorised scope is now **incoming credits only**. Debits are discarded at the
point of reading — never collected, never printed, never stored. During the
investigation 537 debits were skipped this way.

Only business income is stored. Personal credits (family transfers, refunds,
utility rebates, card reversals) are recognised and dropped.

---

## Transfers from Liuba to the business are never income

Client payments that land in the personal account are sometimes forwarded to
the business account. Those transfers appear as "Received money from Liubov
Kapitulskaya" — about $4,581 in 2026.

They are **never income**. Either the client payment behind them is already
recorded from an invoice, or the money is her own capital. Counting the
transfer as well would double it.

The one case that is not safe: a client pays personally and no invoice exists
anywhere. So these are excluded from income but **flagged for confirmation**,
never silently dropped.

Worked example: €900 arrived from Monichkirchnerhof on 5 July (invoice
INV-1050), was forwarded to the business on 6 July, and HubSpot marked the
invoice paid on 7 July. One payment, three records, counted once.

---

## Upwork — the email route only works going forward

Upwork emails every payment with exactly what is needed:

```
Listing Pricelabs and Hostaway configuration for 8   <- contract
Amount billed        $270.83                         <- GROSS
Fees & Taxes         ($28.87)                        <- deductible
Estimated earnings   $241.96                         <- net
```

Better than a CSV export: it arrives automatically, needs no new credential
(it reuses the Gmail app password Stage 10 sets up anyway), and separates
gross from fee - which the bank deposit does not.

**But the mailbox has no history.** Only two Upwork financial emails exist in
it, both after 20 July 2026. The reason is in the mailbox itself: an
"email address change request" dated 2026-07-20. Upwork notifications before
that went to a different address.

So:
- **August onward** - automatic, from Gmail
- **January to July** - no email trail here. Needs Upwork's own CSV export
  (Reports -> Transaction History), imported once like HubSpot and
  Capital One

The $11,797.31 of Upwork income for Jan-Jul is net of roughly 10.7% in fees,
so gross is nearer $13,200 and about $1,400 of deductible fees are currently
missing.

---

## The tax sheet is separate

Decided 24 August 2026: rather than adding tabs to `Hostlyft_Accounting_2026`,
a **separate Google Sheet** lives beside it in the same Drive folder.

The reason the two cannot share a convention: her accounting sheet is
organised so team payouts work - some clients pay after the work is done, and
payouts run at month end, so a month's tab groups work by service period.
**Tax needs cash received.** Those genuinely differ, and forcing one sheet to
do both would corrupt whichever it was not built for.

So the accounting sheet keeps its own convention and is never written to.
The tax sheet is cash-received throughout.

## Still open

- **Whose business is the Brian work** — Hostlyft, or independent like Marcus?
- **Splitting Upwork payouts** between Brian and Marcus needs Upwork's reports.
- **HubSpot processing fees** are a missing deduction.
- **FBAR**: business balances alone were $8,839 on 24 August, against a $10,000
  threshold that tests the maximum at *any point* across *all* foreign
  accounts, personal included. Almost certainly crossed.
