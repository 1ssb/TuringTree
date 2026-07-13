"""
backend/app/routers/branches.py — semantic search over PageIndex git branches.

Thin HTTP wrapper around sockets/branch_index_socket.py. The heavy lifting
(profiling branches, embedding, ranking) all lives in that socket.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..errors import client_error
from ..ragindex import branch_index_socket as bi
from ..ragindex import config

router = APIRouter(prefix="/api/branches", tags=["branches"])


@router.get("")
def list_branches() -> dict:
    """List every origin/* branch of the cloned PageIndex repo."""
    if not config.PAGEINDEX_DIR.exists():
        raise HTTPException(
            status_code=404,
            detail="PageIndex repo not found. Run scripts/setup.sh first.",
        )
    return {"branches": bi.list_origin_branches()}


@router.post("/build")
def build_index(
    llm: bool = Query(
        False,
        description="Use local Ollama embeddings. Default uses the offline "
        "embedder so it works without Ollama running.",
    ),
) -> dict:
    """
    Build (or rebuild) the semantic branch index so /api/branches/search works.

    Profiles every origin branch and embeds it. With `llm=false` (default) it
    uses the dependency-free offline embedder, so it succeeds even when Ollama
    is not running.
    """
    try:
        index = bi.build_branch_index(use_llm=llm)
    except Exception as exc:  # repo missing, git failure, etc.
        raise client_error(exc, 400, "Branch index build") from None

    return {
        "built": True,
        "branch_count": len(index["branches"]),
        "model": index["model"],
    }


@router.get("/search")
def search_branches(
    q: str = Query(..., min_length=1, description="Plain-English query."),
    k: int = Query(5, ge=1, le=25, description="How many results to return."),
) -> dict:
    """Rank branches by relevance to `q` (needs a built index)."""
    try:
        results = bi.search_branches(q, k=k)
    except Exception as exc:  # no index yet, repo missing, etc.
        raise client_error(exc, 400, "Branch search") from None

    return {
        "query": q,
        "results": [
            {
                "score": round(score, 4),
                "branch": branch,
                "hint": profile.splitlines()[0] if profile else "",
            }
            for score, branch, profile in results
        ],
    }
