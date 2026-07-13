"""
sockets/topo_confidence_socket.py — the TOPOLOGICAL-CONFIDENCE socket.

Goal
----
Give every RAG retrieval a *topologically-inspired confidence representation*:
not just "here is the answer", but "here is the SHAPE of the support the answer
rests on, and how much we should trust it".

The whole idea in one sentence: PageIndex turns a document into a **tree** (a
contractible 1-D simplicial complex), retrieval lights up a **subspace** of that
tree, and the *shape* of that lit-up subspace — how dominant, compact, consistent
and stable it is — is a principled confidence signal.

We compute, from cheap-and-exact to rich-and-research:

  1. RELEVANCE FILTRATION  — score every node r(v) in [0,1] (query vs node, via
     the local Ollama embedding model, with an offline lexical fallback), then
     sweep a threshold and watch relevance "islands" form. Because a tree is
     acyclic this is 0-dim persistent homology computable EXACTLY with union-find.
  2. SCORES               — dominance, topological margin, fragmentation, focus
     (LCA depth), and a relevance-mass concentration. The persistence *barcode* is
     the representation; these scalars are reductions of it.
  3. EPISTEMIC HOLES (H1) — build a Vietoris-Rips complex over the node embeddings
     (via `ripser`) and read its 1-cycles: persistent loops flag evidence that
     relates pairwise but does not close into one coherent story.
  4. SHEAF CONSISTENCY    — a cellular-sheaf Dirichlet energy (graph Laplacian with
     identity restriction maps) measuring whether neighbouring nodes "glue".
  5. STABILITY            — perturb the query embedding and measure how much the
     barcode moves (bottleneck / Wasserstein distance via `persim`): a direct use
     of the persistence stability theorem.
  6. CURVATURE            — discrete Forman-Ricci curvature of the support region
     (redundancy vs. bottleneck / fragility).

Everything is wrapped into one `TopoConfidenceReport`.

Libraries used (per the "use library functions wherever you can" brief):
    numpy, scipy, networkx              (always)
    ripser, persim                      (optional; gracefully degraded if absent)
We reuse our own `branch_index_socket` for the embedding backends so the chat and
branch tools share exactly one notion of "embed this text".
"""

from __future__ import annotations

import math
import os
import warnings
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import networkx as nx

# NOTE: `config` and `branch_index_socket` (the Ollama/lexical embedding backends)
# are imported LAZILY inside the few functions that need them, so the deployable
# scoring path — report_from_embeddings() / rag_metrics.score() — needs only
# numpy + scipy + networkx (+ optional ripser/persim) and no workspace config.

# Optional TDA libraries — the apparatus still runs without them.
try:
    from ripser import ripser as _ripser
    _HAS_RIPSER = True
except Exception:  # pragma: no cover - optional dep
    _HAS_RIPSER = False

try:
    import persim as _persim
    _HAS_PERSIM = True
except Exception:  # pragma: no cover - optional dep
    _HAS_PERSIM = False


# ---------------------------------------------------------------------------
# Tunables (all overridable through function arguments).
# ---------------------------------------------------------------------------
EPS = 1e-9
BETTI_STEPS = 101                 # resolution of the Betti curve b0(tau)
PERTURB_SIGMA = 0.05              # query-embedding noise for the stability probe
PERTURB_SAMPLES = 8              # how many perturbed queries to average over
HOLE_PERSISTENCE_MIN = 0.05       # minimum life for an H1 loop to count as a "hole"
NODE_TEXT_CHARS = 1500            # truncate node text before embedding

# Weights for the composite confidence (all signals are mapped to "higher=better").
COMPOSITE_WEIGHTS = {
    "margin": 1.0,
    "dominance": 1.0,
    "concentration": 0.75,
    "focus": 0.75,
    "consistency": 1.0,
    "stability": 1.0,
    "holes_penalty": 0.75,
}


# ===========================================================================
# 0. Document/tree adapters — turn whatever we have into a uniform tree
# ===========================================================================
def tree_from_document(doc: dict) -> dict:
    """
    Build a simple 2-level tree from a grouped dataset document.

    The dataset socket hands us ``{"title", "url", "chunks": [...], "text"}``.
    We make the title the root and each ~512-token chunk a leaf. This lets the
    whole apparatus run on real data *before* a full PageIndex tree exists.
    """
    children = [
        {"title": f"chunk {i + 1}", "text": chunk, "nodes": []}
        for i, chunk in enumerate(doc.get("chunks", []))
    ]
    return {"title": doc.get("title", "document"), "text": doc.get("text", ""), "nodes": children}


