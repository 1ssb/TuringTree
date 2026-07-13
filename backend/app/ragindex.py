"""
backend/app/ragindex.py — bridge to the root RagIndex sockets.

The API does not re-implement any logic: it reuses the exact same sockets the
CLI scripts use. Those sockets live at the repository root, so we add the root
to sys.path once here and re-export the modules the routers need.
"""

from __future__ import annotations

import sys
from pathlib import Path

# backend/app/ragindex.py -> parents[0]=app, [1]=backend, [2]=repo root
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config  # noqa: E402  (import after sys.path tweak, on purpose)
from sockets import (  # noqa: E402
    branch_index_socket,
    dataset_socket,
    ingest_socket,
    pageindex_socket,
    rag_socket,
    upload_socket,
)

__all__ = [
    "config",
    "branch_index_socket",
    "dataset_socket",
    "ingest_socket",
    "pageindex_socket",
    "rag_socket",
    "upload_socket",
    "ROOT",
]
