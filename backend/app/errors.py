"""
backend/app/errors.py — turn an exception into a safe HTTP error.

Routers wrap socket calls in `except Exception`; returning `str(exc)` directly can
leak internals (filesystem paths, git/OS errors, library tracebacks). `client_error`
logs the full exception and surfaces a message that is safe to show the user:
curated socket errors (ValueError / RuntimeError / FileNotFoundError) carry helpful
text, while anything unexpected gets a generic message (the detail stays in logs).
"""

from __future__ import annotations

import logging

from fastapi import HTTPException

_log = logging.getLogger("ragindex.api")

# Exception types whose message is curated by our sockets and safe to surface.
_SAFE_TYPES = (ValueError, RuntimeError, FileNotFoundError)


def client_error(exc: Exception, status_code: int, context: str) -> HTTPException:
    """Log `exc` (with traceback) and return a sanitized HTTPException."""
    _log.warning("%s failed: %s", context, exc, exc_info=True)
    if isinstance(exc, _SAFE_TYPES):
        return HTTPException(status_code=status_code, detail=str(exc))
    return HTTPException(
        status_code=status_code,
        detail=f"{context} failed. Please try again or check the server logs.",
    )
