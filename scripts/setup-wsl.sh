#!/usr/bin/env bash
# Nocturna CPU-only setup for WSL2 Ubuntu. Installs no GPU drivers and downloads no models.
set -euo pipefail
cd "$(dirname "$0")/.."

if ! grep -qi microsoft /proc/version 2>/dev/null; then
  echo "note: this does not look like WSL; continuing anyway."
fi

echo "==> System packages (python3-venv, ffmpeg)"
if command -v apt-get >/dev/null; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq python3 python3-venv python3-pip ffmpeg
fi

PY=${PYTHON:-python3}
"$PY" - <<'PYCHECK'
import sys
if sys.version_info < (3, 11):
    sys.exit(f"Python 3.11+ required, found {sys.version.split()[0]}. Set PYTHON=python3.12 or install a newer Python.")
PYCHECK

echo "==> Virtualenv in .venv"
[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -e ".[postgres,dev]"

[ -f .env ] || { cp .env.example .env; echo "==> Created .env from .env.example"; }
mkdir -p data/audio

echo "==> Database migrations"
.venv/bin/alembic upgrade head

echo "==> Tests"
.venv/bin/pytest -q

cat <<'DONE'

Done. Start the desk with:
  source .venv/bin/activate
  uvicorn nocturna.api:app --reload
Then open http://localhost:8000 in your Windows browser.
DONE
