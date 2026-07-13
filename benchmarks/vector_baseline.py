"""
benchmarks/vector_baseline.py — a classic embedding + cosine-kNN vector store.

This is the *baseline* RagIndex is benchmarked against: exactly what a vector
database does — embed every chunk once, then answer a query by returning the
top-k chunks with the highest cosine similarity. It uses the SAME local embedding
model RagIndex uses (config.EMBED_MODEL via Ollama, offline fallback otherwise),
so the comparison is apples-to-apples: identical embeddings, so identical recall.
The difference the benchmark exposes is the *confidence layer* RagIndex adds on
top — not the raw retrieval.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sockets import branch_index_socket as bi  # noqa: E402


def _l2norm(x: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(x, axis=-1, keepdims=True)
    return x / np.clip(n, 1e-12, None)


@dataclass
class Hit:
    row: int
    score: float
    doc_id: object
    meta: dict


class VectorIndex:
    """An in-memory cosine-kNN index over chunk embeddings (the vector-DB baseline)."""

    def __init__(self, vectors: np.ndarray, items: list[dict], backend: str):
        self.vectors = _l2norm(np.asarray(vectors, dtype=float))  # (n, d), unit rows
        self.items = items                                        # parallel metadata
        self.backend = backend

    @classmethod
    def build(cls, items: list[dict], use_llm=None) -> "VectorIndex":
        """Embed every item's `text` once and build the index. Returns the index."""
        vectors, backend = bi.embed_corpus([it["text"] for it in items], use_llm=use_llm)
        return cls(np.asarray(vectors, dtype=float), items, backend)

    def embed_query(self, query: str) -> np.ndarray:
        """Embed a query with the SAME backend the corpus was embedded with."""
        return np.asarray(bi._embed_one(query, self.backend), dtype=float)

    def search(self, query_vec: np.ndarray, k: int = 5) -> list[Hit]:
        """Return the top-k chunks by cosine similarity to `query_vec`."""
        qv = _l2norm(np.asarray(query_vec, dtype=float)[None, :])[0]
        sims = self.vectors @ qv
        order = np.argsort(-sims)[:k]
        return [
            Hit(int(i), float(sims[i]), self.items[i].get("doc_id"), self.items[i])
            for i in order
        ]
