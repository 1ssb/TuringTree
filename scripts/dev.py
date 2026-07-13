#!/usr/bin/env python3
"""
scripts/dev.py — run the RagIndex backend (FastAPI/uvicorn) and frontend (Vite)
together with ONE command, on any OS:

    python scripts/dev.py

  - backend  -> http://localhost:8000   (uvicorn --reload)
  - frontend -> http://localhost:5173   (vite dev server; proxies /api -> :8000)

Press Ctrl-C to stop both. Prerequisites (one-time): scripts/setup.py has created
the .venv and installed the frontend's node_modules, and Ollama is running (the
backend talks to it over HTTP). Use --no-frontend / --no-backend to run just one.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IS_WINDOWS = os.name == "nt"
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")


def venv_python() -> str:
    """Interpreter inside .venv (differs per OS); fall back to the current one."""
    sub = "Scripts" if IS_WINDOWS else "bin"
    exe = "python.exe" if IS_WINDOWS else "python"
    candidate = ROOT / ".venv" / sub / exe
    return str(candidate) if candidate.exists() else sys.executable


def ollama_up() -> bool:
    try:
        with urllib.request.urlopen(f"{OLLAMA_HOST}/api/tags", timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the RagIndex dev servers together.")
    ap.add_argument("--no-backend", action="store_true", help="Don't start uvicorn.")
    ap.add_argument("--no-frontend", action="store_true", help="Don't start Vite.")
    ap.add_argument("--port", type=int, default=8000, help="Backend port (default 8000).")
    args = ap.parse_args()

    os.chdir(ROOT)
    if not ollama_up():
        print(f"!! Ollama not reachable at {OLLAMA_HOST} — start it ('ollama serve' or the app).")
        print("   The UI still loads, but indexing and chat need Ollama running.\n")

    procs: list[subprocess.Popen] = []
    # Put each child in its own group/session so Ctrl-C is handled cleanly here.
    kw: dict = (
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        if IS_WINDOWS
        else {"start_new_session": True}
    )

    if not args.no_backend:
        cmd = [
            venv_python(), "-m", "uvicorn", "backend.app.main:app",
            "--reload", "--port", str(args.port),
        ]
        print(">> backend :", " ".join(cmd))
        procs.append(subprocess.Popen(cmd, cwd=str(ROOT), **kw))

    if not args.no_frontend:
        npm = shutil.which("npm") or ("npm.cmd" if IS_WINDOWS else "npm")
        cmd = [npm, "--prefix", "frontend", "run", "dev"]
        print(">> frontend:", " ".join(cmd))
        procs.append(subprocess.Popen(cmd, cwd=str(ROOT), **kw))

    if not procs:
        print("Nothing to run (both --no-backend and --no-frontend given).")
        return

    print(f"\n>> Running. Backend :{args.port}, frontend :5173. Press Ctrl-C to stop.\n")
    try:
        while True:
            for p in procs:
                code = p.poll()
                if code is not None:
                    print(f"!! a server exited (code {code}); stopping the rest.")
                    raise KeyboardInterrupt
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n>> Shutting down ...")
    finally:
        for p in procs:
            if p.poll() is None:
                try:
                    p.terminate()
                except Exception:
                    pass
        for p in procs:
            try:
                p.wait(timeout=5)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass


if __name__ == "__main__":
    main()
