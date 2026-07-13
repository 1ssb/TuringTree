"""
The "sockets" package — the seamless integration layer of the workspace.

Why "sockets"?  Just like a wall socket lets you plug in any appliance without
rewiring the house, each module here is a small, self-contained *connector* with
a simple, documented interface. You plug components together through them:

    dataset_socket      ->  pulls data IN  from the Hugging Face dataset
    dataset_db          ->  lands the dataset sample in a local SQLite database
    pageindex_socket    ->  plugs the PageIndex "model" INTO the workspace
    branch_index_socket ->  semantically indexes the model's git branches
    ingest_socket       ->  indexes a dropped file + records its provenance

Keeping every external system behind a thin socket means the rest of the code
never has to know the messy details of `datasets`, `litellm`, or `git`.
"""

from . import dataset_socket
from . import dataset_db
from . import pageindex_socket
from . import branch_index_socket
from . import ingest_socket
from . import topo_confidence_socket
from . import rag_metrics

__all__ = [
    "dataset_socket",
    "dataset_db",
    "pageindex_socket",
    "branch_index_socket",
    "ingest_socket",
    "topo_confidence_socket",
    "rag_metrics",
]
