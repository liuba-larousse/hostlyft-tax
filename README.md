# Hostlyft LLC — Tax Tracker

A free, local system for tracking Hostlyft LLC's business income and expenses,
converting them to USD, categorizing spending, estimating quarterly US federal
tax, and sending reminders before deadlines.

Everything runs on one Mac. No paid services, no cloud, no subscriptions. The
financial database never leaves the machine.

> **New here?** Read **[START-HERE.md](START-HERE.md)** first — it covers
> installing Claude Code and downloading this code.

---

## Setup — do this once

Open **Finder**, go to this folder, and **double-click `setup_mac.command`**.

A Terminal window opens and walks through six steps. It takes about a minute.
When it says *Setup finished*, you're done. Blank secrets at that point are
expected and correct.

If double-clicking is blocked by macOS, run it from Terminal instead:

```
cd ~/Documents/hostlyft-tax
./setup_mac.command
```

### What setup actually does

| Step | In plain English |
|---|---|
| Checks Python | Python is the language this is written in. macOS includes it. |
| Builds `.venv` | A **virtual environment** — a private folder holding this project's libraries, sealed off from the rest of your Mac. |
| Installs libraries | Downloads the four tools listed in `requirements.txt` into `.venv`. |
| Creates `tax/` | The private folder for your secrets and your database. Locked to your account. |
| Creates `tax/.env` | Your personal copy of `.env.example`, where real API keys go. |
| Prints a status check | Shows what's configured and what's still blank. |

**Why a virtual environment matters.** Installing a library normally affects
your whole Mac, and can break an unrelated program that needed a different
version. `.venv` keeps everything this project installs inside one folder.
Deleting that folder undoes it completely — nothing else is touched. It is not
backed up to GitHub; it's rebuilt by re-running setup.

---

## Using it day to day

Two commands, every time you open a new Terminal window:

```
cd ~/Documents/hostlyft-tax
source .venv/bin/activate
```

The second line is the one people forget. It switches Terminal over to this
project's private libraries. You'll know it worked because your prompt gains a
`(.venv)` prefix.

Then, to see your configuration at any point:

```
python -m taxlib.config
```

To run every automatic check (or just double-click `run_tests.command`):

```
python -m pytest
```

---

## What's in this repo

| File / folder | What it is |
|---|---|
| `START-HERE.md` | Mac setup guide — installing Claude Code, GitHub token, downloading the code. |
| `PLAN.md` | The ten-stage build plan, with the tax research and design decisions already made. |
| `SECRETS.md` | Walkthrough for putting your API keys in `tax/.env`. |
| `setup_mac.command` | Double-click to set the project up. Safe to run again. |
| `run_tests.command` | Double-click to run every automatic check. |
| `requirements.txt` | The list of libraries to install, with a note on why each is needed. |
| `.env.example` | Blank template naming every secret and where to get it. Safe for GitHub. |
| `taxlib/` | Shared code — settings, currency, categorisation, notifications. |
| `taxlib/config.py` | Paths, secret-reading, and your tax settings. Everything else asks this file. |
| `taxlib/db.py` | The database: its layout, and every read and write. |
| `scripts/init_db.py` | Creates the database, or reports what's in it. |
| `scripts/check_secrets.py` | Checks `tax/.env` is safe and correctly filled in. |
| `scripts/pull_stripe.py` | Imports Stripe income, fees and payouts. |
| `taxlib/stripe_import.py` | The rules deciding what counts as income. |
| `taxlib/fx.py` | Currency conversion, and the saved rates. |
| `scripts/convert_currency.py` | Puts a US dollar figure on every foreign entry. |
| `taxlib/wise_sca.py` | Signing, so Wise will release statements. |
| `taxlib/wise_import.py` | Classifies every Wise transaction. |
| `scripts/pull_wise.py` | Imports Wise across all three accounts. |
| `taxlib/csv_import.py` | HubSpot and Upwork file imports. |
| `taxlib/capitalone.py` | The card statement, with column detection. |
| `scripts/import_files.py` | Runs those file imports. |
| `taxlib/categorize.py` | Applies the rules in `rules.txt`. |
| `scripts/categorize.py` | Sorts expenses; lists anything it can't. |
| `rules.txt` | **Your** plain-English category rules. Edit freely. |
| `taxlib/gsheets.py` | Google sign-in, retries, reading cell notes. |
| `taxlib/tax_sheet.py` | Builds the tax spreadsheet. |
| `scripts/google_login.py` | One-time Google sign-in. |
| `scripts/build_tax_sheet.py` | Creates or refreshes the tax sheet. |
| `GOOGLE-SETUP.md` | Walkthrough for connecting Google. |
| `taxlib/constants_2026.py` | Every tax figure, with its source. |
| `taxlib/tax.py` | The calculation, step by step. |
| `scripts/verify_brackets.py` | Prints each figure beside its source. |
| `scripts/calc_tax.py` | What to set aside, and why. |
| `scripts/verify_receipts.py` | Traces every invoice to money. |
| `INCOME-SOURCES.md` | Where the money actually comes from. |
| `scripts/wise_keys.py` | Creates and checks the Wise key pair. |
| `scripts/` | The things you actually run — pulling from Stripe, calculating tax, sending reminders. |
| `tests/` | The automatic checks. |
| `tax/` | **Your private data.** Secrets, database and Wise signing key. Never uploaded. |
| `.gitignore` | Keeps secrets, the database, the Wise signing key and bank exports out of GitHub. |

