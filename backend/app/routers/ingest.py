"""
backend/app/routers/ingest.py — upload a document and index it (the trust layer).

Thin HTTP wrapper around sockets/ingest_socket.py. The browser sends a file, we
save it (for provenance), then the ingest socket fingerprints it, builds a
PageIndex tree, saves the tree, and appends an audit-log line. The heavy lifting
all lives in the socket — this router only handles the HTTP plumbing.

    POST /api/ingest        — multipart upload of one document -> tree + provenance
    GET  /api/ingest/log    — everything indexed so far (the audit trail)
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

from ..errors import client_error
from ..middleware import MAX_UPLOAD_BYTES, MAX_UPLOAD_MB
from ..ragindex import config
from ..ragindex import ingest_socket as ingest

router = APIRouter(prefix="/api/ingest", tags=["ingest"])

# Read uploads in 1 MB blocks so large PDFs never balloon memory.
_CHUNK = 1 << 20


@router.post("")
async def ingest_document(file: UploadFile = File(...)) -> dict:
    """
    Index one uploaded document and return its provenance record.

    The response includes the SHA-256 fingerprint, where the tree was saved, and
    the tree itself — so the caller can both trust and display the result.
    """
    name = Path(file.filename or "").name
    suffix = Path(name).suffix.lower()
    if suffix not in ingest.SUPPORTED_SUFFIXES:
        raise HTTPException(
            status_code=415,
            detail=(
                f"Unsupported file type '{suffix}'. "
                f"Supported: {', '.join(sorted(ingest.SUPPORTED_SUFFIXES))}."
            ),
        )

    # Save the upload (kept under data/uploads/ for provenance — git-ignored).
    # Enforce the cap on the bytes actually read — not just the declared
    # Content-Length — so a chunked/understated upload can't fill RAM or disk.
    dest = config.UPLOADS_DIR / name
    too_large = False
    total = 0
    try:
        with open(dest, "wb") as out:
            while block := await file.read(_CHUNK):
                total += len(block)
                if total > MAX_UPLOAD_BYTES:
                    too_large = True
                    break
                out.write(block)
    finally:
        await file.close()
    if too_large:
        try:
            dest.unlink()
        except OSError:
            pass
        raise HTTPException(
            status_code=413,
            detail=f"Request body too large (max {MAX_UPLOAD_MB} MB).",
        )

    # Hand off to the ingest socket: fingerprint -> build tree -> save -> audit.
    # PageIndex builds the tree with asyncio.run() internally, which cannot run on
    # the server's event loop — so we offload the whole blocking step to a worker
    # thread (where there is no running loop).
    try:
        entry = await run_in_threadpool(ingest.ingest_file, dest)
    except Exception as exc:  # Ollama down, PageIndex not cloned, parse error, ...
        raise client_error(exc, 400, "Ingestion") from None

    tree = {}
    tree_path = Path(entry["tree_path"])
    if tree_path.exists():
        import json

        tree = json.loads(tree_path.read_text(encoding="utf-8"))

    return {"provenance": entry, "tree": tree}


@router.get("/log")
def ingest_log() -> dict:
    """Return the full audit trail of everything indexed so far (newest last)."""
    entries = ingest.read_audit_log()
    return {"count": len(entries), "items": entries}
