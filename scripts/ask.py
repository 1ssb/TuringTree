"""
scripts/ask.py — the clean end-to-end entry point: ask a question, get the
retrieved support AND a fully-explained confidence read-out.

Flow:   question -> build/route a document tree -> retrieve the supporting
        passages -> score the retrieval topologically -> explain every score in
        plain English with preset, range-based meanings.

Examples
--------
    python scripts/ask.py "who funds and leads FasterCures?"
    python scripts/ask.py "what is an induced stem cell?" --chunks 400
    python scripts/ask.py "how do I bake bread?" --chunks 400        # watch it abstain
    python scripts/ask.py "what is entropy?" --source pageindex --json

By default the question is scored against ONE document (the largest article in a
sample, or --doc-index N). That is enough to demonstrate the confidence read-out;
the off-topic case correctly comes back low-confidence.
"""

import argparse
import json
import sys
import textwrap
from pathlib import Path

# Windows consoles default to cp1252; force UTF-8 so prints never crash.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sockets import dataset_socket as ds  # noqa: E402
from sockets import pageindex_socket as pi  # noqa: E402
from sockets import topo_confidence_socket as tc  # noqa: E402
from sockets import rag_metrics as rm  # noqa: E402


def _pick_document(n_chunks: int, doc_index: int) -> dict:
    documents = list(ds.to_documents(ds.sample(n_chunks)))
    if not documents:
        raise SystemExit("No documents produced from the dataset sample.")
    if doc_index < 0:
        return max(documents, key=lambda d: len(d["chunks"]))
    return documents[min(doc_index, len(documents) - 1)]


def _use_llm_flag(args):
    if args.llm:
        return True
    if args.lexical:
        return False
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description="Ask a question; get retrieved support + explained confidence.")
    ap.add_argument("query", help="The question to ask.")
    ap.add_argument("--source", choices=["dataset", "pageindex"], default="dataset")
    ap.add_argument("--doc-index", type=int, default=-1,
                    help="Which grouped article to query (-1 = the one with most chunks).")
    ap.add_argument("--chunks", type=int, default=120, help="How many chunks to sample first.")
    ap.add_argument("-k", "--support", type=int, default=3, help="How many supporting passages to show.")
    ap.add_argument("--no-support", action="store_true", help="Hide the retrieved passages.")
    ap.add_argument("--no-perturb", action="store_true", help="Skip the stability probe (faster).")
    ap.add_argument("--json", action="store_true", help="Also print the structured log line.")
    ap.add_argument("--llm", action="store_true", help="Force local Ollama embeddings.")
    ap.add_argument("--lexical", action="store_true", help="Force the offline lexical embeddings.")
    args = ap.parse_args()

    doc = _pick_document(args.chunks, args.doc_index)
    tree = doc if args.source == "dataset" else None
    if args.source == "pageindex":
        print("(building a real PageIndex tree with the local chat model ...)")
        tree = pi.build_tree_from_document(doc)
    else:
        tree = tc.tree_from_document(doc)

    report = tc.topo_confidence_report(tree, args.query, use_llm=_use_llm_flag(args),
                                       perturb=not args.no_perturb)
    metrics = rm.from_report(report)

    bar = "=" * 72
    print(bar)
    print(f"Q: {args.query}")
    print(f"   (scored against: {doc['title']!r} — {report.n_nodes} nodes, backend {report.backend})")
    print(bar)

    if not args.no_support:
        print("\nRetrieved support (what an answer would rest on):")
        for i, s in enumerate(tc.top_support(report, k=args.support), 1):
            print(f"  [{i}] ({s['relevance']:.2f}) {s['title']}")
            for line in textwrap.wrap(s["snippet"], width=78):
                print(f"      {line}")
        print()

    print(metrics.narrate())

    if args.json:
        print("\nstructured log line:")
        print(json.dumps(metrics.to_dict()))


if __name__ == "__main__":
    main()