def _children_of(node: dict) -> list:
    """Return a node's children, tolerating PageIndex ('nodes'/'structure') and generic schemas."""
    for key in ("nodes", "structure", "children", "child", "subsections"):
        kids = node.get(key)
        if isinstance(kids, list):
            return kids
    return []


def _text_of(node: dict) -> str:
    """Pick the most informative text for a node (full text > summary > title > doc description)."""
    for key in ("text", "summary", "title", "doc_description", "node_id"):
        val = node.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


# ===========================================================================
# 1. Flatten the tree into a graph + per-node records
# ===========================================================================
@dataclass
class _NodeRec:
    nid: int
    title: str
    text: str
    depth: int
    parent: Optional[int]


def build_graph(tree: dict) -> tuple[nx.Graph, list[_NodeRec]]:
    """
    Depth-first flatten the tree into:
      * a networkx.Graph whose nodes are 0..n-1 (tree edges only), and
      * a list of _NodeRec carrying title/text/depth/parent for each node.

    Node ids are assigned in DFS pre-order so the root is always id 0.
    """
    records: list[_NodeRec] = []
    graph = nx.Graph()

    def visit(node: dict, parent: Optional[int], depth: int) -> int:
        nid = len(records)
        graph.add_node(nid)
        title = node.get("title") or node.get("node_id") or node.get("doc_name") or f"node {nid}"
        records.append(_NodeRec(nid=nid, title=str(title), text=_text_of(node), depth=depth, parent=parent))
        if parent is not None:
            graph.add_edge(parent, nid)
        for child in _children_of(node):
            if isinstance(child, dict):
                visit(child, nid, depth + 1)
        return nid

    # The PageIndex root is sometimes a bare list of top-level sections.
    if isinstance(tree, list):
        tree = {"title": "document", "nodes": tree}
    visit(tree, None, 0)
    return graph, records


def _lca(records: list[_NodeRec], a: int, b: int) -> int:
    """Lowest common ancestor of two nodes using parent pointers."""
    # Bring both to equal depth, then climb together.
    while records[a].depth > records[b].depth:
        a = records[a].parent  # type: ignore[assignment]
    while records[b].depth > records[a].depth:
        b = records[b].parent  # type: ignore[assignment]
    while a != b:
        a = records[a].parent  # type: ignore[assignment]
        b = records[b].parent  # type: ignore[assignment]
    return a


def _lca_of_set(records: list[_NodeRec], nodes: list[int]) -> int:
    out = nodes[0]
    for n in nodes[1:]:
        out = _lca(records, out, n)
    return out


# ===========================================================================
# 2. Relevance — score each node against the query (semantic, with fallback)
# ===========================================================================
def relevance_over_nodes(
    node_texts: list[str],
    query: str,
    use_llm: Optional[bool] = None,
    node_embeddings: Optional[np.ndarray] = None,
    backend: Optional[str] = None,
) -> tuple[np.ndarray, np.ndarray, str, np.ndarray, np.ndarray]:
    """
    Embed the query and every node, return a 5-tuple:
        raw_cosine[v]    in [-1, 1]
        relevance[v]     in [0, 1]   (min-max normalised — the filtration height)
        backend          which embedding backend was used
        node_embeddings  (n, d) matrix of node vectors
        query_vector     (d,) the embedded query (reused by the stability probe)

    Pass `node_embeddings` (+`backend`) to reuse vectors already computed for this
    tree — only the query is re-embedded, which makes scoring many queries against
    one document cheap. We reuse branch_index_socket.embed_corpus so the embedding
    backend (local Ollama `qwen3-embedding` or the offline lexical fallback) is
    shared with the rest of the workspace.
    """
    from . import branch_index_socket as _bi  # lazy: only this Ollama/lexical path needs it
    import config

    if node_embeddings is None:
        texts = [(t or "")[:NODE_TEXT_CHARS] for t in node_texts]
        node_vecs, backend = _bi.embed_corpus(texts, use_llm=use_llm)
        M = np.asarray(node_vecs, dtype=float)
    else:
        M = np.asarray(node_embeddings, dtype=float)
        backend = backend or config.EMBED_MODEL
    q_vec = _bi._embed_one(query, backend)
    q = np.asarray(q_vec, dtype=float)

    # Cosine similarity, vectorised.
    Mn = M / (np.linalg.norm(M, axis=1, keepdims=True) + EPS)
    qn = q / (np.linalg.norm(q) + EPS)
    cos = Mn @ qn

    # Min-max to [0,1] so the filtration height is comparable across queries.
    lo, hi = float(cos.min()), float(cos.max())
    rel = (cos - lo) / (hi - lo) if hi - lo > EPS else np.ones_like(cos) * 0.5
    return cos, rel, backend, M, q