## What it will do

- Pull paid invoices from **Stripe** as itemized income (gross, with processor
  fees recorded separately as deductible expenses)
- Pull **Wise** transactions for expenses, tagging Stripe payouts as internal
  transfers so income is never double-counted
- Read the per-person **Wise Jars** and reconcile what each team member has
  earned against what they have actually withdrawn
- Convert every amount to USD using the rate on the transaction's date
- Write reconciliation tabs into the existing `Hostlyft_Accounting_2026` Google
  Sheet — new tabs only, never touching the originals
- Estimate quarterly US federal tax and send desktop + email reminders
- Track contractor payment thresholds and which tax forms are on file

### Where your secrets live

`tax/.env` holds your real API keys. Three things keep it private:

1. It's inside `tax/`, which is listed in `.gitignore` — **git refuses to
   upload it**, even if you ask.
2. File permission `600` — only your Mac account can read it.
3. It is never printed. The status check shows only `set` or `blank`.

A test in `tests/test_stage1_config.py` asks git directly whether it would
ignore `tax/.env`, `tax/hostlyft_tax.db` and the Wise private key. If any answer
were ever "no", the tests fail.

**Filling them in:** see **[SECRETS.md](SECRETS.md)** for the full walkthrough.
Then check your work:

```
python scripts/check_secrets.py             # is it safe, and the right shape?
python scripts/check_secrets.py --connect   # do the keys actually work?
```

Neither ever prints a secret — only its shape, e.g. *"starts with `sk_live_`,
107 characters"*. That output is safe to show to anyone.

**Never paste a key into a chat, document or email.** If you do, don't try to
delete the message — go and **roll** the key at the service. The old one dies
instantly. It's free, takes ten seconds, and is completely routine.

**Why a file rather than exports in `~/.zshrc`:** the scheduled 9am reminder
runs under `cron`, and cron does not load your shell settings. Anything exported
in `.zshrc` simply wouldn't exist, and the reminder would fail silently — the
worst kind of failure, because you'd never know it stopped.

---

## The database

One ordinary file: `tax/hostlyft_tax.db`.

It uses **SQLite** — a complete database that lives entirely inside a single
file. Nothing to install, no server to keep running, no account, no monthly fee.
Python has it built in. Copying that one file is a complete backup.

Create it, or see what's in it:

```
python scripts/init_db.py            # create it (safe to re-run)
python scripts/init_db.py --show     # just report, change nothing
python scripts/init_db.py --year 2026
```

### The five tables

| Table | What it holds |
|---|---|
| `income` | Money you earned. Stored **gross** — see below. |
| `expenses` | Money you spent that reduces taxable profit. |
| `stripe_payouts` | **Not income.** The reference list that stops money being counted twice. |
| `fx_rates` | Every exchange rate ever used, saved. |
| `alerts_sent` | Reminders already sent, so each fires once. |

### Income is stored gross, never net

A $2,000 invoice with a $60 Stripe fee is income of **$2,000** *plus* a
deductible expense of **$60**. It is never income of $1,940.

Schedule C asks for gross receipts. Recording the net figure silently throws
away the $60 deduction — you'd pay tax on money you never received.

### Why `stripe_payouts` exists

