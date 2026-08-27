#!/usr/bin/env bash
# Idempotent Cloud Agent bootstrap for usage-dashboard (FastAPI wallet dashboard).
# Runs after checkout; creates a venv and installs the same deps the prod Dockerfile pins,
# plus pytest for the repo's unittest-based suite.
set -euo pipefail

cd "$(dirname "$0")/.."

# python venv module is not in the default image; install it once (idempotent).
if ! python3 -c 'import ensurepip' >/dev/null 2>&1; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq python3-venv
fi

if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi

. .venv/bin/activate
python -m pip install --upgrade pip -q
python -m pip install -q -r .cursor/requirements-dev.txt

# Data dir for rolling snapshots (gitignored). Static ships in the repo.
mkdir -p data

echo "install.sh: done ($(python --version))"