# ===========================================================================
# 3. Tree 0-dim persistence (super-level filtration, union-find, Elder Rule)
# ===========================================================================
@dataclass
class _UF:
    parent: dict = field(default_factory=dict)
    birth: dict = field(default_factory=dict)

    def add(self, x: int, b: float) -> None:
        self.parent[x] = x
        self.birth[x] = b

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x


def tree_persistence(graph: nx.Graph, relevance: np.ndarray) -> list[tuple[float, float, int]]:
    """
    0-dimensional persistent homology of the relevance function on the tree.

    Super-level filtration: lower a threshold tau from 1 to 0; admit nodes with
    r >= tau. Components are *born* at relevance maxima and *die* (Elder Rule:
    the younger/lower-birth component dies) when a node bridges two of them.

    Returns a barcode as a list of (birth, death, representative_node). The one
    *essential* component (the global maximum) is given death 0.0.
    """
    order = sorted(range(len(relevance)), key=lambda v: relevance[v], reverse=True)
    uf = _UF()
    active: set[int] = set()
    bars: list[tuple[float, float, int]] = []

    for v in order:
        rv = float(relevance[v])
        uf.add(v, rv)
        active.add(v)
        for u in graph.neighbors(v):
            if u in active:
                ru, rv_root = uf.find(u), uf.find(v)
                if ru != rv_root:
                    # Elder Rule: the component born LATER (lower birth) dies now.
                    if uf.birth[ru] >= uf.birth[rv_root]:
                        older, younger = ru, rv_root
                    else:
                        older, younger = rv_root, ru
                    bars.append((uf.birth[younger], rv, younger))  # (birth, death, rep)
                    uf.parent[younger] = older

    # Whatever survives is essential (the dominant relevance region): death = 0.
    for root in {uf.find(v) for v in active}:
        bars.append((uf.birth[root], 0.0, root))
    return bars


def positive_bars(bars, eps: float = 1e-6):
    """Keep only bars with real persistence (drop the zero-length merge artefacts)."""
    out = [(b, d, rep) for (b, d, rep) in bars if (b - d) > eps]
    out.sort(key=lambda t: (t[0] - t[1]), reverse=True)
    return out


# ===========================================================================
# 4. Scores derived from the barcode + the tree
# ===========================================================================
def betti_curve(bars, steps: int = BETTI_STEPS) -> tuple[np.ndarray, np.ndarray]:
    """b0(tau): number of live components as the threshold sweeps 1 -> 0."""
    taus = np.linspace(1.0, 0.0, steps)
    b0 = np.array([sum(1 for (b, d, _) in bars if b >= t > d) for t in taus])
    return taus, b0


def scores_from_barcode(
    bars,
    records: list[_NodeRec],
    relevance: np.ndarray,
    focus_tau: float = 0.6,
) -> dict:
    """
    Reduce the barcode + tree into interpretable scalar scores in [0,1].

      dominance     : share of total persistence held by the top feature.
      margin        : persistence gap between the #1 and #2 features (a topo
                      analogue of a spectral gap / classification margin).
      fragmentation : total persistence in NON-dominant features (0 = compact).
      focus         : depth of the LCA of the high-relevance nodes / tree height.
      concentration : 1 - normalised entropy of the relevance mass.
      n_features    : number of persistent components.
    """
    pos = positive_bars(bars)
    pers = [b - d for (b, d, _) in pos]
    total = sum(pers)

    dominance = (pers[0] / total) if total > EPS else 0.0
    margin = (pers[0] - pers[1]) if len(pers) >= 2 else (pers[0] if pers else 0.0)
    fragmentation = float(sum(pers[1:])) if len(pers) > 1 else 0.0

    # Focus: how deep in the tree does the high-relevance support sit?
    height = max((r.depth for r in records), default=1) or 1
    hot = [v for v in range(len(relevance)) if relevance[v] >= focus_tau]
    if not hot:
        hot = [int(np.argmax(relevance))]
    focus = records[_lca_of_set(records, hot)].depth / height

    # Concentration: relevance treated as a probability mass over nodes.
    p = relevance / (relevance.sum() + EPS)
    nz = p[p > EPS]
    entropy = -float((nz * np.log(nz)).sum()) / math.log(len(relevance)) if len(relevance) > 1 else 0.0
    concentration = 1.0 - entropy

    return {
        "dominance": float(dominance),
        "margin": float(margin),
        "fragmentation": float(fragmentation),
        "focus": float(focus),
        "concentration": float(concentration),
        "n_features": len(pos),
    }


