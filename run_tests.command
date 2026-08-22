#!/bin/bash
#
# run_tests.command - run every automatic check in the project.
#
# Double-click it, or run  ./run_tests.command  in Terminal.
# Green "passed" means the maths and the safeguards still behave correctly.

cd "$(dirname "$0")" || exit 1

if [ ! -d ".venv" ]; then
  printf "\n  No .venv folder found - run setup_mac.command first.\n\n"
  printf "Press Return to close.\n"; read -r _; exit 1
fi

# shellcheck disable=SC1091
source .venv/bin/activate

printf "\n\033[1mRunning the checks\033[0m\n\n"
python -m pytest -v
STATUS=$?

if [ $STATUS -eq 0 ]; then
  printf "\n\033[32mEverything passed.\033[0m\n"
else
  printf "\n\033[31mSomething failed.\033[0m Each FAILED line above names the check\n"
  printf "and shows what it expected versus what it got.\n"
fi

printf "\n----------------------------------------------------------\n"
printf "Press Return to close this window.\n"
read -r _
exit $STATUS
