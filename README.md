# Hostlyft LLC — Tax Tracker

A free, local system for tracking Hostlyft LLC's business income and expenses,
converting them to USD, categorizing spending, estimating quarterly US federal
tax, and sending reminders before deadlines.

Everything runs on one Mac. No paid services, no cloud, no subscriptions. The
financial database never leaves the machine.

## New here? Read **[START-HERE.md](START-HERE.md)**

It walks through the Mac setup in plain English — installing Claude Code, getting
a GitHub token, downloading this code, and starting the build. No prior coding
experience assumed.

## What's in this repo

| File | What it is |
|---|---|
| `START-HERE.md` | Step-by-step Mac setup guide. Start here. |
| `PLAN.md` | The ten-stage build plan, with the tax research and design decisions already made. |
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

## Status

Planning complete, no code written yet. The build happens on the Mac, where
Stripe, Wise, the exchange-rate API and Gmail are all reachable.

## Important

This estimates what to set aside for **US federal tax only**. It is not tax
advice, does not cover French tax obligations, and does not file anything.
