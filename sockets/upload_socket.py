"""
sockets/upload_socket.py — the UPLOAD socket.

This is the doorway through which a user's own documents enter the workspace.
The frontend's "Index a folder" page sends the dropped files here; this socket
turns each one into plain text and hands them to the vectorless RAG engine
(sockets/rag_socket.py) to build PageIndex trees over them.

Supported formats:
    .md / .markdown / .txt / .text   plain text (read directly)
    .html / .htm                     tags stripped with the stdlib parser
    .pdf                             text extracted with PyMuPDF (fitz)
    .docx                            paragraphs extracted with python-docx

Everything stays on-device: extraction is local, and tree building runs through
the local Ollama model just like the dataset path. No network, no API keys.
"""

from __future__ import annotations

import io
import os
from html.parser import HTMLParser
from pathlib import Path

from sockets import rag_socket

# Which file types we know how to read. Anything else is skipped (with a note in
# the build summary) so a stray binary in a folder never breaks the whole build.
SUPPORTED_EXTS = {
    ".md",
    ".markdown",
    ".txt",
    ".text",
    ".html",
    ".htm",
    ".pdf",
    ".docx",
}

# How many uploaded documents to index by default, and the minimum amount of text
# a file must have to be worth a tree. Both overridable via env for bigger runs.
UPLOAD_MAX_DOCS = int(os.getenv("RAGINDEX_UPLOAD_MAX_DOCS", "8"))
UPLOAD_MIN_CHARS = int(os.getenv("RAGINDEX_UPLOAD_MIN_CHARS", "40"))


# ── Text extraction ──────────────────────────────────────────────────────────


class _HTMLTextExtractor(HTMLParser):
    """Collect visible text from HTML, skipping <script>/<style> contents."""

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in ("script", "style"):
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            text = data.strip()
            if text:
                self._parts.append(text)

    def text(self) -> str:
        return "\n".join(self._parts)


def _html_to_text(data: bytes) -> str:
    parser = _HTMLTextExtractor()
    parser.feed(data.decode("utf-8", "ignore"))
    return parser.text()


def _pdf_to_text(data: bytes) -> str:
    # PyMuPDF (fitz) is already a dependency (the vendored PageIndex uses it) and is
    # fast and dependency-light, so it is the single PDF text extractor for the app.
    import fitz  # PyMuPDF

    with fitz.open(stream=data, filetype="pdf") as doc:
        pages = [page.get_text() for page in doc]
    return "\n\n".join(p for p in pages if p.strip())


def _docx_to_text(data: bytes) -> str:
    from docx import Document

    document = Document(io.BytesIO(data))
    return "\n".join(p.text for p in document.paragraphs if p.text.strip())


def extract_text(filename: str, data: bytes) -> str:
    """Return the plain-text body of one uploaded file (best effort)."""
    ext = Path(filename).suffix.lower()
    if ext in (".md", ".markdown", ".txt", ".text"):
        return data.decode("utf-8", "ignore")
    if ext in (".html", ".htm"):
        return _html_to_text(data)
    if ext == ".pdf":
        return _pdf_to_text(data)
    if ext == ".docx":
        return _docx_to_text(data)
    # Unknown extension: try to read it as UTF-8 text, else give up on it.
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return ""


# ── Build the index from uploaded files ──────────────────────────────────────


def documents_from_files(files: list[tuple[str, bytes]]) -> list[dict]:
    """
    Turn ``[(filename, raw_bytes), ...]`` into ``[{title, text, url}, ...]``.

    Files are processed in name order for a stable doc_001, doc_002, ... mapping,
    and unreadable / empty files are dropped.
    """
    docs: list[dict] = []
    for name, data in sorted(files, key=lambda f: f[0].lower()):
        ext = Path(name).suffix.lower()
        if ext and ext not in SUPPORTED_EXTS:
            continue
        text = extract_text(name, data).strip()
        if not text:
            continue
        docs.append({"title": Path(name).name, "text": text, "url": name})
    return docs


def build_index(
    files: list[tuple[str, bytes]],
    max_docs: int = UPLOAD_MAX_DOCS,
    model: str | None = None,
    on_progress=None,
) -> dict:
    """
    Index a batch of uploaded files and cache the store to data/rag_store.json.

    Raises ValueError if none of the files yielded readable text (so the API can
    return a clean 400 instead of building an empty index). ``on_progress(done,
    total)`` is invoked after each document so a background job can report it.
    """
    docs = documents_from_files(files)
    if not docs:
        raise ValueError(
            "None of the uploaded files contained readable text "
            "(supported: PDF, Markdown, TXT, DOCX, HTML)."
        )
    return rag_socket.build_store_from_documents(
        docs,
        max_docs=max_docs,
        min_chars=UPLOAD_MIN_CHARS,
        model=model,
        on_progress=on_progress,
        total=min(len(docs), max_docs),
    )