Stripe reports a $2,000 invoice. Six days later Stripe sends $1,940 onward and
Wise reports it arriving. Added up naively that is **$3,940** — tax on nearly
double what you earned.

Stage 6 checks every incoming Wise payment against the list of Stripe payouts.
This table is that list; without it there is nothing to compare against. A
matched credit is still saved, but marked `excluded`, so the decision stays
visible instead of a transaction quietly disappearing.

### Re-running an import is always safe

Every row carries the system it came from and its ID in that system. Those two
together must be unique, so importing the same invoice twice **updates** the
existing row rather than adding a second one. Import as often as you like — the
totals will not move. A test proves this by importing the same data three times
and checking the totals are identical.

### Rounding

Money is rounded with a half always going **up**. Python's built-in `round()`
rounds a halfway value to the nearest *even* number — `round(0.125, 2)` gives
`0.12`, not `0.13`. Correct for statistics, wrong for money. A test pins this.

### Nothing is guessed

Three flags exist so an uncertain answer is never presented as a certain one:

- `excluded` — deliberately left out of totals, with the reason recorded
- `needs_review` — the importer was unsure and refused to guess
- `uncategorized` — no category rule matched yet

`init_db.py --show` reports counts for all three, plus anything not yet
converted to USD. An entry with no USD figure counts as $0, so it says so rather
than passing off a partial total as a complete one.

---

## Importing from Stripe

```
python scripts/pull_stripe.py --dry-run   # show everything, write nothing
python scripts/pull_stripe.py             # import for real
python scripts/pull_stripe.py --year 2025
```

Safe to run any time. Every row is matched on its Stripe ID, so re-running
updates what's there rather than adding it again.

### Income is gross; unpaid invoices are not income

A $225 invoice where Stripe keeps $10.20 is income of **$225** plus an expense
of **$10.20**. Never income of $214.80.

Only **paid** invoices count. Money owed to you isn't money received — open and
draft invoices are listed separately so you can see what's outstanding, but they
stay out of the totals.

### The trap this importer is built around

In this account, **every payment is also an invoice**. Import both and every
payment is counted twice.

That's easy to get wrong, because Stripe's current API deliberately leaves
`charge.invoice` **empty** — so a payment *looks* standalone when it isn't. The
real link runs the other way:

```
invoice  →  payments  →  payment_intent  →  charge
```

The importer builds the set of payment intents belonging to invoices and only
treats a payment as separate income if it genuinely isn't in that set. Anything
it does treat as separate is **flagged for review**, never quietly added — that
flag is where a future double-count would show up first.

### Three kinds of Stripe fee, not one

All three are deductible, and each one missed is a lost deduction:

| Fee | How it arrives |
|---|---|
| Processing fee | taken out of each payment |
| Invoicing fee | a separate ledger entry, no payment attached |
| Multicurrency settlement fee | a separate ledger entry, no payment attached |

The last two are invisible to anything that only looks at payments. Each can
also carry tax on top — a $0.90 invoicing fee with $0.07 tax is recorded as
**$0.97**, because that's what it actually cost.

Checked against the real account, for all three currencies:

```
payout = payment − processing fee − invoicing fee − settlement fee
```

to the cent.

### Nothing is silently dropped

If Stripe ever introduces a kind of ledger entry this importer doesn't
recognise, it says so and tells you to mention it, rather than staying quiet and
leaving money out of the totals.

---

## Currency conversion

```
python scripts/convert_currency.py --dry-run   # show, change nothing
python scripts/convert_currency.py             # convert for real
python scripts/convert_currency.py --rates     # list the rates saved
```

Rates come from the **Frankfurter API** — free with no key, no signup, no quota
and no card, because it's a thin public wrapper over the reference rates the
**European Central Bank** publishes daily as a public service. History back to
1999.

### Both amounts are always kept

The original amount and currency are never touched. The dollar figure is stored
*next to* them, along with the rate used and the date that rate came from. You
can always check the working.

### The ECB only publishes on business days

There's no rate for a Saturday, a Sunday, Christmas Day or Easter Monday. The
previous business day's rate is used, and **both dates are recorded**:

```
2026-08-08   9.00 EUR  ->  $10.38   rate 1.1535 from 2026-08-07  <- 1d earlier
```

A gap of one to four days is a normal weekend or public holiday. Anything longer
is flagged for you to look at.

### A future date returns a stale rate — silently

Asked for a date a week from now, the service returns **200 OK with last
Friday's rate** and no warning whatsoever. A mistyped year would quietly produce
a wrong but entirely plausible number.

