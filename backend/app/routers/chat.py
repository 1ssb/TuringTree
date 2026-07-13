"""
backend/app/routers/chat.py — the vectorless RAG chat endpoint.

Thin HTTP wrapper around sockets/rag_socket.py. The actual reasoning-based
retrieval and answer live in that socket; this router just exposes it:

    GET  /api/index/status   — is the index built? which documents?
    POST /api/index/build    — build (or rebuild) the PageIndex index (slow; needs Ollama)
    POST /api/chat           — ask a question, get a grounded answer + sources

Everything runs locally through Ollama/Qwen — no API keys.
"""

from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from ..errors import client_error
from ..jobs import estimate as job_estimate, get as get_job, run as run_job
from ..middleware import read_upload_within_cap
from ..ragindex import rag_socket, upload_socket

router = APIRouter(prefix="/api", tags=["chat"])


class ChatRequest(BaseModel):
    """A single question for the indexed corpus."""

    message: str = Field(..., min_length=1, description="The user's question.")
    top_k: int = Field(
        3, ge=1, le=6, description="Max number of sections to open while answering."
    )


class ImportRequest(BaseModel):
    """A store imported from a shared bundle."""

    store: dict = Field(..., description="The rag_store contents to restore.")


@router.get("/index/status")
def index_status() -> dict:
    """Report whether the index is built and which documents it covers."""
    return rag_socket.status()


@router.get("/index/tree")
def index_tree() -> dict:
    """Return the indexed corpus as a nested tree for visualization."""
    return rag_socket.tree()


@router.get("/index/export")
def index_export() -> dict:
    """Return the full index so the frontend can package a resumable bundle."""
    store = rag_socket.export_store()
    if not store:
        raise HTTPException(status_code=404, detail="No index has been built yet.")
    return {"store": store, "doc_count": len(store.get("documents", {}))}


@router.post("/index/import")
def index_import(req: ImportRequest) -> dict:
    """Restore an index from an imported bundle so chat/tree resume against it."""
    try:
        return rag_socket.import_store(req.store)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.post("/index/reset")
def index_reset() -> dict:
    """Clear the index so the app starts empty (chat and tree have nothing until rebuilt)."""
    return rag_socket.reset_store()


@router.post("/index/build")
def index_build(
    files: list[UploadFile] = File(
        default=[], description="Folder of documents to index (PDF/MD/TXT/DOCX/HTML)."
    ),
    max_docs: int = Query(
        8, ge=1, le=50, description="Cap on how many documents to index."
    ),
) -> dict:
    """
    Build (or rebuild) the PageIndex index.

    If files are uploaded, index THOSE documents; otherwise fall back to the
    bundled dataset sample. Either way this calls the model to build a tree per
    document, so it needs Ollama running and can take a little while. The result
    is cached to data/rag_store.json.

    Kept synchronous on purpose: PageIndex's tree builder calls asyncio.run()
    internally, which cannot run inside FastAPI's event loop — as a sync handler
    this runs in a worker thread where that is fine.
    """
    try:
        if files:
            payload = []
            read_so_far = 0
            for f in files:
                data = read_upload_within_cap(f, read_so_far)
                read_so_far += len(data)
                payload.append((f.filename or "document", data))
            store = upload_socket.build_index(payload, max_docs=max_docs)
        else:
            store = rag_socket.build_store(max_docs=max_docs)
    except HTTPException:
        raise  # propagate the 413 from the size cap untouched
    except ValueError as exc:  # nothing readable in the upload
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except Exception as exc:  # Ollama down, deps missing, etc.
        raise client_error(exc, 503, "Index build") from None
    return {
        "built": True,
        "doc_count": store["meta"]["doc_count"],
        "documents": [d.get("doc_name") for d in store["documents"].values()],
    }


@router.post("/index/build_async")
def index_build_async(
    files: list[UploadFile] = File(
        default=[], description="Folder of documents to index (PDF/MD/TXT/DOCX/HTML)."
    ),
    max_docs: int = Query(
        8, ge=1, le=50, description="Cap on how many documents to index."
    ),
) -> dict:
    """
    Start an index build in the background and return a job id immediately.

    Same inputs as POST /api/index/build, but non-blocking: the model work runs
    in a worker thread so the request returns at once. Poll
    GET /api/index/jobs/{job_id} for status, progress and the final result.
    """
    # Read the upload bytes NOW — the UploadFile streams close when the request
    # returns, but the build runs later in a background thread. Bytes are read
    # under the size cap so a chunked upload cannot exhaust memory.
    if files:
        payload = []
        read_so_far = 0
        for f in files:
            data = read_upload_within_cap(f, read_so_far)
            read_so_far += len(data)
            payload.append((f.filename or "document", data))
    else:
        payload = None

    def target(on_progress):
        if payload:
            store = upload_socket.build_index(
                payload, max_docs=max_docs, on_progress=on_progress
            )
        else:
            store = rag_socket.build_store(max_docs=max_docs, on_progress=on_progress)
        return {
            "built": True,
            "doc_count": store["meta"]["doc_count"],
            "documents": [d.get("doc_name") for d in store["documents"].values()],
        }

    return {"job_id": run_job(target)}


@router.get("/index/jobs/{job_id}")
def index_job(job_id: str) -> dict:
    """Status, progress and (when finished) the result of a background build."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Unknown job id.")
    elapsed, eta = job_estimate(job)
    return {
        "job_id": job["id"],
        "status": job["status"],
        "progress": job["progress"],
        "elapsed": elapsed,
        "eta": eta,
        "error": job["error"],
        "result": job["result"],
    }


@router.post("/chat")
def chat(req: ChatRequest) -> dict:
    """
    Answer a question over the indexed corpus using vectorless, reasoning-based
    retrieval. Returns {answer, sources, meta}.
    """
    try:
        return rag_socket.answer(req.message, k=req.top_k)
    except RuntimeError as exc:  # index not built yet
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except Exception as exc:  # Ollama unreachable / model error
        raise client_error(exc, 503, "Chat") from None
