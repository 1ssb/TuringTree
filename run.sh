#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# run.sh — open RagIndex as a local app on macOS / Linux.
#
# Builds the web UI the first time, then starts the app and opens your browser.
# Run scripts/setup.sh once beforehand to create the virtual-env and pull the
# local models. Then:
#
#     ./run.sh                 # open the app
#     ./run.sh --no-browser    # serve without opening a browser
#     ./run.sh --port 8765     # pin a port
# ---------------------------------------------------------------------------
set -euo pipefail
cd "$(dirname "$0")"

if [ -x ".venv/bin/python" ]; then
    exec .venv/bin/python scripts/run.py "$@"
elif [ -x ".venv/Scripts/python.exe" ]; then  # Windows venv under Git Bash
    exec .venv/Scripts/python.exe scripts/run.py "$@"
else
    exec python3 scripts/run.py "$@"
fi
