"""
sockets/index_speedup.py — make PageIndex tree-building fast and rebuilds cheap.

Building a PageIndex tree is ~100% local LLM inference (see scripts/profile_index.py):
a fan-out of per-heading ``generate_node_summary`` calls plus one synchronous
``generate_doc_description`` call. This module speeds that up WITHOUT editing the
vendored PageIndex code (``vendor/`` is git-ignored and re-cloned by setup) by
monkeypatching those two entry points at runtime to add three things:

  1. Content-hash caching — every summary/description is keyed by
     ``sha256(model + text)``. A rebuild of unchanged content is then almost free:
     each call is a cache hit, so only genuinely new or edited sections reach the
     model. (Highest-ROI optimization for repeated builds.)
  2. Bounded concurrency — upstream summarises with an *unbounded*
     ``asyncio.gather``, which makes a single Ollama instance thrash (tail latency
     and VRAM blow up past ~4 in-flight requests). We cap concurrent summary calls
     with a per-event-loop semaphore (``config.INDEX_SUMMARY_CONCURRENCY``, def 4).
  3. In-flight de-duplication — identical sections within one document collapse to
     a single model call instead of N.

Apply it once via :func:`install` (idempotent); call :func:`flush` after a build
to persist the cache to ``config.SUMMARY_CACHE_PATH`` (under the git-ignored data/).

The patch targets the ``pageindex.page_index_md`` module namespace, which is where
``md_to_tree`` / ``get_node_summary`` resolve these names (``from .utils import *``).
"""

from __future__ import annotations

import asyncio
import contextvars
import hashlib
import json
import threading
import weakref
from typing import Optional

import config

# ── patch state ───────────────────────────────────────────────────────────────
_INSTALLED = False
_ORIG_NODE_SUMMARY = None  # original async generate_node_summary(node, model=None)
_ORIG_DOC_DESC = None      # original sync  generate_doc_description(structure, model=None)
_ORIG_LITELLM_ACOMPLETION = None  # original litellm.acompletion
_ORIG_LITELLM_COMPLETION = None   # original litellm.completion

# Holds a max-tokens cap ONLY while a node summary / doc description is being
# generated, so the litellm wrappers cap just those calls — never the structure /
# JSON-parsing calls used elsewhere (e.g. the PDF path), which must not truncate.
_cap_var: "contextvars.ContextVar[Optional[int]]" = contextvars.ContextVar(
    "ragindex_index_cap", default=None
)

# One semaphore per event loop, so each asyncio.run() (one per document) gets a
# fresh semaphore bound to its own loop. WeakKeyDictionary lets dead loops GC.
_SEMAPHORES: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()

# ── cache (in-memory, persisted lazily to JSON) ──────────────────────────────
_CACHE: Optional[dict] = None
_CACHE_DIRTY = False
_CACHE_LOCK = threading.Lock()


def _load_cache() -> dict:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    try:
        path = config.SUMMARY_CACHE_PATH
        _CACHE = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        _CACHE = {}
    if not isinstance(_CACHE, dict):
        _CACHE = {}
    return _CACHE


def _enabled() -> bool:
    return bool(getattr(config, "INDEX_SUMMARY_CACHE", True))


def _summary_cap() -> Optional[int]:
    """Output-token cap for summary/description generation (None = uncapped)."""
    try:
        return int(getattr(config, "INDEX_SUMMARY_MAX_TOKENS", 256) or 0) or None
    except (TypeError, ValueError):
        return None


def _key(kind: str, text: str, model: Optional[str]) -> str:
    h = hashlib.sha256()
    h.update((model or "").encode("utf-8"))
    h.update(b"\x00")
    h.update(kind.encode("utf-8"))
    h.update(b"\x00")
    h.update((text or "").encode("utf-8"))
    return h.hexdigest()


def _cache_get(key: str):
    if not _enabled():
        return None
    return _load_cache().get(key)


def _cache_set(key: str, value) -> None:
    global _CACHE_DIRTY
    if not _enabled() or value is None:
        return
    _load_cache()[key] = value
    _CACHE_DIRTY = True


def flush() -> None:
    """Persist the cache to disk if it changed. Best-effort; never raises."""
    global _CACHE_DIRTY
    with _CACHE_LOCK:
        if not _CACHE_DIRTY or _CACHE is None:
            return
        try:
            config.SUMMARY_CACHE_PATH.write_text(
                json.dumps(_CACHE, ensure_ascii=False), encoding="utf-8"
            )
            _CACHE_DIRTY = False
        except Exception:
            pass  # caching is an optimization; never fail a build over it


