"""
sockets/dataset_db.py — the DATASET DATABASE socket.

A tiny, local **SQLite** store for the Wikipedia-science sample. It gives you a
real queryable database — filter by category, count rows, run full-text search —
without any server, extra dependency, or network. SQLite is part of Python's
standard library, so this keeps the project's "runs locally, zero setup" promise.

How it fits in
--------------
* `dataset_socket` is the doorway data comes IN through (parquet / Hugging Face).
* `dataset_db` takes those same chunks and lands them in a SQLite file so you can
  *query* them — perfect for tests and quick experiments.

Build the database (reads the local sample via dataset_socket):
    python scripts/build_dataset_db.py

Then query it from code:
    from sockets import dataset_db
    with dataset_db.connect() as conn:
        print(dataset_db.count(conn))
        for row in dataset_db.search(conn, "photosynthesis", limit=5):
            print(row["title"], "-", row["url"])
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Iterable, Iterator, Optional

import config
from . import dataset_socket

# Columns we persist for every chunk. Keep this in lock-step with the schema and
# with the dicts produced by dataset_socket.iter_chunks().
_COLUMNS = ("title", "category", "url", "text")

# Server-friendly SQLite tuning (override via env). WAL lets readers run while a
# writer (e.g. a rebuild) is in progress instead of blocking, and the busy
# timeout retries on a locked database instead of failing instantly.
_SQLITE_TIMEOUT = float(os.getenv("RAGINDEX_SQLITE_TIMEOUT", "10"))  # seconds
_SQLITE_WAL = os.getenv("RAGINDEX_SQLITE_WAL", "1") not in ("0", "false", "False")


def connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """
    Open (or create) the SQLite database and return a connection.

    Rows come back as `sqlite3.Row`, so you can read columns by name
    (row["title"]) as well as by index. Use it as a context manager — the
    connection commits on a clean exit and rolls back on error:

        with dataset_db.connect() as conn:
            ...
    """
    path = Path(db_path) if db_path is not None else config.DATASET_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: a short-lived connection may be used from FastAPI's
    # worker thread pool; each caller still opens its own connection. `timeout`
    # waits on a busy lock rather than failing instantly.
    conn = sqlite3.connect(
        str(path), check_same_thread=False, timeout=_SQLITE_TIMEOUT
    )
    conn.row_factory = sqlite3.Row
    try:
        if _SQLITE_WAL:
            conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(f"PRAGMA busy_timeout={int(_SQLITE_TIMEOUT * 1000)}")
        conn.execute("PRAGMA synchronous=NORMAL")
    except sqlite3.Error:
        pass  # pragmas are an optimization; never fail a connection over them
    return conn


def _has_fts5(conn: sqlite3.Connection) -> bool:
    """True if this SQLite build supports the FTS5 full-text search extension."""
    try:
        conn.execute("CREATE VIRTUAL TABLE temp.__fts5_probe USING fts5(x)")
        conn.execute("DROP TABLE temp.__fts5_probe")
        return True
    except sqlite3.OperationalError:
        return False


def _create_schema(conn: sqlite3.Connection) -> bool:
    """
    (Re)create the `chunks` table and its indexes. Returns whether FTS5 search is
    available; when it is, an `chunks_fts` virtual table mirrors `chunks` and is
    kept in sync by triggers so full-text queries stay fast.
    """
    conn.executescript(
        """
        DROP TABLE IF EXISTS chunks;
        CREATE TABLE chunks (
            id       INTEGER PRIMARY KEY,
            title    TEXT,
            category TEXT,
            url      TEXT,
            text     TEXT
        );
        CREATE INDEX idx_chunks_category ON chunks(category);
        CREATE INDEX idx_chunks_url ON chunks(url);
        """
    )

    fts = _has_fts5(conn)
    if fts:
        conn.executescript(
            """
            DROP TABLE IF EXISTS chunks_fts;
            CREATE VIRTUAL TABLE chunks_fts USING fts5(
                title, text,
                content='chunks',
                content_rowid='id'
            );
            CREATE TRIGGER chunks_ai AFTER INSERT ON chunks BEGIN
                INSERT INTO chunks_fts(rowid, title, text)
                VALUES (new.id, new.title, new.text);
            END;
            CREATE TRIGGER chunks_ad AFTER DELETE ON chunks BEGIN
                INSERT INTO chunks_fts(chunks_fts, rowid, title, text)
                VALUES ('delete', old.id, old.title, old.text);
            END;
            CREATE TRIGGER chunks_au AFTER UPDATE ON chunks BEGIN
                INSERT INTO chunks_fts(chunks_fts, rowid, title, text)
                VALUES ('delete', old.id, old.title, old.text);
                INSERT INTO chunks_fts(rowid, title, text)
                VALUES (new.id, new.title, new.text);
            END;
            """
        )
    return fts


def build(
    limit: Optional[int] = None,
    category: Optional[str] = None,
    db_path: Optional[Path] = None,
    chunks: Optional[Iterable[dict]] = None,
) -> int:
    """
    Build (or rebuild) the database from the dataset sample and return the number
    of rows written.

    Parameters
    ----------
    limit : stop after this many chunks (None = all available).
    category : only store chunks from this category (None = every category).
    db_path : where to write the SQLite file (defaults to config.DATASET_DB_PATH).
    chunks : an explicit iterable of chunk dicts to load instead of reading the
             dataset socket — handy for tests with tiny, in-memory fixtures.

    Each chunk must look like the dicts produced by dataset_socket.iter_chunks():
        {"text": ..., "title": ..., "category": ..., "url": ...}
    """
    source = chunks if chunks is not None else dataset_socket.iter_chunks(
        limit=limit, category=category
    )

    with connect(db_path) as conn:
        _create_schema(conn)
        rows = (
            (ch.get("title"), ch.get("category"), ch.get("url"), ch.get("text"))
            for ch in source
        )
        cursor = conn.executemany(
            "INSERT INTO chunks (title, category, url, text) VALUES (?, ?, ?, ?)",
            rows,
        )
        # rowcount reflects the executemany batch on most builds; fall back to a
        # COUNT(*) when the driver reports -1.
        written = cursor.rowcount
        if written < 0:
            written = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    return written


def count(conn: sqlite3.Connection, category: Optional[str] = None) -> int:
    """Total number of stored chunks, optionally restricted to one category."""
    if category is None:
        return conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    return conn.execute(
        "SELECT COUNT(*) FROM chunks WHERE category = ?", (category,)
    ).fetchone()[0]


def categories(conn: sqlite3.Connection) -> list[str]:
    """Distinct category names present in the database, alphabetically sorted."""
    cur = conn.execute(
        "SELECT DISTINCT category FROM chunks WHERE category IS NOT NULL ORDER BY category"
    )
    return [r[0] for r in cur.fetchall()]


def by_category(
    conn: sqlite3.Connection, category: str, limit: Optional[int] = None
) -> list[sqlite3.Row]:
    """Return rows for a given category (newest-insert order)."""
    sql = "SELECT * FROM chunks WHERE category = ?"
    params: list = [category]
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    return conn.execute(sql, params).fetchall()


def _fts_query(query: str) -> str:
    """
    Turn arbitrary user input into a safe FTS5 MATCH expression.

    Each whitespace-separated term is wrapped as a quoted FTS5 *phrase* (with any
    embedded double quotes escaped by doubling them). This neutralizes FTS5
    operators — AND, OR, NOT, NEAR, ``*``, parentheses, stray quotes — so a
    search box can never feed syntax that raises ``OperationalError``. Multiple
    terms keep FTS5's implicit-AND behavior. Returns "" for a blank query.
    """
    return " ".join('"' + term.replace('"', '""') + '"' for term in query.split())


def search(
    conn: sqlite3.Connection, query: str, limit: int = 20
) -> list[sqlite3.Row]:
    """
    Full-text search over `title` + `text`.

    Uses the FTS5 index when the database was built with it (fast, relevance
    ranked); otherwise it gracefully falls back to a plain `LIKE` scan so search
    still works on SQLite builds without FTS5. Arbitrary input is safe: query
    terms are quoted as FTS5 phrases, and a blank query simply returns nothing.
    """
    if not query or not query.strip():
        return []

    has_fts = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='chunks_fts'"
    ).fetchone()

    if has_fts:
        match = _fts_query(query)
        if match:
            try:
                return conn.execute(
                    """
                    SELECT c.*
                    FROM chunks_fts f
                    JOIN chunks c ON c.id = f.rowid
                    WHERE chunks_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (match, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                pass  # defensive: fall through to the LIKE scan below

    like = f"%{query}%"
    return conn.execute(
        "SELECT * FROM chunks WHERE title LIKE ? OR text LIKE ? LIMIT ?",
        (like, like, limit),
    ).fetchall()


def iter_rows(conn: sqlite3.Connection) -> Iterator[sqlite3.Row]:
    """Stream every stored chunk in insertion order."""
    cur = conn.execute("SELECT * FROM chunks ORDER BY id")
    yield from cur
