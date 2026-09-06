"""
Getting a message to you - Stage 10.

Two ways, deliberately:

  DESKTOP   a notification in the corner of your Mac. You see it now, but
            only if you happen to be at the machine, and it disappears.
  EMAIL     arrives whether or not the Mac was awake, and stays in your
            inbox until you deal with it.

Neither is enough alone. A tax deadline you saw and then forgot is the same
as one you never saw, so anything that matters goes to both.

WHY THE EMAIL USES AN "APP PASSWORD"

Google stopped letting programs sign in with your real password. An app
password is a 16-character password that works for ONE program and can be
switched off on its own without changing your Google password. It only
exists once 2-Step Verification is on - that is not an extra hurdle, it is
the thing that makes app passwords available at all.

A NOTE ON WHAT "SENT" MEANS

`desktop()` returning True means the command ran without error. It does NOT
prove the notification appeared on screen: if Terminal has never been
granted notification permission, macOS discards it silently and reports
success anyway. That is a real macOS behaviour, not a bug here, and it is
why the desktop channel is never the only one used.
"""

import smtplib
import subprocess
from email.message import EmailMessage

from taxlib import config


# Gmail's outgoing mail server. Port 587 with STARTTLS, which means the
# connection begins in the clear and is upgraded to an encrypted one before
# the password is sent.
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_TIMEOUT = 30


class NotifyError(Exception):
    """
    Something went wrong sending. The message names the credential or the
    setting at fault, in plain English, because a stack trace at 9am tells
    you nothing about which password expired.
    """


# ===========================================================================
#  DESKTOP NOTIFICATION
# ===========================================================================

def _applescript_quote(text):
    """
    Make text safe to drop inside an AppleScript string.

    AppleScript strings are wrapped in double quotes, so a double quote or a
    backslash inside the text would end the string early and turn the rest
    into broken code. Both get a backslash in front of them.

    Newlines are turned into spaces: AppleScript has no multi-line string
    literal here, and a raw newline is a syntax error rather than a wrap.
    """
    text = (text or "").replace("\\", "\\\\").replace('"', '\\"')
    return text.replace("\r", " ").replace("\n", " ")


def desktop(title, message, subtitle=None, dry_run=False):
    """
    Pop up a macOS notification.

    Returns True if the command ran. See the caveat at the top of the file:
    that is not the same as you having seen it.
    """
    if dry_run:
        print(f"    [dry run] desktop notification: {title} - {message}")
        return True

    parts = [f'display notification "{_applescript_quote(message)}"',
             f'with title "{_applescript_quote(title)}"']
    if subtitle:
        parts.append(f'subtitle "{_applescript_quote(subtitle)}"')
    script = " ".join(parts)

    try:
        result = subprocess.run(["osascript", "-e", script],
                                capture_output=True, text=True, timeout=20)
    except FileNotFoundError:
        # osascript ships with macOS. Missing means this isn't a Mac.
        raise NotifyError(
            "Could not show a desktop notification: `osascript` was not "
            "found. Desktop notifications only work on macOS.")
    except subprocess.TimeoutExpired:
        raise NotifyError("The desktop notification timed out after 20 seconds.")

    if result.returncode != 0:
        raise NotifyError(
            "Could not show a desktop notification. macOS said: "
            f"{result.stderr.strip() or 'no reason given'}\n"
            "  Most often this means Terminal has not been given permission "
            "to send notifications.\n"
            "  System Settings -> Notifications -> Terminal -> Allow "
            "Notifications.")

    return True


# ===========================================================================
#  EMAIL
# ===========================================================================

def _email_settings():
    """
    Collect the address and app password, or explain exactly what is missing.

    Checked here rather than at the point of sending so the message names the
    setting, not an SMTP error code.
    """
    address = (config.get_secret("GMAIL_ADDRESS") or "").strip()
    password = (config.get_secret("GMAIL_APP_PASSWORD") or "").strip()
    # Falls back to the sending address: sending yourself the reminder is the
    # normal case, so it should not need configuring twice.
    to_address = (config.get_secret("ALERT_EMAIL_TO") or address).strip()

    missing = []
    if not address:
        missing.append("GMAIL_ADDRESS  - the Gmail address to send from")
    if not password:
        missing.append("GMAIL_APP_PASSWORD - the 16-character app password, "
                       "NOT your Gmail password")

    if missing:
        raise NotifyError(
            "Email is not set up yet. Missing from tax/.env:\n"
            + "\n".join(f"    {line}" for line in missing)
            + "\n  Turn on 2-Step Verification first, then create an app "
              "password at https://myaccount.google.com/apppasswords")

    return address, password, to_address


