"""
backend/app/middleware.py — small ASGI middlewares for the API.

LimitUploadSizeMiddleware guards the upload/build/ingest endpoints from an
out-of-memory request: the build endpoints read uploaded files fully into memory,
so an unbounded body could OOM a worker. We reject anything whose declared size
(the Content-Length header, which browsers and multipart clients always send)
exceeds a configurable cap — cheaply, before the body is read.
"""

from __future__ import annotations

import logging
import os
import time

from fastapi import HTTPException, UploadFile
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

_access_log = logging.getLogger("ragindex.access")

# Methods that cannot change server state — exempt from the CSRF origin check.
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

# Max accepted request-body size. Override with RAGINDEX_MAX_UPLOAD_MB.
MAX_UPLOAD_MB = max(1, int(os.getenv("RAGINDEX_MAX_UPLOAD_MB", "200")))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024


def read_upload_within_cap(
    upload: UploadFile, prior_total: int = 0, chunk: int = 1 << 20
) -> bytes:
    """
    Read an UploadFile fully into memory under the global size cap.

    Unlike the Content-Length pre-check (which a chunked or lying client can
    omit/understate), this counts the bytes actually read and aborts with 413 the
    moment the request crosses MAX_UPLOAD_BYTES — so the build/ingest endpoints
    can never be driven out of memory. ``prior_total`` carries the bytes already
    read for earlier files in the same multipart request, so the cap bounds the
    whole request, not each file in isolation.
    """
    buf = bytearray()
    source = upload.file
    source.seek(0)
    while True:
        block = source.read(chunk)
        if not block:
            return bytes(buf)
        buf.extend(block)
        if prior_total + len(buf) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Request body too large (max {MAX_UPLOAD_MB} MB).",
            )


class LimitUploadSizeMiddleware(BaseHTTPMiddleware):
    """Reject requests whose declared body exceeds MAX_UPLOAD_BYTES with 413."""

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > MAX_UPLOAD_BYTES:
                    return JSONResponse(
                        status_code=413,
                        content={
                            "detail": f"Request body too large (max {MAX_UPLOAD_MB} MB)."
                        },
                    )
            except ValueError:
                pass  # malformed header — let the server handle it normally
        return await call_next(request)


class CsrfOriginMiddleware(BaseHTTPMiddleware):
    """
    Refuse cross-origin state-changing requests — a CSRF guard for the local API.

    The API is unauthenticated and bound to localhost, but a malicious page open
    in the user's browser can still issue *simple* cross-origin requests that CORS
    does not preflight: a multipart upload to /api/index/build or /api/ingest, or
    a no-body POST to /api/index/reset. CORS only blocks the attacker from READING
    the response — the state change still happens. So for any unsafe method we
    require the Origin header (when the browser sends one) to be same-origin or an
    explicitly allowed frontend origin; otherwise we reject with 403.

    Requests with no Origin header (curl, the test suite, the packaged app's own
    in-process calls) and safe methods (GET/HEAD/OPTIONS) are always allowed —
    CSRF is specifically a browser-driven, cross-origin attack.
    """

    def __init__(self, app, allowed_origins) -> None:
        super().__init__(app)
        self._allowed = frozenset(allowed_origins)

    async def dispatch(self, request: Request, call_next):
        if request.method not in _SAFE_METHODS:
            origin = request.headers.get("origin")
            if origin:
                same_origin = (
                    f"{request.url.scheme}://{request.headers.get('host', '')}"
                )
                if origin != same_origin and origin not in self._allowed:
                    _access_log.warning(
                        "Refused cross-origin %s %s from origin %s",
                        request.method,
                        request.url.path,
                        origin,
                    )
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "Cross-origin request refused."},
                    )
        return await call_next(request)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log each request: method, path, response status, and duration."""

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000
        _access_log.info(
            "%s %s -> %s (%.0f ms)",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response
