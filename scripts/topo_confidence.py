"""
scripts/topo_confidence.py — study the *topological confidence* of a retrieval.

It scores the SHAPE of the support a query lights up inside a document tree and
prints an interpretable confidence representation (barcode-derived scores, sheaf
consistency, stability, epistemic holes).

Two tree sources:
  --source dataset    (default) a fast 2-level tree: article -> its ~512-tok chunks.
                      Runs on the local embedding model only (no chat model needed).
  --source pageindex  a real hierarchical PageIndex tree (needs the chat model +
                      Ollama; this is the same path scripts/try_pipeline.py uses).

Examples
--------
    # On-topic vs off-topic on the same article (shows the score discriminates):
    python scripts/topo_confidence.py --contrast

    # Your own question against a real PageIndex tree:
    python scripts/topo_confidence.py --source pageindex --query "what is entropy?"

    # Force the offline lexical embedding backend (no Ollama needed at all):
    python scripts/topo_confidence.py --query "photosynthesis" --lexical
"""

import argparse
import sys
from pathlib import Path

# Windows consoles default to cp1252, which cannot encode some characters; force
# UTF-8 output where supported so prints never crash on encoding.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
except Exception:
    pass

# Make `import config` and `import sockets` work from any directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sockets import dataset_socket as ds  # noqa: E402
from sockets import pageindex_socket as pi  # noqa: E402
from sockets import topo_confidence_socket as tc  # noqa: E402
from sockets import rag_metrics as rm  # noqa: E402

OFF_TOPIC_QUERY = "how to bake sourdough bread at home"


def _pick_document(n_chunks: int, doc_index: int) -> dict:
    """Pull a sample of chunks, regroup into articles, and choose one document."""
    chunks = ds.sample(n_chunks)
    documents = list(ds.to_documents(chunks))
    if not documents:
        raise SystemExit("No documents produced from the dataset sample.")
    # doc_index < 0 => the article made of the most chunks (most interesting).
    if doc_index < 0:
        return max(documents, key=lambda d: len(d["chunks"]))
    return documents[min(doc_index, len(documents) - 1)]


def _use_llm_flag(args) -> bool | None:
    if args.llm:
        return True
    if args.lexical:
        return False
    return None  # auto-detect (uses Ollama embeddings if the server is up)


def _build_tree(doc: dict, source: str):
    if source == "pageindex":
        print("   building a real PageIndex tree (uses the local chat model) ...")
        return pi.build_tree_from_document(doc)
    return tc.tree_from_document(doc)


def main() -> None:
    ap = argparse.ArgumentParser(description="Topological confidence of a RAG retrieval.")
    ap.add_argument("--query", help="The question to score. Defaults to the article title.")
    ap.add_argument("--source", choices=["dataset", "pageindex"], default="dataset")
    ap.add_argument("--doc-index", type=int, default=-1,
                    help="Which grouped article to use (-1 = the one with most chunks).")
    ap.add_argument("--chunks", type=int, default=40, help="How many chunks to sample first.")
    ap.add_argument("--contrast", action="store_true",
                    help="Also score an off-topic query for comparison.")
    ap.add_argument("--metrics", action="store_true",
                    help="Print the product-facing confidence card (KPI + verdict) and JSON.")
    ap.add_argument("--no-perturb", action="store_true", help="Skip the stability probe (faster).")
    ap.add_argument("--llm", action="store_true", help="Force local Ollama embeddings.")
    ap.add_argument("--lexical", action="store_true", help="Force the offline lexical embeddings.")
    args = ap.parse_args()

    print("1) Selecting a document through the dataset socket ...")
    doc = _pick_document(args.chunks, args.doc_index)
    title = doc["title"] or "document"
    print(f"   article: {title!r}  ({len(doc['chunks'])} chunks, {len(doc['text'])} chars)")

    query = args.query or title
    print(f"2) Building the tree (source={args.source}) ...")
    tree = _build_tree(doc, args.source)

    print("3) Computing the topological confidence representation ...\n")
    report = tc.topo_confidence_report(
        tree, query, use_llm=_use_llm_flag(args), perturb=not args.no_perturb
    )
    print(report.summary())

    if args.metrics:
        import json
        metrics = rm.from_report(report)
        print("\n=== product confidence card ===")
        print(metrics.explain())
        print("\nstructured log line:")
        print(json.dumps(metrics.to_dict()))

    if args.contrast:
        print("\n--- contrast: off-topic query on the SAME tree ---")
        off = tc.topo_confidence_report(
            tree, OFF_TOPIC_QUERY, use_llm=_use_llm_flag(args), perturb=not args.no_perturb
        )
        print(off.summary())
        if args.metrics:
            print("\n--- off-topic product card ---")
            print(rm.from_report(off).explain())
        print("\n==> delta confidence (on-topic - off-topic): "
              f"{report.confidence - off.confidence:+.3f}")


if __name__ == "__main__":
    main()