def _loop_semaphore() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    sem = _SEMAPHORES.get(loop)
    if sem is None:
        n = max(1, int(getattr(config, "INDEX_SUMMARY_CONCURRENCY", 4) or 1))
        sem = asyncio.Semaphore(n)
        _SEMAPHORES[loop] = sem
    return sem


def _stable_json(obj) -> str:
    try:
        return json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)
    except Exception:
        return str(obj)


# ── patched entry points ─────────────────────────────────────────────────────
async def _node_summary(node, model=None):
    """Cached + concurrency-bounded replacement for generate_node_summary."""
    text = (node or {}).get("text") or ""
    key = _key("node", text, model)
    hit = _cache_get(key)
    if hit is not None:
        return hit
    async with _loop_semaphore():
        # Re-check inside the gate: a concurrent task with identical text may have
        # just produced it (in-flight de-duplication -> one model call, not N).
        hit = _cache_get(key)
        if hit is not None:
            return hit
        token = _cap_var.set(_summary_cap())
        try:
            result = await _ORIG_NODE_SUMMARY(node, model=model)
        finally:
            _cap_var.reset(token)
    _cache_set(key, result)
    return result


def _doc_description(structure, model=None):
    """Cached replacement for generate_doc_description (synchronous upstream)."""
    key = _key("doc", _stable_json(structure), model)
    hit = _cache_get(key)
    if hit is not None:
        return hit
    token = _cap_var.set(_summary_cap())
    try:
        result = _ORIG_DOC_DESC(structure, model=model)
    finally:
        _cap_var.reset(token)
    _cache_set(key, result)
    return result


def _apply_cap(kwargs: dict) -> dict:
    """Inject the output-token cap (+ keep-alive) when a summary call is active."""
    cap = _cap_var.get()
    if cap:
        kwargs.setdefault("max_tokens", cap)
        keep_alive = getattr(config, "LLM_KEEP_ALIVE", "")
        if keep_alive:
            kwargs.setdefault("keep_alive", keep_alive)
        kwargs.setdefault("timeout", getattr(config, "LLM_TIMEOUT", 180))
    return kwargs


def _capped_acompletion(*args, **kwargs):
    # Returns the coroutine from the original; the caller awaits it.
    return _ORIG_LITELLM_ACOMPLETION(*args, **_apply_cap(kwargs))


def _capped_completion(*args, **kwargs):
    return _ORIG_LITELLM_COMPLETION(*args, **_apply_cap(kwargs))


def install() -> None:
    """
    Monkeypatch PageIndex's summary functions (idempotent). Requires that
    pageindex is already importable (call pageindex_socket.ensure_importable()).
    """
    global _INSTALLED, _ORIG_NODE_SUMMARY, _ORIG_DOC_DESC
    global _ORIG_LITELLM_ACOMPLETION, _ORIG_LITELLM_COMPLETION
    if _INSTALLED:
        return
    from pageindex import page_index_md as M

    _ORIG_NODE_SUMMARY = M.generate_node_summary
    _ORIG_DOC_DESC = M.generate_doc_description
    M.generate_node_summary = _node_summary
    M.generate_doc_description = _doc_description

    # Cap ONLY summary/description generations (scoped via _cap_var) so they can't
    # ramble into long, slow generations on CPU; all other calls stay uncapped.
    import litellm
    litellm.drop_params = True
    litellm.suppress_debug_info = True
    if _ORIG_LITELLM_ACOMPLETION is None:
        _ORIG_LITELLM_ACOMPLETION = litellm.acompletion
        litellm.acompletion = _capped_acompletion
    if _ORIG_LITELLM_COMPLETION is None:
        _ORIG_LITELLM_COMPLETION = litellm.completion
        litellm.completion = _capped_completion

    _INSTALLED = True


def stats() -> dict:
    """Small introspection helper (used by tests/validation)."""
    return {
        "installed": _INSTALLED,
        "cache_enabled": _enabled(),
        "cache_entries": len(_CACHE) if _CACHE is not None else 0,
        "concurrency": int(getattr(config, "INDEX_SUMMARY_CONCURRENCY", 4)),
        "cache_path": str(config.SUMMARY_CACHE_PATH),
    }
