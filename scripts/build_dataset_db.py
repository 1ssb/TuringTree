"""
scripts/build_dataset_db.py — build the local SQLite database from the sample.

Why this exists
---------------
The dataset socket reads a bundled parquet SAMPLE of the Wikipedia-science data.
This script lands that same sample in a small **SQLite** database (data/dataset.sqlite)
so you can *query* it — filter by category, run full-text search, count rows —
which is handy for tests and quick experiments. SQLite needs no server and is
part of Python's standard library, so nothing extra has to be installed.

The database lives in data/ (git-ignored) and is always regenerable, so it never
bloats the repo.

Examples
--------
    # Build the whole sample into the database
    python scripts/build_dataset_db.py

    # Only the first 2,000 chunks (fast, great for tests)
    python scripts/build_dataset_db.py --limit 2000

    # Only one category
    python scripts/build_dataset_db.py --category Natural_sciences

    # Quick sanity check after building
    python scripts/build_dataset_db.py --stats
"""

import argparse
import sys
from pathlib import Path

# Make `import config` and `import sockets` work no matter where this is run from.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402  (import after sys.path tweak, on purpose)
from sockets import dataset_db  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a local SQLite database from the dataset sample."
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Only store the first N chunks (default: all available).",
    )
    parser.add_argument(
        "--category", default=None,
        help="Only store chunks from this category (e.g. Natural_sciences).",
    )
    parser.add_argument(
        "--stats", action="store_true",
        help="After building, print row counts and the available categories.",
    )
    args = parser.parse_args()

    print(f">> Building SQLite database at {config.DATASET_DB_PATH} ...")
    written = dataset_db.build(limit=args.limit, category=args.category)
    print(f">> Wrote {written:,} chunks.")

    if args.stats:
        with dataset_db.connect() as conn:
            print(f">> Total rows: {dataset_db.count(conn):,}")
            cats = dataset_db.categories(conn)
            print(f">> Categories ({len(cats)}): {', '.join(cats) if cats else '(none)'}")


if __name__ == "__main__":
    main()