So future dates are refused here, before the request is ever made.

### Unsupported currencies fail loudly

The ECB covers about 30 currencies. USD, EUR and GBP are all included. Anything
else stops with an explanation and a suggestion — it is never guessed. A wrong
rate on a tax return with nothing to show it was a guess is far worse than an
honest gap.

### Re-importing doesn't undo the conversion

Stage 4 imports a €900 invoice with no dollar figure — it doesn't know the rate.
Stage 5 works it out. Then Stage 4 runs again, still offering no dollar figure.

Handled naively, that second import **erases the conversion**, and the totals
silently drop back to counting the invoice as $0. Nothing errors; the number is
just quietly wrong.

So a re-import keeps the conversion — but **only while the amount and currency
are unchanged**. If Stripe ever corrects an invoice from €900 to €1,000, the old
dollar figure is now wrong, so it's cleared and worked out again. A stale
conversion would be worse than none.

### The simpler official alternative

The IRS also publishes a **single yearly average rate** per currency and accepts
it for translating foreign income, as long as you're consistent:

> *"Yearly average currency exchange rates"* —
> https://www.irs.gov/individuals/international-taxpayers/yearly-average-currency-exchange-rates

Daily rates are more precise and are what this tool uses. If daily ever becomes
more maintenance than it's worth, the yearly average is the sanctioned fallback:
one number per currency per year, applied to every transaction in that currency.
Pick one method and stay with it — mixing them within a year is what causes
problems.

---

## Two businesses, one tax return

Every income and expense row carries a `business` tag:

| Tag | What it is |
|---|---|
| `hostlyft` | work done through Hostlyft LLC |
| `marcus` | separate work, paid into the personal Wise account |

They **report separately**, so the Hostlyft profit-and-loss used for team splits
stays honest. They are **taxed together**, because a single-member LLC is a
disregarded entity — both land on the same 1040. Self-employment tax is worked
out on the combined figure, and the FEIE and Social Security caps are combined
limits too.

Leaving Marcus out would understate self-employment tax by roughly **$6,900**.

An unknown tag is rejected rather than accepted. A typo like `marcuss` would
otherwise create a silent third business that no report ever shows, and the money
would simply vanish from every total without an error.

---

## A jar is not a payment

A Wise jar is a labelled pot **inside your own account**. Moving money into one
pays nobody — it is still your money. So:

- allocating to a jar is **not** a deductible expense
- only an actual **withdrawal** is deductible
- only **withdrawals** count toward the $600 threshold
- jar balances still count toward the FBAR $10,000 test

Three numbers per person, never conflated:

| Number | Where it comes from | What it's for |
|---|---|---|
| Earned | the Sheet's split calculation | team management |
| In jar | Wise SAVINGS balance | cash held on their behalf |
| **Withdrawn** | actual transfers out | **the tax deduction** |

This is enforced structurally, not by remembering: jar balances live in the
`wise_jars` table and the `expenses` table has no way to hold one. An owner's
draw is recorded as excluded with a reason — visible, but not reducing profit.

**The December consequence.** Money still in jars on 31 December isn't deductible
that year but still inflates taxable profit. At 15.3%, **$8,000 left in jars
costs about $1,224** in real tax. Stage 10 warns from 1 December.

---

## The team

| Name | Also known as | Status | Form | 1099-NEC? |
|---|---|---|---|---|
| Katerina Mrvova | — | **US citizen** | **W-9** | **yes, at $600** |
| Yetunde Olaniyan | Ayoka | not a US person | W-8BEN | no |
| Olaide Olaniyan | — | not a US person | W-8BEN | no |
| Evgeniya Dyatlovskaya | Jane | not a US person | W-8BEN | no |
| Sunniva Texe | — | not a US person | W-8BEN | no |

Wise transfers may be labelled with a full name **or** a nickname, so both are
matched — "Ayoka" and "Yetunde Olaniyan" are one person, and missing one form
would split the total and hide a $600 crossing.

Matching is on **whole words only**. Without that, "Jane" would match "Janet" and
quietly attribute a stranger's payment to a contractor.

Katerina's US-person status is written as a fixed fact rather than a setting, and
a test pins it. US citizenship decides it; dual nationality and living abroad
don't change it, and a US citizen cannot sign a W-8BEN because that form
certifies foreign status. A missing W-9 TIN triggers 24% backup withholding.

