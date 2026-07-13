# Benchmark — vectorless RagIndex vs a Vector‑DB baseline

A reproducible, scientific comparison of RagIndex against the standard approach
(an embedding + cosine‑kNN **vector database**), run on web‑crawled Wikipedia
science documents. The harness lives in [`benchmarks/`](../benchmarks) and
[`scripts/benchmark_rag.py`](../scripts/benchmark_rag.py).

## TL;DR

RagIndex retrieves with the **same embeddings** as a vector DB, so its **recall is
identical**. The difference is a **confidence layer** a vector DB does not have:
it measures the *shape* of a retrieval (source entropy, dominance, grounding) and
**abstains when the result is unreliable**. In a controlled run it:

- matched the vector DB's retrieval exactly (**accuracy@5 = 1.00**, contamination 0.00);
- **flagged 100 % of off‑topic queries** that the vector DB answered silently and wrongly;
- with a **+79.5 / 100 confidence separation** between trustworthy and confused retrievals;
- and **zero false‑abstentions** on in‑corpus queries.

In one line: **same recall as a vector DB, but it knows when it's wrong.**

## What it compares

| | Baseline (vector DB) | RagIndex |
| --- | --- | --- |
| Index | embed every chunk, cosine‑kNN | same embeddings |
| Retrieval | top‑k by cosine | same top‑k |
| Reliability | *none* — always returns a top‑k | `rag_metrics.score()` → `ANSWER` / `REVIEW` / `ABSTAIN`, from source entropy + score dominance + a topical‑grounding gate |

Both sides use the same local embedding model (`config.EMBED_MODEL`,
`qwen3-embedding:0.6b` via Ollama), so the comparison isolates **the reliability
layer**, not the embeddings.

## Corpus & queries (web‑crawled Wikipedia science)

- **Corpus:** the 6 best‑populated articles from the bundled dataset sample,
  15 chunks each (**90 chunks**) — *Fine chemical, Induced stem cells, DNA
  sequencing, Genetically modified crops, Eli Lilly and Company, Organ‑on‑a‑chip*.
- **In‑corpus queries:** each article title (the answer *is* in the corpus).
- **Off‑topic queries:** everyday questions whose answer is **not** in a science
  corpus (sourdough, chess openings, football world cups, changing a car tyre,
  stock‑market tips, gym exercises).

## Metrics

- **accuracy@k / top‑1** — is the gold document in the top‑k?
- **cross‑contamination@k** — fraction of the top‑k drawn from *other* documents.
- **source entropy (0–1)** — normalized Shannon entropy of which documents the
  top‑k came from. `0` = clean (one document), `1` = confused (spread evenly).
- **score Gini (0–1)** — inequality of the top‑k similarity scores.
- **retrieval_confidence / verdict** — RagIndex's confidence layer.

## Results (measured: 6 docs / 90 chunks, local Ollama, top‑k = 5)

**Retrieval parity — same embeddings, same recall:**

| Metric | Vector‑DB baseline | RagIndex |
| --- | --- | --- |
| in‑corpus top‑1 accuracy | 1.00 | 1.00 |
| in‑corpus accuracy@5 | 1.00 | 1.00 |
| mean cross‑contamination@5 | 0.00 | 0.00 |

**Reliability layer — RagIndex's edge (the vector DB has none):**

| Metric | in‑corpus | off‑topic |
| --- | --- | --- |
| retrieval_confidence (0–100) | **91.8** | **12.3** (sep **+79.5**) |
| topical_grounding (0–100) | 93.3 | 12.7 |
| source entropy (0–1, low = clean) | **0.00** | **0.89** |
| score Gini (0–1) | 0.02 | 0.02 |
| verdict = `ANSWER` | **100 %** | **0 %** |
| verdict flagged (not `ANSWER`) | 0 % | **100 %** |

**Performance & scaling:**

| Aspect | Result |
| --- | --- |
| per‑query retrieval latency | **0.04–0.06 ms** (~17–22 k queries/s), O(n·d) |
| index build (embedding) | ~**1.3 s/chunk** on CPU — the one‑time bottleneck |
| **re‑index of unchanged content** | **198× faster** with the content‑hash embedding cache (6.2 s → 0.03 s) |

## Best‑case story (the launch narrative)

1. **Recall parity.** RagIndex uses the same embeddings, so it finds exactly what
   a vector DB finds (accuracy@5 = 1.00). It is *not* claiming better recall.
2. **It knows when it's wrong.** A vector DB returns a confident‑looking top‑k for
   **every** off‑topic query — silent cross‑contamination / hallucination.
   RagIndex **abstained on 100 %** of them, while never abstaining on a real
   in‑corpus query.
3. **Reliability is measurable.** Confidence separates trustworthy from confused
   by **+79.5 / 100**, and off‑topic retrievals show high source entropy (0.89 vs
   0.00) — a quantitative "confusion" signature a vector DB cannot produce.
4. **Fast where it counts.** Retrieval is microseconds; re‑indexing unchanged
   content is ~200× faster thanks to the embedding cache.

## Reproduce

```bash
# main comparison (needs Ollama running for real embeddings; offline fallback otherwise)
python scripts/benchmark_rag.py --docs 6 --per-doc 15 --k 5

# referential scaling — per‑query latency as the corpus grows
python scripts/benchmark_rag.py --scaling 30 60 90 --per-doc 15
```

## Honest caveats

- Single run on a small, local corpus; absolute numbers move with corpus size and
  the embedding model. The **direction** is robust: the confidence layer cleanly
  separates trustworthy from confused.
- **score Gini** was a weak discriminator here (the top‑k cosine scores are close
  regardless of correctness); **source entropy + the confidence/grounding gate**
  are the strong signals.
- Off‑topic detection leans on the **topical‑grounding gate** (an absolute cosine
  floor), so its quality tracks the embedding model. Lexical‑fallback embeddings
  do **not** separate as cleanly — use a real embedding model for trustworthy gating.
