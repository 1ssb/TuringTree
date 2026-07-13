"""
scripts/make_dataset_sample.py — build the consolidated dataset sample.

Why this exists
---------------
We want the project to be **self-contained**: clone the repo and everything you
need is right here, including the data. But the full Hugging Face dataset is
~1.5 GB / 1.2M rows — far too big to commit.

So instead we stream the first N rows of the dataset and save them to ONE small
local parquet file, committed directly with Git (small enough to need no LFS). The
dataset socket automatically prefers this local file (see sockets/dataset_socket.py),
so the whole pipeline runs OFFLINE with no Hugging Face download.

Re-run any time to regenerate or resize the sample:
    python scripts/make_dataset_sample.py                  # uses config default
    RAGINDEX_SAMPLE_ROWS=50000 python scripts/make_dataset_sample.py

Note: the data is derived from Wikipedia (CC BY-SA). Keep that attribution if
you redistribute the sample.
"""

import sys
from pathlib import Path

# Make `import config` work no matter where this script is run from.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402  (import after sys.path tweak, on purpose)


def main() -> None:
    # Imported lazily so this file can be opened/inspected without the deps.
    from datasets import load_dataset
    import pyarrow as pa
    import pyarrow.parquet as pq

    n = config.DATASET_SAMPLE_ROWS
    columns = [
        config.DATASET_TEXT_COLUMN,
        config.DATASET_TITLE_COLUMN,
        config.DATASET_CATEGORY_COLUMN,
        config.DATASET_URL_COLUMN,
    ]

    print(f">> Streaming {n:,} rows from {config.DATASET_ID} (split={config.DATASET_SPLIT}) ...")
    stream = load_dataset(config.DATASET_ID, split=config.DATASET_SPLIT, streaming=True)

    # Collect the chosen columns row by row (streaming = no full download).
    collected = {col: [] for col in columns}
    for i, row in enumerate(stream):
        if i >= n:
            break
        for col in columns:
            collected[col].append(row.get(col))
        if (i + 1) % 5000 == 0:
            print(f"   ... {i + 1:,} rows")

    # Write a single compressed parquet file (zstd = good ratio, widely supported).
    config.DATASET_DIR.mkdir(parents=True, exist_ok=True)
    table = pa.table(collected)
    pq.write_table(table, config.LOCAL_DATASET_PATH, compression="zstd")

    size_mb = config.LOCAL_DATASET_PATH.stat().st_size / 1e6
    print(f">> Wrote {table.num_rows:,} rows -> {config.LOCAL_DATASET_PATH} ({size_mb:.1f} MB)")
    print(">> The dataset socket will now read this local file instead of streaming.")


if __name__ == "__main__":
    main()
