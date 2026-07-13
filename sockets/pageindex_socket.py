"""
sockets/pageindex_socket.py — the MODEL socket.

This plugs the PageIndex project (cloned into vendor/PageIndex) into the
workspace. PageIndex is a "vectorless, reasoning-based RAG" engine: instead of
chopping a document into vectors, it asks an LLM to build a hierarchical
"table-of-contents" tree that an agent can later reason over.

This socket hides two awkward details from the rest of the code:
  1. PageIndex is a *vendored repo*, not a pip package, so we add it to sys.path.
  2. Its markdown entry point (`md_to_tree`) is async and wants a file path, so
     we wrap it in a simple, synchronous, text-in/tree-out function.

Everything runs LOCALLY through Ollama (PageIndex talks to it via LiteLLM using
the `ollama_chat/...` provider), so there are NO API keys. Just make sure the
Ollama server is running and the chat model is pulled — scripts/setup.sh does both.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from typing import Optional

import config


def ensure_importable() -> None:
    """
    Make `import pageindex` work by putting vendor/PageIndex on the import path.

    We insert it at the front of sys.path so the vendored copy always wins over
    any unrelated package that might share the name.
    """
    path = str(config.PAGEINDEX_DIR)
    if not config.PAGEINDEX_DIR.exists():
        raise RuntimeError(
            f"PageIndex was not found at {path}. Run scripts/setup.sh first "
            "(it clones the repo and all its branches)."
        )
    if path not in sys.path:
        sys.path.insert(0, path)


def _require_ollama() -> None:
    """
    Fail early (with a friendly message) if the local Ollama server is not
    reachable or the chat model has not been pulled. Everything runs onboard, so
    there is no API key to configure.
    """
    import urllib.request

    try:
        with urllib.request.urlopen(f"{config.OLLAMA_HOST}/api/tags", timeout=3) as resp:
            installed = json.loads(resp.read()).get("models", [])
    except Exception as exc:
        raise RuntimeError(
            f"Cannot reach Ollama at {config.OLLAMA_HOST} ({exc}). "
            "Start it with `ollama serve`, or run scripts/setup.sh."
        ) from None

    names = {m.get("name", "") for m in installed}
    if not any(name == config.OLLAMA_CHAT_TAG or name.startswith(config.OLLAMA_CHAT_TAG)
               for name in names):
        raise RuntimeError(
            f"Ollama chat model '{config.OLLAMA_CHAT_TAG}' is not pulled yet. "
            f"Run:  ollama pull {config.OLLAMA_CHAT_TAG}   (or scripts/setup.sh)."
        )


def build_tree_from_markdown_text(
    text: str,
    title: str = "document",
    model: Optional[str] = None,
    add_summary: bool = True,
) -> dict:
    """
    Turn raw Markdown/plain text into a PageIndex tree.

    Parameters
    ----------
    text : the document body.
    title : used as the top-level heading of the document.
    model : LLM to use (defaults to config.LLM_MODEL).
    add_summary : ask PageIndex to attach a short summary to each tree node.

    Returns the tree as a nested dict (title / node_id / summary / nodes ...).
    """
    ensure_importable()
    _require_ollama()

    # Imported here because it only exists after PageIndex is on sys.path.
    from pageindex.page_index_md import md_to_tree

    # Add content-hash caching + bounded concurrency to the summary fan-out
    # (idempotent; patches the vendored functions in place).
    from sockets import index_speedup
    index_speedup.install()

    # Bound each LLM call so a hung Ollama can't block the build forever.
    import litellm
    litellm.request_timeout = config.LLM_TIMEOUT
    litellm.suppress_debug_info = True

    # `md_to_tree` reads from a file, so write the text to a temporary .md file
    # inside data/ and clean it up afterwards.
    yes_no = "yes" if add_summary else "no"
    with tempfile.NamedTemporaryFile(
        "w", suffix=".md", dir=config.DATA_DIR, delete=False, encoding="utf-8"
    ) as fh:
        fh.write(f"# {title}\n\n{text}\n")
        md_path = fh.name

    try:
        # md_to_tree is async; asyncio.run executes it and returns the result.
        tree = asyncio.run(
            md_to_tree(
                md_path=md_path,
                if_thinning=False,
                if_add_node_summary=yes_no,
                summary_token_threshold=200,
                model=model or config.INDEX_LLM_MODEL,
                if_add_doc_description="yes",
                if_add_node_text="yes",
                if_add_node_id="yes",
            )
        )
    finally:
        os.unlink(md_path)
        index_speedup.flush()  # persist newly cached summaries/descriptions

    # md_to_tree derives `doc_name` from the temporary file's name (e.g.
    # "tmpc3be9q2n"). Replace it with the real title so saved trees carry a
    # meaningful name everywhere they are stored.
    if isinstance(tree, dict) and title:
        tree["doc_name"] = title
    return tree


def build_tree_from_document(doc: dict, model: Optional[str] = None) -> dict:
    """
    Convenience bridge: take a grouped document from the dataset socket and build
    a tree from it. This is the line where the two sockets "click" together.
    """
    return build_tree_from_markdown_text(doc["text"], title=doc["title"], model=model)
