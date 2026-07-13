#!/usr/bin/env python3
"""
scripts/run.py — open RagIndex as a local app in ONE step.

Once ``python scripts/setup.py`` has been run a single time, this script:
  1. builds the web UI if it isn't built yet (frontend/dist), then
  2. starts the desktop app (UI + JSON API on one local URL) and opens your
     browser at it.

    python scripts/run.py                # build if needed, then open the app
    python scripts/run.py --no-browser   # serve without opening a browser
    python scripts/run.py --port 8765    # pin a port

Any extra flags are passed straight through to ``desktop.launcher`` so this stays
a thin, predictable wrapper. Prefer the ``run.bat`` / ``run.sh`` shortcuts in the
repo root, which call this with the project's virtual-env Python automatically.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
DIST_INDEX = FRONTEND / "dist" / "index.html"


def _ui_is_built() -> bool:
    """True once Vite has emitted the production bundle the launcher serves."""
    return DIST_INDEX.exists()


def _build_ui() -> None:
    """Install web deps (first run only) and build the production UI bundle."""
    npm = "npm.cmd" if sys.platform.startswith("win") else "npm"
    if not (FRONTEND / "node_modules").exists():
        print("Installing web UI dependencies (one-time) ...")
        subprocess.run([npm, "install"], cwd=FRONTEND, check=True)
    print("Building the web UI ...")
    subprocess.run([npm, "run", "build"], cwd=FRONTEND, check=True)


def main() -> int:
    if not _ui_is_built():
        try:
            _build_ui()
        except (OSError, subprocess.CalledProcessError) as exc:
            print(f"Could not build the web UI automatically: {exc}", file=sys.stderr)
            print(
                "Install Node.js 18+ and run `npm install && npm run build` in "
                "frontend/, then re-run this script.",
                file=sys.stderr,
            )
            return 1

    # Launch via the SAME interpreter (so an active virtual-env is honoured) and
    # forward any extra CLI flags (e.g. --no-browser, --port 8765).
    return subprocess.call(
        [sys.executable, "-m", "desktop.launcher", *sys.argv[1:]], cwd=ROOT
    )


if __name__ == "__main__":
    raise SystemExit(main())
