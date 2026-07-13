# Integration & Test Findings — `optimized` + Full Workspace

**Branch:** `feat/optimized-integration`
**Date:** 2026-06-24
**Base:** `upstream/optimized` (Rudra's optimized branch) — `0` behind `main`, `30` ahead
**Integrated:** Himanshu's SQLite dataset store + ingestion unification (`feat/dataset-db`)

---

## 1. Goal

Take Rudra's `optimized` branch as the new base, integrate the remaining
workstream (Himanshu's SQLite dataset store) on top, prefer the optimized
versions on any conflict, keep the confidence **score card** as-is, then test
the combined result in every practical way.

The confidence-scoring **score card** (`sockets/rag_metrics.py`,
`sockets/topo_confidence_socket.py`) and the watchdog **ingestion** work were
already present in `main` — and therefore already in `optimized` (verified
identical, untouched by the optimization work). So the only piece left to
integrate was the **dataset DB**.

## 2. What the `optimized` branch adds (30 commits over `main`)

| Area | Highlights |
| --- | --- |
| Backend perf | async `/api/index/build_async` + job polling (`backend/app/jobs.py`), content-hash summary cache + bounded concurrency (`sockets/index_speedup.py`), mtime-memoized `rag_store` loads, configurable smaller index model |
| Frontend perf | lazy-loaded routes, vendor chunking, RAF/WebGL pause on hidden tab, memoized chat messages, lazy hero-video preload |
| Portability / infra | Docker stack + `docker-compose.yml`, one-command `scripts/dev.py`, GitHub Actions CI (pytest + frontend build), pinned vendored PageIndex commit, cross-OS git resolution, configurable `VITE_API_BASE_URL` |

## 3. Integration approach

- Created `feat/optimized-integration` from `upstream/optimized`.
- Merged `feat/dataset-db` (which carries Himanshu's DB + ingestion unification).
- **Result: a single content conflict** in `sockets/rag_socket.py`.

### 3.1 Conflict resolution — `sockets/rag_socket.py`

The two branches edited the same region for **complementary** reasons:

- `optimized` added `_cache_store` (mtime-keyed memoization of the RAG store).
- `feat/dataset-db` added the ingestion bridge: `upsert_document`, a cross-process
  `_store_lock`, atomic `_write_store`, and `_next_doc_id`.

Resolved as a **union** (not "pick one"), consistent with "prefer optimized":

- **Imports** unioned (`time`, `contextlib.contextmanager`, `Callable`, `Optional`).
- Kept optimized's `_cache_store` + mtime-memoized `load_store` (the actual perf win).
- Added Himanshu's `upsert_document` machinery (required so ingested docs join the
  shared index).
- `build_store_from_documents` keeps the upsert-based body (so ingested docs
  survive a rebuild) and returns the freshly-merged store via the memoized
  `load_store()` — i.e. both optimizations apply together.

Optimized's conflicting tail referenced a `documents` dict that the merged
(upsert-based) loop no longer builds, so it could not run as-is; the union above
is the only consistent, working resolution and preserves both features.

All other overlapping files (`config.py`, `branch_index_socket.py`,
`pageindex_socket.py`) auto-merged cleanly.

## 4. Test results — all green

Environment: Windows, Python 3.12, local Ollama (`qwen2.5:7b-instruct`,
`qwen3-embedding:0.6b`), `ripser`/`persim` installed.

| # | Test | Result |
| --- | --- | --- |
| 1 | Conflict markers across repo | **none** |
| 2 | `py_compile` of resolved + key sockets | **OK** |
| 3 | Full backend suite (`pytest tests/`) | **40 / 40 passed** |
| 4 | Backend imports + route registration | **OK** — all routes below present |
| 5 | Optimized modules import (`jobs`, `index_speedup`) | **OK** |
| 6 | Live SQLite build (500 chunks) + query | **OK** (count/categories/search correct) |
| 7 | DB FTS5 special-character robustness | **0 crashes** (quote / `AND` / `NEAR(` / empty / unbalanced) |
| 8 | Score on **real data** (`verify_metrics --llm`) | **14 / 14**, on-topic 93.7 vs off-topic 7.5, **separation +86.2** |
| 9 | Frontend production build (TS typecheck + Vite) | **OK** — code-splitting active |

### Registered API routes (integrated app)
```
/api/health            /api/branches          /api/branches/build
/api/branches/search   /api/dataset/sample    /api/chat
/api/index/build       /api/index/build_async /api/index/jobs/{job_id}
/api/index/status      /api/index/tree        /api/index/export
/api/index/import      /api/ingest            /api/ingest/log
```
Optimized's async indexing, Himanshu's ingestion, the chat share/export, and the
score-backed chat all coexist.

## 5. Scope / diffstat

- vs `optimized`: **16 files, +779 / −26** (the dataset DB + ingestion bridge).
- vs `main`: **44 files, +1954 / −151** (optimized's perf/infra + the dataset DB).
- No frontend regressions; no breaking changes to existing routes.

## 6. Findings & notes

- **No functional regressions** from combining optimization + DB; perf caching and
  the ingestion lock are independent and compose correctly.
- The **score card is unchanged** end-to-end (`optimized` did not touch it), and it
  still behaves correctly on real data (+86.2 KPI separation).
- Himanshu's earlier FTS5 bug remains fixed in the integrated branch (0 crashes).
- `_cache_store` is retained from optimized; after Himanshu's atomic `_write_store`
  the file mtime changes, so the memoized `load_store()` reloads correctly — the
  cache and the writer are compatible.
- Optional follow-up (non-blocking): the optimized branch ships a CI workflow
  (`.github/workflows/ci.yml`) — once this lands, CI will run this same suite on
  every push.

## 7. Reproduce locally

```powershell
# Backend tests
.\.venv\Scripts\python.exe -m pytest tests/ -q

# Build the SQLite store + sanity stats
.\.venv\Scripts\python.exe scripts/build_dataset_db.py --limit 500 --stats

# Score on real data (needs Ollama running)
.\.venv\Scripts\python.exe scripts/verify_metrics.py --llm --docs 2 --chunks 300

# Frontend production build
cd frontend; npm install; npm run build
```

## 8. Verdict

**PASS — ready to review.** `optimized` + the SQLite dataset store + ingestion
unification + the confidence score card all integrate cleanly and pass every
test run above. One merge conflict, resolved as a union that preserves both the
optimization and the new database functionality. A follow-up stress run (§9)
surfaced and **fixed** one Windows concurrency bug in the store lock.

---

## 9. Stress test (follow-up, 2026-06-24)

Heavier run targeting the integration's risk points (synthetic inputs; a temp
store path so real data was untouched).

| Scenario | Load | Result |
| --- | --- | --- |
| Concurrent ingestion through `_store_lock` | 80 parallel `upsert_document`, 24 workers | **80 / 80 stored, no loss** |
| Re-ingest identical docs (dedupe by sha256) | 80 again | **80 (deduped, no duplicates)** |
| Concurrent DB readers | 300 searches, 24 workers | **0 errors** |
| DB build + FTS throughput | 3000-chunk build; 500 searches | build **1.15 s**; **~1360 searches/s** |
| Score throughput (realistic N=16) | 800 calls | **~139 / s** |
| Score scaling | N = 300 / 600 / 1000, `perturb=False` | 0.5 s / 13 s / 48 s — finite, correct |

### 9.1 Bug found **and fixed** — Windows concurrency crash in the store lock

Under 24-worker concurrent ingestion, `rag_socket._store_lock` crashed with
`PermissionError: [Errno 13]`. On Windows, a lock file another writer just
released is briefly in a **delete-pending** state, and `os.open(..., O_EXCL)` on
it raises `PermissionError` (EACCES) — **not** `FileExistsError`, which was the
only exception the retry loop caught. On this OneDrive-synced workspace (known to
lock files aggressively), the API and the folder-watcher ingesting at the same
time could crash an ingestion.

**Fix** (`sockets/rag_socket.py`): the acquire loop now retries on both
`FileExistsError` **and** `PermissionError`, with a hard deadline so a genuine
permission failure raises (`TimeoutError`) instead of spinning forever.

**After the fix:** 80 / 80 concurrent upserts succeed with zero loss and zero
duplicates; the full suite still passes **40 / 40**.

### 9.2 Scaling note (not a blocker)

Score time grows super-linearly with passage count — the `ripser` H1 /
Vietoris–Rips step dominates (~0.5 s at N=300 vs ~48 s at N=1000). RAG retrieval
scores a small top-k (≤ ~20 passages), so this never bites in practice. If a
caller ever scores hundreds of passages at once, cap N or skip H1 hole detection
above a threshold.

### 9.3 Reproduce

```powershell
# Concurrency + load were run via a throwaway harness; the load knobs were:
#   80 parallel upsert_document (24 workers) on a temp store
#   db.build(limit=3000) + 500 FTS searches + 300 concurrent searches
#   rag_metrics.score at N = 300 / 600 / 1000 (perturb=False)
.\.venv\Scripts\python.exe -m pytest tests/ -q   # regression gate: 40/40
```

**Stress verdict: PASS** — concurrent ingestion is now loss-free and crash-free,
DB and concurrent reads are fast, score throughput is healthy, and the one
concurrency bug found was fixed and re-verified.
