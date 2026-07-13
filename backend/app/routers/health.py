"""
backend/app/routers/health.py — "is everything wired up?" + readiness probe.

GET /api/health        — liveness + component status (Ollama, dataset, DB, index,
                         PageIndex). Always 200 if the process is up.
GET /api/health/ready  — readiness probe for a load balancer: 200 when the core
                         dependency (Ollama) is reachable, else 503.
"""

from __future__ import annotations

import urllib.request

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..ragindex import config, rag_socket

router = APIRouter(prefix="/api", tags=["health"])


def _ollama_reachable() -> bool:
    try:
        with urllib.request.urlopen(f"{config.OLLAMA_HOST}/api/tags", timeout=3):
            return True
    except Exception:
        return False


@router.get("/health")
def health() -> dict:
    """Liveness + component status (no model calls)."""
    try:
        index = rag_socket.status()
    except Exception:
        index = {"built": False, "doc_count": 0}

    return {
        "status": "ok",
        "ollama": {"host": config.OLLAMA_HOST, "reachable": _ollama_reachable()},
        "models": {
            "chat": config.OLLAMA_CHAT_TAG,
            "embed": config.OLLAMA_EMBED_TAG,
        },
        "dataset": {
            "local_sample_present": config.LOCAL_DATASET_PATH.exists(),
            "sample_rows": config.DATASET_SAMPLE_ROWS,
            "db_present": config.DATASET_DB_PATH.exists(),
        },
        "index": {
            "built": bool(index.get("built")),
            "doc_count": int(index.get("doc_count", 0)),
        },
        "pageindex_cloned": config.PAGEINDEX_DIR.exists(),
    }


@router.get("/health/ready")
def readiness() -> JSONResponse:
    """Readiness: 200 when Ollama (the core dependency) is reachable, else 503."""
    if _ollama_reachable():
        return JSONResponse({"ready": True}, status_code=200)
    return JSONResponse(
        {"ready": False, "reason": "Ollama not reachable"}, status_code=503
    )
