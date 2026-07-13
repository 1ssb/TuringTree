"""
scripts/try_pipeline.py — see the two sockets click together end to end.

Flow:
    dataset socket  ->  group chunks into one article  ->  PageIndex model socket

It pulls a handful of chunks from the Hugging Face science dataset, rebuilds the
article they came from, and asks PageIndex to turn it into a semantic
"table-of-contents" tree.

Prerequisites:
    1. Run scripts/setup.sh (installs deps, clones PageIndex, pulls the local
       Qwen models, and starts Ollama).
    2. That's it — everything runs locally on Ollama, so NO API keys are needed.

Run it:
    python scripts/try_pipeline.py
"""

import json
import sys
from pathlib import Path

# Make `import config` and `import sockets` work from any directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sockets import dataset_socket as ds  # noqa: E402
from sockets import pageindex_socket as pi  # noqa: E402


def main() -> None:
    print("1) Pulling a sample through the dataset socket ...")
    # Grab enough chunks that at least one complete article is present,
    # then group them back into whole documents.
    chunks = ds.sample(40)
    documents = list(ds.to_documents(chunks))

    # Pick the article made of the most chunks — it is the most interesting to index.
    doc = max(documents, key=lambda d: len(d["chunks"]))
    print(f"   chose article: {doc['title']!r} ({len(doc['chunks'])} chunks, {len(doc['text'])} chars)")

    print("2) Handing it to the PageIndex model socket to build a tree ...")
    tree = pi.build_tree_from_document(doc)

    print("3) PageIndex semantic tree:\n")
    print(json.dumps(tree, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
