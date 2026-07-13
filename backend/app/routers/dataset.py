"""
backend/app/routers/dataset.py — peek at the bundled Wikipedia-science sample.

Thin HTTP wrapper around sockets/dataset_socket.py. Reads the local parquet
sample when present (offline), otherwise streams from Hugging Face.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from ..errors import client_error
from ..ragindex import dataset_socket as ds

router = APIRouter(prefix="/api/dataset", tags=["dataset"])


@router.get("/sample")
def sample(
    limit: int = Query(10, ge=1, le=200, description="How many chunks to return."),
    category: str | None = Query(None, description="Optional category filter."),
) -> dict:
    """Return a handful of dataset chunks: {text, title, category, url}."""
    try:
        rows = ds.sample(limit, category=category)
    except Exception as exc:  # missing deps / dataset unavailable
        raise client_error(exc, 400, "Dataset sample") from None

    return {"count": len(rows), "items": rows}