# ===========================================================================
# 5. Epistemic holes — Vietoris-Rips H1 over the node embeddings (ripser)
# ===========================================================================
# Skip the (super-linear) Vietoris-Rips H1 above this many nodes. RAG retrieval
# scores a small top-k, so this never bites in practice; it only guards against a
# pathological call (~48s at N=1000) blocking a request. Override via env.
_H1_MAX_NODES = int(os.getenv("RAGINDEX_H1_MAX_NODES", "512"))


def embedding_holes(node_embeddings: np.ndarray) -> Optional[dict]:
    """
    Build a Vietoris-Rips complex on the node embeddings and read its 1-cycles.

    A persistent H1 loop = passages that relate pairwise but never close into a
    single coherent region: a candidate contradiction / missing connector.
    Returns None if ripser is unavailable or there are too few nodes.
    """
    n = int(node_embeddings.shape[0])
    if not _HAS_RIPSER or n < 4:
        return None
    if n > _H1_MAX_NODES:
        # Vietoris-Rips H1 is super-linear (~48s at N=1000). RAG retrieval scores
        # a small top-k, so skip H1 above this guard rather than block the request.
        return None
    X = node_embeddings / (np.linalg.norm(node_embeddings, axis=1, keepdims=True) + EPS)
    # Rows are points (nodes), columns are embedding dims — that is intentional, so
    # silence ripser's "more columns than rows" heuristic warning.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        dgms = _ripser(X, maxdim=1)["dgms"]
    h1 = dgms[1]
    holes = [(float(b), float(d)) for b, d in h1 if (d - b) > HOLE_PERSISTENCE_MIN]
    holes.sort(key=lambda bd: bd[1] - bd[0], reverse=True)
    return {
        "n_holes": len(holes),
        "max_persistence": (holes[0][1] - holes[0][0]) if holes else 0.0,
        "holes": holes[:5],
        "h0": [[float(b), float(d)] for b, d in dgms[0]],
        "h1": [[float(b), float(d)] for b, d in h1],
    }


# ===========================================================================
# 6. Sheaf consistency — cellular-sheaf Dirichlet energy (graph Laplacian)
# ===========================================================================
def sheaf_consistency(graph: nx.Graph, node_embeddings: np.ndarray) -> dict:
    """
    Treat the node embeddings as a 0-cochain on the tree and measure how well
    neighbouring stalks "glue" under identity restriction maps. This is the
    cellular-sheaf Dirichlet energy  E = sum_{(u,v) in E} || x_u - x_v ||^2 ,
    i.e. tr(X^T L X) with L the graph Laplacian.

      consistency : 1 - mean_edge_energy/4   (unit vectors => energy in [0,4])
      fiedler     : algebraic connectivity (robustness of the gluing)
    General (non-identity) restriction maps are a documented extension hook.
    """
    n = graph.number_of_nodes()
    if graph.number_of_edges() == 0 or n < 2:
        return {"consistency": 1.0, "fiedler": 0.0, "mean_edge_energy": 0.0}

    X = node_embeddings / (np.linalg.norm(node_embeddings, axis=1, keepdims=True) + EPS)
    L = nx.laplacian_matrix(graph, nodelist=range(n)).astype(float)
    energy = float(np.trace(X.T @ (L @ X)))           # = sum of ||x_u - x_v||^2
    mean_edge_energy = energy / graph.number_of_edges()
    consistency = 1.0 - min(max(mean_edge_energy / 4.0, 0.0), 1.0)

    try:
        fiedler = float(nx.algebraic_connectivity(graph, method="lanczos"))
    except Exception:
        fiedler = 0.0

    return {
        "consistency": consistency,
        "fiedler": fiedler,
        "mean_edge_energy": mean_edge_energy,
    }


