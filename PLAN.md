# Hostlyft LLC — Tax Tracker: Build Plan

**For Claude:** this plan was written across planning sessions in Claude Code on
the web, where every external service (Stripe, Wise, exchange rates, Gmail, and
irs.gov) was blocked by the network proxy. It carries research and decisions
already made — read it fully, then start at Stage 1.

**The user has no coding experience.** Explain each step in plain English before
doing it, define technical terms, and check in before moving between stages. She
asked for this explicitly.

---

## The goal

A free, local system for Hostlyft LLC (single-member LLC) tracking business income
and expenses, converting to USD, categorizing spending, reconciling team earnings
against actual withdrawals, estimating quarterly US federal tax, and sending
reminders. No paid services. Everything runs on her Mac.

## Her tax situation (established — do not re-ask)

- **Married Filing Separately.** Married abroad to a non-US person, filing alone,
  no children living with her. The IRS counts a foreign marriage as married, so
  "filing alone" means MFS — **not Single**.
- Hostlyft is her **only income**. Standard deduction **$16,100**.
- **Lives in France**, settled permanently — bona fide residence, full year.
- **Pays no social security contributions anywhere.**
- **Pays no French income tax.**

**She explicitly rejected a padded/conservative estimate.** She is self-filing
with no CPA review, so an inflated number is just a wrong number that costs her
cash flow all year. Build for accuracy. Do not re-add "assume the worst" defaults.

---

## Findings that cost real time to establish

### 1. Wise blocks personal tokens from reading statements

Under PSD2, statement endpoints reject every personal-token request with HTTP 403
and an `x-2fa-approval` header. Fix: generate an RSA keypair, upload the public key
in Wise settings, sign the one-time token from that header with the private key,
retry with the signed value. ~20 minutes of user setup and the most likely place to
get stuck. Reference: `github.com/transferwise/digital-signatures-examples`
(`sca-personal-tokens`).

### 2. The 2026 IRS figures were NOT read from the primary source

The planning sandbox blocked `irs.gov`. Figures below were cross-checked across
independent sources and agree, but the PDF was never opened. **`irs.gov` is
reachable from the Mac, so the first task of Stage 9 is to verify every number
against https://www.irs.gov/pub/irs-drop/rp-25-32.pdf Table 4.** Do not skip.

### 3. Record income gross, not net

Schedule C asks for gross receipts. A $2,000 invoice with a $60 Stripe fee is
income $2,000 **plus** a $60 deductible expense — never income of $1,940. Netting
silently loses the fee deduction.

### 4. Money in a Wise jar is still her money

A jar is a label inside her own account, not a payment. Therefore:

- Allocating to a jar is **not** a deductible expense — only the **withdrawal** is
- The **$600 contractor threshold counts withdrawals**, not allocations
- Jar balances count toward her **FBAR** aggregate

This drives the whole reconciliation design. Three numbers per person:

| Number | Source | Used for |
|---|---|---|
| **Earned** | Sheet's split calculation | Team management |
| **In jar** | Wise SAVINGS balance | Cash held on their behalf |
| **Withdrawn** | Actual transfers out | **The tax deduction** |

### 5. Only one team member gets a 1099

| Sheet name | Also known as | Status | Forms |
|---|---|---|---|
| Katerina Mrvova | — | **US citizen** (also Czech, lives in Brazil) | **W-9 + 1099-NEC at $600** |
| Yetunde Olaniyan | "Ayoka" | Not a US person | W-8BEN, no 1099 |
| Evgeniya Dyatlovskaya | **"Jane"** | Not a US person | W-8BEN, no 1099 |
| Sunniva Texe | — | Not a US person | W-8BEN, no 1099 |

Match **both** full names and nicknames against Wise transactions — transfers may
be labelled either way.

**Katerina cannot be recorded as Czech.** She asked. A US citizen is a US person
for tax purposes regardless of dual citizenship or residence; no election changes
that; and a US citizen cannot sign a W-8BEN, which certifies *foreign* status.
Explained once and accepted — **do not re-litigate it and do not build a setting
that allows it.** A missing W-9 TIN triggers **24% backup withholding**.

*Verify on the Mac:* whether foreign-source payments to a US citizen abroad are
1099-NEC reportable at all — https://www.irs.gov/instructions/i1099mec. Default to
issuing.

