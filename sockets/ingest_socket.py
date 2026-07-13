"""
sockets/ingest_socket.py — the INGESTION socket.

This is the "trust layer" of the workspace. It takes ONE document file and turns
it into a PageIndex tree, while recording exactly where that tree came from — so
every result in the system is traceable back to an unmodified source file.

It deliberately stays thin: the heavy lifting (building the tree) is delegated to
the existing pageindex_socket. This socket only adds the three things that make
the pipeline *trustworthy*:

  1. PROVENANCE — hash the raw bytes of the file (SHA-256) so you can later prove
     the tree was built from that exact, unmodified document.
  2. PERSISTENCE — save the resulting tree to disk (data/trees/<name>.json) so it
     can be queried later instead of being printed once and lost.
  3. AUDITABILITY — append one line to an append-only log (data/audit_log.jsonl)
     recording WHAT was indexed, WHEN, its hash, and where the tree was saved.

It then folds the tree into the shared RAG store (sockets/rag_socket.py) so the
ingested document immediately becomes answerable through the same query engine
the dataset uses — one queryable index for everything, however it arrived.

The watcher in scripts/watch_incoming.py calls ingest_file() whenever a new file
lands in the incoming/ folder, but you can also call it by hand on any file.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
from pathlib import Path
from typing import Optional

import config
from sockets import pageindex_socket as pi
from sockets import upload_socket


# Every file type the uploader can read. Ingestion routes them all through the
# SAME unified path (text extraction -> markdown tree), so a PDF/DOCX/HTML costs
# the same as plain text and indexing latency tracks length, not format.
SUPPORTED_SUFFIXES = upload_socket.SUPPORTED_EXTS


# ---------------------------------------------------------------------------
# Step 1: provenance — a stable fingerprint of the raw file
# ---------------------------------------------------------------------------
def hash_file(path: Path, chunk_size: int = 1 << 20) -> str:
    """
    Return the SHA-256 hex digest of a file's raw bytes.

    Reading in chunks keeps memory flat even for large PDFs. The digest is the
    document's fingerprint: if a single byte changes, the hash changes, so it
    proves the tree was built from this exact file.
    """
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk_size), b""):
            digest.update(block)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Step 2: persistence — turn one file into a saved PageIndex tree
# ---------------------------------------------------------------------------
def build_tree_for_file(path: Path, model: Optional[str] = None) -> dict:
    """
    Build a PageIndex tree from a single file using the UNIFIED procedure: extract
    plain text from the file (whatever its format), then build a markdown-style
    tree from that text. Every document type — PDF, Markdown, TXT, HTML, DOCX —
    takes the same fast path, so indexing latency tracks a document's *length*,
    not its format. Unsupported or empty files raise ValueError.
    """
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(
            f"Unsupported file type '{suffix}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_SUFFIXES))}."
        )
    text = upload_socket.extract_text(path.name, path.read_bytes()).strip()
    if not text:
        raise ValueError(f"No readable text could be extracted from '{path.name}'.")
    return pi.build_tree_from_markdown_text(text, title=path.stem, model=model)


def _tree_output_path(path: Path, file_hash: str) -> Path:
    """
    Where to save the tree for `path`. We include a short hash slice in the name
    so re-indexing a changed file with the same name does not overwrite the old
    tree (different content -> different hash -> different file).
    """
    return config.TREES_DIR / f"{path.stem}.{file_hash[:12]}.json"


# ---------------------------------------------------------------------------
# Step 3: auditability — append-only provenance log
# ---------------------------------------------------------------------------
def _append_audit(entry: dict, log_path: Path = config.AUDIT_LOG_PATH) -> None:
    """
    Append one JSON record to the audit log as a single line (JSON Lines format).

    Append-only + one-line-per-event makes the log easy to tail, hard to silently
    reorder, and trivial to parse later for a "show me everything indexed" view.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# The one public entry point the watcher (and the API) call
# ---------------------------------------------------------------------------
def ingest_file(path: Path, model: Optional[str] = None) -> dict:
    """
    Index a single document end to end and return the audit record.

    Steps: fingerprint the file -> build its PageIndex tree -> save the tree ->
    append a provenance line to the audit log. Returns the audit entry so callers
    (the watcher, a future API route) can print or react to it.
    """
    path = Path(path)
    file_hash = hash_file(path)

    tree = build_tree_for_file(path, model=model)

    tree_path = _tree_output_path(path, file_hash)
    tree_path.write_text(json.dumps(tree, indent=2, ensure_ascii=False), encoding="utf-8")

    # Make the document answerable: fold its tree into the shared RAG store that
    # rag_socket.answer() reads, so ingested files join the same queryable index
    # the dataset fills. Imported lazily to keep this socket import-light.
    from sockets import rag_socket

    doc_type = path.suffix.lower().lstrip(".") or "txt"
    rag_doc_id = rag_socket.upsert_document(
        tree,
        doc_name=path.stem,
        doc_type=doc_type,
        sha256=file_hash,
        source_file=path.name,
        model=model,
    )

    entry = {
        "time": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "source_file": path.name,
        "source_path": str(path.resolve()),
        "sha256": file_hash,
        "size_bytes": path.stat().st_size,
        "tree_path": str(tree_path),
        "rag_doc_id": rag_doc_id,
        "model": model or config.LLM_MODEL,
    }
    _append_audit(entry)
    return entry


def read_audit_log(log_path: Path = config.AUDIT_LOG_PATH) -> list[dict]:
    """
    Return every audit record as a list of dicts (newest last).

    Handy for a "what has been indexed so far?" view — e.g. a future API route or
    a CLI status command. Returns an empty list if nothing has been indexed yet.
    """
    if not Path(log_path).exists():
        return []
    entries = []
    for line in Path(log_path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # skip a corrupt line instead of failing the whole log
    return entries