# ===========================================================================
# 7. Stability — how far does the barcode move when the query is perturbed?
# ===========================================================================
def _bars_to_diagram(bars) -> np.ndarray:
    """Super-level bars (birth>=death) -> persim points (death, birth) with first<second."""
    pts = [(d, b) for (b, d, _) in bars if (b - d) > 1e-6]
    return np.asarray(pts, dtype=float) if pts else np.zeros((0, 2))


def _diagram_distance(d1: np.ndarray, d2: np.ndarray) -> float:
    """Bottleneck distance via persim when available; else a simple matched L-inf."""
    if _HAS_PERSIM:
        try:
            return float(_persim.bottleneck(d1, d2))
        except Exception:
            pass
    # Fallback: compare sorted persistence spectra (cheap, monotone surrogate).
    p1 = np.sort(d1[:, 1] - d1[:, 0])[::-1] if len(d1) else np.zeros(0)
    p2 = np.sort(d2[:, 1] - d2[:, 0])[::-1] if len(d2) else np.zeros(0)
    k = max(len(p1), len(p2))
    p1 = np.pad(p1, (0, k - len(p1)))
    p2 = np.pad(p2, (0, k - len(p2)))
    return float(np.max(np.abs(p1 - p2))) if k else 0.0


def perturbation_stability(
    graph: nx.Graph,
    node_embeddings: np.ndarray,
    query_vec: np.ndarray,
    base_bars,
    sigma: float = PERTURB_SIGMA,
    samples: int = PERTURB_SAMPLES,
    seed: int = 0,
) -> dict:
    """
    Re-embed a jittered query `samples` times, rebuild the barcode each time, and
    measure the mean bottleneck distance to the base barcode. Small movement =>
    the retrieval's *shape* is robust => high stability (persistence stability
    theorem in action).
    """
    rng = np.random.default_rng(seed)
    Mn = node_embeddings / (np.linalg.norm(node_embeddings, axis=1, keepdims=True) + EPS)
    base = _bars_to_diagram(base_bars)
    dists = []
    for _ in range(samples):
        q = query_vec + rng.normal(0.0, sigma, size=query_vec.shape) * np.linalg.norm(query_vec)
        qn = q / (np.linalg.norm(q) + EPS)
        cos = Mn @ qn
        lo, hi = float(cos.min()), float(cos.max())
        rel = (cos - lo) / (hi - lo) if hi - lo > EPS else np.ones_like(cos) * 0.5
        dists.append(_diagram_distance(base, _bars_to_diagram(tree_persistence(graph, rel))))
    mean_d = float(np.mean(dists)) if dists else 0.0
    return {"mean_distance": mean_d, "stability": float(max(0.0, 1.0 - mean_d))}


# ===========================================================================
# 8. Curvature — Forman-Ricci of the support region (redundancy vs. fragility)
# ===========================================================================
def forman_curvature(graph: nx.Graph, support_nodes: list[int]) -> dict:
    """
    Discrete Forman-Ricci curvature on the support sub-graph. For an edge (u,v):
        Ric_F = 4 - deg(u) - deg(v) + 3 * (#triangles on the edge)
    Strongly negative => a bottleneck the evidence funnels through (fragile);
    higher => redundant, multiply-supported (robust).
    """
    H = graph.subgraph(support_nodes)
    vals = []
    for u, v in H.edges():
        tri = len(list(nx.common_neighbors(H, u, v)))
        vals.append(4 - H.degree(u) - H.degree(v) + 3 * tri)
    if not vals:
        return {"mean": 0.0, "min": 0.0, "n_edges": 0}
    return {"mean": float(np.mean(vals)), "min": float(np.min(vals)), "n_edges": len(vals)}


