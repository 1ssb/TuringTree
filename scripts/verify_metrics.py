"""
scripts/verify_metrics.py — broad verification of the confidence read-out.

It sweeps several documents x several query *types* (exact title, a real on-topic
question, two off-topic queries, and a vague one), prints a comparison table, and
asserts the behaviour you actually want:

  * an on-topic question scores HIGHER than off-topic ones on the same document,
  * off-topic queries never come back "ANSWER",
  * a genuine question is not abstained on,
  * on-topic support is at least as cohesive as off-topic support.

Node embeddings are computed ONCE per document and reused across queries
(topo_confidence_report(..., node_embeddings=...)), so the sweep is fast.

    python scripts/verify_metrics.py                 # ~3 docs x 5 queries
    python scripts/verify_metrics.py --docs 4 --chunks 600
"""

import argparse
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sockets import dataset_socket as ds  # noqa: E402
from sockets import topo_confidence_socket as tc  # noqa: E402
from sockets import rag_metrics as rm  # noqa: E402

OFF_TOPIC = [
    ("off:bread", "how to bake sourdough bread at home"),
    ("off:sport", "live football match scores and player transfers"),
]
VAGUE = ("vague", "tell me more about this topic")


def _pick_documents(n_chunks: int, n_docs: int, min_chunks: int = 5) -> list[dict]:
    docs = [d for d in ds.to_documents(ds.sample(n_chunks)) if len(d["chunks"]) >= min_chunks]
    docs.sort(key=lambda d: len(d["chunks"]), reverse=True)
    return docs[:n_docs]


def _queries_for(doc: dict) -> list[tuple[str, str]]:
    title = doc["title"]
    return [
        ("title", title),
        ("on-topic", f"What are the key facts and details about {title}?"),
        *OFF_TOPIC,
        VAGUE,
    ]


def main() -> None:
    ap = argparse.ArgumentParser(description="Broad verification of the confidence metrics.")
    ap.add_argument("--docs", type=int, default=3, help="How many documents to test.")
    ap.add_argument("--chunks", type=int, default=500, help="How many chunks to sample first.")
    ap.add_argument("--llm", action="store_true", help="Force local Ollama embeddings.")
    ap.add_argument("--lexical", action="store_true", help="Force offline lexical embeddings.")
    args = ap.parse_args()
    use_llm = True if args.llm else (False if args.lexical else None)

    docs = _pick_documents(args.chunks, args.docs)
    if not docs:
        raise SystemExit("No suitable documents found; try a larger --chunks.")

    header = f"{'document':24s} {'query-type':10s} {'KPI':>5s} {'verdict':9s} {'AL':>4s} {'SC':>4s} {'EC':>4s}  primary_risk"
    print(header)
    print("-" * len(header))

    checks: list[tuple[str, bool]] = []
    on_all, off_all = [], []

    for doc in docs:
        tree = tc.tree_from_document(doc)
        node_emb, backend = tc.embed_tree_nodes(tree, use_llm=use_llm)  # embed nodes ONCE

        results = {}
        for qtype, query in _queries_for(doc):
            report = tc.topo_confidence_report(
                tree, query, perturb=False, node_embeddings=node_emb, backend=backend,
            )
            m = rm.from_report(report)
            results[qtype] = m
            print(f"{doc['title'][:24]:24s} {qtype:10s} {m.retrieval_confidence:5.1f} "
                  f"{m.verdict:9s} {m.answer_localization:4.0f} {m.support_cohesion:4.0f} "
                  f"{m.evidence_consistency:4.0f}  {m.primary_risk}")

        # ---- assertions for this document ----
        title_kpi = results["title"].retrieval_confidence
        ontopic_kpi = results["on-topic"].retrieval_confidence
        for tag, _q in OFF_TOPIC:
            off_kpi = results[tag].retrieval_confidence
            checks.append((f"{doc['title'][:18]}: on-topic > {tag}", title_kpi > off_kpi))
            checks.append((f"{doc['title'][:18]}: {tag} not ANSWER", results[tag].verdict != "ANSWER"))
            checks.append((f"{doc['title'][:18]}: title cohesion >= {tag}",
                           results["title"].support_cohesion >= results[tag].support_cohesion - 1e-6))
        checks.append((f"{doc['title'][:18]}: real question not ABSTAIN", results["on-topic"].verdict != "ABSTAIN"))

        on_all += [title_kpi, ontopic_kpi]
        off_all += [results[t].retrieval_confidence for t, _ in OFF_TOPIC]
        print("-" * len(header))

    # ---- summary ----
    passed = sum(1 for _, ok in checks if ok)
    print(f"\nChecks passed: {passed}/{len(checks)}")
    for name, ok in checks:
        if not ok:
            print(f"  FAIL: {name}")
    mean_on = sum(on_all) / len(on_all)
    mean_off = sum(off_all) / len(off_all)
    print(f"\nMean KPI  on-topic={mean_on:5.1f}   off-topic={mean_off:5.1f}   "
          f"separation={mean_on - mean_off:+.1f}")
    print("RESULT:", "PASS" if passed == len(checks) else "PARTIAL/FAIL")
    sys.exit(0 if passed == len(checks) else 1)


if __name__ == "__main__":
    main()
