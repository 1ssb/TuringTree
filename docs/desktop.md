# Desktop app — run, build, and install

RagIndex runs as a **single-process desktop application**: one executable starts
the server, serves the UI and JSON API on `localhost`, and opens your browser.
Everything stays **on-device** — the app talks only to a local
[Ollama](https://ollama.com) runtime, so there are no API keys and no data leaves
the machine.

This guide covers three things: running from a checkout, building the
self-contained app, and producing a Windows installer.

---

## 1. Run from source (no build needed)

The fastest way to use the app — no packaging step:

```bash
# one-time: build the UI so the backend can serve it
npm --prefix frontend install && npm --prefix frontend run build

# start the desktop app (picks a free port, opens the browser)
python -m desktop.launcher
```

Useful flags:

| Flag | Effect |
| --- | --- |
| `--no-browser` | don't open a browser (headless / CI) |
| `--port 8000` | pin a port instead of choosing a free one |
| `--data-dir PATH` | override where data is stored |
| `--host 127.0.0.1` | bind address (localhost only by default) |

The launcher binds to **127.0.0.1 only**, so the app is never exposed to the
network.

---

## 2. Build the self-contained app

This freezes the app (Python + the UI + the bundled dataset + the vendored
PageIndex model) into a folder you can copy to a machine **without Python**.

**Prerequisites on the build machine:**

1. Run setup once so the vendored model exists — `vendor/PageIndex` is cloned by
   [scripts/setup.sh](../scripts/setup.sh) (it is intentionally not committed).
2. Install the build tool: `pip install -r requirements-dev.txt` (adds PyInstaller).
3. Node.js 18+ (to build the UI).

**Build:**

```bash
python scripts/build_desktop.py          # builds the UI if needed, then freezes
# → dist/RagIndex/RagIndex(.exe)
```

Run `dist/RagIndex/RagIndex` (or `RagIndex.exe`) to start the app. The build uses
[packaging/ragindex.spec](../packaging/ragindex.spec); the same spec works on
Windows, macOS and Linux (PyInstaller produces a native build per OS).

---

## 3. Make a Windows installer

Wrap the frozen app in a friendly, **per-user** installer (no admin rights):

1. Install [Inno Setup](https://jrsoftware.org/isinfo.php).
2. Build the app first (step 2), then compile the installer:

   ```bash
   iscc packaging\windows\ragindex.iss
   # → dist/installer/RagIndex-Setup-0.1.0.exe
   ```

The installer adds Start-Menu (and optional desktop) shortcuts and an uninstaller.
It installs under `%LOCALAPPDATA%\Programs\RagIndex`, while the app's data lives
separately under `%LOCALAPPDATA%\RagIndex`, so the install folder stays read-only
at runtime.

**macOS / Linux:** the frozen folder from step 2 is the payload — wrap it in a
`.dmg`/`.app` (macOS) or an AppImage (Linux) to distribute. These are the natural
follow-ups to the Windows installer.

---

## Where data is stored

The app never writes to its install folder. All caches, indexes and uploads go to
a per-user directory (override with `RAGINDEX_DATA_DIR`):

| OS | Default data directory |
| --- | --- |
| Windows | `%LOCALAPPDATA%\RagIndex` |
| macOS | `~/Library/Application Support/RagIndex` |
| Linux | `$XDG_DATA_HOME/RagIndex` or `~/.local/share/RagIndex` |

---

## Ollama (the local model runtime)

Chat and document indexing need a local Ollama server with the two models pulled.
Branch search works offline without it.

```bash
# install Ollama from https://ollama.com, then:
ollama serve
ollama pull qwen2.5:7b-instruct      # chat / reasoning model
ollama pull qwen3-embedding:0.6b     # embedding model
```

The launcher does a quick pre-flight check and prints a friendly hint if Ollama
isn't running. Ollama is **not** bundled in the app on purpose — it is a separate
runtime that the app reaches over HTTP.

---

## Notes & caveats

- The first freeze is heavy (it bundles the full ML stack: litellm, datasets,
  PyMuPDF, NumPy/SciPy). The resulting folder is large; this is expected.
- Unsigned executables may be flagged by SmartScreen/antivirus. For public
  distribution, **code-sign** the executable and installer.
- Keep the `vendor/PageIndex` checkout in sync with the pinned version before
  building so the bundled model matches the source.