---

## Reconciliation

```
python scripts/reconcile.py            # compare, print, record
python scripts/reconcile.py --no-save  # just look
```

**Your accounting sheet is only ever read.** Nothing in this system writes to it.
The tax sheet, which this system does own, is separate.

### Per person — three numbers that must never be confused

| Number | Where it comes from | What it's for |
|---|---|---|
| **Earned** | your sheet's split calculation | team management |
| **Withdrawn** | actual Wise transfers out | **the tax deduction** |
| **In jar** | Wise savings balances | money set aside, still yours |

`gap = earned − withdrawn − in jar`. Positive means someone has earned money that
has neither been paid to them nor set aside. Negative means more has been paid or
reserved than the sheet says they earned.

**The split rules are read, never recalculated.** The 5% off the top, the 70%
shared between Katerina and Ayoka, Evgeniya's 80%, Sunniva's $25/hr — all of that
already lives in your sheet's formulas. Reimplementing it here would create a
second version to drift out of step with the first.

**Rows are found by their label, never their position.** The monthly tabs are not
identically laid out — May has an extra payout row that July doesn't, which shifts
everything below it. Reading "row 56" would pick up the wrong person's money.

### Sheet against database

Compares your sheet's Hostlyft income, month by month, against what Stripe and
Wise actually reported. It **reports** disagreement and stops — it never resolves
it. Neither record is automatically right: the sheet holds decisions the bank
can't see, and the bank holds transactions that may not have been typed in yet.

**Single months are expected to differ.** The database records income in the month
the money *arrived*; your sheet records it against the month it was *for*. An
invoice raised in one month and paid the next lands in different months in the two
records without either being wrong. **The year total is the comparison that
means something.**

### What it refuses to guess

Payout rows labelled only `Olaniyan (subcontractor)` are reported, not attributed.
Two people on the roster share that surname, and crediting the row to the wrong one
would move somebody's $600 threshold.

---

## Reminders

Nothing is on a timer yet. Every alert is run by hand and works out for itself
whether today is the day. Putting it on a schedule is Stage 13, on the main Mac.

```
python scripts/check_alerts.py --dry-run      # what would be sent. Sends nothing.
python scripts/check_alerts.py                # actually send
python scripts/check_alerts.py --test-notify  # prove both channels work
python scripts/check_alerts.py --on 2026-12-01 --dry-run   # pretend it's December
```

Five things can raise an alert:

| Alert | When |
|---|---|
| Quarterly estimated tax | the 7 days before 15 Apr, 15 Jun, 15 Sep, 15 Jan |
| FBAR | late March, and again in early October |
| Money still in jars | any day in December |
| $600 contractor threshold | as soon as withdrawals cross it |
| Missing W-9 / W-8BEN | any day one is missing, wrong or expired |

**Each is sent once**, recorded in `alerts_sent`, and not repeated. A run that
says nothing needs you is the normal result — that silence is what makes the
noisy days worth reading. `--force` sends again anyway.

**A failed send is not recorded as sent.** If the Mac is offline the alert stays
pending and goes out on the next run, rather than being marked done and never
seen.

### Two ways it reaches you, on purpose

