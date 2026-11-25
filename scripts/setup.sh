#!/usr/bin/env bash
# One-command setup for Lead Radar. Idempotent: safe to run repeatedly.
#   scripts/setup.sh                 create .venv, install requirements, create .env, run the self-test
#   scripts/setup.sh --with-browser  also install Google Chrome for Playwright (needed for browser tasks)
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

WITH_BROWSER=0
for arg in "$@"; do
  case "$arg" in
    --with-browser) WITH_BROWSER=1 ;;
    -h|--help) sed -n '2,5p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null 2>&1 || { echo "error: $PY not found; install Python 3.9 or newer" >&2; exit 1; }
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' \
  || { echo "error: Python 3.9 or newer is required (found $("$PY" -V 2>&1))" >&2; exit 1; }
echo "$("$PY" -V 2>&1) ok"

if [ ! -d .venv ]; then
  "$PY" -m venv .venv
  echo "created .venv"
fi
VPY=".venv/bin/python"
[ -x "$VPY" ] || VPY=".venv/Scripts/python"   # Git Bash on Windows

"$VPY" -m pip install --quiet --upgrade pip
"$VPY" -m pip install --quiet -r requirements.txt
echo "requirements installed"

if [ ! -f .env ]; then
  cp .env.example .env
  echo "created .env from .env.example (edit it if you need SMTP or a custom Chrome path)"
fi

if [ "$WITH_BROWSER" -eq 1 ]; then
  # The code launches Playwright with channel="chrome", so it needs Google Chrome (not the bundled Chromium).
  "$VPY" -m playwright install chrome
else
  echo "skipping browser install (pass --with-browser, or install Google Chrome yourself)"
fi

"$VPY" radar.py --selftest
"$VPY" -m py_compile radar.py browser.py pdfmaker.py scripts/seed_demo_data.py

cat <<'MSG'

Setup complete. Start the app with:
  scripts/run.sh
then open http://127.0.0.1:8790
MSG
