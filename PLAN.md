# Hostlyft LLC — Tax Tracking System: Build Plan

**For Claude:** this plan was written during a planning session in Claude Code on
the web, where every external service was blocked. It lives in its own repo
(`liuba-larousse/hostlyft-tax`), separate from the Hostlyft website codebase. It carries the research and
decisions already made. Read it fully, then start at Stage 1. The user has **no
coding experience** — explain each step in plain English before doing it, define
technical terms, and check in before moving between stages.

---

## The goal

A free, local system for Hostlyft LLC (single-member LLC) that tracks business
income and expenses, converts everything to USD, categorizes spending, estimates
quarterly federal tax, and sends reminders. No paid services. Everything runs on
the user's Mac.

## The user's tax situation (established — do not re-ask)

- **Married Filing Separately.** Married abroad to a non-US person, filing alone,
  no children living with her. The IRS counts a foreign marriage as married, so
  "filing alone" means MFS — **not Single**. Head of Household needs a qualifying
  dependent; she has none.
- Hostlyft is her **only income**. Standard deduction **$16,100**.
- **Lives in France**, settled permanently — bona fide residence, full year.
- **Pays no social security contributions anywhere.**
- **Pays no French income tax.**

**She explicitly rejected a conservative/padded estimate.** She is self-filing
with no CPA review, so an inflated number is simply a wrong number that costs her
cash flow all year. Build for accuracy, not for a safety margin. Do not re-add
"assume the worst" defaults.

## Three findings that cost real time to discover

**1. Wise blocks personal tokens from reading statements.** Under PSD2, the
statement endpoint rejects every personal-token request with HTTP 403 and an
`x-2fa-approval` header. The fix: generate an RSA keypair, upload the public key
in Wise settings, sign the one-time token from that header with the private key,
retry with the signed value. Budget ~20 minutes of user setup; it's the most
likely place to get stuck. Reference implementation:
`github.com/transferwise/digital-signatures-examples` (`sca-personal-tokens`).
Statement endpoint:
`GET /v1/profiles/{profileId}/balance-statements/{balanceId}/statement.json`
with `currency`, `intervalStart`, `intervalEnd`, `type=COMPACT`. Max window 469
days. Being deprecated in favour of v4 balances — check current docs, which are
reachable from the Mac.

**2. The IRS figures below were NOT read from the primary source.** The planning
sandbox blocked `irs.gov`. They were cross-checked across independent sources and
agree, but the PDF itself was never opened. **`irs.gov` is reachable from the
user's Mac, so the first task of Stage 9 is to open
https://www.irs.gov/pub/irs-drop/rp-25-32.pdf and verify every number against
Table 4 before the calculator is trusted.** Do not skip this.

**3. Record income gross, not net.** Schedule C asks for gross receipts. A $2,000
invoice with a $60 Stripe fee is income $2,000 **plus** a $60 deductible expense —
never income of $1,940. Netting silently loses the fee deduction.

---

## Structure

This repo IS the project — files at the root, no subfolder. Standalone Python,
separate from the hostlyft website repo entirely.

A `.gitignore` is already committed excluding `.env`, `*.db` and the virtual
environment, so her secrets and the database of real financial data never reach
GitHub. Code backed up; money not.

---

## Build order

Ten stages. Explain → user says go → build → user reviews → next.

One deviation from the user's original numbering: currency conversion (her step 5)
comes **before** Wise (her step 3b), because Wise is multi-currency and needs the
converter to exist. Tell her this, briefly.

### Stage 1 — Skeleton
`README.md`, `requirements.txt`, `.env.example`, `taxlib/config.py`,
`setup_mac.command` (double-clickable). Explain what a virtual environment is and
why it keeps libraries contained to this folder.

### Stage 2 — Database
SQLite = a complete database in one ordinary file (`tax/hostlyft_tax.db`). No
server, no signup, no fee — explain it that way.

Her two tables as specified:
- `income` — date, amount, currency, amount_usd, source, description
- `expenses` — date, amount, currency, amount_usd, category, description, vendor

Plus three needed for correctness:
- `stripe_payouts` — **not income**; the reference list the double-count check
  compares against. Without it there is nothing to match.
- `fx_rates` — cache, so re-runs give identical numbers and don't re-hit the API.
- `alerts_sent` — so the $600 alarm fires once, not every day forever.

Every row carries a source ID; re-running any import must update, never duplicate.

### Stage 3 — Secrets
`tax/.env`, `chmod 600`, never committed. Recommend the file over `~/.zshrc`
exports for one concrete reason worth explaining: **cron does not load shell
settings**, so exported variables vanish and the 9am reminder fails silently.
Full terminal walkthrough — `cd`, `nano`, `chmod` — each explained.

### Stage 4 — Stripe income
`scripts/pull_stripe.py`. Each paid invoice → one income row at **gross**; Stripe
fee → separate expense row. Also store payouts (amount, currency, `arrival_date`)
in `stripe_payouts` for Stage 6.

