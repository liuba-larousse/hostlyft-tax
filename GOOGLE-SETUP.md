# Connecting to Google Sheets — a walkthrough

About 15 minutes, all on the Google Cloud website. It creates a **robot user**
that can read and write one folder of your Drive, and nothing else.

Run the checker after each step. It stops at the first thing that's wrong and
tells you what to do:

```
cd ~/Documents/hostlyft-tax
source .venv/bin/activate
python scripts/check_google.py
```

---

## Why this is needed at all

Google won't let a program open a spreadsheet just because *you* can see it.
The program needs an identity of its own — a **service account**, which is a
robot user with its own email address, something like:

```
hostlyft-tax@hostlyft-tax-2026.iam.gserviceaccount.com
```

You then **share your folder with that address**, exactly as you'd share it
with a colleague. The robot can only ever see what you've shared. Nothing else
in your Drive is reachable.

It's needed for three things: reading the notes inside your tabs, creating the
tax sheet, and writing to it.

---

## Step 1 — Create a project

1. Go to **console.cloud.google.com**
2. Sign in as **team@hostlyft.com** — the account that owns the sheet
3. At the top, click the project dropdown → **New Project**
4. Name: `hostlyft-tax` · **Create**
5. Wait a few seconds, then make sure the dropdown shows `hostlyft-tax`

> A "project" is just a container. It's free, and nothing here costs money —
> the Sheets API has a generous free quota and this tool makes a handful of
> calls a day.

**If it asks for billing:** you can skip it. The APIs we use don't require it.

---

## Step 2 — Switch on the two APIs

An API is off by default until you enable it for the project.

1. Left menu → **APIs & Services** → **Library**
2. Search **Google Sheets API** → click it → **Enable**
3. Go back to Library, search **Google Drive API** → click it → **Enable**

Both are needed: Sheets to read and write cells, Drive to find the folder and
create the new file in it.

---

## Step 3 — Create the robot user

1. Left menu → **IAM & Admin** → **Service Accounts**
2. **+ Create Service Account**
3. Name: `hostlyft-tax` — the email is filled in for you
4. **Create and Continue**
5. *"Grant this service account access to project"* — **skip it**, click
   **Continue**. Those roles are about the Cloud project, not your Drive.
6. *"Grant users access"* — skip, click **Done**

You'll now see it listed with an email ending
`.iam.gserviceaccount.com`. **Copy that address** — you need it in step 5.

---

## Step 4 — Download its key

1. Click the service account you just made
2. Top tabs → **Keys**
3. **Add Key** → **Create new key** → choose **JSON** → **Create**

A file downloads immediately, named something like
`hostlyft-tax-2026-a1b2c3d4e5f6.json`. **Google never shows it again** — if you
lose it, delete the key and make a new one.

### Put it in the right place

The project expects it at `tax/google_service_account.json`. In Terminal:

```
mv ~/Downloads/hostlyft-tax-*.json ~/Documents/hostlyft-tax/tax/google_service_account.json
chmod 600 ~/Documents/hostlyft-tax/tax/google_service_account.json
```

`mv` moves and renames in one go. The `*` matches whatever Google called it.
`chmod 600` locks it so only your account can read it.

**Check it:**

```
python scripts/check_google.py
```

Step 1 should pass and print the robot's email address. Step 3 will fail — that's
expected, you haven't shared anything yet.

> ⚠️ That file is a **private key**. Anyone holding it can act as the robot.
> It sits in `tax/`, which `.gitignore` blocks, and the checker confirms git
> refuses to upload it.

---

## Step 5 — Share your folder with the robot

**This is the step everyone forgets**, and Google's error when you do is a bare
"not found", as though the file didn't exist.

1. Open **Google Drive**
2. Find the folder containing `Hostlyft_Accounting_2026`
3. Right-click the folder → **Share**
4. Paste the robot's email address (from step 3 or the checker output)
5. Set it to **Editor** — not Viewer; it needs to create the tax sheet
6. **Untick "Notify people"** — it's a robot, the email would bounce
7. **Share**

Share the **folder**, not just the sheet. The new tax sheet gets created inside
that folder, which needs folder-level permission.

---

## Step 6 — Check everything

```
python scripts/check_google.py
```

All five steps should pass:

```
1. THE KEY FILE                       found, locked, git-ignored
2. DOES GOOGLE ACCEPT IT?             signed in to Drive
3. CAN IT SEE YOUR ACCOUNTING SHEET?  yes, and can edit
4. CAN IT CREATE THE TAX SHEET?       yes, folder is writable
5. CAN IT READ THE NOTES?             yes, N tabs
```

Nothing is written to your sheet by this — it only reads.

---

## If something goes wrong

**"does not exist" (404)** — the folder or sheet hasn't been shared with the
robot. Being able to see it yourself isn't enough. Redo step 5, and check you
pasted the `.iam.gserviceaccount.com` address rather than your own.

**"refused access" (403)** — either an API isn't enabled (step 2), or you shared
as Viewer instead of Editor.

**"not a service-account key"** — Google hands out several kinds of credential
file and they look alike. You need the one from **Service Accounts → Keys**, not
an OAuth client file.

**"rejected the key" (401)** — the key was deleted in the console. Make a new
one and repeat step 4.

**You accidentally shared with the wrong address** — remove it in Drive's share
dialog. Nothing was exposed unless that address belongs to someone real.

---

## What happens next

Once this passes, the tax sheet gets built: a **separate** spreadsheet beside
your accounting sheet, run on **cash received**, holding the gross/net figures,
processor fees, currency conversions and the tax summary.

Your accounting sheet keeps its own convention — grouping a month by service
period so end-of-month team payouts work — and is **never written to**.
