#!/usr/bin/env bash
# Loads .env (if present) and starts Lead Radar on http://127.0.0.1:8790
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
if [ -f .env ]; then set -a; . ./.env; set +a; fi
# An empty CHROME_BIN in .env must not override the built-in default.
[ -n "${CHROME_BIN:-}" ] || unset CHROME_BIN
VPY=".venv/bin/python"
[ -x "$VPY" ] || VPY="${PYTHON:-python3}"
exec "$VPY" radar.py