### 6. There are TWO businesses, not one — Marcus is not Hostlyft work

Marcus pays **$4,000/month (~$48,000/yr)** into her **personal** Wise account, and
that work is done **independently, not through Hostlyft LLC**.

**This must be in the tax calculation.** A single-member LLC is a disregarded
entity, so both businesses land on the same 1040 anyway, and:

- **SE tax is computed on combined net earnings**, not per business
- The **$132,900 FEIE cap** and **$184,500 Social Security cap** are combined
  limits, not per-business

Omitting Marcus would understate SE tax by roughly **$6,900**.

**No liability concern.** An earlier draft flagged commingling — that flag was
based on the assumption Marcus was LLC work and is **resolved**. No LLC money runs
through the personal account. Do not raise it again.

**Schedule C is an open decision.** She describes the Marcus work as "related but
not identical" to Hostlyft's revenue management. That's a genuine judgement call
between one Schedule C and two. Tag rows so it can be filed either way, and raise
it as a decision to make **before filing**, not now. Total tax is the same either
way; only expense attribution differs.

**Her sheet currently books Marcus inside Hostlyft's totals**
(`INCOME — Marcus (Flat, USD, 100% to Liuba)` feeding `TOTAL INCOME BY CURRENCY`),
which overstates Hostlyft revenue by ~$48k. She chose to **report them
separately** — Hostlyft totals exclude Marcus, with a combined figure for tax.
Fix this in the new tabs; **do not edit her existing tabs**.

**Money stays in the personal account** — she does not transfer it to the business
account, so there is no personal→business internal transfer to match.

---

---

## Her Google Sheet — extend it, never rebuild it

`Hostlyft_Accounting_2026`, Drive file ID
`1KtqNg_hJFkceP7JRzFg_ru_7Q9jwmrrLbUz6UVUHJhg`.

Tabs: Annual Summary (per currency, never blended) · Accounting Setup · 12 monthly
tabs · Subscriptions · Monthly exchange rates.

Business rules already encoded there:

- Liuba takes **5% off the top** of Katerina/Ayoka and Evgeniya client payments
  before group percentages apply
- **Katerina + Ayoka** share a client group: 70% combined, split 50/50
- **Evgeniya** takes 80% of her assigned clients' revenue
- **Sunniva** is hourly at **$25.00/hr**
- **Marcus** is flat $4,000/month, 100% to Liuba, no contractor split
- **Payouts lag one month** — this month's payouts come from last month's income
- Every payment carries a currency; totals are per currency, never blended

**Do not modify her existing tabs. Additions only, as new tabs.**

## Architecture — both database and sheet

Raw facts go to **both** SQLite *and* new tabs in the sheet. She chose this
deliberately: the database is the append-only audit record, the sheet is where she
actually looks.

**The duplication is a feature:** reconciliation compares sheet against database
and flags disagreement, so a hand-edited tab surfaces instead of passing silently.

Writing to Sheets needs a free Google service account — create a Cloud project,
enable the Sheets API, create a service account, share the sheet with its email.
~15 minutes, walked through in the README.

---

## Build order

Explain → she says go → build → she reviews → next.

One deviation from her original numbering: currency conversion (her step 5) comes
**before** Wise (her step 3b), because Wise is multi-currency and needs it. Tell
her this briefly.

### Stage 1 — Skeleton
`requirements.txt`, `.env.example`, `taxlib/config.py`, `setup_mac.command`
(double-clickable). Explain what a virtual environment is and why it contains
libraries to this folder.

### Stage 2 — Database
SQLite = a complete database in one ordinary file (`hostlyft_tax.db`). No server,
no signup, no fee — explain it that way.

Her two required tables, each with an added **`business`** column
(`hostlyft` | `marcus`) so the two income streams report separately while the tax
calculator still sums both:
- `income` — date, amount, currency, amount_usd, source, description, **business**
- `expenses` — date, amount, currency, amount_usd, category, description, vendor,
  **business**

Plus, for correctness:
- `stripe_payouts` — **not income**; the reference list the double-count check
  compares against
- `wise_jars` — per-person jar balances over time
- `contractor_ledger` — earned / in-jar / withdrawn per person
- `fx_rates` — cache, so re-runs give identical numbers
- `alerts_sent` — so alarms fire once, not daily forever

Every row carries a source ID; re-running any import updates, never duplicates.

