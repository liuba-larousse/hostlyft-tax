# Connecting to Google Sheets — a walkthrough

About 10 minutes, all on the Google Cloud website.

Run the checker whenever you want to see where you've got to. It stops at the
first thing that's wrong and tells you what to do:

```
cd ~/Documents/hostlyft-tax
source .venv/bin/activate
python scripts/check_google.py
```

---

## Why this isn't a service account

The original plan used a **service account** — a robot user you share a folder
with. Your Google Workspace blocks those:

```
Service account key creation is disabled
iam.disableServiceAccountKeyCreation
```

That's applied automatically to new organisations under Google's "Secure by
Default" enforcement. Nothing has gone wrong.

So the tool **signs in as you** instead, once, in a browser. Google recommends
this over service-account keys anyway: there's no long-lived private key sitting
on disk, only a token you can revoke from your account page at any moment.

### What it can reach

**One permission: read and write Google Sheets.** Not Drive, not your documents,
not your photos, not your folders.

That narrowness costs one small thing, and it's worth knowing up front: a newly
created spreadsheet lands at the **top level of My Drive** rather than inside a
folder, because putting it in a folder would need Drive access. You drag it
across once. That seemed a much better trade than handing a background job
access to every file you own.

Withdraw it any time at **myaccount.google.com/permissions**.

---

## Step 1 — Create a project

1. **console.cloud.google.com**, signed in as **team@hostlyft.com**
2. Project dropdown at the top → **New Project**
3. Name: `hostlyft-tax` → **Create**
4. Make sure the dropdown then shows `hostlyft-tax`

Free. If it asks about billing, skip it — nothing here needs it.

---

## Step 2 — Switch on the Sheets API

1. **APIs & Services** → **Library**
2. Search **Google Sheets API** → **Enable**

That's the only API needed. The Drive API isn't, because we're not asking for
Drive access.

---

## Step 3 — Configure the Auth Platform

Google renamed and redesigned this in 2026. It used to be called the "OAuth
consent screen"; it is now **Google Auth Platform**, and the steps are
different from most guides you will find online.

If you see *"Google Auth Platform not configured yet"* with a dashed cloud, you
are in the right place.

1. Click the blue **Get started** button.

2. **App Information**
   - *App name:* `Hostlyft Tax Tracker`
   - *User support email:* pick **team@hostlyft.com** from the dropdown
   - **Next**

3. **Audience** — the important one
   - Choose **Internal**
   - **Next**

   > **Why Internal matters.** It means only people inside your own Workspace
   > can use the app, so Google does not need to review it. It also avoids a
   > trap: an **External** app sits in "Testing" mode, and testing-mode tokens
   > **expire after 7 days** — the tool would silently stop working a week
   > later.
   >
   > If **Internal** is greyed out, your account is not a Workspace
   > organisation. Choose External and tell me — there is a extra step to stop
   > the 7-day expiry.

4. **Contact Information**
   - *Email addresses:* `team@hostlyft.com`
   - **Next**

5. **Finish**
   - Tick **I agree to the Google API Services: User Data Policy**
   - **Continue**, then **Create**

You land back on the Overview, now configured.

---

## Step 4 — Create the app registration

Still inside **Google Auth Platform**, in the left-hand menu:

1. Click **Clients**
2. **+ Create client**
3. *Application type:* **Desktop app** ← must be Desktop, not Web
4. *Name:* `Hostlyft Tax Tracker`
5. **Create**
6. A panel appears — click **Download JSON**

> There is no "Data Access" step to do. The tool asks for the one permission it
> needs at sign-in time, and because the app is Internal, Google does not
> require the scope to be declared here first.

### Put it where the tool expects

```
mv ~/Downloads/client_secret_*.json ~/Documents/hostlyft-tax/tax/google_oauth_client.json
chmod 600 ~/Documents/hostlyft-tax/tax/google_oauth_client.json
```

`mv` moves and renames in one go; the `*` matches whatever Google called it.

> This file identifies the **application**, not you. On its own it grants
> nothing. The next step is what actually gives access.

---

## Step 5 — Sign in

```
python scripts/google_login.py
```

A browser opens. Sign in as **team@hostlyft.com** and approve.

You'll likely see **"Google hasn't verified this app"** — that's expected for
an Internal app you created yourself minutes ago. Click **Advanced** → **Go to
Hostlyft Tax Tracker (unsafe)**. It's your own app; the warning is aimed at
apps written by strangers.

When it's done the tab says so, and a token is saved to `tax/google_token.json`
— locked to your account and blocked from GitHub.

From then on it renews itself silently. No browser again, which is what lets the
scheduled job in Stage 13 run unattended.

---

## Step 6 — Check it

```
python scripts/check_google.py
```

All four should pass:

```
1. THE APP REGISTRATION           Desktop OAuth client found
2. ARE YOU SIGNED IN?             yes, spreadsheets only
3. CAN IT OPEN YOUR SHEET?        Hostlyft_Accounting_2026, 17 tabs
4. CAN IT READ THE NOTES?         yes, N cell notes found
```

Nothing is written to your sheet — this only reads.

---

## If something goes wrong

**"is a WEB application client"** — you picked the wrong application type in
step 4. Go to **Clients**, delete it, and create another as **Desktop app**.

**You can't find the "OAuth consent screen"** — it was renamed. It is now
**Google Auth Platform**, and the Internal/External choice lives under
**Audience**.

**"The Google Sheets API is not switched on"** — step 2 was missed, or was done
in a different project. Check the project dropdown says `hostlyft-tax`.

**"Google hasn't verified this app"** — expected. Advanced → Go to … (unsafe).

**"Google would not renew the sign-in"** — usually the consent screen is
External and still in Testing, which expires tokens after 7 days. Set it to
Internal, then `python scripts/google_login.py --force`.

**You want to disconnect it** — `python scripts/google_login.py --revoke`
forgets the token on this Mac. To withdraw at Google's end too, visit
myaccount.google.com/permissions.

---

## What happens next

The tax sheet gets built: a **separate** spreadsheet run on **cash received**,
holding gross and net figures, processor fees, currency conversions and the tax
summary. It appears in My Drive; drag it next to your accounting sheet once.

Your accounting sheet keeps its own convention — grouping a month by service
period so end-of-month team payouts work — and is **never written to**.
