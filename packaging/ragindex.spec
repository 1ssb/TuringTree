# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for the RagIndex desktop app.

Build it with the helper (recommended — it builds the UI first):

    python scripts/build_desktop.py

…or directly once the frontend is built (frontend/dist exists):

    pyinstaller packaging/ragindex.spec --noconfirm

It produces a self-contained app under dist/RagIndex/ whose executable starts the
single-process server (UI + API on localhost) and opens the browser. Ollama is an
external runtime and is intentionally NOT bundled — the app talks to a local
Ollama server over HTTP (see docs/desktop.md).
"""

import os

from PyInstaller.building.datastruct import Tree
from PyInstaller.utils.hooks import collect_all, collect_submodules

# SPECPATH is the directory containing this spec (packaging/); the repo is its parent.
REPO_ROOT = os.path.abspath(os.path.join(SPECPATH, os.pardir))  # noqa: F821 (SPECPATH is injected)


def _p(*parts):
    return os.path.join(REPO_ROOT, *parts)

# --- Data files & binaries -------------------------------------------------
# Entries passed to Analysis(datas=...) must be 2-tuples (src, dest). collect_all()
# returns those; the big directory TREES (built UI, dataset, vendored PageIndex)
# are appended to a.datas AFTER Analysis, because Tree() yields 3-tuple TOC
# entries that the datas= argument rejects.
datas = []
binaries = []

# --- Hidden imports --------------------------------------------------------
# PageIndex is imported via a runtime sys.path insert, and several deps are pulled
# in lazily, so PyInstaller's static analysis can't see them. List them explicitly.
hiddenimports = [
    "config",
    "uvicorn",
    "anyio",
    "httpx",
    "multipart",          # python-multipart — FastAPI file uploads
    "fitz",               # PyMuPDF
    "PyPDF2",
    "yaml",
    "numpy",
    "scipy",
    "networkx",
]
hiddenimports += collect_submodules("uvicorn")
hiddenimports += collect_submodules("backend")
hiddenimports += collect_submodules("sockets")

# --- Collect data-heavy / dynamically-imported packages whole ---------------
# litellm, datasets and tiktoken ship data files and use lazy provider imports;
# collect_all is the robust way to bundle them. Guarded so a missing optional
# package never breaks the build.
for _pkg in ("litellm", "datasets", "tiktoken", "tokenizers", "huggingface_hub", "pyarrow"):
    try:
        _d, _b, _h = collect_all(_pkg)
        datas += _d
        binaries += _b
        hiddenimports += _h
    except Exception:
        pass


a = Analysis(
    [_p("desktop", "launcher.py")],
    pathex=[REPO_ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib"],
    noarchive=False,
)

# Bundle the built UI, the dataset sample, and the vendored PageIndex tree (its
# loose .py files + config.yaml) so the model socket finds it at runtime exactly
# as in a checkout. Tree() yields TOC entries appended directly to a.datas.
a.datas += Tree(_p("frontend", "dist"), prefix="frontend/dist")
a.datas += Tree(_p("dataset"), prefix="dataset")
a.datas += Tree(
    _p("vendor", "PageIndex"),
    prefix="vendor/PageIndex",
    excludes=[".git", "*.pyc", "__pycache__", "cookbook", "examples", "tests"],
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="RagIndex",
    console=True,           # show the small status console (port + Ctrl+C to quit)
    icon=None,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="RagIndex",
)
