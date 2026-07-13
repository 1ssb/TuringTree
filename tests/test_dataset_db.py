"""Tests for the SQLite dataset store (sockets/dataset_db.py)."""

from sockets import dataset_db

CHUNKS = [
    {"text": "Photosynthesis converts light into chemical energy.",
     "title": "Photosynthesis", "category": "Biology", "url": "u1"},
    {"text": "Mitochondria are the powerhouse of the cell.",
     "title": "Mitochondria", "category": "Biology", "url": "u2"},
    {"text": "Newton described the three laws of motion.",
     "title": "Newton", "category": "Physics", "url": "u3"},
]


def test_build_and_count(tmp_path):
    db = tmp_path / "t.sqlite"
    assert dataset_db.build(db_path=db, chunks=CHUNKS) == 3

    conn = dataset_db.connect(db)
    try:
        assert dataset_db.count(conn) == 3
        assert dataset_db.count(conn, category="Biology") == 2
        assert dataset_db.categories(conn) == ["Biology", "Physics"]
    finally:
        conn.close()


def test_search_finds_text(tmp_path):
    db = tmp_path / "t.sqlite"
    dataset_db.build(db_path=db, chunks=CHUNKS)

    conn = dataset_db.connect(db)
    try:
        rows = dataset_db.search(conn, "powerhouse")
        assert any(r["title"] == "Mitochondria" for r in rows)
    finally:
        conn.close()


def test_search_handles_fts_special_characters(tmp_path):
    db = tmp_path / "t.sqlite"
    dataset_db.build(db_path=db, chunks=CHUNKS)

    conn = dataset_db.connect(db)
    try:
        # Inputs that would otherwise crash a raw FTS5 MATCH must not raise.
        for q in ['"', 'cell"', 'a AND b', 'NEAR(', '(', '*', "", "   "]:
            assert isinstance(dataset_db.search(conn, q, limit=5), list)

        # A quote-containing query still matches the real term after escaping.
        rows = dataset_db.search(conn, 'powerhouse"', limit=5)
        assert any(r["title"] == "Mitochondria" for r in rows)

        # A blank query returns nothing.
        assert dataset_db.search(conn, "   ", limit=5) == []
    finally:
        conn.close()


def test_by_category(tmp_path):
    db = tmp_path / "t.sqlite"
    dataset_db.build(db_path=db, chunks=CHUNKS)

    conn = dataset_db.connect(db)
    try:
        rows = dataset_db.by_category(conn, "Physics")
        assert len(rows) == 1
        assert rows[0]["title"] == "Newton"
    finally:
        conn.close()