# ===========================================================================
# 9. The report — assemble everything + a composite confidence
# ===========================================================================
@dataclass
class TopoConfidenceReport:
    query: str
    backend: str
    n_nodes: int
    relevance: np.ndarray
    raw_cosine: np.ndarray
    bars: list
    records: list
    betti: tuple
    scores: dict
    holes: Optional[dict]
    sheaf: dict
    stability: dict
    curvature: dict
    confidence: float
    signals: dict

    def summary(self) -> str:
        s = self.scores
        lines = [
            f"query        : {self.query!r}",
            f"backend      : {self.backend}   nodes: {self.n_nodes}",
            f"CONFIDENCE   : {self.confidence:.3f}   (composite, 0=diffuse .. 1=sharp)",
            "-" * 58,
            f"  margin        {s['margin']:.3f}   (gap between #1 and #2 region)",
            f"  dominance     {s['dominance']:.3f}   (share of persistence in #1)",
            f"  fragmentation {s['fragmentation']:.3f}   (mass outside #1; lower better)",
            f"  focus         {s['focus']:.3f}   (LCA depth / height; higher=localised)",
            f"  concentration {s['concentration']:.3f}   (1 - relevance entropy)",
            f"  n_features    {s['n_features']}",
            f"  consistency   {self.sheaf['consistency']:.3f}   (sheaf gluing; fiedler={self.sheaf['fiedler']:.3f})",
            f"  stability     {self.stability['stability']:.3f}   (1 - mean bottleneck move)",
            f"  curvature     mean={self.curvature['mean']:.2f} min={self.curvature['min']:.2f}",
        ]
        if self.holes is not None:
            lines.append(f"  holes (H1)    {self.holes['n_holes']}   max_life={self.holes['max_persistence']:.3f}")
        else:
            lines.append("  holes (H1)    n/a (ripser absent or <4 nodes)")
        return "\n".join(lines)


def _composite(signals: dict, weights: Optional[dict] = None) -> float:
    weights = weights or COMPOSITE_WEIGHTS
    num = sum(weights[k] * signals[k] for k in weights)
    den = sum(weights.values())
    return float(num / den) if den else 0.0


def topo_confidence_report(
    tree: dict,
    query: str,
    use_llm: Optional[bool] = None,
    perturb: bool = True,
    focus_tau: float = 0.6,
    node_embeddings: Optional[np.ndarray] = None,
    backend: Optional[str] = None,
) -> TopoConfidenceReport:
    """
    End-to-end: tree + query -> full topological confidence representation.

    Pass `node_embeddings` (+`backend`), e.g. from `embed_tree_nodes`, to score
    many queries against the same tree without re-embedding its nodes.
    """
    graph, records = build_graph(tree)
    node_texts = [f"{r.title}. {r.text}" for r in records]
    raw_cos, rel, backend, node_emb, q_vec = relevance_over_nodes(
        node_texts, query, use_llm=use_llm, node_embeddings=node_embeddings, backend=backend,
    )
    return _assemble_report(graph, records, rel, raw_cos, node_emb, q_vec,
                            backend=backend, query=query, perturb=perturb, focus_tau=focus_tau)


def _assemble_report(
    graph, records, rel, raw_cos, node_emb, q_vec, *,
    backend: str, query: str, perturb: bool = True, focus_tau: float = 0.6,
    holes_embeddings: Optional[np.ndarray] = None,
) -> TopoConfidenceReport:
    """Shared core: graph + relevance + embeddings -> a full report. Used by both
    the tree path (topo_confidence_report) and the embeddings path
    (report_from_embeddings)."""
    bars = tree_persistence(graph, rel)
    scores = scores_from_barcode(bars, records, rel, focus_tau=focus_tau)
    betti = betti_curve(bars)
    holes = embedding_holes(holes_embeddings if holes_embeddings is not None else node_emb)
    sheaf = sheaf_consistency(graph, node_emb)

    stability = (
        perturbation_stability(graph, node_emb, q_vec, bars)
        if perturb else {"mean_distance": 0.0, "stability": 1.0}
    )

    hot = [v for v in range(len(rel)) if rel[v] >= focus_tau] or [int(np.argmax(rel))]
    curvature = forman_curvature(graph, hot)

    signals = {
        "margin": scores["margin"],
        "dominance": scores["dominance"],
        "concentration": scores["concentration"],
        "focus": scores["focus"],
        "consistency": sheaf["consistency"],
        "stability": stability["stability"],
        "holes_penalty": 1.0 / (1.0 + (holes["n_holes"] if holes else 0)),
    }
    confidence = _composite(signals)

    return TopoConfidenceReport(
        query=query, backend=backend, n_nodes=len(records), relevance=rel, raw_cosine=raw_cos,
        bars=bars, records=records, betti=betti, scores=scores, holes=holes, sheaf=sheaf,
        stability=stability, curvature=curvature, confidence=confidence, signals=signals,
    )


def analyze_document(doc: dict, query: str, **kw) -> TopoConfidenceReport:
    """Convenience: build a tree from a dataset document, then report."""
    return topo_confidence_report(tree_from_document(doc), query, **kw)


