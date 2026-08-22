# Start Here — Hostlyft Tax Tracker

This folder will hold a free, local system that tracks Hostlyft's income and
expenses, converts everything to USD, estimates your quarterly federal tax, and
reminds you before deadlines.

**Nothing is built yet.** This file gets you set up on your Mac. `PLAN.md` next to
it is the build plan — once Claude Code is running on your Mac, it reads that and
picks up where we left off.

---

## Why you have to move to your Mac

The planning happened in Claude Code on the web, which runs on a temporary
computer in the cloud. That machine blocks the internet services this project
needs — Stripe, Wise, the exchange-rate service, Gmail — and it isn't a Mac, so it
can't test Mac notifications or the scheduler either.

On your own Mac, all of that works. So we move.

---

## Step 1 — Install Claude Code

If you typed `claude` and saw `zsh: command not found: claude`, that just means it
isn't installed yet. Nothing is broken.

Open **Terminal** (press `Cmd+Space`, type "Terminal", press Enter) and paste:

```
curl -fsSL https://claude.ai/install.sh | bash
```

In plain English: `curl` downloads the installer from Anthropic, and `| bash` runs
it. It installs into your home folder — no admin password, nothing system-wide.

**Then close Terminal completely and open it again.** This matters: your Terminal
only looks for new commands when it starts, so `claude` stays "not found" until
you restart it. This trips up nearly everyone.

Check it worked:

```
claude --version
```

You should see a number followed by `(Claude Code)`.

---

## Step 2 — Give your Mac permission to download your code

This repository is **private**, so GitHub needs proof of who you are.

If `git clone` ever asks `Username for 'https://github.com':`, that is why. Note
that typing your GitHub password will **not** work — GitHub stopped accepting
account passwords in 2021. You need an access token instead.

**Create one:**

1. Go to https://github.com/settings/tokens
2. **Generate new token** → **Generate new token (classic)**
3. Note: `Mac laptop`
4. Expiration: 90 days (or longer)
5. Tick the box marked **repo** — the only one needed
6. Scroll down, **Generate token**
7. **Copy it now** — it starts with `ghp_` and GitHub never shows it again

---

## Step 3 — Download your code

In Terminal:

```
cd ~/Documents
```

`cd` means "change directory" — this puts you in Documents, so the code lands
somewhere you can find in Finder.

```
git clone https://github.com/liuba-larousse/hostlyft-tax.git
```

When it asks:

- **Username:** `liuba-larousse`
- **Password:** paste the `ghp_` token from Step 2, **not** your real password.
  Nothing appears as you paste — no dots, no stars. That is normal, it is hidden
  on purpose. Just press Enter.

Then move into the folder:

```
cd hostlyft-tax
```

Confirm the files are there:

```
ls
```

You should see `PLAN.md`, `README.md` and `START-HERE.md`.

---

## Step 4 — Start Claude and pick up where we left off

```
claude
```

It opens a browser window once to log you in. Then type exactly this:

```
Read PLAN.md and START-HERE.md, then start with Stage 1. I have no coding
experience — explain each step in plain English and check in with me before moving
to the next stage.
```

That's it. Everything decided during planning — your tax situation, the API
research, the design — is in `PLAN.md`, so you won't have to re-explain anything.

---

## If something goes wrong

**`command not found: claude` even after installing and restarting** — the
installer puts Claude in `~/.local/bin`, which your Terminal may not search. Look
for a yellow "Setup notes" line in the installer output saying exactly this. Fix:

```
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc && source ~/.zshrc
```

`PATH` is the list of folders your Mac searches when you type a command. This adds
`~/.local/bin` to it (`>>` appends to the file — a single `>` would erase it) and
`source` reloads the file immediately so you don't have to restart.

**`Authentication failed`** — the token was wrong or you pasted your password.
Redo Step 2. Being invisible when pasted is normal.

**`Repository not found`** — usually means the token is missing the **repo**
tickbox. Make a new one.

**Terminal looks frozen** — press **Control+C** to cancel whatever's running.

**You get genuinely stuck** — you can run `claude` from any folder, even without
the code downloaded, and just describe what you're seeing. It can help from there.
