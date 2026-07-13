"""
backend/app/main.py — the FastAPI application.

Run it from the repository root (with the project's virtual environment active):

    uvicorn backend.app.main:app --reload --port 8000

Then open http://localhost:8000/docs for interactive API docs.

This API is a thin layer over the existing RagIndex sockets, exposing:
    GET  /api/health             — system status (Ollama, dataset, PageIndex)
    GET  /api/branches           — list PageIndex origin branches
    POST /api/branches/build     — build the semantic branch index
    GET  /api/branches/search    — semantic branch search
    GET  /api/dataset/sample     — sample chunks from the dataset
    GET  /api/index/status       — is the vectorless RAG index built?
    POST /api/index/build        — build the PageIndex index (needs Ollama)
    POST /api/chat               — ask the indexed corpus (vectorless RAG)
    POST /api/ingest             — upload a document, index it, get provenance
    GET  /api/ingest/log         — the audit trail of everything indexed
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .middleware import (
    CsrfOriginMiddleware,
    LimitUploadSizeMiddleware,
    RequestLoggingMiddleware,
)
from .routers import branches, chat, dataset, health, ingest
from .settings import ALLOWED_ORIGINS
from .spa import mount_spa

# Configure logging once for the app. Level via RAGINDEX_LOG_LEVEL (default INFO).
logging.basicConfig(
    level=os.getenv("RAGINDEX_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger("ragindex.api")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """
    Warm the chat model in a background thread at startup so the FIRST request
    doesn't pay the cold-reload cost (local inference is CPU-bound). Best-effort
    and non-blocking: startup returns immediately and it no-ops if Ollama is down.
    Disable with RAGINDEX_WARMUP=0.
    """
    import threading

    from .ragindex import config, rag_socket

    if getattr(config, "WARMUP_ON_START", True):
        threading.Thread(
            target=rag_socket.warmup, name="ragindex-warmup", daemon=True
        ).start()
    yield


app = FastAPI(
    title="RagIndex API",
    description="Local API for the RagIndex workspace — fully on-device, no API keys.",
    version="0.1.0",
    lifespan=_lifespan,
)

# Reject oversized request bodies early — an out-of-memory guard for the
# upload/build/ingest endpoints (configurable via RAGINDEX_MAX_UPLOAD_MB).
app.add_middleware(LimitUploadSizeMiddleware)

# Allow the React dev server (and any configured origins) to call the API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# CSRF guard: refuse cross-origin state-changing requests. CORS alone does not
# preflight "simple" cross-origin POSTs (multipart uploads, the no-body /reset),
# so it cannot stop a malicious page from triggering them — this can.
app.add_middleware(CsrfOriginMiddleware, allowed_origins=ALLOWED_ORIGINS)

# Log every request (method, path, status, duration).
app.add_middleware(RequestLoggingMiddleware)


@app.exception_handler(Exception)
async def _unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    """Last-resort handler: log the full traceback, return a sanitized 500.

    Keeps internal errors (stack traces, paths) out of the HTTP response while
    making sure they are captured in the server logs.
    """
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error."})


app.include_router(health.router)
app.include_router(branches.router)
app.include_router(dataset.router)
app.include_router(chat.router)
app.include_router(ingest.router)


# Serve the built UI as one process when present (the packaged desktop app);
# otherwise expose a small JSON landing (dev, where Vite serves the UI). The SPA
# catch-all is registered LAST so every /api/* route and /docs take precedence.
if not mount_spa(app):

    @app.get("/", tags=["root"])
    def root() -> dict:
        """Tiny landing payload that points to the docs and health check."""
        return {
            "name": "RagIndex API",
            "docs": "/docs",
            "health": "/api/health",
        }
