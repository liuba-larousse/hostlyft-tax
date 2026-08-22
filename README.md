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
| `scripts/` | The things you actually run — pulling from Stripe, calculating tax, sending reminders. |
| `tests/` | The automatic checks. |
| `tax/` | **Your private data.** Secrets and database. Never uploaded. |

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

## Build progress

| Stage | What it adds | Status |
|---|---|---|
| 1 | Skeleton — setup script, settings, secrets template | ✅ done |
| 2 | Database — income, expenses, payouts, FX cache, alerts | ✅ done |
| 3 | Secrets walkthrough | ✅ done |
| 4 | Stripe income (gross, with fees as expenses) | ✅ done |
| 5 | Currency conversion to USD | not started |
| 6 | Wise + double-count prevention | not started |
| 7 | Capital One one-time CSV import | not started |
| 8 | Categorization | not started |
| 9 | Tax calculator | not started |
| 10 | Reminders, $600 contractor alarm, FBAR | not started |

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