A desktop notification you saw and forgot is the same as one you never saw, so
anything that matters also goes to email. Email needs a Gmail **app password** —
not your Gmail password, which Google no longer accepts from programs. Turn on
2-Step Verification first (app passwords don't exist without it), then create one
at https://myaccount.google.com/apppasswords and put it in `tax/.env` as
`GMAIL_APP_PASSWORD`.

**`osascript` reporting success does not prove a notification appeared.** If
Terminal has never been granted notification permission, macOS discards it
silently and reports success anyway. System Settings → Notifications → Terminal →
Allow Notifications. This is a real macOS behaviour, and it is why the desktop
channel is never used alone.

### What the FBAR alert deliberately will not tell you

FBAR asks whether **all** your foreign accounts **combined** ever topped $10,000
at **any moment** in the year. This database holds jar balances on the handful of
days a sync ran, and does not hold your main Wise operating balance at all — so it
cannot answer that. The alert says so plainly and sends you to your Wise
statements. A confident "you're under the limit" from this data would be a wrong
answer about something carrying criminal penalties.

---

## Contractor forms

```
python scripts/check_forms.py                          # where everyone stands
python scripts/check_forms.py --received "Katerina Mrvova" --on 2026-09-10 --tin
python scripts/check_forms.py --received "Yetunde Olaniyan" --on 2026-09-10
python scripts/check_forms.py --not-received "Sunniva Texe"    # undo
```

**Which form somebody needs is not set here.** That comes from the roster in
`taxlib/config.py`, which records why each person is treated as they are. This
only records whether the form has actually arrived.

Three things this catches that "did the form come back?" alone would miss:

- **A W-8BEN expires.** It is valid until the last day of the third calendar year
  after signing — one signed in June 2026 lapses on 31 December 2029. An expired
  form is worth no more than a missing one, and nothing else would notice. The
  expiry date is worked out for you; you never type it.
- **A W-9 without a taxpayer ID number** is on file but not usable — 24% backup
  withholding still applies. Recorded separately from "received" for that reason.
- **The wrong form.** A US citizen signing a W-8BEN is not merely unhelpful; that
  form certifies *foreign* status.

**Collecting the form and issuing a 1099 are different obligations.** The form is
owed from the first dollar, with no threshold. The 1099 applies only to Katerina,
and only past $600 of withdrawals. Being under $600 removes the 1099, never the
form — the form is what establishes no 1099 is owed.

### The $600 threshold is Katerina's alone

Not a higher threshold for the other four — **none at all.** $600 is the 1099-NEC
filing threshold, and a 1099-NEC reports payments to **US persons**. Payment for
services is sourced by *where the work is done*, so work performed abroad by a
non-US person is foreign-source income: no 1099-NEC, no 1042-S, no withholding, and
no amount at which anything starts.

So the four foreign contractors are tracked on one question — **is the W-8BEN on
file and current** — which has no threshold and applies from the first dollar. A
missing W-8BEN on someone paid $5,470 is serious, but it is a missing form, not a
crossed line with a January deadline, and the tool no longer describes it as one.

The caveat, worth recognising rather than acting on: this holds because the work is
done outside the US. Services performed *inside* the US become US-source and fall
under different rules.

---

## Upgrading the database

`CREATE TABLE IF NOT EXISTS` adds missing tables, but it will **not** add a
column to a table that already exists. So when a later stage needs a new column,
the database holding your real records is altered in place.

Rebuilding instead would throw away every transaction, every categorisation
decision, and the record of which alerts have already fired. That's never the
right trade.

```
python scripts/init_db.py     # creates, or upgrades in place. Safe to re-run.
```

Each migration step is written so running it twice is harmless. Back up first —
`tax/backups/` holds a snapshot taken before each upgrade.

---

## Build progress

| Stage | What it adds | Status |
|---|---|---|
| 1 | Skeleton — setup script, settings, secrets template | ✅ done |
| 2 | Database — income, expenses, payouts, jars, ledger, FX cache, alerts | ✅ done |
| 3 | Secrets walkthrough | ✅ done |
| 4 | Stripe income (gross, with fees as expenses) | ✅ done |
| 5 | Currency conversion to USD | ✅ done |
| 6 | Wise — all three accounts, jars, double-count prevention | ✅ done |
| 7 | File imports — Capital One, HubSpot, Upwork | ✅ done |
| 8 | Categorization | ✅ done |
| 9 | Tax calculator (both businesses combined) | ✅ done |
| 10 | Reminders — quarterly, FBAR, jars, contractor alarm | ✅ done |
| 11 | Google tax sheet + reconciliation | ✅ done |
| 12 | Contractor forms tracker (W-9 / W-8BEN) | ✅ done |
| 12b | Home office, travel, meals, equipment deductions | not started |
| 13 | Scheduling + migration to the main Mac | not started |


Currency conversion (Stage 5) deliberately comes before Wise (Stage 6): Wise
holds several currencies at once, so the converter has to exist first.

---

## Notes on this Mac

- Python **3.9.6**, the version Apple ships. Nothing extra was installed.
- `urllib3` is pinned below version 2 in `requirements.txt`. Apple's Python is
  built against an older encryption library (LibreSSL), and urllib3 v2 prints a
  warning about it on every run. Version 1.26 supports it properly and stays
  quiet. Secure connections work either way — this is about not training
  yourself to ignore warnings. If you ever install a newer Python from
  python.org, that pin can be removed.

---

## Important

This estimates what to set aside for **US federal tax only**. It is not tax
advice, does not cover French tax obligations, and does not file anything.
