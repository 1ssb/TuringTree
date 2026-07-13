# Retrieval Confidence Scoring

A small, **embedding-agnostic** library that scores *how much you should trust a
RAG retrieval*. It turns the geometry of embeddings you have already computed
into a single confidence KPI, four explainable drivers, and an actionable
verdict — with **no extra LLM call and no labels**.

```python
from sockets.rag_metrics import score      # (as a standalone package you'd rename this)

m = score(query_embedding, passage_embeddings, texts=passages)

m.verdict                 # "ANSWER" | "REVIEW" | "ABSTAIN" | "ESCALATE"
m.retrieval_confidence    # 0..100 headline KPI
m.to_dict()               # flat JSON, ready for structured logging / dashboards
print(m.narrate())        # human-readable, range-based explanation
```

---

## Contents

1. [Why this exists](#1-why-this-exists)
2. [The metrics](#2-the-metrics)
3. [How it works](#3-how-it-works)
4. [Public API & the JSON contract](#4-public-api--the-json-contract)
5. [Integration guide](#5-integration-guide)
6. [Calibration](#6-calibration)
7. [Architecture & files](#7-architecture--files)
8. [Dependencies](#8-dependencies)
9. [Testing](#9-testing)
10. [Limitations & future work](#10-limitations--future-work)

---

## 1. Why this exists

A RAG pipeline retrieves passages and generates an answer, but it rarely says
*"how sure am I that this answer is actually supported by what I retrieved?"*
Without that signal you cannot safely gate, abstain, escalate, or alert on
quality regressions.

This library answers the question from the **shape** of the retrieval. After your
retriever has embedded the query and the candidate passages, the *relevance* the
query induces over those passages has a structure:

- a confident retrieval lights up **one coherent, well-separated region**;
- a poor retrieval is **diffuse, fragmented, or not actually on-topic**.

We quantify that structure with cheap, classical tools (cosine similarity, a
0-dimensional persistence filtration, a graph Laplacian) and fold it into one
calibratable confidence read-out. It needs only the embeddings you already have.

## 2. The metrics

Everything is on a `0..100, higher = healthier` scale, plus one categorical
verdict. The KPI **decomposes** so every dip is explainable.

$$\text{retrieval\_confidence} \;=\; \underbrace{\text{topical\_grounding}}_{\text{gate, }0..1}\;\times\;\underbrace{\big(0.35\,\text{AL} + 0.25\,\text{SC} + 0.25\,\text{EC} + 0.15\,\text{QR}\big)}_{\text{weighted shape score}}$$

| Metric | Question it answers | Low value means → action | Cost |
| --- | --- | --- | --- |
| **`retrieval_confidence`** (KPI) | "Can I trust this retrieval?" | gate the response | free |
| `topical_grounding` | "Is the query even *about* these passages?" | off-topic → abstain / widen retrieval | free |
| `answer_localization` | "Did the query hit **one** coherent region?" | no answer locus → don't synthesize | free |
| `support_cohesion` | "Is the support compact, not scattered?" | fragmented → re-retrieve / merge chunks | free |
| `evidence_consistency` | "Do the retrieved pieces agree?" | contradiction → surface conflicting sources | free |
| `query_robustness` | "Would a paraphrase change the result?" | brittle → ask the user to clarify | +k embeds |

> *"free"* = pure post-processing of the embedding scores you already computed.
> `query_robustness` is the only one with a cost (~8 re-embeddings for the
> stability probe); disable it with `perturb=False`.

**Verdict policy** (the one field serving code branches on):

| Verdict | When | Suggested action |
| --- | --- | --- |
| `ESCALATE` | consistency low **and** a persistent contradiction loop | route to a human / show conflicting sources |
| `ABSTAIN` | KPI below the abstain threshold | withhold; ask to rephrase / return "not found" |
| `REVIEW` | KPI in the caveat band **or** any driver below its floor | serve with a caveat / trigger re-retrieval |
| `ANSWER` | KPI high and all drivers healthy | serve |

Each result also carries `primary_risk` (the weakest signal) and a one-line
`verdict_reason`, so triage is a glance.

## 3. How it works

The engine is deliberately small and classical. Four ideas:

**(a) Relevance filtration → persistence barcode.**
Score every passage by cosine similarity to the query and min-max normalise to
`[0,1]`. Sweep a threshold from 1 down to 0 and watch relevance "islands" appear
and merge. On a tree (or the synthetic star we build for a flat top-k list) this
is exactly **0-dimensional persistent homology**, computed in near-linear time
with union-find. The barcode's dominant-bar **margin** and total non-dominant
**fragmentation** become `answer_localization` and `support_cohesion`.

**(b) Topical grounding gate.**
Min-max normalisation *always* manufactures a "most relevant" passage, so the
shape can look confident even for an off-topic query. The raw (un-normalised)
cosine does not lie: we gate the KPI on a sigmoid of the top-k raw cosine. This
is the single most important guard against false confidence.

**(c) Evidence consistency.**
A cellular-sheaf Dirichlet energy (graph Laplacian with identity restriction
maps) measures whether neighbouring passages "glue"; a persistent **H1 loop**
(Vietoris–Rips over the embeddings) flags evidence that relates pairwise but
never closes into one coherent story — a contradiction signature.

**(d) Query robustness.**
Perturb the query embedding a few times, recompute the barcode, and measure how
far it moves (bottleneck / Wasserstein distance). Small movement ⇒ a robust,
phrasing-insensitive retrieval — a direct use of the persistence stability
theorem.

The full, heavily-commented implementation lives in
[`sockets/topo_confidence_socket.py`](../sockets/topo_confidence_socket.py); the
product-facing mapping (bands, verdict, KPI) in
[`sockets/rag_metrics.py`](../sockets/rag_metrics.py).

## 4. Public API & the JSON contract

```python
score(
    query_embedding,      # (d,)   the question vector
    passage_embeddings,   # (n, d) one row per retrieved passage
    texts=None,           # optional passage texts (for support snippets only)
    parents=None,         # optional tree structure; omit for a flat top-k list
    policy=None,          # MetricPolicy (thresholds + weights)
    calibrator=None,      # optional callable mapping KPI fraction -> P(correct)
    perturb=True,         # set False to skip the stability probe (faster)
) -> RagConfidenceMetrics
```

`RagConfidenceMetrics` exposes `.verdict`, `.retrieval_confidence`, the five
sub-scores, `.primary_risk`, `.to_dict()`, and `.narrate()`.

**`to_dict()` is the stable contract** (locked by a test). Keys:

| Key | Type | Meaning |
| --- | --- | --- |
| `retrieval_confidence` | float | 0..100 KPI |
| `confidence_band` | str | `HIGH` / `MEDIUM` / `LOW` |
| `retrieval_confidence_band` | str | `strong` / `good` / `mixed` / `weak` |
| `topical_grounding` (+`_band`) | float, str | absolute on-topic gate |
| `answer_localization` (+`_band`) | float, str | one coherent region? |
| `support_cohesion` (+`_band`) | float, str | compact vs scattered |
| `evidence_consistency` (+`_band`) | float, str | pieces agree? |
| `query_robustness` (+`_band`) | float, str | paraphrase-stable? |
| `verdict`, `verdict_action`, `verdict_reason` | str | the decision + why |
| `primary_risk` | str | weakest signal (triage pointer) |
| `grounding_assessed` | bool | false on the offline lexical backend |
| `evidence.*` | numbers/str | raw drill-down (margin, fragmentation, sheaf energy, contradiction loops, stability move, …) |

Every value is plain-Python / JSON-serialisable.

## 5. Integration guide

```python
from sockets.rag_metrics import score

def answer(query_vec, passages, passage_vecs):
    m = score(query_vec, passage_vecs, texts=passages)
    log.info("rag_confidence", **m.to_dict())          # structured logging

    if m.verdict == "ABSTAIN":
        return "I couldn't find a confident answer — try rephrasing."
    if m.verdict in ("REVIEW", "ESCALATE"):
        flag_for_review(m.primary_risk, m.verdict_reason)
    return generate_answer(query, passages)            # your existing generator
```

- **Flat top-k** (the common case): omit `parents`; passages hang off a synthetic
  centroid root.
- **Hierarchy** (e.g. a section tree): pass `parents` (a parent index per node,
  root = `None`, parents before children) to activate the `focus` depth signal.
- **Dashboards / SLOs**: track the KPI distribution and `% ANSWER/REVIEW/ABSTAIN`;
  alert on `p10(retrieval_confidence)` dropping or `% ABSTAIN` rising — a
  label-free retrieval-quality regression signal.

## 6. Calibration

The defaults are tuned for `qwen3-embedding:0.6b`. **Before trusting absolute
numbers, calibrate to your embedding model and data** — two knobs:

1. **Grounding gate** — `MetricPolicy.grounding_center` / `grounding_scale`. Measure
   the top-k raw cosine for a sample of on-topic vs off-topic (query, passages)
   pairs; set `center` near the boundary and `scale` to the spread.
2. **KPI → probability** — fit isotonic/Platt regression mapping the raw KPI to
   `P(answer correct)` on a labelled set and pass it as `calibrator=`.

Verdict thresholds and KPI weights also live in `MetricPolicy` and are per-deployment.

## 7. Architecture & files

The feature is two layers, plus optional workspace glue and demos.

**Portable core** (this is the deployable unit — copy these to integrate):

| File | Role |
| --- | --- |
| [`sockets/topo_confidence_socket.py`](../sockets/topo_confidence_socket.py) | the engine: relevance filtration, persistence, sheaf, stability, holes, curvature; `report_from_embeddings()` is the embedding-only entry point |
| [`sockets/rag_metrics.py`](../sockets/rag_metrics.py) | the product layer: KPI + grounding gate + bands + verdict + `score()` facade |
| [`tests/test_score_api.py`](../tests/test_score_api.py) | 25 contract / invariant / edge-case tests (no network) |

The engine's `config` / embedding-backend imports are **lazy**, so the `score()`
path needs only `numpy` + `scipy` + `networkx` (+ optional `ripser` / `persim`).

**Workspace glue & demos** (RagIndex-specific, *not* required to integrate the
scorer): the Ollama/lexical embedding path and dataset/PageIndex adapters in the
engine, plus the demo CLIs `scripts/ask.py`, `scripts/topo_confidence.py`, and
the verification harness `scripts/verify_metrics.py`.

## 8. Dependencies

| Dependency | Required? | Used for |
| --- | --- | --- |
| `numpy` | yes | vectors, union-find filtration |
| `scipy` | yes | sheaf Laplacian linear algebra |
| `networkx` | yes | graph build, Laplacian, curvature |
| `ripser` | optional | Vietoris–Rips H1 "epistemic holes" |
| `persim` | optional | bottleneck distance for stability |

`ripser`/`persim` are guarded: without them, H1 holes degrade gracefully and
stability falls back to a sorted-persistence surrogate.

## 9. Testing

```bash
python tests/test_score_api.py            # zero-dependency runner
python -m pytest tests/test_score_api.py  # CI (pip install -r requirements-dev.txt)
```

25 tests using only synthetic embeddings (no Ollama, dataset, or network):

- **Contract** — the exact `to_dict()` key set is frozen and asserted; outputs are
  JSON-serialisable, range-bounded, verdict-enum valid.
- **Invariants** — on-topic → ANSWER, off-topic → ABSTAIN, grounding monotone in
  cosine, KPI separation, fragmentation on a split tree, determinism, calibrator,
  custom policy.
- **Edge cases** — n = 1/2 passages, identical passages, zero query, list inputs,
  dimension mismatch (clear `ValueError`), empty input, a real parent tree, and a
  300-passage load test.

## 10. Limitations & future work

- **Calibration is required** for absolute numbers to be meaningful on a new
  embedding model (the gate is cosine-scale dependent).
- **Flat top-k fragmentation is weaker** than hierarchical: the synthetic
  centroid root absorbs a single coherent cluster, so `support_cohesion`
  primarily fires when *relevant* material is structurally split. Pass `parents`
  when you have structure.
- **The sheaf uses identity restriction maps** (graph Dirichlet energy). Learned
  restriction maps would make `evidence_consistency` sharper.
- **Lexical/offline backend** cannot assess `topical_grounding` (absolute cosines
  don't separate); it reports `grounding_assessed = false` and scores shape only.
