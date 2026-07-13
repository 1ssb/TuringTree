"""
scripts/build_desktop.py — build the RagIndex desktop app end-to-end.

One command turns a checkout into a self-contained app:

    python scripts/build_desktop.py            # build UI (if needed) + freeze
    python scripts/build_desktop.py --rebuild-ui   # force a fresh UI build

Steps:
  1. Build the React UI into frontend/dist (skipped if already present).
  2. Run PyInstaller with packaging/ragindex.spec.

Output: dist/RagIndex/ — run dist/RagIndex/RagIndex(.exe) to start the app.
Ollama is an external runtime and is not bundled (see docs/desktop.md).
"""

from __future__ import annotations

import argparse
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = REPO_ROOT / "frontend"
DIST_UI = FRONTEND_DIR / "dist"
SPEC = REPO_ROOT / "packaging" / "ragindex.spec"


def _run(cmd: list[str], cwd: Path) -> None:
    print(f"\n$ {' '.join(cmd)}  (in {cwd})")
    subprocess.run(cmd, cwd=str(cwd), check=True)


def _npm() -> str:
    """Resolve the npm executable (npm.cmd on Windows)."""
    for name in ("npm", "npm.cmd"):
        found = shutil.which(name)
        if found:
            return found
    sys.exit("error: npm not found on PATH. Install Node.js 18+ to build the UI.")


def build_ui(force: bool) -> None:
    if DIST_UI.joinpath("index.html").is_file() and not force:
        print(f"UI already built at {DIST_UI} (use --rebuild-ui to force).")
        return
    npm = _npm()
    _run([npm, "install"], cwd=FRONTEND_DIR)
    _run([npm, "run", "build"], cwd=FRONTEND_DIR)
    if not DIST_UI.joinpath("index.html").is_file():
        sys.exit("error: UI build did not produce frontend/dist/index.html.")


def freeze() -> None:
    if importlib.util.find_spec("PyInstaller") is None:
        sys.exit(
            "error: PyInstaller is not installed.\n"
            "       pip install -r requirements-dev.txt   (or: pip install pyinstaller)"
        )
    _run(
        [sys.executable, "-m", "PyInstaller", str(SPEC), "--noconfirm", "--clean"],
        cwd=REPO_ROOT,
    )
    out = REPO_ROOT / "dist" / "RagIndex"
    exe = out / ("RagIndex.exe" if sys.platform.startswith("win") else "RagIndex")
    print("\nDone.")
    print(f"  app:  {out}")
    print(f"  run:  {exe}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the RagIndex desktop app.")
    parser.add_argument("--rebuild-ui", action="store_true", help="force a fresh UI build")
    parser.add_argument("--skip-ui", action="store_true", help="skip the UI build step")
    args = parser.parse_args(argv)

    if not args.skip_ui:
        build_ui(force=args.rebuild_ui)
    freeze()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
