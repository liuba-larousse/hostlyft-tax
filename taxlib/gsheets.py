"""
gsheets.py - talking to Google Sheets and Drive as a service account.

WHAT A SERVICE ACCOUNT IS
    A robot user with its own email address, something like

        hostlyft-tax@your-project.iam.gserviceaccount.com

    Google will not let a program open a spreadsheet just because YOU can
    see it. The program needs an identity of its own, and you share the file
    with that identity exactly as you would with a colleague.

    That is the step everyone forgets, and the error when you do is
    unhelpful - a bare 404, as though the file did not exist. So
    check_google.py tests for it specifically and says so in plain words.

WHY THE KEY FILE MATTERS
    The downloaded JSON is a private key. Anyone holding it can act as that
    robot. It lives in tax/, is chmod 600, and .gitignore blocks it.

    It can only reach what you have shared with it - nothing else in your
    Drive - which is why sharing one FOLDER rather than your whole account
    is the right shape.

A NOTE ON THE WARNINGS
    Google's libraries print an end-of-life warning on every import, because
    macOS ships Python 3.9. They are silenced here so real problems stay
    visible - but the warning is telling the truth, and installing a current
    Python is worth doing when the project moves to the main Mac.
"""

import warnings

warnings.filterwarnings("ignore", category=FutureWarning,
                        module=r"google.*")

import json          # noqa: E402
from pathlib import Path   # noqa: E402

from taxlib import config  # noqa: E402


# Read and write spreadsheets, and see files that have been shared.
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


class GoogleError(Exception):
    """Something went wrong reaching Google, explained in plain English."""


def key_path():
    """Where the service-account key file lives."""
    raw = config.get_secret("GOOGLE_SERVICE_ACCOUNT_JSON",
                            default="tax/google_service_account.json")
    path = Path(raw)
    return path if path.is_absolute() else config.ROOT / path


def read_key_file(path=None):
    """Load and sanity-check the key file, without ever printing the key."""
    path = Path(path) if path else key_path()

    if not path.exists():
        raise GoogleError(
            f"No service-account key at {path}.\n"
            f"Download it from the Google Cloud console and save it there.\n"
            f"See the walkthrough in GOOGLE-SETUP.md")

    try:
        data = json.loads(path.read_text())
    except Exception:
        raise GoogleError(f"{path} is not readable JSON. Re-download it.")

    if data.get("type") != "service_account":
        raise GoogleError(
            f"{path} is not a service-account key - its type is "
            f"'{data.get('type')}'.\n"
            f"Google hands out several kinds of credential file and they "
            f"look similar. You need the one created under\n"
            f"  IAM & Admin -> Service Accounts -> Keys -> Add key -> JSON")

    for field in ("client_email", "private_key", "project_id"):
        if not data.get(field):
            raise GoogleError(f"{path} is missing '{field}'. Re-download it.")

    return data


def credentials(path=None):
    """Turn the key file into something the Google libraries accept."""
    from google.oauth2 import service_account

    data = read_key_file(path)
    try:
        return service_account.Credentials.from_service_account_info(
            data, scopes=SCOPES)
    except Exception as error:
        raise GoogleError(f"The key file was rejected: {error}")


def service(name, version, path=None):
    """Build a Google API client. name is 'sheets' or 'drive'."""
    from googleapiclient.discovery import build
    return build(name, version, credentials=credentials(path),
                 cache_discovery=False)


def describe_error(error, what):
    """Turn a Google API error into something worth reading."""
    status = getattr(getattr(error, "resp", None), "status", None)

    if status == 404:
        return (f"Google says {what} does not exist.\n"
                f"Almost always this means it has NOT been shared with the "
                f"service account.\n"
                f"A service account can only see what you share with it - "
                f"being able to see it yourself is not enough.\n"
                f"Share it with the robot's email address, giving Editor "
                f"access.")
    if status == 403:
        return (f"Google refused access to {what} (403).\n"
                f"Either the Sheets and Drive APIs are not switched on for "
                f"the project, or the service account was shared as Viewer "
                f"rather than Editor.")
    if status == 401:
        return ("Google rejected the key (401). It has probably been "
                "deleted in the console. Create a new one.")
    return f"Google returned an error for {what}: {error}"
