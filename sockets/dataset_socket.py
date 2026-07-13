"""
sockets/dataset_socket.py — the DATASET socket.

This is the single doorway through which Wikipedia-science data enters the
workspace. It wraps the Hugging Face `datasets` library so the rest of the code
can ask for "some chunks" or "some documents" without knowing anything about
streaming, parquet files, or column names.

The dataset (Laz4rz/wikipedia_science_chunked_small_rag_512) is 1.2M rows / 1.5 GB.
To keep the project self-contained we ship a bounded SAMPLE of it as a local
parquet file committed right in the repo (see scripts/make_dataset_sample.py). When
that file is present this socket reads it directly, so everything runs OFFLINE.
If it is missing (or RAGINDEX_USE_LOCAL_DATASET=0) we fall back to *streaming* the
full dataset from Hugging Face on demand, which uses almost no disk.
"""

from __future__ import annotations

from typing import Iterable, Iterator, Optional

import config


def _load_stream():
    """
    Open the dataset in streaming mode.

    `datasets` is imported here (lazily) rather than at the top of the file so
    that simply importing this module does not require the library to be
    installed — handy for tooling and tests.
    """
    from datasets import load_dataset

    return load_dataset(
        config.DATASET_ID,
        split=config.DATASET_SPLIT,
        streaming=True,
    )


def _iter_local_rows() -> Iterator[dict]:
    """
    Read rows from the local parquet SAMPLE (no network, no Hugging Face).

    pyarrow is imported lazily and we read in batches so memory stays low even
    for large samples.
    """
    import pyarrow.parquet as pq

    parquet = pq.ParquetFile(str(config.LOCAL_DATASET_PATH))
    for batch in parquet.iter_batches(batch_size=1024):
        columns = {name: batch.column(name).to_pylist() for name in batch.schema.names}
        row_count = len(next(iter(columns.values()))) if columns else 0
        for i in range(row_count):
            yield {name: columns[name][i] for name in columns}


def _iter_rows() -> Iterator[dict]:
    """
    Yield raw dataset rows from the best available source: the local LFS sample
    if we have it, otherwise Hugging Face streaming.
    """
    if config.USE_LOCAL_DATASET and config.LOCAL_DATASET_PATH.exists():
        yield from _iter_local_rows()
    else:
        yield from _load_stream()


def iter_chunks(
    limit: Optional[int] = None,
    category: Optional[str] = None,
) -> Iterator[dict]:
    """
    Yield individual ~512-token chunks as clean dictionaries.

    Parameters
    ----------
    limit : stop after this many chunks (None = no limit).
    category : if given, only return chunks whose `category` matches
               (e.g. "Natural_sciences").

    Each yielded item looks like:
        {"text": ..., "title": ..., "category": ..., "url": ...}
    """
    count = 0
    for row in _iter_rows():
        if category and row.get(config.DATASET_CATEGORY_COLUMN) != category:
            continue
        yield {
            "text": row[config.DATASET_TEXT_COLUMN],
            # Titles in this dataset sometimes have leading spaces, so strip them.
            "title": (row.get(config.DATASET_TITLE_COLUMN) or "").strip(),
            "category": row.get(config.DATASET_CATEGORY_COLUMN),
            "url": row.get(config.DATASET_URL_COLUMN),
        }
        count += 1
        if limit is not None and count >= limit:
            break


def sample(n: int = 10, category: Optional[str] = None) -> list[dict]:
    """Convenience helper: return a list of `n` chunks (good for quick demos)."""
    return list(iter_chunks(limit=n, category=category))


def to_documents(chunks: Iterable[dict]) -> Iterator[dict]:
    """
    Group consecutive chunks that belong to the SAME article into one document.

    The dataset splits long Wikipedia pages into several chunks that share the
    same `url`. PageIndex builds its tree from a whole document, so here we stitch
    those chunks back together.

    Yields dictionaries like:
        {"title": ..., "url": ..., "category": ..., "chunks": [...], "text": "..."}
    where `text` is every chunk joined back together in order.
    """
    current: Optional[dict] = None
    for ch in chunks:
        if current is not None and current["url"] == ch["url"]:
            current["chunks"].append(ch["text"])
        else:
            if current is not None:
                yield _finalize(current)
            current = {
                "title": ch["title"],
                "url": ch["url"],
                "category": ch["category"],
                "chunks": [ch["text"]],
            }
    if current is not None:
        yield _finalize(current)


def _finalize(doc: dict) -> dict:
    """Join a document's chunks into one text blob and return it."""
    doc["text"] = "\n\n".join(doc["chunks"])
    return doc


def to_markdown(doc: dict) -> str:
    """
    Render a grouped document as simple Markdown (a title heading + body).

    This is the exact shape the PageIndex socket expects, which is what makes the
    two sockets "click" together in scripts/try_pipeline.py.
    """
    return f"# {doc['title']}\n\n{doc['text']}\n"
