"""
scripts/watch_incoming.py — the watchdog runner (live document ingestion).

Start this once and leave it running. It watches the incoming/ folder and, the
moment a document lands there, hands it to the ingestion socket which builds a
PageIndex tree, saves it, and records a provenance line in the audit log.

This file stays deliberately THIN: watchdog only tells us "a file appeared", and
all the real work lives in sockets/ingest_socket.py (which in turn reuses
sockets/pageindex_socket.py). That keeps the socket style intact.

Run it:
    python scripts/watch_incoming.py

Then, in another terminal (or your file explorer), drop a .pdf / .md / .txt file
into the incoming/ folder and watch it get indexed automatically. Press Ctrl+C
to stop the watcher.
"""

import sys
import time
from pathlib import Path

# Make `import config` and `import sockets` work from any directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from watchdog.events import FileSystemEventHandler  # noqa: E402
from watchdog.observers import Observer  # noqa: E402

import config  # noqa: E402
from sockets import ingest_socket as ingest  # noqa: E402


def _is_ready(path: Path, settle_seconds: float = 1.0, timeout: float = 30.0) -> bool:
    """
    Wait until a freshly created file has finished being written.

    A file-created event can fire while the OS is still copying the bytes in. We
    poll the file size until it stops changing for `settle_seconds`, so we never
    try to index a half-written document.
    """
    last_size = -1
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            return False
        if size == last_size:
            return True
        last_size = size
        time.sleep(settle_seconds)
    return True  # give up waiting and try anyway


class IncomingHandler(FileSystemEventHandler):
    """Reacts to new files in the watched folder by indexing them."""

    def on_created(self, event) -> None:
        if event.is_directory:
            return

        path = Path(event.src_path)
        if path.suffix.lower() not in ingest.SUPPORTED_SUFFIXES:
            print(f"[watch] ignored (unsupported type): {path.name}")
            return

        if not _is_ready(path):
            print(f"[watch] skipped (vanished before ready): {path.name}")
            return

        print(f"[watch] indexing: {path.name} ...")
        try:
            entry = ingest.ingest_file(path)
        except Exception as exc:  # one bad file must not kill the watcher
            print(f"[watch] FAILED to index {path.name}: {exc}")
            return

        print(
            f"[watch] done: {entry['source_file']}\n"
            f"        sha256={entry['sha256'][:12]}...  tree={entry['tree_path']}"
        )


def main() -> None:
    print(f"Watching {config.INCOMING_DIR} for new documents (Ctrl+C to stop).")
    print(f"Trees   -> {config.TREES_DIR}")
    print(f"Audit   -> {config.AUDIT_LOG_PATH}\n")

    observer = Observer()
    observer.schedule(IncomingHandler(), str(config.INCOMING_DIR), recursive=False)
    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping watcher ...")
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()
