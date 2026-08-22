# Filling in your secrets — a walkthrough

Your API keys go in one file: **`tax/.env`**. This page walks through putting
them there, explaining every command.

Nothing here is risky. The worst that happens is a typo, and
`check_secrets.py` catches those.

---

## Why a file, and not `~/.zshrc`

You may have seen advice to put keys in `~/.zshrc` as `export` lines. **Don't**,
for one specific reason:

Your quarterly reminders will run under **`cron`**, the Mac's scheduler. Cron
starts programs with a nearly empty environment — it does **not** load your
shell settings. Anything you `export` in `.zshrc` simply would not exist when
cron runs.

The reminder would fail **silently**. No error, no email, nothing. You'd find
out in April.

A file is read by the program itself, so it works identically whether you run it
by hand or cron runs it at 9am.

---

## Before you start — one safety rule

**Never paste a secret key into a chat window, a document, or an email** —
including into your conversation with Claude. Type it straight into the file and
nowhere else.

If you ever do paste one somewhere by accident, don't panic and don't try to
delete the message. Go to the service and **roll** (regenerate) the key. That
makes the old one dead, instantly and permanently. Rolling a key is free,
takes ten seconds, and is completely normal.

---

## Step 1 — Open Terminal in the right folder

Press `Cmd+Space`, type `Terminal`, press Enter.

```
cd ~/Documents/hostlyft-tax
```

`cd` means **change directory** — it moves you into a folder, the way
double-clicking does in Finder. `~` is shorthand for your home folder.

```
source .venv/bin/activate
```

This switches Terminal over to this project's private libraries. Your prompt
gains a `(.venv)` prefix. **This is the step people forget.**

---

## Step 2 — Get your Stripe key

1. Go to **dashboard.stripe.com**
2. Left sidebar → **Developers** → **API keys**
3. Find the row labelled **Secret key**
4. Click **Reveal**, then copy it

Two traps on that page:

- There are **two** keys side by side. **Publishable** (`pk_live_…`) is the
  wrong one — it's designed to be public and can't read your invoices. You want
  **Secret** (`sk_live_…`).
- If there's a **Test mode** toggle switched on, you'll get `sk_test_…`, which
  only sees pretend transactions. Turn test mode off for real figures.

The checker catches both mistakes by name, so if in doubt, just try it.

---

## Step 3 — Open the file

```
nano tax/.env
```

`nano` is a text editor that runs inside Terminal. It's deliberately simple.

Things to know:

- **The mouse does nothing.** Move with the arrow keys only.
- The `^` symbols along the bottom mean the **Control** key. `^O` is
  Control+O, not Shift+6.

---

## Step 4 — Type your key in

Arrow down to the line that reads:

```
STRIPE_SECRET_KEY=
```

Put the cursor at the very end of that line, after the `=`, and paste with
**Cmd+V**. You should end up with:

```
STRIPE_SECRET_KEY=sk_live_51ABCdef...
```

Rules for this file:

| Do | Don't |
|---|---|
| `NAME=value` | `NAME = value` (no spaces around `=`) |
| Paste straight after `=` | Add quotes — they aren't needed |
| One setting per line | Let a value wrap onto a second line |

---

## Step 5 — Save and quit

- **Control+O** — save (nano calls this "write out")
- **Enter** — confirm the filename
- **Control+X** — quit

If you get lost, **Control+X** then **N** quits without saving. Nothing breaks.

---

## Step 6 — Check the permissions

```
chmod 600 tax/.env
```

`chmod` means **change mode** — it sets who is allowed to do what with a file.
The three digits are three groups of people:

| Digit | Who | `6` means |
|---|---|---|
| 1st | you | read + write |
| 2nd | your groups | — |
| 3rd | everyone else | — |

So `600` = you can read and write it, nobody else on the Mac can even open it.

`setup_mac.command` already did this. Running it again costs nothing and is
worth the habit.

---

## Step 7 — Check it worked

```
python scripts/check_secrets.py
```

This checks the file is locked down, and that each value is the **right shape** —
without ever printing your secrets. The output is safe to show anyone.

Then prove the key actually works:

```
python scripts/check_secrets.py --connect
```

This makes one read-only call to Stripe and reports your account name back. It
changes nothing and moves no money.

---

## What the checker catches

| You did this | It says |
|---|---|
| Pasted the publishable key | *that is the PUBLISHABLE key. You need the one labelled Secret key — click 'Reveal' next to it* |
| Pasted the test key | *that is the TEST key — it only sees pretend transactions* |
| Copy stopped halfway | *only 11 characters — looks cut off mid-paste* |
| Pasted a webhook secret | *that is a webhook signing secret, not the API key* |
| Copied from a web page and got a curly quote | *contains a character that isn't a plain letter, digit or symbol* |
| Left a space at the end | *has a space at the start or end* |
| Used your real Gmail password | *a Google app password is exactly 16 letters* |

That last category is worth explaining. Copying from a web page can drag along
a character you **cannot see** — a curly quote, a non-breaking space. The key
looks perfect on screen and the server rejects it with no explanation. That
mistake can cost an hour. The checker finds it in a second.

---

## Other commands

```
python scripts/check_secrets.py --fix-permissions   # re-lock the file
```

---

## What to fill in when

| Secret | Needed for | Fill in |
|---|---|---|
| `STRIPE_SECRET_KEY` | Stage 4 — your income | **now** |
| `WISE_API_TOKEN` | Stage 6 — Wise | Stage 6 |
| `WISE_PROFILE_ID` | Stage 6 — Wise | Stage 6 (looked up for you) |
| `GMAIL_ADDRESS` | Stage 10 — reminders | already done |
| `GMAIL_APP_PASSWORD` | Stage 10 — reminders | Stage 10 |

Blank is fine until then. Nothing breaks — the tool that needs it will tell you.

---

## If it goes wrong

**`nano: command not found`** — very unusual. Use `open -e tax/.env` to edit in
TextEdit instead.

**`No such file or directory`** — you're in the wrong folder. Run
`cd ~/Documents/hostlyft-tax` and try again. `pwd` shows where you are.

**`python: command not found`** — you skipped `source .venv/bin/activate`.

**The key was correct yesterday and is refused today** — someone rolled it in
the dashboard. Generate a new one and paste it in.

**You pasted a key somewhere public** — roll it. Stripe: *API keys* → the `…`
menu next to the key → **Roll key**. The old one dies immediately.
