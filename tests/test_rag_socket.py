"""Tests for the shared RAG store: upsert, de-duplication, and merge-on-build."""

from sockets import rag_socket


def _fake_tree(name="Doc"):
    return {"doc_name": name, "doc_description": "d", "structure": [], "line_count": 1}


def test_upsert_assigns_sequential_ids_and_dedupes_by_hash(tmp_path, monkeypatch):
    monkeypatch.setattr(rag_socket, "STORE_PATH", tmp_path / "rag_store.json")

    id1 = rag_socket.upsert_document(_fake_tree("A"), doc_name="A",
                                     sha256="hash-a", source_file="a.md")
    id2 = rag_socket.upsert_document(_fake_tree("B"), doc_name="B",
                                     sha256="hash-b", source_file="b.md")
    assert id1 == "doc_001"
    assert id2 == "doc_002"

    # Re-ingesting the same bytes reuses the id and does not grow the store.
    again = rag_socket.upsert_document(_fake_tree("A"), doc_name="A",
                                       sha256="hash-a", source_file="a.md")
    assert again == "doc_001"
    assert rag_socket.status()["doc_count"] == 2


def test_upsert_dedupes_dataset_docs_by_url(tmp_path, monkeypatch):
    monkeypatch.setattr(rag_socket, "STORE_PATH", tmp_path / "rag_store.json")

    first = rag_socket.upsert_document(_fake_tree("A"), doc_name="A", url="http://x/1")
    second = rag_socket.upsert_document(_fake_tree("A v2"), doc_name="A v2", url="http://x/1")
    assert first == second  # same url updates in place
    assert rag_socket.status()["doc_count"] == 1


def test_build_store_merges_and_preserves_ingested(tmp_path, monkeypatch):
    monkeypatch.setattr(rag_socket, "STORE_PATH", tmp_path / "rag_store.json")

    # An already-ingested document sits in the store.
    rag_socket.upsert_document(_fake_tree("Ingested"), doc_name="Ingested",
                               sha256="ing", source_file="i.md")

    fake_docs = [
        {"text": "x" * 2000, "title": "DS1", "url": "ds1"},
        {"text": "y" * 2000, "title": "DS2", "url": "ds2"},
    ]
    monkeypatch.setattr(rag_socket.dataset_socket, "iter_chunks",
                        lambda limit=None: iter([]))
    monkeypatch.setattr(rag_socket.dataset_socket, "to_documents",
                        lambda chunks: iter(fake_docs))
    monkeypatch.setattr(rag_socket.pageindex_socket, "build_tree_from_markdown_text",
                        lambda text, title="d", model=None: _fake_tree(title))

    out = rag_socket.build_store(max_docs=2)
    names = {d["doc_name"] for d in out["documents"].values()}
    assert "Ingested" in names          # survived the dataset rebuild
    assert {"DS1", "DS2"} <= names

    # Rebuilding again de-duplicates dataset docs by url — no pile-up.
    out2 = rag_socket.build_store(max_docs=2)
    assert out2["meta"]["doc_count"] == 3
