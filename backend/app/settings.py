"""
backend/app/settings.py — small settings for the API itself.

Kept separate from the root `config.py` (which configures the RagIndex sockets)
to avoid any name clash. Override values with environment variables if needed.
"""

from __future__ import annotations

import os

# Which web origins may call this API from the browser (the Vite dev server by
# default). Provide a comma-separated list via RAGINDEX_FRONTEND_ORIGINS to add
# more (e.g. a deployed frontend URL).
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "RAGINDEX_FRONTEND_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if origin.strip()
]
