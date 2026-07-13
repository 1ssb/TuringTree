"""
benchmarks/metrics.py — reliability + retrieval metrics for the RAG benchmark.

Pure numpy, no LLM. These quantify "how confident / how confused is a retrieval":

  * gini(scores)            — inequality of the similarity scores. High = one clear
                              winner (confident); low/flat = ambiguous (confused).
  * source_entropy(doc_ids) — normalized Shannon entropy of which source documents
                              the top-k came from. 0 = all from one doc (clean);
                              1 = spread evenly across docs (contaminated/confused).
  * accuracy_at_k / contamination_rate — standard retrieval correctness.
"""

from __future__ import annotations

from collections import Counter
from typing import Iterable, Sequence

import numpy as np


def gini(values: Sequence[float]) -> float:
    """Gini coefficient of non-negative values (0 = equal, ~1 = one dominates)."""
    x = np.clip(np.asarray(values, dtype=float), 0.0, None)
    x = np.sort(x)
    n = x.size
    total = x.sum()
    if n == 0 or total == 0:
        return 0.0
    index = np.arange(1, n + 1)
    return float((2.0 * np.sum(index * x)) / (n * total) - (n + 1.0) / n)


def shannon_entropy(weights: Sequence[float]) -> float:
    """Shannon entropy (bits) of a non-negative weight vector."""
    p = np.asarray(weights, dtype=float)
    p = p[p > 0]
    if p.size == 0:
        return 0.0
    p = p / p.sum()
    return float(-np.sum(p * np.log2(p)))


def normalized_entropy(counts: Sequence[float]) -> float:
    """Entropy normalized to [0, 1] (0 = pure/one bucket, 1 = uniform spread)."""
    c = np.asarray(counts, dtype=float)
    c = c[c > 0]
    k = c.size
    if k <= 1:
        return 0.0
    return shannon_entropy(c) / np.log2(k)


def source_entropy(doc_ids: Iterable) -> float:
    """Normalized entropy of the source-document distribution of a retrieval."""
    counts = list(Counter(doc_ids).values())
    return normalized_entropy(counts)


def accuracy_at_k(retrieved_doc_ids: Sequence, gold_doc_id) -> float:
    """1.0 if the gold document appears anywhere in the top-k, else 0.0."""
    return 1.0 if gold_doc_id in set(retrieved_doc_ids) else 0.0


def top1_correct(retrieved_doc_ids: Sequence, gold_doc_id) -> float:
    """1.0 if the single best hit is from the gold document."""
    return 1.0 if retrieved_doc_ids and retrieved_doc_ids[0] == gold_doc_id else 0.0


def contamination_rate(retrieved_doc_ids: Sequence, gold_doc_id) -> float:
    """Fraction of the top-k that came from a document OTHER than the gold one."""
    if not retrieved_doc_ids:
        return 0.0
    wrong = sum(1 for d in retrieved_doc_ids if d != gold_doc_id)
    return wrong / len(retrieved_doc_ids)
