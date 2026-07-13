"""RagIndex desktop launcher package.

Turns the single-process FastAPI app into a real desktop application: it picks a
per-user writable data directory, serves the bundled UI + API on localhost, and
opens the browser. It is the PyInstaller entry point (see packaging/ragindex.spec)
and also runs straight from a checkout:

    python -m desktop.launcher
"""
