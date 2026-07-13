"""
sockets/rag_socket.py — the vectorless RAG engine.

This is the socket that actually *answers questions* over the corpus, the way
PageIndex intends: **no vectors, no embeddings, no chunking-by-distance**.

How it works (reasoning-based retrieval):

  1. BUILD  — turn a handful of dataset articles into PageIndex "trees" (each a
              table-of-contents of nodes with titles + summaries + text). Cached
              to data/rag_store.json so it is built only once.
  2. SELECT — give the LLM the *outline* of every document (titles + summaries,
              no full text) and let it reason about which sections could answer
              the question. It returns the node line numbers to open.
  3. FETCH  — open exactly those nodes with PageIndex's own retrieval tool
              (retrieve.get_page_content) to pull their text.
  4. ANSWER — give the LLM the question + only those sections and ask for a
              grounded answer that cites the documents it used.

Everything runs LOCALLY through Ollama/Qwen via LiteLLM (config.LLM_MODEL), so
there are no API keys. If the LLM step is unavailable or returns junk, SELECT
falls back to a dependency-free keyword overlap so the system degrades to a
sensible answer instead of crashing.
"""

from __future__ import annotations

import json
import os
import re
import time
from contextlib import contextmanager
from typing import Callable, Optional

import config
from sockets import dataset_socket, pageindex_socket

# Where the built index is cached (data/ is git-ignored and rebuilt locally).
STORE_PATH = config.DATA_DIR / "rag_store.json"

# How many articles to index, and the scan/size limits used while assembling
# them. All overridable via env so a beefier machine can index more.
RAG_DOCS = int(os.getenv("RAGINDEX_RAG_DOCS", "4"))
SCAN_CHUNKS = int(os.getenv("RAGINDEX_RAG_SCAN_CHUNKS", "800"))
MIN_DOC_CHARS = int(os.getenv("RAGINDEX_RAG_MIN_DOC_CHARS", "800"))

# Retrieval budgets.
SELECT_K = 3                 # max sections to open per question
PER_NODE_CHARS = 3000        # cap on each opened section
TOTAL_CONTEXT_CHARS = 8000   # cap on the whole grounding context

# In-process cache of the parsed store, invalidated by file mtime so repeated
# status()/tree()/chat calls don't re-read and re-parse rag_store.json each time.
_STORE_CACHE: Optional[dict] = None
_STORE_CACHE_MTIME: Optional[float] = None


def _cache_store(store: Optional[dict]) -> None:
    """Remember a freshly written/loaded store keyed on the file's current mtime."""
    global _STORE_CACHE, _STORE_CACHE_MTIME
    _STORE_CACHE = store
    try:
        _STORE_CACHE_MTIME = STORE_PATH.stat().st_mtime if STORE_PATH.exists() else None
    except OSError:
        _STORE_CACHE_MTIME = None


# ── LLM helper ────────────────────────────────────────────────────────────────

def _llm(messages: list[dict], temperature: float = 0.0, max_tokens: int = 1024) -> str:
    """Call the local chat model through LiteLLM and return its text."""
    import litellm

    litellm.drop_params = True  # ignore params Ollama doesn't support
    litellm.suppress_debug_info = True  # no "give feedback / provider list" banners
    # keep_alive keeps the model resident between calls so a brief pause doesn't
    # trigger a multi-second cold reload (local inference is CPU-bound).
    extra = {"keep_alive": config.LLM_KEEP_ALIVE} if config.LLM_KEEP_ALIVE else {}
    resp = litellm.completion(
        model=config.LLM_MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=config.LLM_TIMEOUT,
        **extra,
    )
    return (resp["choices"][0]["message"]["content"] or "").strip()


def warmup() -> None:
    """
    Load the chat model into memory (a 1-token generation) so the FIRST real
    request doesn't pay the cold-reload cost. Best-effort and non-fatal: used at
    server startup and safe to call when Ollama is down (it no-ops on error).
    """
    try:
        _llm([{"role": "user", "content": "ok"}], max_tokens=1)
    except Exception:
        pass


# ── 1. Build / load the index ────────────────────────────────────────────────

