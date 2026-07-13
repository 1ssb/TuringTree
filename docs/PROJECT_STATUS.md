# Project status — what's done & what's pending

This is the **honest, complete picture** of where Turing Tree (RagIndex) stands.

> Released as a single clean commit on **`main`**, tagged **`v1.0.0`** (MIT).
> · Working tree: **clean** · `origin/main`: **pushed**

For *how* each finished piece works, see [ARCHITECTURE.md](ARCHITECTURE.md).

---

## ✅ Done so far

### Milestone 1 — Core workspace scaffolding · commit `49482a6`
- [x] **Central config** ([config.py](../config.py)) — one control panel for every path,
      dataset id, and model name; dependency-light so it imports before any install.
- [x] **Dataset socket** ([sockets/dataset_socket.py](../sockets/dataset_socket.py)) —
      streams the Hugging Face dataset, regroups chunks into whole articles, and
      renders them to Markdown.
- [x] **Model socket** ([sockets/pageindex_socket.py](../sockets/pageindex_socket.py)) —
      adapts the vendored PageIndex repo (adds it to `sys.path`, wraps the async
      `md_to_tree` into a simple sync call).
- [x] **Branch-index socket** ([sockets/branch_index_socket.py](../sockets/branch_index_socket.py)) —
      zero-dependency semantic search over the PageIndex repo's git branches,
      with an offline embedding fallback (stable md5 hashing).
- [x] **Scripts** — reproducible [setup.sh](../scripts/setup.sh), the branch CLI
      [index_branches.py](../scripts/index_branches.py), and the end-to-end demo
      [try_pipeline.py](../scripts/try_pipeline.py).
- [x] **Reproducibility model** — `vendor/` and `data/` git-ignored and rebuilt by
      `setup.sh`, so the repo stays small and every checkout reproduces the same env.

### Milestone 2 — Fully local (Ollama + Qwen, no API keys) · commit `9638885`
- [x] **Removed all cloud/OpenAI usage** — migrated to a local **Ollama** runtime.
- [x] **Pinned local models** ([ollama-models.txt](../ollama-models.txt)) —
      `qwen2.5:7b-instruct` (chat) and `qwen3-embedding:0.6b` (embeddings).
- [x] **LiteLLM routing** — PageIndex uses `ollama_chat/...`, the branch indexer
      uses `ollama/...`, both pointed at the local server. **No keys anywhere.**
- [x] **`setup.sh` extended** — installs Ollama, starts the server, pulls the models.
- [x] **`.env.example` has no secrets** — only optional overrides.
- [x] **Dependency conflict fixed** — pinned `python-dotenv==1.0.1` to satisfy
      `litellm==1.83.7` (upstream's `1.2.2` conflicts under a strict resolver).
- [x] **Validated end-to-end** — branch search ranks the right branches; PageIndex
      builds a tree + real document description from a dataset article via local Qwen.

### Milestone 3 — Consolidated dataset, bundled in-repo · commit `7206e11`
- [x] **Sample builder** ([scripts/make_dataset_sample.py](../scripts/make_dataset_sample.py)) —
      streams N rows and writes ONE zstd parquet.
- [x] **Bundled sample committed** — `dataset/wikipedia_science_chunked_sample.parquet`
      (**30,000 rows, ~13 MB**) lives in the repo as a **normal Git blob**.
- [x] **Dataset socket made local-first** — reads the bundled parquet when present,
      falls back to Hugging Face streaming otherwise → **runs offline**.
- [x] **Git LFS deliberately dropped** — the remote's LFS budget was exhausted, and
      a ~13 MB file is well under Git's limits, so LFS was unnecessary. (See the
      note below if you ever want a much larger, LFS-backed sample.)

### Milestone 4 — Published
- [x] **Pushed to GitHub** — `main` at `https://github.com/1ssb/TuringTree.git`,
      a single clean commit tagged `v1.0.0` under the MIT License.

---

## 🔜 Pending / not yet done

> These are split into **what the new `ui-ux` branch is for**, **known
> limitations**, and **smaller follow-ups**. None of them block the project from
> running today — they are the natural next steps.

### A. User interface (the reason this `ui-ux` branch exists) — NOT STARTED
- [ ] **There is no UI yet.** The whole project is currently CLI/library-only
      (`python scripts/...`). The `ui-ux` branch is the intended home for one.
- [ ] **Decide the UI shape** — e.g. a small **web app** (FastAPI/Flask backend +
      a simple frontend) or a terminal UI. *Awaiting your direction.*
- [ ] **"Branch search" screen** — a text box that calls
      `branch_index_socket.search_branches()` and shows ranked results.
- [ ] **"Document → tree" screen** — pick/paste an article, run
      `pageindex_socket.build_tree_from_document()`, and render the tree visually.
- [ ] **Dataset browser** — page through the bundled sample (title / category / url).
- [ ] **Wire the UI to Ollama status** — show whether the local server/models are up.

> Nothing has been built for any of the above yet — this is the next major effort.

