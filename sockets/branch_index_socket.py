"""
sockets/branch_index_socket.py — the BRANCH-INDEX socket.

Goal: "semantically index all the origin branches" of the PageIndex repo so you
can ask, in plain English, *"which branch deals with markdown trees?"* and get
the right branch back — without checking out or reading each one by hand.

How it works (the whole idea in 4 steps):

  1. LIST every remote branch (origin/*) of the cloned repo.
  2. PROFILE each branch: build a short text description of what it is about by
     mining cheap git signals (branch name, latest commit message, which files
     differ from main, and the top of its README).
  3. EMBED each profile into a vector of numbers. Similar meanings -> similar
     vectors. We use real LLM embeddings when an API key is available, and fall
     back to a dependency-free offline method otherwise.
  4. SEARCH by embedding your query the same way and ranking branches by cosine
     similarity (how close the vectors point in the same direction).

This module deliberately uses ONLY the Python standard library + git, so it runs
immediately after cloning — no pip install required.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import shutil
import subprocess
import urllib.request
from pathlib import Path
from typing import Optional

import config

_log = logging.getLogger("ragindex.branch_index")


# ---------------------------------------------------------------------------
# Step 1 + 2: talk to git and build a text "profile" for each branch
# ---------------------------------------------------------------------------
# Resolved path to the git executable (cached after the first lookup).
_GIT_EXE: Optional[str] = None


def _git_exe() -> str:
    """
    Resolve the git executable.

    Prefer the PATH (shutil.which). On Windows, when Python is launched from a
    shell whose PATH the native interpreter doesn't fully inherit (e.g. MSYS /
    Git Bash), git can be missing from that PATH — so fall back to the standard
    Git-for-Windows install locations before giving up. Cached after first call.
    """
    global _GIT_EXE
    if _GIT_EXE is not None:
        return _GIT_EXE
    found = shutil.which("git")
    if not found and os.name == "nt":
        for candidate in (
            r"C:\Program Files\Git\cmd\git.exe",
            r"C:\Program Files (x86)\Git\cmd\git.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Git\cmd\git.exe"),
        ):
            if os.path.isfile(candidate):
                found = candidate
                break
    _GIT_EXE = found or "git"  # last resort: let subprocess raise a clear error
    return _GIT_EXE


def _git(repo: Path, *args: str) -> str:
    """
    Run a git command inside `repo` and return its stdout (trimmed).

    We do NOT raise on a non-zero exit code on purpose: some look-ups (such as a
    README that does not exist on a particular branch) are expected to fail, and
    the callers simply treat empty output as "nothing here".
    """
    result = subprocess.run(
        [_git_exe(), "-C", str(repo), *args],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    return (result.stdout or "").strip()


def list_origin_branches(repo: Path = config.PAGEINDEX_DIR) -> list[str]:
    """Return every remote branch name under origin/ (the 'origin/HEAD' pointer is skipped)."""
    raw = _git(repo, "branch", "-r", "--format=%(refname:short)")
    branches = []
    for line in raw.splitlines():
        name = line.strip()
        if not name or "->" in name:  # skip e.g. "origin/HEAD -> origin/main"
            continue
        if name.startswith("origin/"):
            branches.append(name)
    return sorted(set(branches))


def collect_branch_text(
    branch: str,
    repo: Path = config.PAGEINDEX_DIR,
    base: str = "origin/main",
) -> str:
    """
    Build a short, readable profile that captures what `branch` is about.

    We stitch together four cheap-but-telling git signals:
      1. the branch name        (often very descriptive: feat/markdown-tree)
      2. the latest commit       (subject + body)
      3. what differs from main  (the list of changed files)
      4. the top of the README   (overall project context on that branch)
    """
    parts = [f"branch: {branch}"]

    commit = _git(repo, "log", "-1", "--format=%s%n%b", branch)
    if commit:
        parts.append("latest commit:\n" + commit)

    if branch != base:
        changed = _git(repo, "diff", "--stat", f"{base}...{branch}")
        if changed:
            parts.append("changes vs main:\n" + changed)

    readme = _git(repo, "show", f"{branch}:README.md")
    if readme:
        # Keep only the first 40 lines so one big README cannot dominate.
        parts.append("readme:\n" + "\n".join(readme.splitlines()[:40]))

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Step 3: turn text into vectors (two interchangeable backends)
# ---------------------------------------------------------------------------
def _stable_hash(text: str) -> int:
    """
    A hash that is identical across runs.

    Python's built-in hash() is randomized per process, which would make a saved
    index unsearchable later. md5 is stable, so we use it for the offline embedder.
    """
    return int.from_bytes(hashlib.md5(text.encode("utf-8")).digest()[:8], "big")


def _lexical_embed(text: str, dim: int = 256) -> list[float]:
    """
    Offline, dependency-free embedding using the "hashing trick".

    It slides a 3-character window over the text and hashes each piece into one
    of `dim` buckets, then L2-normalises the counts. This captures word/character
    overlap. It is NOT as smart as a neural embedding (it matches spelling more
    than meaning), but it needs nothing installed and always works. Start the
    local Ollama server to upgrade to true semantic embeddings automatically.
    """
    vec = [0.0] * dim
    text = text.lower()
    for i in range(len(text) - 2):
        bucket = _stable_hash(text[i : i + 3]) % dim
        vec[bucket] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _ollama_available() -> bool:
    """Return True if a local Ollama server is reachable (used for auto-detect)."""
    try:
        with urllib.request.urlopen(f"{config.OLLAMA_HOST}/api/tags", timeout=3):
            return True
    except Exception:
        return False


def _llm_embed(texts: list[str]) -> list[list[float]]:
    """
    Real semantic embeddings from the local Ollama server via LiteLLM, using the
    `ollama/<model>` provider (config.EMBED_MODEL). No API key — fully onboard.
    """
    import litellm

    response = litellm.embedding(model=config.EMBED_MODEL, input=texts)
    return [item["embedding"] for item in response["data"]]


# Content-hash embedding cache: embedding is the index-build bottleneck (~1s+ per
# chunk on CPU), so cache each text's vector by sha256(model + text). Re-embedding
# unchanged content is then instant. Transparent + correct (identical vectors).
_EMBED_CACHE_PATH = config.DATA_DIR / "embedding_cache.json"
_EMBED_CACHE_ON = os.getenv("RAGINDEX_EMBED_CACHE", "1") not in ("0", "false", "False")
_embed_cache: Optional[dict] = None


def _embed_key(text: str) -> str:
    h = hashlib.sha256()
    h.update(config.EMBED_MODEL.encode("utf-8"))
    h.update(b"\x00")
    h.update((text or "").encode("utf-8"))
    return h.hexdigest()


def _embed_cache_load() -> dict:
    global _embed_cache
    if _embed_cache is None:
        try:
            _embed_cache = (
                json.loads(_EMBED_CACHE_PATH.read_text(encoding="utf-8"))
                if _EMBED_CACHE_PATH.exists()
                else {}
            )
        except Exception:
            _embed_cache = {}
        if not isinstance(_embed_cache, dict):
            _embed_cache = {}
    return _embed_cache


def _llm_embed_cached(texts: list[str]) -> list[list[float]]:
    """Like _llm_embed but cached per text by content hash (only misses hit Ollama)."""
    if not _EMBED_CACHE_ON:
        return _llm_embed(texts)
    cache = _embed_cache_load()
    keys = [_embed_key(t) for t in texts]
    missing = [(i, t) for i, (t, k) in enumerate(zip(texts, keys)) if k not in cache]
    if missing:
        fresh = _llm_embed([t for _, t in missing])
        for (i, _), vec in zip(missing, fresh):
            cache[keys[i]] = vec
        try:
            _EMBED_CACHE_PATH.write_text(json.dumps(cache), encoding="utf-8")
        except Exception:
            pass  # cache is an optimization; never fail embedding over it
    return [cache[k] for k in keys]


def embed_corpus(
    texts: list[str],
    use_llm: Optional[bool] = None,
) -> tuple[list[list[float]], str]:
    """
    Embed many texts and report which backend was used.

    `use_llm=None` (default) auto-detects: it uses real embeddings from the local
    Ollama server when it is reachable, otherwise the offline lexical fallback.
    Returns (vectors, backend_label) so the label can be saved with the index.
    """
    if use_llm is None:
        # Use real embeddings when the local Ollama server is up; otherwise the
        # offline lexical method keeps the indexer working with zero setup.
        use_llm = _ollama_available()

    if use_llm:
        try:
            return _llm_embed_cached(texts), config.EMBED_MODEL
        except Exception as exc:  # server down / model not pulled -> fall back
            _log.warning("Ollama embedding failed (%s); using offline fallback.", exc)

    return [_lexical_embed(t) for t in texts], "lexical-fallback"


def _embed_one(text: str, backend: str) -> list[float]:
    """Embed a single query using the SAME backend the index was built with."""
    if backend == "lexical-fallback":
        return _lexical_embed(text)
    return _llm_embed([text])[0]


# ---------------------------------------------------------------------------
# Step 4: build the index and search it
# ---------------------------------------------------------------------------
def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity: 1.0 = identical direction, 0.0 = unrelated."""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def build_branch_index(
    repo: Path = config.PAGEINDEX_DIR,
    out_path: Path = config.BRANCH_INDEX_PATH,
    use_llm: Optional[bool] = None,
) -> dict:
    """
    Build the semantic index for every origin branch and save it to JSON.

    The saved file records, for each branch: its name, the text profile we built,
    and the embedding vector. It also stores which `model`/backend produced the
    vectors, so searches later use a matching query embedding.
    """
    branches = list_origin_branches(repo)
    if not branches:
        raise RuntimeError(
            f"No origin branches found in {repo}. Is it a clone? "
            "Run scripts/setup.sh to clone PageIndex and fetch its branches."
        )

    profiles = [collect_branch_text(b, repo) for b in branches]
    vectors, backend = embed_corpus(profiles, use_llm=use_llm)

    index = {
        "repo": str(repo),
        "model": backend,
        "branches": [
            {"branch": b, "profile": p, "vector": v}
            for b, p, v in zip(branches, profiles, vectors)
        ],
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(index, indent=2), encoding="utf-8")
    return index


def search_branches(
    query: str,
    index_path: Path = config.BRANCH_INDEX_PATH,
    k: int = 5,
) -> list[tuple[float, str, str]]:
    """
    Return the `k` branches most relevant to `query`.

    Each result is a tuple: (similarity_score, branch_name, branch_profile).
    """
    if not Path(index_path).exists():
        raise RuntimeError(
            f"No index found at {index_path}. Build it first with:\n"
            "    python scripts/index_branches.py build"
        )

    index = json.loads(Path(index_path).read_text(encoding="utf-8"))
    backend = index.get("model", "lexical-fallback")
    query_vec = _embed_one(query, backend)

    scored = [
        (_cosine(query_vec, entry["vector"]), entry["branch"], entry["profile"])
        for entry in index["branches"]
    ]
    scored.sort(key=lambda row: row[0], reverse=True)
    return scored[:k]