### Stage 3 — Secrets
`.env`, `chmod 600`, never committed. Holds Stripe key, Wise token, Gmail app
password, `GOOGLE_SHEET_ID`, service-account JSON path.

Recommend the file over `~/.zshrc` exports for one concrete reason worth
explaining: **cron does not load shell settings**, so exported variables vanish and
the 9am reminder fails silently.

### Stage 4 — Stripe income
Each paid invoice → one income row at **gross**; Stripe fee → separate expense row.
Also store payouts (amount, currency, `arrival_date`) for Stage 6 matching.

### Stage 5 — Currency conversion
`taxlib/fx.py` using the **Frankfurter API** (`api.frankfurter.dev`) — free because
it wraps exchange rates the ECB publishes daily as a public service. No key,
signup, quota or card.

Two limits to code around and document:
- ECB publishes **business days only** — walk back to the last business day for
  weekend dates and record which date was used
- ~30 major currencies; anything else fails loudly rather than guessing

Store both original and USD amounts, always. Document the **IRS annual average
exchange rate** as the sanctioned simpler fallback — she asked for this explicitly.
Her sheet has a monthly-average rates tab: say in the README that daily rates are
authoritative for tax and the sheet's tab is a reference view.

### Stage 6 — Wise + double-count prevention
`wise_keys.py` (keypair generation, per finding 1), then `pull_wise.py`.

- `GET /v2/profiles` returns **both** the personal and business profiles for the
  authenticated user; the SCA keypair is tied to the login, not one profile, so a
  single token and keypair covers both. **Confirm against her live account** — this
  could not be called from the planning sandbox.
- **Business profile:** pull everything — **STANDARD** balances (operating money)
  and **SAVINGS** balances (jars):
  `GET /v4/profiles/{profileId}/balances?types=SAVINGS` returns each with its `name`
- **Personal profile: read narrowly.** Pull **only incoming payments matching
  Marcus**, tagged `business = marcus`. Her personal spending must never be read,
  stored, or written to the database or the sheet. This was an explicit choice —
  respect it.
- Per-jar balances and transaction history
- Classify every outgoing transfer: contractor withdrawal (match name *and*
  nickname), business expense, or Liuba's own draw

**Double-count prevention.** Stage 4 stored every Stripe payout. Each **incoming**
Wise credit is checked against that list. Exact match on amount + currency within a
few days → tag `internal transfer — already counted via Stripe`, **exclude from
income**. Close but inexact → `possible transfer — needs review`, surface it. Never
silently guess. Unmatched credits → flag for confirmation, never auto-add.

Worked example — $2,000 invoice paid Sept 3, Stripe takes $60, pays out $1,940
arriving Sept 9:

| Source | Record | Income? |
|---|---|---|
| Stripe invoice | $2,000 | Yes — $2,000 |
| Stripe fee | $60 | No — expense |
| Wise credit Sept 9 | $1,940 → matched | **No — internal transfer** |

Counted: **$2,000**. Without the check: **$3,940** — tax on nearly double actual
earnings.

### Stage 7 — Capital One one-time import
Historical only, April–July, run once, fully offline. README covers the export:
capitalone.com → the card → *View Statements* / *Download Transactions* → date
range → **CSV**. Typical columns: `Transaction Date, Posted Date, Card No.,
Description, Category, Debit, Credit`. **Auto-detect the layout** rather than
hard-coding — banks change these. **Skip payments to the card itself** (transfers,
not expenses). Refuse to run twice on the same file unless forced.

### Stage 8 — Categorization
Rules in a plain-English file she can edit without touching code:
- PriceLabs, ClickUp, HubSpot → `software`
- All four contractors, **full names and nicknames** → `contractor`
- Registered agent fees → `compliance/admin`
- Capital One rows → matched on description

Unmatched → `uncategorized`, **listed after every run**, never silently guessed.
When new vendors appear, **ask her for the rule** — she asked for this explicitly.

### Stage 9 — Tax calculator (France-specific)

**First task: verify the bracket figures against the IRS PDF** (finding 2).

**US income tax — likely $0.** As a bona fide resident of France for the full year,
the **Foreign Earned Income Exclusion** (Form 2555) excludes up to **$132,900** for
2026. Under that, US taxable income is ~$0. She still files Form 1040 + Form 2555.
Above the cap, the excess is taxed under the **§911(f) stacking rule** — at the
rates that would have applied without the exclusion. Model this.

