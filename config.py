"""
config.py — One central place for every setting in the RagIndex workspace.

Think of this file as the "control panel". Every other file imports values from
here instead of hard-coding paths or names, so you only ever change things once.

It is intentionally dependency-light: importing it must work even before you have
installed anything, because the git-branch indexer relies on it and only needs
Python's standard library + git.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Project paths
# ---------------------------------------------------------------------------
# ROOT is the folder that contains this file (the workspace root).
ROOT = Path(__file__).resolve().parent

VENDOR_DIR = ROOT / "vendor"             # third-party code we "plug in"
PAGEINDEX_DIR = VENDOR_DIR / "PageIndex"  # the cloned PageIndex "model"

# Where caches + generated files live. Defaults to ROOT/data for development, but a
# packaged/installed app points RAGINDEX_DATA_DIR at a per-user, WRITABLE location
# (e.g. %LOCALAPPDATA%\RagIndex) because the install directory is read-only. Every
# writable artifact in the project derives from DATA_DIR, so this single override
# relocates all of them at once.
_data_override = os.getenv("RAGINDEX_DATA_DIR")
DATA_DIR = Path(_data_override).expanduser().resolve() if _data_override else ROOT / "data"
BRANCH_INDEX_PATH = DATA_DIR / "branch_index.json"  # output of the branch indexer

# ---------------------------------------------------------------------------
# Live ingestion (watchdog) paths
# ---------------------------------------------------------------------------
# Drop a document into INCOMING_DIR and the watcher (scripts/watch_incoming.py)
# indexes it automatically: it builds a PageIndex tree (saved under TREES_DIR)
# and records a tamper-evident provenance line in AUDIT_LOG_PATH. INCOMING_DIR is
# user-supplied data, so it is git-ignored; the trees and audit log live under the
# already-ignored data/ folder.
INCOMING_DIR = (
    Path(os.environ["RAGINDEX_INCOMING_DIR"]).expanduser().resolve()
    if os.getenv("RAGINDEX_INCOMING_DIR")
    else ROOT / "incoming"
)                                         # watched folder: drop files here
TREES_DIR = DATA_DIR / "trees"            # one saved PageIndex tree per document
AUDIT_LOG_PATH = DATA_DIR / "audit_log.jsonl"  # append-only provenance log
UPLOADS_DIR = DATA_DIR / "uploads"        # files received via the API (kept for provenance)

# Make sure the folders we write to always exist so writes never fail. Guarded so
# importing config never crashes if a path is momentarily not writable (the
# packaged app always passes a writable RAGINDEX_DATA_DIR).
for _dir in (DATA_DIR, TREES_DIR, INCOMING_DIR, UPLOADS_DIR):
    try:
        _dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

# ---------------------------------------------------------------------------
# Load optional overrides from a local .env file (model tags, OLLAMA_HOST, ...).
# Everything runs locally through Ollama, so NO API keys are required. The
# python-dotenv import is optional: if it is not installed yet we simply skip it.
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except Exception:  # package not installed yet — totally fine for branch indexing
    pass


def _int_env(name: str, default: int, lo: int, hi: int) -> int:
    """Read an int env var; fall back to `default` on missing/invalid, clamped to [lo, hi]."""
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(lo, min(hi, value))

# ---------------------------------------------------------------------------
# The Hugging Face dataset we plug into the workspace.
# Columns (confirmed from the dataset viewer):
#   text     -> the ~512-token chunk of article text
#   category -> e.g. "Natural_sciences"
#   url      -> the source Wikipedia URL (same url == same article)
#   title    -> the article title (note: it can have leading spaces)
# ---------------------------------------------------------------------------
DATASET_ID = "Laz4rz/wikipedia_science_chunked_small_rag_512"
DATASET_SPLIT = "train"
DATASET_TEXT_COLUMN = "text"
DATASET_TITLE_COLUMN = "title"
DATASET_CATEGORY_COLUMN = "category"
DATASET_URL_COLUMN = "url"

# ---------------------------------------------------------------------------
# Consolidated LOCAL copy of the dataset — a bounded SAMPLE that lives in the repo
# at dataset/. It is small (~13 MB), so it is committed DIRECTLY with Git (no LFS
# needed — LFS only pays off for large files). When this parquet file exists, the
# dataset socket reads it instead of streaming from Hugging Face, so the whole
# project is self-contained and runs OFFLINE. Want a much bigger sample? Track
# *.parquet with Git LFS (needs LFS budget on your GitHub plan) and raise the row
# count below.
# ---------------------------------------------------------------------------
DATASET_DIR = ROOT / "dataset"
LOCAL_DATASET_PATH = DATASET_DIR / "wikipedia_science_chunked_sample.parquet"

# ---------------------------------------------------------------------------
# Local SQLite database — a queryable copy of the dataset sample, handy for
# testing and quick experiments (filter by category, full-text search, etc.).
# It is BUILT from the parquet sample by scripts/build_dataset_db.py and lives in
# data/ (git-ignored) so it is always regenerable and never bloats the repo.
# SQLite needs no server and ships with Python's standard library, which keeps
# the project's "runs locally, zero setup" promise intact.
# ---------------------------------------------------------------------------
DATASET_DB_PATH = DATA_DIR / "dataset.sqlite"

# Prefer the local sample when present (set RAGINDEX_USE_LOCAL_DATASET=0 to force
# streaming the full dataset straight from Hugging Face instead).
USE_LOCAL_DATASET = os.getenv("RAGINDEX_USE_LOCAL_DATASET", "1") not in ("0", "false", "False")

# How many rows scripts/make_dataset_sample.py streams when building the sample.
# 30k rows is ~13 MB of zstd-parquet — a useful slice that stays light in Git.
DATASET_SAMPLE_ROWS = _int_env("RAGINDEX_SAMPLE_ROWS", 30000, 1, 5_000_000)

# ---------------------------------------------------------------------------
# Local LLM runtime — Ollama. Everything runs onboard: no cloud, no API keys.
# ---------------------------------------------------------------------------
# Where the local Ollama server listens. The Ollama CLI reads OLLAMA_HOST, while
# LiteLLM (used internally by PageIndex) reads OLLAMA_API_BASE — keep them equal.
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
os.environ.setdefault("OLLAMA_API_BASE", OLLAMA_HOST)
os.environ.setdefault("OLLAMA_HOST", OLLAMA_HOST)

# Keep LiteLLM quiet in normal use: it otherwise logs every call at INFO and
# prints "Give Feedback / Provider List" banners that look alarming in a shipped
# app. Set RAGINDEX_LLM_VERBOSE=1 to restore its chatter for debugging. This is
# set here (config is imported before any litellm call, by both the API and the
# CLI) so the whole app stays quiet from one place.
if os.getenv("RAGINDEX_LLM_VERBOSE", "0") in ("0", "false", "False"):
    os.environ.setdefault("LITELLM_LOG", "WARNING")
    logging.getLogger("LiteLLM").setLevel(logging.WARNING)

# Bare model tags = what `ollama pull` downloads (also listed in ollama-models.txt):
#   - chat/answering model the app runs for retrieval + grounded answers
#   - embedding model the git-branch indexer uses for semantic search
# The default chat model is the small, fast 3B instruct so answers return quickly
# on CPU. Want higher-quality (but slower) answers? Pull the 7B and point chat at
# it: `ollama pull qwen2.5:7b-instruct` then set RAGINDEX_CHAT_TAG=qwen2.5:7b-instruct.
OLLAMA_CHAT_TAG = os.getenv("RAGINDEX_CHAT_TAG", "qwen2.5:3b-instruct")
OLLAMA_EMBED_TAG = os.getenv("RAGINDEX_EMBED_TAG", "qwen3-embedding:0.6b")
# Model for the INDEX/summary step. Building the tree is a fan-out of short section
# summaries, so a small 3B instruct keeps builds fast on CPU. By default this is the
# SAME model as chat (above), so exactly one model stays resident in memory — there
# are no multi-second model swaps between indexing and answering. Override with
# RAGINDEX_INDEX_TAG / RAGINDEX_INDEX_MODEL.
OLLAMA_INDEX_TAG = os.getenv("RAGINDEX_INDEX_TAG", "qwen2.5:3b-instruct")

# Fully-qualified names LiteLLM understands and routes to the LOCAL Ollama server:
#   ollama_chat/<tag>  -> chat completion  (/api/chat)
#   ollama/<tag>       -> embeddings       (/api/embeddings)
LLM_MODEL = os.getenv("RAGINDEX_LLM_MODEL", f"ollama_chat/{OLLAMA_CHAT_TAG}")
EMBED_MODEL = os.getenv("RAGINDEX_EMBED_MODEL", f"ollama/{OLLAMA_EMBED_TAG}")

# ---------------------------------------------------------------------------
# Index-build speed-ups (see sockets/index_speedup.py)
# ---------------------------------------------------------------------------
# Building a PageIndex tree is ~100% local LLM inference (a per-heading summary
# fan-out + one doc-description call). These knobs make it cheaper:
#
#   - INDEX_LLM_MODEL: model used for tree building / summaries. Defaults to the
#     small OLLAMA_INDEX_TAG (qwen2.5:3b-instruct) because section summaries don't
#     need a large model — this keeps builds fast on CPU. Override with
#     RAGINDEX_INDEX_MODEL to point it at a different model.
#   - INDEX_SUMMARY_CONCURRENCY: cap on simultaneous summary calls. A single
#     Ollama instance thrashes (tail latency + VRAM) past ~4 in-flight requests,
#     so the upstream unbounded fan-out is bounded to this (default 4).
#   - SUMMARY_CACHE_PATH: a content-hash cache of summaries/descriptions, so
#     rebuilding unchanged content is near-instant (only edited sections re-run).
INDEX_LLM_MODEL = os.getenv("RAGINDEX_INDEX_MODEL", f"ollama_chat/{OLLAMA_INDEX_TAG}")
INDEX_SUMMARY_CONCURRENCY = _int_env("RAGINDEX_INDEX_CONCURRENCY", 4, 1, 32)
INDEX_SUMMARY_CACHE = os.getenv("RAGINDEX_INDEX_CACHE", "1") not in ("0", "false", "False")
SUMMARY_CACHE_PATH = DATA_DIR / "summary_cache.json"

# Per-LLM-call timeout (seconds). Bounds a hung Ollama call so it can't block a
# request or a build forever — generous default; no single local call should
# approach it. Override with RAGINDEX_LLM_TIMEOUT.
LLM_TIMEOUT = _int_env("RAGINDEX_LLM_TIMEOUT", 180, 5, 3600)

# ---------------------------------------------------------------------------
# Latency controls — local inference is CPU-bound (~8 tokens/sec), so wall-clock
# time is dominated by (a) reloading a model that Ollama unloaded after an idle
# gap and (b) the number of OUTPUT tokens generated. These knobs keep the model
# warm and cap generation length so small docs index and answers return quickly.
# ---------------------------------------------------------------------------
# Keep the Ollama model resident between calls so a brief pause doesn't trigger a
# multi-second reload. Passed straight through to Ollama (e.g. "30m", "1h", or
# "-1" to keep it loaded until evicted). Set to "" to use Ollama's own default.
LLM_KEEP_ALIVE = os.getenv("RAGINDEX_LLM_KEEP_ALIVE", "30m")

# Max output tokens for the ANSWER step. Generation time scales with output tokens
# on CPU, so this is kept tight for fast, focused answers. Raise
# RAGINDEX_ANSWER_MAX_TOKENS if you want longer answers (at the cost of latency).
ANSWER_MAX_TOKENS = _int_env("RAGINDEX_ANSWER_MAX_TOKENS", 280, 64, 2048)

# Max output tokens for the SELECT step (it only emits a tiny JSON array).
SELECT_MAX_TOKENS = _int_env("RAGINDEX_SELECT_MAX_TOKENS", 96, 16, 512)

# Only spend an extra LLM call choosing sections when the corpus has at least this
# many documents. Below it, the deterministic keyword fallback opens the obvious
# document(s) INSTANTLY — saving a whole model call per question. Since every chat
# query is otherwise two CPU model calls (select + answer), keeping this threshold
# generous makes typical small personal-document indexes answer in one call.
SELECT_LLM_MIN_DOCS = _int_env("RAGINDEX_SELECT_LLM_MIN_DOCS", 8, 1, 1000)

# Cap the length of each node summary / doc description generated while indexing.
# Plenty for a concise summary, but prevents pathological long generations that
# dominate build time on CPU (see sockets/index_speedup.py).
INDEX_SUMMARY_MAX_TOKENS = _int_env("RAGINDEX_INDEX_SUMMARY_MAX_TOKENS", 256, 32, 2048)

# Warm the chat model at server startup so the first request is fast, not a cold
# reload. Set RAGINDEX_WARMUP=0 to skip (e.g. on a machine without Ollama).
WARMUP_ON_START = os.getenv("RAGINDEX_WARMUP", "1") not in ("0", "false", "False")

# Upstream repository for the PageIndex "model" (used by scripts/setup.sh).
PAGEINDEX_REPO_URL = "https://github.com/VectifyAI/PageIndex.git"