### Stage 5 — Currency conversion
`taxlib/fx.py` using the **Frankfurter API** (`api.frankfurter.dev`). Free because
it's a thin public wrapper over exchange rates the European Central Bank publishes
daily as a public service — no key, signup, quota, or card. History to 1999.

Two limits to code around and document:
- ECB publishes **business days only** — walk back to the last business day for
  weekend/holiday dates and record which date was actually used.
- ~30 major currencies. Anything else must fail loudly, never guess.

Store both original and USD amounts, always. Document the **IRS annual average
exchange rate** in the README as the sanctioned simpler fallback if daily-rate
conversion becomes too much to maintain — she asked for this explicitly.

### Stage 6 — Wise + double-count prevention
`scripts/wise_keys.py` (keypair generation, per finding 1), then
`scripts/pull_wise.py`.

The mechanism, which must be explained to her with the example below:
1. Stage 4 stored every Stripe payout.
2. Each **incoming** Wise credit is checked against that list.
3. Exact match on amount + currency within a few days → tag
   `internal transfer — already counted via Stripe`, **exclude from income**.
4. Close but inexact → `possible transfer — needs review`, surface it. Never
   silently guess either way.
5. Unmatched credit → flag for confirmation, never auto-add as income.
6. **Outgoing** payments → expenses.

Worked example — $2,000 invoice paid Sept 3, Stripe takes $60, pays out $1,940
arriving in Wise Sept 9:

| Source | Record | Income? |
|---|---|---|
| Stripe invoice | $2,000 | Yes — $2,000 |
| Stripe fee | $60 | No — expense |
| Wise credit Sept 9 | $1,940 → matched | **No — internal transfer** |

Counted: **$2,000**. Without the check: **$3,940** — tax on nearly double actual
earnings.

### Stage 7 — Capital One one-time import
`scripts/import_capitalone.py`. Historical only, April–July, run once, fully
offline.

README must explain the export: capitalone.com → the card → *View Statements* /
*Download Transactions* → date range → **CSV** → Download. Typical columns:
`Transaction Date, Posted Date, Card No., Description, Category, Debit, Credit`.
**Auto-detect the layout** rather than hard-coding — banks change these. **Skip
payments to the card itself** (transfers, not expenses — another double-count
trap). Refuse to run twice on the same file unless forced.

### Stage 8 — Categorization
`taxlib/categorize.py`, rules in a plain-English file she can edit without
touching code:
- PriceLabs, ClickUp, HubSpot → `software`
- Ayoka, Katerina, Jane, Sunniva → `contractor`
- Registered agent fees → `compliance/admin`
- Capital One rows → matched on description

Unmatched → `uncategorized`, **listed after every run**, never silently guessed.
When new vendors appear, **ask her for the rule** — she asked for this explicitly.

### Stage 9 — Tax calculator (France-specific — read carefully)

**First task: verify the bracket figures against the IRS PDF** (finding 2 above).
`irs.gov` is reachable from her Mac.

Her situation splits the bill in two, and the split is counter-intuitive:

**US income tax — likely $0.** As a bona fide resident of France for the full
year, the **Foreign Earned Income Exclusion** (Form 2555) excludes up to
**$132,900** for 2026. Under that, US taxable income is ~$0. She still files Form
1040 + Form 2555 — owing nothing is not the same as filing nothing. Above the cap,
the excess is taxed under the **§911(f) stacking rule** — at the rates that would
have applied without the exclusion, not from the bottom bracket. Model this.

**The 20% QBI deduction is removed entirely.** It is moot once FEIE zeroes taxable
income, and §199A requires a *US* trade or business, which foreign-earned
self-employment income generally is not. Do not reintroduce it.

**US self-employment tax — the entire bill.** FEIE does **not** reduce it. IRS:
*"You must pay self-employment tax on all your net profit from self-employment,
even if you claimed the foreign earned income exclusion."*

Only the **US–France totalization agreement** can remove it. SSA's France pamphlet
states that *self-employed workers who work only in France are assigned French
coverage* — the treaty already assigns her to France. But claiming the exemption
requires a **French Certificate of Coverage** from the agency collecting her
contributions. She pays into nothing, so no certificate exists. Model both:

| Scenario | US SE tax |
|---|---|
| **Today** — unregistered, no certificate | **Full 15.3%** on 92.35% of net profit |
| **Registered in France** (e.g. URSSAF) with certificate | **$0** |

Surface honestly, do not sell the switch: French self-employed contributions for a
service business run roughly 21–24% **of revenue**, which can exceed 15.3% of
*profit*. Registering is about compliance where she lives, not a guaranteed saving.

**Say once, do not repeat or moralize:** permanently resident in France, running a
business there, paying neither social contributions nor income tax anywhere is not
a stable position — France taxes residents on worldwide income. This tool covers
US federal tax only; her larger exposure is likely French.