**The 20% QBI deduction is removed entirely.** Moot once FEIE zeroes taxable
income, and §199A requires a *US* trade or business. Do not reintroduce it.

**US self-employment tax — the entire bill.** FEIE does **not** reduce it. IRS:
*"You must pay self-employment tax on all your net profit from self-employment,
even if you claimed the foreign earned income exclusion."*

Only the **US–France totalization agreement** can remove it. SSA's France pamphlet:
*self-employed workers who work only in France are assigned French coverage.* But
claiming it requires a **French Certificate of Coverage** from the agency
collecting her contributions — she pays into nothing, so none exists. Model both:

| Scenario | US SE tax |
|---|---|
| **Today** — unregistered, no certificate | **Full 15.3%** on 92.35% of net profit |
| **Registered in France** (e.g. URSSAF) with certificate | **$0** |

Surface honestly, do not sell the switch: French self-employed contributions for a
service business run roughly 21–24% **of revenue**, which can exceed 15.3% of
*profit*. Registering is about compliance where she lives, not a guaranteed saving.

**Say once, do not repeat or moralize:** permanently resident in France running a
business there while paying neither social contributions nor income tax anywhere is
not a stable position — France taxes residents on worldwide income. This tool
covers US federal tax only; her larger exposure is likely French.

`constants_2026.py`, every figure cited inline:
- SE tax **15.3%** = 12.4% Social Security + 2.9% Medicare
- Social Security wage cap **$184,500** (SSA 2026 contribution and benefit base)
- MFS brackets, Rev. Proc. 2025-32 **Table 4**: 10% to $12,400 · 12% to $50,400 ·
  22% to $105,700 · 24% to $201,775 · 32% to $256,225 · 35% to $384,350 · 37% above
- Standard deduction **$16,100** · FEIE cap **$132,900**
- Additional Medicare Tax 0.9% above **$125,000** — the MFS threshold is $125,000,
  **not** the $200,000 quoted everywhere for single filers

Ship `verify_brackets.py` printing each number beside the IRS URL.

`calc_tax.py`, explaining each step in plain terms as it runs:

```
net profit = (hostlyft income + marcus income) − expenses_usd
             ← BOTH businesses; SE tax is on combined net earnings
             ← expenses use ACTUAL WITHDRAWALS, not the sheet's
               lagged payout allocations (finding 4)
SE tax     = 15.3% × (92.35% × net profit)
             SS portion capped at $184,500; Medicare uncapped
             +0.9% above $125,000
             → $0 if the certificate-of-coverage setting is on
FEIE       = min(net profit, $132,900)
taxable    = max(0, net profit − FEIE − half SE tax − $16,100)
income tax = MFS brackets on `taxable`, stacking rule above the FEIE cap
TOTAL      = SE tax + income tax   ← in practice almost entirely SE tax
```

An editable `settings` block holds: filing status (MFS), country (France), bona
fide residence (true), certificate of coverage (false — she flips it if obtained).

Also explain the **safe harbor** rule: paying 100% of last year's total tax shields
her from underpayment penalties regardless of how this year lands.

### Stage 10 — Reminders, contractor alarm, FBAR, jars

