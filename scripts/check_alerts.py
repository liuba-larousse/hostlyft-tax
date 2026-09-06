"""
check_alerts.py - work out what needs your attention, and tell you.

    python scripts/check_alerts.py --dry-run
        Show what WOULD be sent. Sends nothing. Start here.

    python scripts/check_alerts.py
        Actually send. Anything already sent is skipped.

    python scripts/check_alerts.py --test-notify
        Send one obvious test message, to prove email and desktop
        notifications work before you rely on them.

    python scripts/check_alerts.py --on 2026-12-01 --dry-run
        Pretend it is another date. Useful for seeing the December jars
        warning in September, without waiting for December.

    python scripts/check_alerts.py --force
        Send again even if it went out before.

NOTHING HERE INSTALLS A SCHEDULE. This is run by hand. Putting it on a
timer is Stage 13, on your main Mac.

WHY IT GOES QUIET
    Each alert is recorded once sent, so it does not arrive again every
    morning. A run that says "nothing due" means nothing needs you - that
    is the normal outcome and it is what makes the noisy days worth
    reading.
"""

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from taxlib import alerts, config, db, notify   # noqa: E402

BOLD, GREEN, YELLOW, RED, CYAN, OFF = (
    "\033[1m", "\033[32m", "\033[33m", "\033[31m", "\033[36m", "\033[0m")


def show(alert, verbose):
    """Print one alert the way it will arrive."""
    mark = f"{RED}!{OFF}" if alert.urgent else " "
    print(f"  {mark} {BOLD}{alert.subject}{OFF}")
    print(f"      {CYAN}desktop:{OFF} {alert.short}")
    if verbose:
        print()
        for line in alert.body.splitlines():
            print(f"      {line}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Check for tax reminders and send them.")
    parser.add_argument("--dry-run", action="store_true",
                        help="show what would be sent, send nothing")
    parser.add_argument("--test-notify", action="store_true",
                        help="send a test message to prove both channels work")
    parser.add_argument("--force", action="store_true",
                        help="send even if it has gone out before")
    parser.add_argument("--on", metavar="YYYY-MM-DD",
                        help="pretend today is this date")
    parser.add_argument("--year", type=int,
                        default=config.SETTINGS["tax_year"])
    parser.add_argument("--full", action="store_true",
                        help="print the whole message, not just the subject")
    parser.add_argument("--quiet", action="store_true",
                        help="print nothing when nothing is due")
    args = parser.parse_args()

    today = args.on or date.today().isoformat()
    try:
        date.fromisoformat(today)
    except ValueError:
        print(f"{RED}'{today}' is not a date. Use YYYY-MM-DD.{OFF}")
        return 1

    # ------------------------------------------------------ --test-notify
    if args.test_notify:
        print(f"\n{BOLD}Sending a test message{OFF}")
        print("  One desktop notification, one email. Nothing is due - this")
        print("  only checks the plumbing.\n")
        delivery = notify.test_notification(dry_run=args.dry_run)

        print(f"  desktop notification   "
              f"{GREEN + 'sent' + OFF if delivery.desktop_ok else RED + 'FAILED' + OFF}")
        print(f"  email                  "
              f"{GREEN + 'sent' + OFF if delivery.email_ok else RED + 'FAILED' + OFF}")
        for problem in delivery.problems:
            print(f"\n{YELLOW}  {problem}{OFF}")

        if delivery.desktop_ok and not args.dry_run:
            print(f"\n{YELLOW}  If no notification appeared on screen, macOS")
            print("  discarded it silently. Terminal needs permission:")
            print("  System Settings -> Notifications -> Terminal ->")
            print(f"  Allow Notifications.{OFF}")
        print()
        return 0 if delivery.anything_arrived else 1

    # ------------------------------------------------------- what is due
    connection = db.init_db()
    due = alerts.due(connection, today=today, tax_year=args.year)
    to_send = due if args.force else alerts.unsent(connection, due)
    already = len(due) - len(to_send)

    if not due:
        if not args.quiet:
            print(f"\n{GREEN}Nothing needs you today ({today}).{OFF}")
            print("  No deadline within a week, no forms outstanding, no")
            print("  thresholds crossed. This is the normal result.\n")
        connection.close()
        return 0

    print(f"\n{BOLD}Reminders for {today}{OFF}")
    print("=" * 70)
    print()

    if not to_send:
        print(f"{GREEN}{already} alert{'' if already == 1 else 's'} due, but "
              f"all have been sent already.{OFF}")
        print("  They are not repeated so they stay worth reading.")
        print("  Use --force to send again.\n")
        for alert in due:
            show(alert, args.full)
        connection.close()
        return 0

    if already:
        print(f"{already} other alert{'' if already == 1 else 's'} already "
              f"sent, not repeated.\n")

    for alert in to_send:
        show(alert, args.full)

    # ------------------------------------------------------------ sending
    if args.dry_run:
        print("-" * 70)
        print(f"{YELLOW}DRY RUN - nothing was sent and nothing was recorded.")
        print(f"Run without --dry-run to send.{OFF}\n")
        connection.close()
        return 0

    print("-" * 70)
    sent = failed = 0
    for alert in to_send:
        delivery = notify.send(alert.subject, alert.body, short=alert.short)

        if delivery.anything_arrived:
            # Recorded only when something actually got through. If the Mac
            # was offline, the alert must still be waiting on the next run
            # rather than being marked done and never seen.
            db.record_alert(connection, alert_key=alert.key,
                            alert_type=alert.kind, subject=alert.subject,
                            detail=alert.short)
            connection.commit()
            channels = " and ".join(
                [name for name, ok in (("desktop", delivery.desktop_ok),
                                       ("email", delivery.email_ok)) if ok])
            print(f"  {GREEN}sent{OFF} ({channels})  {alert.subject}")
            sent += 1
        else:
            print(f"  {RED}FAILED{OFF}  {alert.subject}")
            failed += 1

        for problem in delivery.problems:
            print(f"{YELLOW}      {problem}{OFF}")

    print()
    print(f"  {sent} sent, {failed} failed.")
    if failed:
        print(f"\n{YELLOW}  Failed alerts were NOT recorded as sent, so they")
        print(f"  will be tried again next run.{OFF}")
    print()

    connection.close()
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
