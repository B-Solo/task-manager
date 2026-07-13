#!/usr/bin/env bash
#
# Launch the Viewer (the TV machine — macOS host "BESOLOMO-M-WDKQ").
# Activates the repo's virtualenv and starts the full-screen Viewer + server.
#
# Usage:  ./run-viewer.sh
# Runs from anywhere — it cd's to its own directory (the repo root) first.

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

VENV=".venv"
if [ ! -f "$VENV/bin/activate" ]; then
  echo "No virtualenv at $VENV. Create it once with:" >&2
  echo "  python3 -m venv .venv" >&2
  echo "  source .venv/bin/activate && pip install -r viewer/requirements.txt" >&2
  exit 1
fi

# shellcheck disable=SC1091
source "$VENV/bin/activate"

# exec so Ctrl+C in the terminal goes straight to Python (clean shutdown).
exec python viewer/src/app.py "$@"