`taxlib/notify.py` — desktop notification via `osascript`, email via Gmail SMTP
(`smtp.gmail.com:587`, STARTTLS, stdlib `smtplib`). README walks through enabling
2-Step Verification **first** (app passwords don't exist without it), then
generating one at myaccount.google.com/apppasswords. Her address:
help.hostlyft@gmail.com.

**Scheduling is NOT set up in this stage.** Build the alert scripts so they can be
run by hand and tested; the schedule is installed last, in Stage 13, on her main
computer. Each alert must be runnable on demand.

Alerts:
- **Quarterly tax** — one week before Apr 15, Jun 15, Sep 15, Jan 15
- **FBAR** — late March, October backstop. She runs her business through Wise, a
  foreign account. If all foreign accounts combined exceeded **$10,000 at any
  point**, **FinCEN Form 114** is required — filed with FinCEN, *not* the IRS. Due
  April 15, automatic extension to October 15. Civil and criminal penalties apply.
  Nothing else prompts for it, which is why it's here.
- **1 December "still in jars"** — money left in jars on 31 December is not
  deductible that year but is still her money, inflating taxable profit. At 15.3%,
  $8,000 left in jars costs ~**$1,224** in real tax. Target: **jars empty by ~20
  December**. Alert from 1 December so she can chase.

Testing, which she asked for explicitly: `--test-notify` fires both immediately,
`--dry-run` shows what would happen without sending.

### Stage 11 — Google Sheet reconciliation

Writes **new tabs only**:

- `Raw_Income`, `Raw_Expenses` — every Stripe and Wise transaction, with dates,
  source IDs and the `business` tag
- `Business_Summary` — three views: **Hostlyft only** (excluding Marcus, so the
  P&L she uses for team splits is honest), **Marcus only**, and **combined** for
  tax
- `Reconciliation` — per person: **running cumulative earned, cumulative withdrawn,
  current jar balance, and the gap**. She chose a running balance over
  month-by-month, since monthly mismatches are expected and noisy
- Sheet-vs-database disagreement check

Never writes to her existing tabs. Refuses to run rather than overwrite anything.

### Stage 12 — Contractor forms tracker

- **Katerina** — W-9 on file? 1099-NEC alert at $600 of **withdrawals**
- **Ayoka, Jane, Sunniva** — W-8BEN on file? No 1099
- Flags anyone missing their form — the real exposure
- **Sunniva still gets a year-end flag even if under $600**, as she asked
- Alerts recorded so each fires once

### Stage 13 — Scheduling (LAST — and on her main computer)

**Do this only after every other stage is built, tested and working by hand.** She
was explicit: the schedule goes on her **main computer**, which may not be the
machine the build happens on. See "Which machine" below.

**Her choice: launchd for the alerts, cron for the daily sync.**

Why the split. `cron` skips any run scheduled while the Mac is asleep — silently,
with no catch-up. For the daily sync that is tolerable, because each run re-reads a
trailing window and a missed day is picked up by the next one. For the quarterly
tax alert, the FBAR reminder and the 1 December jars warning, a silently skipped
run defeats the entire purpose, so those use `launchd`, whose
`StartCalendarInterval` runs a missed job when the Mac next wakes.

| Job | Mechanism | When |
|---|---|---|
| Daily sync | cron | **11:00 daily** — her working hours, most likely awake |
| Weekly digest (exceptions only) | cron | Monday 11:00 |
| Monthly close + reconciliation | cron | 1st, 11:00 |
| Quarterly tax estimate | **launchd** | Apr 8, Jun 8, Sep 8, Jan 8 |
| FBAR | **launchd** | Late March, October backstop |
| Jars warning | **launchd** | 1 December |
| Forms check (W-9 / W-8BEN) | **launchd** | January |

Two Mac traps to document — both fail **silently**:
- `cron` needs **Full Disk Access** (System Settings → Privacy & Security) or jobs
  never run
- Terminal needs **notification permission** or `osascript` alerts never appear

If 11:00 runs are often missed because the Mac is closed, moving the sync to
launchd is a one-line change — note this in the README rather than pre-emptively
complicating it.

Verification she asked for: trigger each job manually first, confirm the
notification and email arrive, then check the log shows the scheduled run firing on
its own before trusting it. `/var/mail/$USER` confirms cron fired; `launchctl list`
shows the launchd jobs.

---

## Ongoing operation — this is an automation, not a one-off

She confirmed this must run continuously, not be re-run by hand.

**Daily sync** (`run_daily.py`): pull Stripe → pull Wise (both profiles) → convert
to USD → categorize → check contractor thresholds. Silent unless something needs
her.

**Two properties that make repetition safe:**

1. **Idempotent.** Every record carries its Stripe/Wise ID, so a repeat run updates
   rather than inserts. Running twice can never double her income. This is what
   makes scheduling safe at all — test it explicitly.
2. **Trailing 30-day window.** Each run re-reads the last 30 days, not merely
   "since last sync". So a missed run is not a lost run, and — importantly —
   Stripe refunds and Wise corrections that alter an *already-recorded*
   transaction get picked up.

First run backfills from 1 January 2026; subsequent runs use the trailing window.

**Weekly digest** (Monday) — **exceptions only**, her explicit choice. Send only
when something needs her: uncategorised vendors, a contractor approaching or
crossing $600, a failed sync, a reconciliation mismatch, a jar balance growing
unusually. A silent week means nothing needs her. Do not send routine "all is well"
mail — it trains her to ignore the channel.

**Monthly** (1st) — reconcile team earned/in-jar/withdrawn, refresh sheet tabs,
full summary. Matches her sheet's monthly tabs and one-month payout lag.

**Failure alerting — build this, it is not optional.** A silently broken automation
is worse than none, because she will trust it:

- Any failed run emails her with the reason (expired Stripe key, Wise SCA
  rejection, network failure, Google credentials revoked)
- A **heartbeat check**: if no sync has succeeded in 7 days, that is itself an
  alert
- A rotating log file recording every run, what it did, and what it changed

**Token expiry is a when, not an if.** Wise personal tokens and Google service
account keys can be revoked or expire. Fail with a plain-English message naming
which credential died and how to replace it — not a stack trace.

### Migration to her main Mac — CONFIRMED, this WILL happen

**She is building on her current MacBook Pro and switching to a different main Mac
at the very end.** So Stage 13 is a *migration*, not merely a schedule install.

`git clone` brings the code. It deliberately does **not** bring:

- `.env` — Stripe key, Wise token, Gmail app password, Google sheet ID
- the Wise private signing key
- the Google service-account JSON
- `hostlyft_tax.db` — every financial record

**Recommended: move the data, regenerate the secrets.**

- **Database** — AirDrop the single `.db` file. Mac-to-Mac, encrypted, never
  touching cloud storage or email. It carries transaction history, categorisation
  decisions and the record of which alerts already fired, so copying beats
  rebuilding.
- **Secrets** — create fresh on the main Mac rather than copying. Stripe key and
  Gmail app password are simply re-entered. The Wise keypair is regenerated and its
  public half re-uploaded to her Wise settings (~10 min). The Google service-account
  JSON is re-downloaded from the Cloud console. **No private key travels between
  machines.**

Fallback if regeneration proves awkward: AirDrop those too — acceptable between two
Macs she owns, never via email or cloud sync.

**Then, and only then:**

1. `check_setup.py` — one command verifying every dependency on the new machine:
   env vars present, Stripe authenticates, Wise authenticates *including the SCA
   signature*, Google Sheets writable, database readable, desktop notification
   appears, test email arrives. Turns "did I move everything?" into a yes/no.
2. Install the schedule.
3. **Delete `.env`, the keys and the database from the build Mac.** Live
   credentials left on a secondary machine are a real exposure — put it on the
   checklist, not in her memory.

---

## Tests

Each stage ships tests runnable in one command:

1. Stripe→Wise fixture asserting income totals **$2,000, not $3,940** — the one
   that matters most
2. Every import run twice — totals must not change
3. FX conversion on a Saturday date, proving business-day fallback
4. Wise SCA request signing verified against its own public key
5. Synthetic Capital One CSV, including a card payment that must be skipped
6. `calc_tax.py` at $80,000 profit → income tax **$0**, SE tax **≈$11,304**; the
   certificate toggle flipping SE tax to **$0**
7. `calc_tax.py` at $150,000 → exercises the FEIE cap and stacking rule
8. Reconciliation: someone earning $5,000 who withdrew $3,200 shows a $1,800
   running gap; jar balance agrees
9. Sheet-vs-database mismatch detected and reported
10. Dry run proving no existing tab is modified — diff the sheet before and after
11. $600 alert fires on **withdrawals**, not jar allocations
12. Katerina's row → 1099-NEC alert; other three → W-8BEN reminders, no 1099
13. Marcus income is included in the tax total but excluded from Hostlyft-only
    reporting; personal-account rows other than Marcus are never stored
14. **Idempotency under repetition** — run the daily sync three times over the same
    period; income, expense and contractor totals must be identical each time
15. A simulated failure (bad token) produces an email naming the credential, not a
    stack trace; the heartbeat fires when no sync has succeeded in 7 days

## Out of scope — flag, don't guess

French income tax and French social contributions (her likely larger exposure),
Foreign Tax Credit modelling (nothing to credit — she pays no French income tax),
US state tax, home-office/vehicle/mileage/depreciation, filing anything, paying
anyone. Also out of scope: advising Katerina on her own US filing — that is hers.

**One decision to raise before she files, not now:** whether the Marcus work is the
same trade or business as Hostlyft (one Schedule C) or a separate one (two
Schedule Cs). She described it as "related but not identical". Total tax is
identical either way; only expense attribution differs.