def email(subject, body, to=None, dry_run=False):
    """
    Send one plain-text email through Gmail.

    Returns the address it went to.

    A DRY RUN DELIBERATELY DOES NOT REQUIRE THE APP PASSWORD. The whole
    point of --dry-run is to see what would happen before anything is set
    up, and the first time it is ever run the app password will not exist
    yet. Failing there would send her off to configure Gmail to look at a
    preview. It still says the password is missing, so the gap is visible
    rather than hidden.
    """
    if dry_run:
        address = (config.get_secret("GMAIL_ADDRESS") or "").strip()
        to_address = (to or config.get_secret("ALERT_EMAIL_TO")
                      or address or "(no address configured)")
        print(f"    [dry run] email to {to_address}: {subject}")
        if not (config.get_secret("GMAIL_APP_PASSWORD") or "").strip():
            print("    [dry run] note: GMAIL_APP_PASSWORD is not set yet, so "
                  "a real send would fail.")
        return to_address

    address, password, default_to = _email_settings()
    to_address = (to or default_to)

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = address
    message["To"] = to_address
    message.set_content(body)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT) as server:
            server.starttls()          # upgrade to an encrypted connection
            server.login(address, password)
            server.send_message(message)
    except smtplib.SMTPAuthenticationError:
        raise NotifyError(
            "Gmail rejected the login. Two usual causes:\n"
            "    1. GMAIL_APP_PASSWORD holds your real Gmail password. It "
            "needs the 16-character app password instead.\n"
            "    2. The app password was revoked. Make a new one at "
            "https://myaccount.google.com/apppasswords\n"
            f"  The address it tried was {address}.")
    except (smtplib.SMTPException, OSError) as problem:
        # OSError covers the machine simply being offline.
        raise NotifyError(
            f"Could not reach Gmail to send the reminder: {problem}\n"
            "  If the Mac is offline this will succeed on the next run.")

    return to_address


# ===========================================================================
#  BOTH AT ONCE
# ===========================================================================

class Delivery:
    """
    What actually happened when a message was sent.

    One channel failing must not stop the other - being offline should not
    also cost you the desktop notification - so both are attempted and both
    outcomes are recorded here rather than the first failure ending the run.
    """

    def __init__(self):
        self.desktop_ok = False
        self.email_ok = False
        self.problems = []

    @property
    def anything_arrived(self):
        return self.desktop_ok or self.email_ok

    def __repr__(self):
        return (f"<Delivery desktop={self.desktop_ok} email={self.email_ok} "
                f"problems={len(self.problems)}>")


def send(subject, body, short=None, to=None, dry_run=False,
         want_desktop=True, want_email=True):
    """
    Send one alert to both channels.

    `short` is the one-line version for the desktop pop-up, which has room
    for a sentence and not a page. Without it, the subject is used.
    """
    delivery = Delivery()

    if want_desktop:
        try:
            desktop("Hostlyft Tax", short or subject, dry_run=dry_run)
            delivery.desktop_ok = True
        except NotifyError as problem:
            delivery.problems.append(str(problem))

    if want_email:
        try:
            email(subject, body, to=to, dry_run=dry_run)
            delivery.email_ok = True
        except NotifyError as problem:
            delivery.problems.append(str(problem))

    return delivery


def test_notification(dry_run=False):
    """
    Prove both channels work, right now, without waiting for a real deadline.

    This is what `--test-notify` runs. It is deliberately obvious in tone so
    that a test message is never mistaken for a real tax reminder.
    """
    subject = "Hostlyft tax tracker - test message"
    body = (
        "This is a test.\n\n"
        "If you are reading this, email reminders work. If a notification "
        "also appeared in the corner of your screen, desktop reminders work "
        "too.\n\n"
        "Nothing is due. Nothing needs doing. This message was sent by hand "
        "with --test-notify to check the plumbing before the real reminders "
        "start.\n")
    return send(subject, body, short="Test message - nothing is due.",
                dry_run=dry_run)
