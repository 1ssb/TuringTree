"""Tests for the ingestion socket (provenance, persistence, store wiring)."""

from pathlib import Path

import pytest

from sockets import ingest_socket, rag_socket


def test_ingest_file_end_to_end(tmp_path, monkeypatch):
    # Avoid any LLM/Ollama call: fake the tree builder.
    monkeypatch.setattr(
        ingest_socket.pi, "build_tree_from_markdown_text",
        lambda text, title="document", model=None: {
            "doc_name": title, "structure": [], "doc_description": "d"
        },
    )
    # Redirect all outputs into the temp dir.
    trees = tmp_path / "trees"
    trees.mkdir()
    monkeypatch.setattr(ingest_socket.config, "TREES_DIR", trees)
    monkeypatch.setattr(rag_socket, "STORE_PATH", tmp_path / "rag_store.json")

    captured = []
    monkeypatch.setattr(ingest_socket, "_append_audit",
                        lambda entry, *a, **k: captured.append(entry))

    doc = tmp_path / "note.md"
    doc.write_text("# Note\n\nhello world", encoding="utf-8")

    entry = ingest_socket.ingest_file(doc)

    assert entry["source_file"] == "note.md"
    assert len(entry["sha256"]) == 64
    assert entry["rag_doc_id"] == "doc_001"
    assert Path(entry["tree_path"]).exists()
    assert captured and captured[0]["rag_doc_id"] == "doc_001"

    # The ingested document is now part of the queryable store.
    status = rag_socket.status()
    assert status["doc_count"] == 1
    assert status["documents"][0]["provenance"]["source_file"] == "note.md"


def test_build_tree_for_file_rejects_unsupported(tmp_path):
    f = tmp_path / "image.bin"
    f.write_bytes(b"\x00\x01\x02")
    with pytest.raises(ValueError):
        ingest_socket.build_tree_for_file(f)


def test_build_tree_for_file_unifies_pdf_through_markdown_path(tmp_path, monkeypatch):
    # A PDF must take the SAME text-extract -> markdown-tree path as plain text,
    # not a separate, heavier PDF pipeline. That is what makes indexing latency
    # uniform across formats.
    monkeypatch.setattr(
        ingest_socket.upload_socket, "extract_text",
        lambda name, data: "extracted pdf text",
    )
    captured = {}
    monkeypatch.setattr(
        ingest_socket.pi, "build_tree_from_markdown_text",
        lambda text, title="document", model=None: captured.update(text=text, title=title)
        or {"doc_name": title},
    )
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    tree = ingest_socket.build_tree_for_file(pdf)

    assert captured["text"] == "extracted pdf text"
    assert tree["doc_name"] == "report"
    # The separate heavy PDF builder was removed as part of the unification.
    assert not hasattr(ingest_socket.pi, "build_tree_from_pdf")


def test_read_audit_log_parses_jsonl(tmp_path):
    log = tmp_path / "audit.jsonl"
    log.write_text('{"a": 1}\n\n{"b": 2}\n', encoding="utf-8")
    assert ingest_socket.read_audit_log(log) == [{"a": 1}, {"b": 2}]


def test_read_audit_log_missing_file(tmp_path):
    assert ingest_socket.read_audit_log(tmp_path / "nope.jsonl") == []