def build_store_from_documents(
    docs,
    max_docs: Optional[int] = None,
    min_chars: int = MIN_DOC_CHARS,
    model: Optional[str] = None,
    on_progress: Optional[Callable[[int, int], None]] = None,
    total: Optional[int] = None,
) -> dict:
    """
    Turn an iterable of ``{title, text, url}`` documents into PageIndex trees and
    add them to the shared store at ``data/rag_store.json``.

    This is the shared core behind dataset indexing (build_store) AND
    user-uploaded-folder indexing (sockets/upload_socket.py). It MERGES into any
    existing store via upsert_document rather than replacing it, so documents
    added through ingestion (sockets/ingest_socket.py) survive a rebuild, and
    dataset/upload docs are de-duplicated by their ``url``. Requires Ollama —
    tree building + node summaries run on the local model.
    """
    n = 0
    model = model or config.INDEX_LLM_MODEL
    total = total if total is not None else (max_docs or 0)
    # Emit an initial 0/total so a watching job knows the size up front and can
    # show a real progress bar / ETA from the first poll (not just a spinner).
    if on_progress is not None:
        try:
            on_progress(0, total)
        except Exception:
            pass
    for doc in docs:
        if max_docs is not None and n >= max_docs:
            break
        if len((doc.get("text") or "")) < min_chars:
            continue  # skip stubs — too small to be worth indexing
        tree = pageindex_socket.build_tree_from_markdown_text(
            doc["text"], title=doc.get("title") or f"doc_{n + 1:03d}", model=model
        )
        # upsert_document normalizes the tree, assigns/reuses a doc_id, and
        # persists under a lock — de-duplicating dataset/upload docs by url.
        upsert_document(
            tree,
            doc_name=doc.get("title") or "",
            url=doc.get("url"),
            doc_type="md",
            model=model,
        )
        n += 1
        if on_progress is not None:
            try:
                on_progress(n, max(total, n))
            except Exception:
                pass

    # Each document was upserted under a lock in the loop above; return the
    # freshly-merged store (load_store is mtime-memoized, so this is cheap).
    return load_store() or {"documents": {}, "meta": {"doc_count": 0}}


def _next_doc_id(documents: dict) -> str:
    """Pick the next free doc_NNN id, continuing build_store()'s numbering."""
    highest = 0
    for did in documents:
        m = re.match(r"doc_(\d+)$", did)
        if m:
            highest = max(highest, int(m.group(1)))
    return f"doc_{highest + 1:03d}"


