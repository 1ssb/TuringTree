"""
scripts/index_branches.py — command-line tool for the branch-index socket.

Examples
--------
    # See every origin branch the workspace knows about
    python scripts/index_branches.py list

    # Build the semantic index (offline by default; add --llm for local Ollama embeddings)
    python scripts/index_branches.py build
    python scripts/index_branches.py build --llm

    # Ask which branch is about something, in plain English
    python scripts/index_branches.py search "markdown table of contents"
"""

import argparse
import sys
from pathlib import Path

# Make `import config` and `import sockets` work no matter where this is run from.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402  (import after sys.path tweak, on purpose)
from sockets import branch_index_socket as bi  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Semantically index PageIndex's git branches.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List all origin/* branches.")

    build = sub.add_parser("build", help="Build the semantic branch index.")
    build.add_argument(
        "--llm",
        action="store_true",
        help="Force real embeddings via local Ollama. Default auto-detects if it's running.",
    )

    search = sub.add_parser("search", help="Search branches by meaning.")
    search.add_argument("query", help="What you are looking for, in plain English.")
    search.add_argument("-k", type=int, default=5, help="How many results to show.")

    args = parser.parse_args()

    if args.command == "list":
        for branch in bi.list_origin_branches():
            print(branch)

    elif args.command == "build":
        # --llm forces LLM embeddings; without it we auto-detect (None).
        index = bi.build_branch_index(use_llm=True if args.llm else None)
        print(f"Indexed {len(index['branches'])} branches using backend '{index['model']}'.")
        print(f"Saved to: {config.BRANCH_INDEX_PATH}")

    elif args.command == "search":
        results = bi.search_branches(args.query, k=args.k)
        print(f"Top {len(results)} branches for: {args.query!r}\n")
        for score, branch, profile in results:
            # Show the first line of the profile as a quick hint of what it is.
            hint = profile.splitlines()[0] if profile else ""
            print(f"  {score:.3f}  {branch}")
            print(f"          {hint}")


if __name__ == "__main__":
    main()
