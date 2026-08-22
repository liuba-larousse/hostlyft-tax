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
| `setup_mac.command` | Double-click to set the project up. Safe to run again. |
| `run_tests.command` | Double-click to run every automatic check. |
| `requirements.txt` | The list of libraries to install, with a note on why each is needed. |
| `.env.example` | Blank template naming every secret and where to get it. Safe for GitHub. |
| `taxlib/` | Shared code — settings, currency, categorisation, notifications. |
| `taxlib/config.py` | Paths, secret-reading, and your tax settings. Everything else asks this file. |
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

**Why a file rather than exports in `~/.zshrc`:** the scheduled 9am reminder
runs under `cron`, and cron does not load your shell settings. Anything exported
in `.zshrc` simply wouldn't exist, and the reminder would fail silently — the
worst kind of failure, because you'd never know it stopped.

---

## Build progress

| Stage | What it adds | Status |
|---|---|---|
| 1 | Skeleton — setup script, settings, secrets template | ✅ done |
| 2 | Database — income, expenses, payouts, FX cache, alerts | not started |
| 3 | Secrets walkthrough | not started |
| 4 | Stripe income (gross, with fees as expenses) | not started |
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
