#!/usr/bin/env python3
"""
scripts/setup.py — cross-platform, one-command setup for the RagIndex workspace.

Runs the SAME steps on Windows, macOS, and Linux (the OS-specific bits — venv
paths, Ollama install, background server start — are handled here), so teammates
on any machine get an identical environment.

Use any Python 3.10+:

    python  scripts/setup.py          # Windows
    python3 scripts/setup.py          # macOS / Linux

…or the thin wrappers:  scripts/setup.sh (Unix)  •  scripts/setup.ps1 / setup.bat (Windows).

Steps (all idempotent — safe to re-run):
  1. Create the .venv virtual environment.
  2. Install Python deps (requirements.txt + backend/requirements.txt).
  3. Seed .env from .env.example (if present and missing).
  4. Clone the vendored PageIndex model, refresh its branches, and pin it to a
     known-good commit (RAGINDEX_PAGEINDEX_REF) for reproducibility.
  5. Install the frontend's Node deps (npm install), if npm is available.
  6. Ensure Ollama is installed + running and pull the pinned models.

Everything runs LOCALLY through Ollama — no cloud accounts, no API keys.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IS_WINDOWS = os.name == "nt"
SYSTEM = platform.system()  # "Windows" | "Darwin" | "Linux"
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
PAGEINDEX_REPO = "https://github.com/VectifyAI/PageIndex.git"
# Pin the vendored PageIndex to a known-good commit for reproducibility (the
# branch indexer still sees all origin/* branches; only the working tree is
# pinned). Override with RAGINDEX_PAGEINDEX_REF=<tag|branch|sha>, or set it empty
# to track upstream HEAD.
PAGEINDEX_REF = os.environ.get(
    "RAGINDEX_PAGEINDEX_REF", "293730afbd4319a683fe4aee439360a2b21b8c3c"
)
OLLAMA_DOWNLOAD = "https://ollama.com/download"


# ── tiny logging helpers ─────────────────────────────────────────────────────


def info(msg: str) -> None:
    print(f">> {msg}", flush=True)


def warn(msg: str) -> None:
    print(f"!! {msg}", flush=True)


def run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> int:
    """Echo and run a command, returning its exit code."""
    info("$ " + " ".join(str(c) for c in cmd))
    result = subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=False)
    if check and result.returncode != 0:
        raise SystemExit(f"Command failed ({result.returncode}): {' '.join(cmd)}")
    return result.returncode


def have(tool: str) -> bool:
    return shutil.which(tool) is not None


def venv_python() -> Path:
    """Path to the interpreter inside .venv (differs per OS)."""
    if IS_WINDOWS:
        return ROOT / ".venv" / "Scripts" / "python.exe"
    return ROOT / ".venv" / "bin" / "python"


# ── 1. virtual environment ───────────────────────────────────────────────────


def ensure_venv() -> None:
    venv_dir = ROOT / ".venv"
    if venv_dir.exists():
        info("Virtual environment .venv already exists.")
        return
    info("Creating virtual environment in .venv ...")
    run([sys.executable, "-m", "venv", str(venv_dir)])


# ── 2. Python dependencies ───────────────────────────────────────────────────


def install_python_deps() -> None:
    py = str(venv_python())
    info("Installing Python dependencies ...")
    run([py, "-m", "pip", "install", "--upgrade", "pip"])
    run([py, "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")])
    backend_req = ROOT / "backend" / "requirements.txt"
    if backend_req.exists():
        run([py, "-m", "pip", "install", "-r", str(backend_req)])


# ── 3. .env seed ─────────────────────────────────────────────────────────────


def seed_env() -> None:
    example = ROOT / ".env.example"
    env = ROOT / ".env"
    if example.exists() and not env.exists():
        info("Creating .env from .env.example ...")
        env.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")


# ── 4. PageIndex model ───────────────────────────────────────────────────────


def ensure_pageindex() -> None:
    if not have("git"):
        warn("git not found — skipping PageIndex. Install Git and re-run.")
        return
    dest = ROOT / "vendor" / "PageIndex"
    if not (dest / ".git").exists():
        info("Cloning the PageIndex model ...")
        (ROOT / "vendor").mkdir(parents=True, exist_ok=True)
        run(["git", "clone", PAGEINDEX_REPO, str(dest)])
    else:
        info("PageIndex already present — refreshing branches ...")
    run(["git", "-C", str(dest), "fetch", "--all", "--prune"], check=False)
    if PAGEINDEX_REF:
        info(f"Pinning PageIndex to {PAGEINDEX_REF} ...")
        code = run(["git", "-C", str(dest), "checkout", "--quiet", PAGEINDEX_REF], check=False)
        if code != 0:
            warn(f"Could not check out RAGINDEX_PAGEINDEX_REF={PAGEINDEX_REF}; using current HEAD.")


# ── 5. frontend ──────────────────────────────────────────────────────────────


def install_frontend_deps() -> None:
    frontend = ROOT / "frontend"
    if not frontend.exists():
        return
    npm = shutil.which("npm")
    if not npm:
        warn(
            "npm not found — skipping the frontend. Install Node.js 18+ from "
            "https://nodejs.org and run `npm install` inside frontend/."
        )
        return
    info("Installing frontend dependencies (npm install) ...")
    run([npm, "install"], cwd=frontend, check=False)


# ── 6. Ollama runtime + models ───────────────────────────────────────────────


def ollama_reachable() -> bool:
    try:
        with urllib.request.urlopen(f"{OLLAMA_HOST}/api/tags", timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


def ollama_version() -> str:
    try:
        out = subprocess.run(
            ["ollama", "--version"], capture_output=True, text=True, check=False
        )
        return (out.stdout or out.stderr).strip() or "installed"
    except Exception:
        return "installed"


def install_ollama() -> None:
    info("Ollama not found — attempting to install it ...")
    try:
        if SYSTEM == "Darwin":
            if have("brew"):
                run(["brew", "install", "ollama"], check=False)
            else:
                warn(f"Homebrew not found. Download Ollama from {OLLAMA_DOWNLOAD}.")
        elif SYSTEM == "Linux":
            run(["sh", "-c", "curl -fsSL https://ollama.com/install.sh | sh"], check=False)
        elif SYSTEM == "Windows":
            if have("winget"):
                run(
                    [
                        "winget", "install", "--id", "Ollama.Ollama", "-e",
                        "--accept-package-agreements", "--accept-source-agreements",
                    ],
                    check=False,
                )
            else:
                warn(f"Download the Ollama Windows installer from {OLLAMA_DOWNLOAD}.")
        else:
            warn(f"Unsupported OS '{SYSTEM}'. Install Ollama from {OLLAMA_DOWNLOAD}.")
    except Exception as exc:  # never let an install attempt abort setup
        warn(f"Automatic Ollama install failed ({exc}). See {OLLAMA_DOWNLOAD}.")


def start_ollama_server() -> None:
    info("Starting the Ollama server in the background ...")
    try:
        if IS_WINDOWS:
            flags = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(
                subprocess, "DETACHED_PROCESS", 0
            )
            subprocess.Popen(["ollama", "serve"], creationflags=flags)
        else:
            subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
    except Exception as exc:
        warn(f"Could not start Ollama automatically ({exc}).")
        return
    for _ in range(30):
        if ollama_reachable():
            return
        time.sleep(1)


def pull_models() -> None:
    models_file = ROOT / "ollama-models.txt"
    if not models_file.exists():
        return
    info("Pulling local models from ollama-models.txt ...")
    for raw in models_file.read_text(encoding="utf-8").splitlines():
        model = raw.split("#", 1)[0].strip()  # strip comments + whitespace
        if not model:
            continue
        info(f"  - {model}")
        run(["ollama", "pull", model], check=False)


def ensure_ollama(skip_models: bool) -> None:
    if not have("ollama"):
        install_ollama()
    if not have("ollama"):
        warn(
            f"Ollama is not installed. Get it from {OLLAMA_DOWNLOAD}, then re-run "
            "this script to pull the models."
        )
        return
    info(f"Using Ollama: {ollama_version()}")
    if not ollama_reachable():
        start_ollama_server()
    if not ollama_reachable():
        warn(
            "Could not reach the Ollama server. Start it ('ollama serve' or the "
            "Ollama app) and re-run to pull the models."
        )
        return
    if skip_models:
        info("Skipping model pulls (--skip-models).")
        return
    pull_models()


# ── next steps ───────────────────────────────────────────────────────────────


def print_next_steps() -> None:
    if IS_WINDOWS:
        activate = r".venv\Scripts\Activate.ps1   (PowerShell)   or   .venv\Scripts\activate.bat (cmd)"
    else:
        activate = "source .venv/bin/activate"
    print(
        "\n"
        ">> Setup complete — everything runs locally, no API keys needed.\n"
        "\n"
        "   Start the backend (terminal 1):\n"
        f"     {activate}\n"
        "     uvicorn backend.app.main:app --reload --port 8000\n"
        "\n"
        "   Start the frontend (terminal 2):\n"
        "     npm --prefix frontend run dev\n"
        "\n"
        "   Then open http://localhost:5173 and index a folder.\n"
    )


# ── main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Cross-platform RagIndex setup.")
    parser.add_argument("--skip-frontend", action="store_true", help="Skip npm install.")
    parser.add_argument(
        "--skip-ollama", action="store_true", help="Skip Ollama install/serve/pull."
    )
    parser.add_argument(
        "--skip-models", action="store_true", help="Set up Ollama but don't pull models."
    )
    args = parser.parse_args()

    os.chdir(ROOT)
    print("=== RagIndex setup ===")
    info(f"OS: {SYSTEM} {platform.release()}")
    info(f"Python: {platform.python_version()} ({sys.executable})")
    if sys.version_info < (3, 10):
        warn("Python 3.10+ is recommended. Some dependencies may not install on older versions.")

    ensure_venv()
    install_python_deps()
    seed_env()
    ensure_pageindex()
    if not args.skip_frontend:
        install_frontend_deps()
    if not args.skip_ollama:
        ensure_ollama(skip_models=args.skip_models)

    print_next_steps()


if __name__ == "__main__":
    main()
