"""
backend/app/spa.py — serve the built React UI from the API (single-process app).

When the frontend has been built (frontend/dist exists, RAGINDEX_FRONTEND_DIST
points at a dist folder, or the files are bundled by PyInstaller), mount it so the
whole product is ONE server: the JSON API at /api/* and the UI everywhere else.
Client-side routes (/chat, /upload, ...) fall back to index.html.

In development (no dist) this is a no-op — the Vite dev server serves the UI and
proxies /api here. So the same backend works for both `npm run dev` and the
packaged desktop app.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, Response

from .ragindex import ROOT


def _dist_dir() -> Path | None:
    """Locate a built frontend (index.html present), or None in dev."""
    candidates: list[Path] = []
    override = os.getenv("RAGINDEX_FRONTEND_DIST")
    if override:
        candidates.append(Path(override))
    # PyInstaller unpacks bundled data under sys._MEIPASS.
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "frontend" / "dist")
    candidates.append(ROOT / "frontend" / "dist")
    for candidate in candidates:
        if candidate and (candidate / "index.html").is_file():
            return candidate
    return None


def mount_spa(app: FastAPI) -> bool:
    """Serve the built SPA if present. Returns True if it was mounted."""
    dist = _dist_dir()
    if dist is None:
        return False

    dist = dist.resolve()
    index_html = dist / "index.html"

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> Response:
        # Serve a real built file when it exists (assets/*.js, favicon.svg, ...),
        # otherwise return index.html so client-side routing works.
        if full_path:
            candidate = (dist / full_path).resolve()
            try:
                candidate.relative_to(dist)  # block path traversal (../)
            except ValueError:
                return FileResponse(index_html)
            if candidate.is_file():
                return FileResponse(candidate)
        return FileResponse(index_html)

    return True