def embed_tree_nodes(tree: dict, use_llm: Optional[bool] = None) -> tuple[np.ndarray, str]:
    """
    Embed every node of a tree ONCE, in build_graph() order, and return
    (embeddings, backend). Feed the result back into `topo_confidence_report`'s
    `node_embeddings=`/`backend=` to score many queries against one document
    cheaply (only the query is re-embedded per call).
    """
    _graph, records = build_graph(tree)
    texts = [(f"{r.title}. {r.text}")[:NODE_TEXT_CHARS] for r in records]
    from . import branch_index_socket as _bi  # lazy: embedding backend
    vecs, backend = _bi.embed_corpus(texts, use_llm=use_llm)
    return np.asarray(vecs, dtype=float), backend


def top_support(report: "TopoConfidenceReport", k: int = 3, exclude_root: bool = True) -> list[dict]:
    """
    Return the k most relevant nodes — the passages a RAG answer would rest on.
    Each item: {title, relevance, snippet}. This is the 'what was retrieved'.
    """
    idx = list(range(len(report.relevance)))
    if exclude_root and len(idx) > 1:
        idx = [i for i in idx if report.records[i].parent is not None] or idx
    ranked = sorted(idx, key=lambda i: float(report.relevance[i]), reverse=True)[:k]
    out = []
    for i in ranked:
        rec = report.records[i]
        snippet = " ".join((rec.text or "").split())[:240]
        out.append({"title": rec.title, "relevance": float(report.relevance[i]), "snippet": snippet})
    return out


def report_from_embeddings(
    query_embedding,
    passage_embeddings,
    texts: Optional[list[str]] = None,
    parents: Optional[list[Optional[int]]] = None,
    perturb: bool = True,
    focus_tau: float = 0.6,
    backend: str = "precomputed",
) -> TopoConfidenceReport:
    """
    Build a report straight from caller-provided embeddings — NO Ollama, dataset or
    PageIndex. This is the integration entry point: a host that already embedded
    its query and retrieved passages passes them in directly.

    passage_embeddings : (n, d) array, one row per retrieved passage.
    query_embedding    : (d,) array for the question.
    texts              : optional passage texts (used only for support snippets).
    parents            : optional tree structure (parent index per node; root=None;
                         a parent must appear before its children). If omitted we
                         hang every passage off a synthetic centroid root — the
                         right default for a flat top-k retrieval.
    """
    P = np.asarray(passage_embeddings, dtype=float)
    if P.ndim != 2 or P.shape[0] == 0:
        raise ValueError("passage_embeddings must be a non-empty (n, d) array")
    q = np.asarray(query_embedding, dtype=float).ravel()
    if q.shape[0] != P.shape[1]:
        raise ValueError(
            f"query_embedding dim {q.shape[0]} != passage_embeddings dim {P.shape[1]}"
        )
    n = P.shape[0]
    ptexts = list(texts) if texts is not None else [f"passage {i + 1}" for i in range(n)]

    # passage-only cosine -> the absolute grounding signal (excludes synthetic root)
    Pn = P / (np.linalg.norm(P, axis=1, keepdims=True) + EPS)
    qn = q / (np.linalg.norm(q) + EPS)
    pass_cos = Pn @ qn

    if parents is None:
        centroid = P.mean(axis=0, keepdims=True)
        M = np.vstack([centroid, P])
        node_texts = ["(retrieved context)"] + ptexts
        node_parents: list[Optional[int]] = [None] + [0] * n
    else:
        M = P
        node_texts = ptexts
        node_parents = list(parents)

    graph = nx.Graph()
    records: list[_NodeRec] = []
    for i, (t, par) in enumerate(zip(node_texts, node_parents)):
        graph.add_node(i)
        depth, p = 0, par
        while p is not None:
            depth += 1
            p = node_parents[p]
        records.append(_NodeRec(nid=i, title=str(t)[:80], text=str(t), depth=depth, parent=par))
        if par is not None:
            graph.add_edge(par, i)

    Mn = M / (np.linalg.norm(M, axis=1, keepdims=True) + EPS)
    cos_all = Mn @ qn
    lo, hi = float(cos_all.min()), float(cos_all.max())
    rel = (cos_all - lo) / (hi - lo) if hi - lo > EPS else np.ones_like(cos_all) * 0.5

    return _assemble_report(
        graph, records, rel, pass_cos, M, q, backend=backend, query="<embedded>",
        perturb=perturb, focus_tau=focus_tau, holes_embeddings=P,
    )
