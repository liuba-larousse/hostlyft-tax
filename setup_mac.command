#!/bin/bash
#
# setup_mac.command - one-time setup for the Hostlyft tax tracker.
#
# Double-click this file in Finder, or run  ./setup_mac.command  in Terminal.
# It is safe to run again later; it never overwrites your secrets.
#
# The .command extension is a macOS thing: it makes a script double-clickable,
# opening a Terminal window to show you what happens.

# When you double-click, Finder starts the script from your home folder, not
# from the project folder. This line moves to wherever this script lives, so
# everything below works either way.
cd "$(dirname "$0")" || exit 1

# Stop immediately if any command fails, instead of ploughing on and leaving a
# half-finished mess.
set -e

# Colours, so problems are visible rather than buried in a wall of text.
BOLD=$'\033[1m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RED=$'\033[31m'; OFF=$'\033[0m'

say()  { printf "%s\n" "$*"; }
step() { printf "\n${BOLD}%s${OFF}\n" "$*"; }
ok()   { printf "  ${GREEN}OK${OFF}    %s\n" "$*"; }
warn() { printf "  ${YELLOW}NOTE${OFF}  %s\n" "$*"; }
fail() { printf "\n  ${RED}PROBLEM${OFF}  %s\n" "$*"; }

# Whatever happens, keep the window open so you can read it. Without this, a
# double-clicked script that fails flashes up and vanishes.
finish() {
  printf "\n%s\n" "----------------------------------------------------------"
  printf "Press Return to close this window.\n"
  read -r _
}
trap finish EXIT

say ""
say "${BOLD}Hostlyft Tax Tracker - Mac setup${OFF}"
say "=========================================================="
say "Project folder: $(pwd)"


# --------------------------------------------------------------------------
step "1. Checking Python"
# --------------------------------------------------------------------------
# Python is the language this project is written in. macOS ships with it, so
# there is normally nothing to install.

if ! command -v python3 >/dev/null 2>&1; then
  fail "python3 was not found on this Mac."
  say  "  Install Apple's developer tools by running this in Terminal:"
  say  "      xcode-select --install"
  say  "  Then double-click this file again."
  exit 1
fi

PYTHON_VERSION="$(python3 --version 2>&1)"
ok "$PYTHON_VERSION"


# --------------------------------------------------------------------------
step "2. Building the virtual environment"
# --------------------------------------------------------------------------
# A "virtual environment" is a private folder (.venv) holding this project's
# libraries. Without it, installing something here could change the version
# another program on your Mac depends on, and break it.
#
# With it, everything this project installs is sealed inside .venv. Deleting
# that one folder undoes it completely. .venv is in .gitignore, so it never
# goes to GitHub - it is rebuilt by running this script.

if [ -d ".venv" ]; then
  ok ".venv already exists - reusing it"
else
  say "  Creating .venv ..."
  python3 -m venv .venv
  ok "created"
fi

# "Activating" means: for the rest of this script, python and pip refer to the
# copies inside .venv rather than the ones belonging to macOS.
# shellcheck disable=SC1091
source .venv/bin/activate
ok "activated  ($(python --version 2>&1))"


# --------------------------------------------------------------------------
step "3. Installing the libraries"
# --------------------------------------------------------------------------
# pip is Python's installer. It reads requirements.txt and downloads each
# library listed there into .venv.

say "  Updating pip itself ..."
python -m pip install --quiet --upgrade pip

say "  Installing from requirements.txt (may take a minute) ..."
if python -m pip install --quiet -r requirements.txt; then
  ok "libraries installed"
else
  fail "Installation failed."
  say  "  The most common cause is no internet connection."
  say  "  To see the full error, run this in Terminal:"
  say  "      cd \"$(pwd)\" && source .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi


# --------------------------------------------------------------------------
step "4. Creating the private data folder"
# --------------------------------------------------------------------------
# tax/ holds the only two things that must never leave this Mac: your secrets
# and your financial database. .gitignore blocks both from GitHub.

mkdir -p tax
chmod 700 tax   # 700 = only your Mac account can open this folder
ok "tax/  ready (private to your account)"


# --------------------------------------------------------------------------
step "5. Creating your secrets file"
# --------------------------------------------------------------------------
# tax/.env is your personal copy of .env.example, with real values in it.

if [ -f "tax/.env" ]; then
  ok "tax/.env already exists - left untouched"
else
  cp .env.example tax/.env
  ok "tax/.env created from the template (all values still blank)"
fi

chmod 600 tax/.env   # 600 = only you can read or write this file
ok "tax/.env locked to your account only"


# --------------------------------------------------------------------------
step "6. Checking the configuration"
# --------------------------------------------------------------------------

say ""
python -m taxlib.config


# --------------------------------------------------------------------------
say ""
say "${BOLD}${GREEN}Setup finished.${OFF}"
say ""
say "Nothing above needs fixing - blank secrets are expected this early."
say "You fill each one in when the stage that needs it arrives."
say ""
say "${BOLD}To use the project from Terminal, two commands:${OFF}"
say "    cd \"$(pwd)\""
say "    source .venv/bin/activate"
say ""
say "The second one is the step people forget. Your prompt shows (.venv)"
say "at the front once it has worked."
