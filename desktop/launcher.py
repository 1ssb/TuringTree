"""
desktop/launcher.py — run RagIndex as a one-click desktop application.

This is the entry point the packaged build (PyInstaller) executes, and it also
runs straight from a checkout:

    python -m desktop.launcher                 # opens http://127.0.0.1:<port>
    python -m desktop.launcher --no-browser    # headless (CI / servers)
    python -m desktop.launcher --port 8000      # pin a port

What it does, in order:
  1. Resolve a per-user, WRITABLE data directory (e.g. %LOCALAPPDATA%\\RagIndex on
     Windows) and point the app at it via RAGINDEX_DATA_DIR. An installed app must
     never write to its read-only install folder, so this step is what makes the
     packaged build behave correctly.
  2. Bind to localhost only (127.0.0.1) on a free port — a desktop app should not
     be reachable from the network.
  3. Do a quick, non-fatal Ollama pre-flight so the user gets a friendly hint if
     the local model runtime isn't up (branch search still works offline).
  4. Serve the bundled UI + JSON API as ONE process and open the browser.
  5. Shut the server down cleanly on Ctrl+C.

The small helpers below are kept pure (no side effects beyond what they return or
the environment they set) so they can be unit-tested without starting a server.
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

# Run correctly even when invoked as `python desktop/launcher.py` (in which case
# sys.path[0] is the desktop/ folder, not the repo root) and when frozen.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

APP_NAME = "RagIndex"
DEFAULT_HOST = "127.0.0.1"  # localhost only — never expose a desktop app to the LAN
PREFERRED_PORT = 8765       # used when free; otherwise the OS assigns one


def user_data_dir(app_name: str = APP_NAME) -> Path:
    """Per-user, writable data directory following each OS's convention.

    Windows: %LOCALAPPDATA%\\<app>;  macOS: ~/Library/Application Support/<app>;
    Linux/other: $XDG_DATA_HOME/<app> or ~/.local/share/<app>.
    """
    if sys.platform.startswith("win"):
        base = os.getenv("LOCALAPPDATA") or os.path.expanduser(r"~\AppData\Local")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.getenv("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return Path(base).expanduser() / app_name


def find_free_port(preferred: int | None = PREFERRED_PORT, host: str = DEFAULT_HOST) -> int:
    """Return `preferred` if it is bindable, otherwise an OS-assigned free port."""
    if preferred:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind((host, preferred))
                return preferred
            except OSError:
                pass  # in use — fall through to an ephemeral port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((host, 0))
        return probe.getsockname()[1]


def configure_runtime(data_dir: Path | None = None) -> Path:
    """Create the writable data dir and point the app at it via the environment.

    Uses ``setdefault`` so values explicitly set by the user/installer win. Returns
    the resolved data directory. Must run BEFORE the app (and thus config.py) is
    imported, because config.py reads these on import.
    """
    resolved = (data_dir or user_data_dir()).expanduser()
    incoming = resolved / "incoming"
    for folder in (resolved, incoming):
        folder.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("RAGINDEX_DATA_DIR", str(resolved))
    os.environ.setdefault("RAGINDEX_INCOMING_DIR", str(incoming))
    os.environ.setdefault("RAGINDEX_LOG_LEVEL", "INFO")
    return resolved


def ollama_available(host: str | None = None, timeout: float = 1.5) -> bool:
    """Best-effort check that the local Ollama runtime is reachable (non-fatal)."""
    base = (host or os.getenv("OLLAMA_HOST", "http://localhost:11434")).rstrip("/")
    try:
        import httpx

        return httpx.get(f"{base}/api/tags", timeout=timeout).status_code == 200
    except Exception:
        return False


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="ragindex",
        description="Run RagIndex as a local desktop app (UI + API on one URL).",
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=None, help="port (default: a free port)")
    parser.add_argument("--data-dir", default=None, help="override the data directory")
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    data_dir = configure_runtime(Path(args.data_dir) if args.data_dir else None)
    host = args.host
    port = args.port or find_free_port(PREFERRED_PORT, host)
    url = f"http://{host}:{port}"

    print(f"{APP_NAME} — local, on-device RAG")
    print(f"  data:  {data_dir}")
    print(f"  url:   {url}")
    if not ollama_available():
        print(
            "  note:  Ollama not detected — chat & indexing need it "
            "(branch search still works offline). Start it with `ollama serve`."
        )

    # Import the app only AFTER configure_runtime() so config.py sees the data dir.
    from backend.app.main import app
    import uvicorn

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level=os.getenv("RAGINDEX_LOG_LEVEL", "info").lower(),
        workers=1,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="ragindex-uvicorn", daemon=True)
    thread.start()

    # Wait until the server reports started (or the thread dies on a bind error).
    while not server.started and thread.is_alive():
        time.sleep(0.05)
    if not thread.is_alive():
        print("error: the server failed to start.", file=sys.stderr)
        return 1

    print(f"{APP_NAME} is ready. Press Ctrl+C to stop.")
    if not args.no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass  # headless box — the URL is printed above

    try:
        while thread.is_alive():
            thread.join(0.5)
    except KeyboardInterrupt:
        print("\nShutting down…")
    finally:
        server.should_exit = True
        thread.join(timeout=5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