@contextmanager
def _store_lock(timeout: float = 10.0, poll: float = 0.05):
    """
    A simple cross-process lock around the store's read-modify-write.

    Both the API (/api/ingest) and the folder watcher can ingest at the same
    time; without a lock their load -> modify -> save sequences could interleave
    and silently drop a document. We hold an exclusive lock file next to the
    store. If a stale lock outlives `timeout` (e.g. a writer crashed), we reclaim
    it so the system never deadlocks.
    """
    lock_path = STORE_PATH.parent / (STORE_PATH.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    hard_deadline = start + max(timeout * 3.0, timeout + 5.0)
    fd = None
    while fd is None:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except (FileExistsError, PermissionError):
            # FileExistsError  => the lock is held by another writer.
            # PermissionError  => on Windows the lock file is in a transient
            # "delete-pending" state from another writer's release (or OneDrive/AV
            # briefly holding it). Both mean "retry shortly", not "fail".
            now = time.monotonic()
            if now > hard_deadline:
                raise TimeoutError(f"could not acquire store lock at {lock_path}")
            if now - start > timeout:
                try:
                    os.unlink(lock_path)  # reclaim a stale lock from a crashed writer
                except OSError:
                    pass
                start = time.monotonic()
            else:
                time.sleep(poll)
    try:
        yield
    finally:
        os.close(fd)
        try:
            os.unlink(lock_path)
        except OSError:
            pass


def _write_store(store: dict) -> None:
    """Atomically persist the store (write a temp file, then replace)."""
    tmp_path = STORE_PATH.parent / (STORE_PATH.name + ".tmp")
    tmp_path.write_text(json.dumps(store, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp_path, STORE_PATH)


def upsert_document(
    tree: dict,
    doc_name: str,
    url: Optional[str] = None,
    doc_type: str = "md",
    sha256: Optional[str] = None,
    source_file: Optional[str] = None,
    model: Optional[str] = None,
) -> str:
    """
    Add (or replace) one PageIndex tree in the shared RAG store and return its
    doc_id.

    This is the bridge that lets *ingested* documents (sockets/ingest_socket.py)
    join the very same store that build_store() fills from the dataset — so there
    is ONE queryable index that answer() reads, no matter how a document arrived.

    The tree is normalized to the exact shape the retrieval/answer steps expect
    (see build_store): a `type`, a `doc_name`, and a `url`. Re-ingesting the same
    bytes (matched by `sha256`) updates the existing record in place instead of
    appending a duplicate.

    The whole read-modify-write runs under a cross-process lock so concurrent
    ingestion (API + watcher) can never lose a document.
    """
    with _store_lock():
        store = load_store() or {"documents": {}, "meta": {}}
        documents = store.setdefault("documents", {})

        record = dict(tree)
        record["type"] = record.get("type") or doc_type
        record["doc_name"] = doc_name or record.get("doc_name") or "document"
        record["url"] = url
        if sha256 or source_file:
            record["provenance"] = {"sha256": sha256, "source_file": source_file}

        # De-duplicate: prefer the content fingerprint (ingested files), then
        # fall back to the url (dataset articles). Local uploads have url=None,
        # so they never collide with each other on the url path.
        doc_id = None
        if sha256:
            for did, info in documents.items():
                if (info.get("provenance") or {}).get("sha256") == sha256:
                    doc_id = did
                    break
        if doc_id is None and url:
            for did, info in documents.items():
                if info.get("url") == url:
                    doc_id = did
                    break
        if doc_id is None:
            doc_id = _next_doc_id(documents)

        documents[doc_id] = record
        store["meta"] = {
            "doc_count": len(documents),
            "model": model or config.LLM_MODEL,
        }
        _write_store(store)
    return doc_id


def build_store(
    max_docs: int = RAG_DOCS,
    model: Optional[str] = None,
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> dict:
    """
    Build PageIndex trees over the first `max_docs` sizeable dataset articles and
    cache them. Requires Ollama (tree building + summaries run on the model).
    Returns the store dict: {"documents": {doc_id: doc_info}, "meta": {...}}.
    """
    docs = dataset_socket.to_documents(dataset_socket.iter_chunks(limit=SCAN_CHUNKS))
    return build_store_from_documents(
        docs, max_docs=max_docs, model=model, on_progress=on_progress, total=max_docs
    )


def load_store() -> Optional[dict]:
    """
    Return the cached store if it exists, else None.

    Memoized in-process: the parsed JSON is reused until rag_store.json changes on
    disk (detected via mtime), so frequent status()/tree()/chat calls don't
    re-read and re-parse the file every time. Callers treat the result as
    read-only, so sharing the cached object is safe.
    """
    global _STORE_CACHE, _STORE_CACHE_MTIME
    if not STORE_PATH.exists():
        _STORE_CACHE = None
        _STORE_CACHE_MTIME = None
        return None
    try:
        mtime: Optional[float] = STORE_PATH.stat().st_mtime
    except OSError:
        mtime = None
    if _STORE_CACHE is not None and mtime is not None and mtime == _STORE_CACHE_MTIME:
        return _STORE_CACHE
    try:
        data = json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None
    _STORE_CACHE = data
    _STORE_CACHE_MTIME = mtime
    return data


def status() -> dict:
    """Lightweight index status for the API (no model calls)."""
    store = load_store()
    docs = (store or {}).get("documents", {})
    return {
        "built": bool(docs),
        "doc_count": len(docs),
        "documents": [
            {
                "doc_id": did,
                "doc_name": d.get("doc_name", did),
                "url": d.get("url"),
                # Present for ingested documents (sockets/ingest_socket.py): ties
                # a queryable doc back to the exact source file + fingerprint.
                "provenance": d.get("provenance"),
            }
            for did, d in docs.items()
        ],
        "store_path": str(STORE_PATH),
    }


def _node_to_viz(node: dict) -> dict:
    """Map one PageIndex structure node to a compact viz node (title + summary)."""
    children = [_node_to_viz(c) for c in (node.get("nodes") or [])]
    summary = (node.get("summary") or node.get("prefix_summary") or "").strip()
    return {
        "name": node.get("title") or node.get("node_id") or "section",
        "kind": "node",
        "summary": summary[:280],
        "children": children,
    }


def tree() -> dict:
    """
    Return the indexed corpus as a nested tree for visualization (no model calls):
    root -> documents -> sections..., each node is {name, kind, summary, children}.
    """
    store = load_store() or {}
    docs = store.get("documents", {})
    doc_nodes = []
    for doc_id, info in docs.items():
        name = info.get("doc_name", doc_id)
        children = []
        for n in info.get("structure", []) or []:
            # Skip the injected title-only node (title == doc name, no children).
            if n.get("title") == name and not n.get("nodes"):
                continue
            children.append(_node_to_viz(n))
        doc_nodes.append(
            {
                "name": name,
                "kind": "doc",
                "summary": (info.get("doc_description") or "").strip()[:280],
                "url": info.get("url"),
                "children": children,
            }
        )
    return {
        "name": "Your index",
        "kind": "root",
        "doc_count": len(docs),
        "children": doc_nodes,
    }


def export_store() -> Optional[dict]:
    """Return the full cached store, for packaging a resumable bundle."""
    return load_store()


def import_store(store: dict) -> dict:
    """
    Replace the cached index with an imported store (from a shared bundle) so the
    chat and tree resume against it. Validates the basic shape before writing.
    """
    if not isinstance(store, dict) or not isinstance(store.get("documents"), dict):
        raise ValueError("Invalid bundle: it has no 'documents' map.")
    STORE_PATH.write_text(json.dumps(store, ensure_ascii=False), encoding="utf-8")
    _cache_store(store)
    return {"doc_count": len(store["documents"])}


def reset_store() -> dict:
    """
    Clear the index: delete the cached store so chat and tree start empty again.

    Backs the "Reset index" control in the UI (POST /api/index/reset). Best-effort
    and safe to call when nothing is built yet. The whole removal runs under the
    cross-process store lock, and the in-process cache is invalidated so status()
    reflects the empty index immediately. The summary cache is intentionally left
    in place so re-indexing the same documents stays fast.
    """
    with _store_lock():
        try:
            if STORE_PATH.exists():
                STORE_PATH.unlink()
        except OSError:
            pass
        _cache_store(None)
    return {"built": False, "doc_count": 0}


# ── 2. Select relevant sections (the vectorless retrieval) ────────────────────

def _catalog(store: dict) -> str:
    """A compact, text-free outline of every document for the LLM to reason over."""
    pageindex_socket.ensure_importable()
    from pageindex.retrieve import get_document_structure

    documents = store["documents"]
    parts = []
    for doc_id, info in documents.items():
        outline = get_document_structure(documents, doc_id)  # JSON, text removed
        parts.append(
            f"[{doc_id}] {info.get('doc_name', doc_id)}\n"
            f"description: {info.get('doc_description', '').strip()}\n"
            f"outline (each node has a line_num you can open): {outline}"
        )
    return "\n\n".join(parts)


# Very common words carry no topical signal, so they're ignored when ranking
# documents by keyword overlap — otherwise "what/and/the/document" would tie
# unrelated documents and defeat the "open only the clear match" rule below.
_STOPWORDS = frozenset(
    "the a an and or but of to in on at for from with by about into over under is "
    "are was were be been being do does did doing have has had what which who whom "
    "whose when where why how this that these those it its their our your my can "
    "could will would should may might must not no yes you we they so as if then "
    "than too very just also more most some any tell give show explain describe "
    "summarize summary overview recap document documents doc docs file files".split()
)


def _keyword_fallback(query: str, store: dict, k: int = SELECT_K) -> list[dict]:
    """Deterministic backup selection: rank docs by word overlap, open all nodes."""
    pageindex_socket.ensure_importable()
    from pageindex.utils import structure_to_list

    q_words = {
        w
        for w in re.findall(r"[a-z0-9]+", query.lower())
        if len(w) > 2 and w not in _STOPWORDS
    }
    scored = []
    for doc_id, info in store["documents"].items():
        hay = f"{info.get('doc_name','')} {info.get('doc_description','')}".lower()
        score = sum(1 for w in q_words if w in hay)
        scored.append((score, doc_id, info))
    scored.sort(key=lambda t: t[0], reverse=True)

    # When the query clearly matches some documents (keyword overlap), open ONLY
    # the best-matching one(s): pulling in unrelated documents would dilute the
    # answer and depress its confidence. With no overlap at all (a vague query),
    # fall back to the top-k documents as a best effort.
    best = scored[0][0] if scored else 0
    chosen = [t for t in scored if t[0] == best] if best > 0 else scored[:k]

    picks = []
    for _, doc_id, info in chosen[:k]:
        lines = [
            str(node["line_num"])
            for node in structure_to_list(info.get("structure", []))
            if node.get("line_num")
        ]
        if lines:
            picks.append({"doc_id": doc_id, "pages": ",".join(lines[:5])})
    return picks


def select_sections(query: str, store: dict, k: int = SELECT_K) -> list[dict]:
    """Ask the model which sections to open; fall back to keyword overlap."""
    # On a small corpus, skip the model entirely and open the obvious document(s):
    # an LLM "which document?" call is pure latency when there are only a handful
    # to choose from. The deterministic keyword fallback is instant.
    if len(store.get("documents", {})) < config.SELECT_LLM_MIN_DOCS:
        return _keyword_fallback(query, store, k)
    catalog = _catalog(store)
    prompt = (
        "You are the retrieval step of a vectorless RAG system. Reason over the "
        "document outlines below and choose the sections most likely to answer "
        "the question.\n\n"
        f"QUESTION: {query}\n\n"
        f"DOCUMENTS:\n{catalog}\n\n"
        f"Return ONLY a JSON array (no prose) of at most {k} items, each like "
        '{"doc_id": "doc_001", "pages": "12,40"} where `pages` lists the '
        "line_num values of the section headers to open. Choose the fewest "
        "sections that cover the answer."
    )
    try:
        raw = _llm([{"role": "user", "content": prompt}], max_tokens=config.SELECT_MAX_TOKENS)
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        picks = json.loads(match.group(0)) if match else []
        cleaned = [
            {"doc_id": p["doc_id"], "pages": str(p.get("pages", "")).strip()}
            for p in picks
            if isinstance(p, dict)
            and p.get("doc_id") in store["documents"]
            and str(p.get("pages", "")).strip()
        ]
        if cleaned:
            return cleaned[:k]
    except Exception:
        pass
    return _keyword_fallback(query, store, k)


# ── 3. Fetch the chosen sections ─────────────────────────────────────────────

def gather_context(store: dict, picks: list[dict]) -> list[dict]:
    """Open the selected sections with PageIndex's retrieval tool."""
    pageindex_socket.ensure_importable()
    from pageindex.retrieve import get_page_content

    documents = store["documents"]
    gathered: list[dict] = []
    total = 0
    for pick in picks:
        doc_id, pages = pick["doc_id"], pick["pages"]
        info = documents.get(doc_id, {})
        try:
            content = json.loads(get_page_content(documents, doc_id, pages))
        except Exception:
            continue
        if isinstance(content, dict) and content.get("error"):
            continue
        text = "\n".join(p.get("content", "") for p in content).strip()
        if not text:
            continue
        text = text[:PER_NODE_CHARS]
        if total + len(text) > TOTAL_CONTEXT_CHARS:
            text = text[: max(0, TOTAL_CONTEXT_CHARS - total)]
        total += len(text)
        gathered.append(
            {
                "doc_id": doc_id,
                "doc_name": info.get("doc_name", doc_id),
                "url": info.get("url"),
                "pages": pages,
                "text": text,
            }
        )
        if total >= TOTAL_CONTEXT_CHARS:
            break
    return gathered


# ── 4. Answer ────────────────────────────────────────────────────────────────

# Whole-document / meta questions: their wording is about *asking* (summarize,
# overview, ...) rather than the topic, so question-only grounding under-scores
# them. For these (and only these) we also ground the produced answer.
_META_QUERY_RE = re.compile(
    r"summar|overview|recap|gist|tl;?dr|key\s+(points|takeaways)|main\s+(points|ideas)"
    r"|high[\s-]level|what(?:'s| is| are)?\s+(?:this|it|the\s+(?:doc|document|file|text|paper))"
    r"\s+about|tell\s+me\s+about\s+(?:this|the\s+(?:doc|document|file|paper))"
    r"|describe\s+(?:this|the\s+(?:doc|document|paper))",
    re.IGNORECASE,
)


def _is_meta_query(query: str) -> bool:
    """True for whole-document / overview questions (summarize, overview, gist, ...)."""
    return bool(_META_QUERY_RE.search(query or ""))


def assess_confidence(
    query: str, context: list[dict], answer: Optional[str] = None
) -> Optional[dict]:
    """
    Score how well the opened sections actually support the answer, as an
    interpretable **0..100 confidence** plus the measured drivers behind it.

    Grounding ("on-topic") normally compares the QUESTION to the retrieved
    passages. That breaks for whole-document / meta queries ("summarize this",
    "give me an overview", "what is this about") whose words are *about asking*,
    not about the topic — so question-only grounding scores them falsely low. For
    those queries only, we ALSO ground the produced ANSWER (the summary, which
    does match the content) and keep the more-grounded reading. Specific off-topic
    questions are NOT meta, so they still fail grounding and score low as before.

    The paraphrase-stability probe is skipped (it would cost extra embedding calls),
    so the number is built from grounding + the support's focus, cohesion and
    consistency. Best-effort: returns None on any failure so an answer is never
    blocked by its own score.
    """
    if not context:
        return None
    try:
        import numpy as np
        from sockets import branch_index_socket, rag_metrics

        texts = [c["text"] for c in context]
        # Add the answer as a second grounding probe ONLY for meta/summary queries
        # (see above): it rescues their score without weakening off-topic detection.
        probes = [query]
        if answer and answer.strip() and _is_meta_query(query):
            probes.append(answer.strip())
        vectors, _backend = branch_index_socket.embed_corpus(probes + texts)
        arr = np.asarray(vectors, dtype=float)
        passages = arr[len(probes):]
        # Weight only the measured drivers (drop query_robustness, whose stability
        # probe we skip for speed) so the headline number stays honest.
        policy = rag_metrics.MetricPolicy(weights={
            "answer_localization": 0.45,
            "support_cohesion": 0.30,
            "evidence_consistency": 0.25,
        })
        # Keep the most-grounded reading across the probe(s).
        best = None
        for i in range(len(probes)):
            m = rag_metrics.score(arr[i], passages, texts=texts, perturb=False, policy=policy)
            if best is None or m.retrieval_confidence > best.retrieval_confidence:
                best = m
        m = best
        return {
            "score": round(float(m.retrieval_confidence), 1),
            "verdict": m.verdict,
            "reason": m.verdict_reason,
            "grounded": bool(m.grounding_assessed),
            "drivers": {
                "grounding": round(float(m.topical_grounding), 1),
                "focus": round(float(m.answer_localization), 1),
                "cohesion": round(float(m.support_cohesion), 1),
                "consistency": round(float(m.evidence_consistency), 1),
            },
        }
    except Exception:
        return None


def answer(query: str, store: Optional[dict] = None, k: int = SELECT_K) -> dict:
    """
    Answer a question with the vectorless RAG and return:
        {answer, sources: [{doc_id, doc_name, url, pages}], meta: {...}}
    Raises RuntimeError if the index has not been built yet.
    """
    store = store or load_store()
    if not store or not store.get("documents"):
        raise RuntimeError(
            "The index has not been built yet. Build it first "
            "(POST /api/index/build or rag_socket.build_store())."
        )

    pageindex_socket._require_ollama()  # friendly error if Ollama is down

    picks = select_sections(query, store, k=k)
    context = gather_context(store, picks)

    if not context:
        # The selected sections didn't resolve to any text — e.g. a smaller model
        # picking plausible-looking but invalid line numbers. Before giving up,
        # retry with the deterministic keyword selection, which reads real
        # line_num values straight from each document's structure.
        fallback = _keyword_fallback(query, store, k)
        if fallback and fallback != picks:
            context = gather_context(store, fallback)

    if not context:
        return {
            "answer": "I could not find anything relevant to that in the indexed "
            "documents. Try rephrasing, or index more documents.",
            "sources": [],
            "confidence": {
                "score": 0.0,
                "verdict": "ABSTAIN",
                "reason": "no relevant section was found in the indexed documents",
                "grounded": False,
                "drivers": None,
            },
            "meta": {"docs_indexed": len(store["documents"]), "sections_used": 0},
        }

    blocks = "\n\n".join(
        f"[{c['doc_name']}]\n{c['text']}" for c in context
    )
    messages = [
        {
            "role": "system",
            "content": (
                "You answer strictly from the provided sources. Cite the document "
                "names you used in your answer. If the sources do not contain the "
                "answer, say so plainly. Be concise and specific."
            ),
        },
        {"role": "user", "content": f"Question: {query}\n\nSources:\n{blocks}"},
    ]
    text = _llm(messages, max_tokens=config.ANSWER_MAX_TOKENS)

    return {
        "answer": text,
        "sources": [
            {
                "doc_id": c["doc_id"],
                "doc_name": c["doc_name"],
                "url": c["url"],
                "pages": c["pages"],
            }
            for c in context
        ],
        "confidence": assess_confidence(query, context, answer=text),
        "meta": {
            "docs_indexed": len(store["documents"]),
            "sections_used": len(context),
        },
    }
