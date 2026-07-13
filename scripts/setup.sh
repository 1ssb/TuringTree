#!/usr/bin/env bash
# scripts/setup.sh — Unix (macOS / Linux) setup wrapper for RagIndex.
#
# The real, cross-platform logic lives in scripts/setup.py so Windows, macOS,
# and Linux all run the exact same steps. This wrapper just finds a Python 3
# interpreter and hands off (forwarding any extra flags, e.g. --skip-ollama):
#
#     bash scripts/setup.sh
#
set -euo pipefail

# Always operate from the project root (the parent of this scripts/ folder).
cd "$(dirname "$0")/.."

# Prefer python3.13 (best wheel support); fall back to any python3 / python.
PY=""
for candidate in python3.13 python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then
    PY="$candidate"
    break
  fi
done

if [ -z "$PY" ]; then
  echo "Python 3 is required but was not found. Install Python 3.10+ and re-run." >&2
  exit 1
fi

exec "$PY" scripts/setup.py "$@"
