"""
gsheets.py - talking to Google Sheets as you, via a one-time browser sign-in.

WHY NOT A SERVICE ACCOUNT
    The original design used a service account - a robot user with its own
    email, which you share a folder with. Hostlyft's Google Workspace blocks
    those keys by policy (`iam.disableServiceAccountKeyCreation`, applied
    automatically under Google's "Secure by Default" enforcement).

    So the tool signs in AS Liuba instead. Google recommends this over
    service-account keys anyway: there is no long-lived private key on disk,
    only a token that can be revoked from her account page at any moment.

WHAT IT CAN REACH - deliberately narrow
    One scope only:

        https://www.googleapis.com/auth/spreadsheets

    That is read and write access to Google SHEETS, and nothing else. No
    documents, no photos, no PDFs, no folders. Drive access was deliberately
    NOT requested.

    The one thing it costs: a newly created spreadsheet lands in the top
    level of My Drive rather than inside a folder, because putting it in a
    folder needs Drive access. Dragging it across once is a smaller price
    than handing a background job the keys to every file she owns.

TWO FILES
    tax/google_oauth_client.json   downloaded from the Cloud console. It
                                   identifies the APPLICATION, not her.
    tax/google_token.json          written by the sign-in. This one carries
                                   the access. chmod 600, gitignored.
"""

import warnings

warnings.filterwarnings("ignore", category=FutureWarning, module=r"google.*")

import json          # noqa: E402
from pathlib import Path   # noqa: E402

from taxlib import config  # noqa: E402


# Sheets only. Not Drive. See the note above.
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

CLIENT_FILE = "google_oauth_client.json"
TOKEN_FILE = "google_token.json"


class GoogleError(Exception):
    """Something went wrong reaching Google, explained in plain English."""


def client_path():
    return config.DATA_DIR / CLIENT_FILE


def token_path():
    return config.DATA_DIR / TOKEN_FILE


def read_client_file(path=None):
    """Check the downloaded OAuth client file is the right kind."""
    path = Path(path) if path else client_path()

    if not path.exists():
        raise GoogleError(
            f"No OAuth client file at {path}.\n"
            f"Create one at console.cloud.google.com:\n"
            f"  APIs & Services -> Credentials -> Create credentials\n"
            f"  -> OAuth client ID -> Desktop app -> download the JSON\n"
            f"See GOOGLE-SETUP.md")

    try:
        data = json.loads(path.read_text())
    except Exception:
        raise GoogleError(f"{path} is not readable JSON. Re-download it.")

    # A desktop client file has a top-level "installed" key.
    if "installed" not in data:
        if "web" in data:
            raise GoogleError(
                f"{path} is a WEB application client.\n"
                f"Create it again choosing application type "
                f"'Desktop app' - a web client expects a hosted redirect "
                f"address and cannot complete a sign-in from a Mac.")
        if data.get("type") == "service_account":
            raise GoogleError(
                f"{path} is a service-account key, not an OAuth client.\n"
                f"Those are blocked by your organisation's policy, which is "
                f"why we are using a sign-in instead.")
        raise GoogleError(
            f"{path} is not a Desktop OAuth client file. Re-download it "
            f"from Credentials -> OAuth client ID -> Desktop app.")

    return data


def sign_in(path=None):
    """
    Open a browser once, ask for approval, and save the token.

    Only ever run by hand, from scripts/google_login.py. Everything else
    uses the saved token and refreshes it silently.
    """
    from google_auth_oauthlib.flow import InstalledAppFlow

    read_client_file(path)          # fail early with a useful message
    flow = InstalledAppFlow.from_client_secrets_file(
        str(path or client_path()), SCOPES)

    # A local one-shot web server catches Google's redirect. Port 0 means
    # "any free port", so nothing on the Mac is disturbed.
    creds = flow.run_local_server(port=0, open_browser=True,
                                  authorization_prompt_message="",
                                  success_message="Signed in. You can close "
                                                  "this tab and go back to "
                                                  "Terminal.")
    save_token(creds)
    return creds


def save_token(creds):
    config.ensure_data_dir()
    path = token_path()
    path.write_text(creds.to_json())
    path.chmod(0o600)
    return path


def credentials():
    """
    The saved token, refreshed if it has gone stale.

    Refreshing happens silently and needs no browser, which is what lets a
    scheduled job run unattended.
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    path = token_path()
    if not path.exists():
        raise GoogleError(
            "Not signed in to Google yet.\n"
            "Run:  python scripts/google_login.py")

    creds = Credentials.from_authorized_user_file(str(path), SCOPES)

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            save_token(creds)
        except Exception as error:
            raise GoogleError(
                f"Google would not renew the sign-in: {error}\n"
                f"This usually means access was revoked, or the OAuth "
                f"consent screen is still in 'Testing' mode - which expires "
                f"tokens after 7 days. Set it to 'Internal' and sign in "
                f"again:  python scripts/google_login.py")

    if not creds.valid:
        raise GoogleError(
            "The saved Google sign-in is no longer valid.\n"
            "Run:  python scripts/google_login.py")

    return creds


def service(name="sheets", version="v4"):
    from googleapiclient.discovery import build
    return build(name, version, credentials=credentials(),
                 cache_discovery=False)


def describe_error(error, what):
    """Turn a Google API error into something worth reading."""
    status = getattr(getattr(error, "resp", None), "status", None)

    if status == 404:
        return (f"Google says {what} does not exist. Check the ID in "
                f"tax/.env is right.")
    if status == 403:
        message = str(error)
        if "disabled" in message or "not been used" in message:
            return (f"The Google Sheets API is not switched on for this "
                    f"project.\n"
                    f"Turn it on: console.cloud.google.com -> APIs & "
                    f"Services -> Library -> Google Sheets API -> Enable")
        return f"Google refused access to {what} (403). {message[:180]}"
    if status == 401:
        return ("Google rejected the sign-in (401). Run "
                "scripts/google_login.py again.")
    return f"Google returned an error for {what}: {str(error)[:200]}"