### B. Known limitations / gaps
- [ ] **No automated tests** — there is no test suite or CI; validation so far has
      been manual end-to-end runs.
- [ ] **PageIndex is a plain clone, not pinned** — `vendor/PageIndex` is re-cloned
      at `HEAD` by `setup.sh`. For stronger reproducibility, pin it to an exact
      commit or convert it to a **git submodule**.
- [x] **Unified document indexing** — PDF, DOCX, HTML, Markdown and TXT are all
      extracted to plain text and indexed through one `build_tree_from_markdown_text()`
      path, so latency tracks a document's length, not its format (the separate,
      much heavier per-format PDF pipeline was removed).
- [ ] **Branch index is local-only** — `data/branch_index.json` is git-ignored and
      must be rebuilt with `index_branches.py build` after cloning.
- [ ] **Sample, not full dataset** — only 30k of 1.2M rows are bundled. A much
      larger sample needs **Git LFS budget** on the GitHub account (see note below).
- [ ] **First setup is a big download** — `qwen2.5:7b-instruct` is ~4.7 GB; the
      initial `setup.sh` run pulls several GB of models.

### C. Smaller follow-ups
- [ ] **Push the `ui-ux` branch** to `origin` once it has work on it
      (`git push -u origin ui-ux`).
- [ ] **Add CI** (lint + a smoke test that imports the sockets and reads the sample).
- [ ] **Document a "lighter machine" path** — e.g. swap to `qwen2.5:3b-instruct`.

---

## 📌 Note: enabling a larger, LFS-backed dataset later

The bundled sample is intentionally small so it commits cleanly as a normal Git
object. If you later raise the **Git LFS budget** on the GitHub account and want a
much bigger sample:

```bash
git lfs track "*.parquet"                                   # re-enable LFS for parquet
RAGINDEX_SAMPLE_ROWS=250000 python scripts/make_dataset_sample.py   # build a bigger sample
git add .gitattributes dataset/ && git commit -m "Store larger dataset via LFS"
git push
```

---

## Quick reference — commands that work today

```bash
# One-time, reproducible setup (deps + PageIndex + Ollama + Qwen models)
bash scripts/setup.sh

# Branch semantic search
python scripts/index_branches.py list
python scripts/index_branches.py build
python scripts/index_branches.py search "markdown tree"

# Dataset -> PageIndex end-to-end demo
python scripts/try_pipeline.py

# Rebuild / resize the bundled dataset sample
python scripts/make_dataset_sample.py
RAGINDEX_SAMPLE_ROWS=100000 python scripts/make_dataset_sample.py

# Single-process app (UI + API on one URL) and the vector-DB benchmark
npm --prefix frontend install && npm --prefix frontend run build
uvicorn backend.app.main:app --port 8000
python scripts/benchmark_rag.py --docs 6 --per-doc 15 --k 5
```

---

## Launch readiness (product branch)

The project has moved from "working prototype" to a **launchable product
representation**. What is now in place on top of the core pipeline:

- **Production hardening** — request logging + a global exception handler that
  never leaks internals, an upload‑size limit (`RAGINDEX_MAX_UPLOAD_MB`),
  enriched `/api/health` + `/api/health/ready` probes, SQLite WAL/busy‑timeout
  for concurrent access, bounded LLM timeouts, and clamped concurrency/sample
  env knobs. Full pytest suite green (**40/40**).
- **Single‑process desktop app** — a one‑click launcher
  ([desktop/launcher.py](../desktop/launcher.py)) serves the built React UI at `/`
  (SPA routing + path‑traversal guard) and the API at `/api/*` from **one process
  on localhost**, stores data in a per‑user writable folder (`RAGINDEX_DATA_DIR`),
  and opens the browser. It freezes into a self‑contained app with PyInstaller
  ([packaging/ragindex.spec](../packaging/ragindex.spec),
  [scripts/build_desktop.py](../scripts/build_desktop.py)) and ships a per‑user
  Windows installer ([packaging/windows/ragindex.iss](../packaging/windows/ragindex.iss)).
  Build/run/install guide: [docs/desktop.md](desktop.md).
- **Scientific benchmark** — a reproducible harness ([benchmarks/](../benchmarks),
  [scripts/benchmark_rag.py](../scripts/benchmark_rag.py)) shows **recall parity**
  with a vector DB and a **+79.5/100 confidence separation** that lets RagIndex
  **abstain on 100 % of off‑topic queries** a vector DB answers silently and
  wrongly. Method + numbers: [docs/benchmark.md](benchmark.md).
- **Faster re‑indexing** — a content‑hash embedding cache makes re‑indexing of
  unchanged content **~198× faster** (`RAGINDEX_EMBED_CACHE`).

**Shippable for the major platforms:** the Windows installer is done; macOS
(`.dmg`/`.app`) and Linux (AppImage) wrap the same PyInstaller payload and are the
natural next packaging step. Optional polish before a public release: an app icon
and code‑signing the executable/installer to avoid SmartScreen warnings.