`constants_2026.py`, every figure cited inline:
- SE tax **15.3%** = 12.4% Social Security + 2.9% Medicare
- Social Security wage cap **$184,500** (SSA 2026 contribution and benefit base)
- MFS brackets, Rev. Proc. 2025-32 **Table 4**: 10% to $12,400 · 12% to $50,400 ·
  22% to $105,700 · 24% to $201,775 · 32% to $256,225 · 35% to $384,350 · 37% above
- Standard deduction **$16,100**
- FEIE cap **$132,900**
- Additional Medicare Tax 0.9% above **$125,000** — the MFS threshold is $125,000,
  **not** the $200,000 quoted everywhere for single filers

Ship `verify_brackets.py` printing each number beside the IRS URL.

`scripts/calc_tax.py`, explaining each step in plain terms as it runs:

```
net profit = income_usd − expenses_usd
SE tax     = 15.3% × (92.35% × net profit)
             SS portion capped at $184,500; Medicare uncapped
             +0.9% above $125,000
             → $0 if the certificate-of-coverage setting is on
FEIE       = min(net profit, $132,900)
taxable    = max(0, net profit − FEIE − half SE tax − $16,100)
             (half-SE-tax deduction cannot offset excluded income)
income tax = MFS brackets on `taxable`, stacking rule above the FEIE cap
TOTAL      = SE tax + income tax   ← in practice almost entirely SE tax
```

An editable `settings` block holds: filing status (MFS), country (France), bona
fide residence (true), certificate of coverage (false — she flips it if obtained),
and FEIE-vs-FTC (FEIE; there is no French income tax to credit).

Also explain the **safe harbor** rule: paying 100% of last year's total tax shields
her from underpayment penalties regardless of how this year lands.

### Stage 10 — Reminders, contractor alarm, FBAR

`taxlib/notify.py` — desktop notification via `osascript`, email via Gmail SMTP
(`smtp.gmail.com:587`, STARTTLS, stdlib `smtplib`). README walks through enabling
2-Step Verification **first** (app passwords don't exist without it), then
generating one at myaccount.google.com/apppasswords. Her address:
help.hostlyft@gmail.com.

`scripts/run_quarterly.py` — one week before Apr 15, Jun 15, Sep 15, Jan 15.
Cron: `0 9 8 1,4,6,9 *` (9am on the 8th of Jan, Apr, Jun, Sep).

**FBAR — add this; it is arguably higher-risk than the tax deadlines.** She runs
her business through **Wise**, a foreign financial account. If all foreign accounts
combined exceeded **$10,000 at any point** in the calendar year, **FinCEN Form 114**
is required — filed with FinCEN, *not* the IRS. Due April 15, automatic extension
to October 15, no request needed. Civil and criminal penalties apply. With a
multi-currency business account this almost certainly applies, and nothing prompts
you about it. Remind in late March, and again in September if unfiled.

`scripts/check_contractors.py` — daily. Totals per contractor; both alerts fire the
moment anyone crosses **$600** (W-9 + 1099-NEC threshold), recorded in
`alerts_sent` so it fires once. **Sunniva gets a specific year-end flag in December
even if under $600** — she asked for this so she can consciously confirm rather
than forget. All four are paid via Wise, so the tracker sees every payment; still
print the caveat that it counts only what is in the database.

Two Mac traps to document — both fail **silently**:
- `cron` needs **Full Disk Access** (System Settings → Privacy & Security) or jobs
  never run at all.
- Terminal needs **notification permission** or `osascript` alerts never appear.

Testing, which she asked for explicitly: `--test-notify` fires both immediately,
`--dry-run` shows what would happen without sending, and `/var/mail/$USER` confirms
cron actually fired.

## Tests

Each stage ships tests runnable in one command:
1. Stripe→Wise fixture asserting income totals **$2,000, not $3,940** — the one
   that matters most.
2. Every import run twice — totals must not change.
3. FX conversion on a Saturday date, proving business-day fallback.
4. Wise SCA signing verified against its own public key.
5. A synthetic Capital One CSV including a card payment that must be skipped.
6. `calc_tax.py` at $80,000 profit → income tax **$0**, SE tax **≈$11,304**; and
   the certificate-of-coverage setting flipping SE tax to **$0**.
7. `calc_tax.py` at $150,000 profit → exercises the FEIE cap and stacking rule.
8. Contractor alarm at $599 (silent) and $601 (fires), then re-run to prove it
   doesn't double-fire.

## Out of scope — flag, don't guess

French income tax and French social contributions (her likely larger exposure),
Foreign Tax Credit modelling (nothing to credit — she pays no French income tax),
US state tax, home-office or vehicle deductions, mileage, depreciation, filing
anything, or paying the IRS.
This estimates what to set aside. A CPA — especially given she's abroad — should
confirm it.
