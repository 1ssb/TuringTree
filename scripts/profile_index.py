"""
scripts/profile_index.py — stage-level latency profiler for the index builder.

Answers the question "why does building the index take so long, and where is the
time actually spent?" by instrumenting the REAL pipeline
(pageindex_socket.build_tree_from_markdown_text -> page_index_md.md_to_tree) and
timing every stage plus every individual LLM call.

It does NOT touch the production code: it monkeypatches litellm + a few
page_index_md stage functions purely to time them, then runs an ordinary tree
build on a synthetic-but-realistic multi-section document.

Run (with the project's virtual environment active):
    # Windows (PowerShell):  .venv\Scripts\Activate.ps1
    # macOS / Linux:         source .venv/bin/activate
    python scripts/profile_index.py                 # ~10 sections (default)
    python scripts/profile_index.py --sections 16 --words 180
    python scripts/profile_index.py --sections 6 12 20   # scaling sweep

Needs Ollama running with the chat model pulled (same as a real build).
"""

from __future__ import annotations

import argparse
import statistics
import sys
import threading
import time
from pathlib import Path

# Make the workspace root importable (config, sockets, ...).
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from sockets import pageindex_socket  # noqa: E402

# Put vendor/PageIndex on sys.path so we can import + patch its internals.
pageindex_socket.ensure_importable()

import litellm  # noqa: E402
from pageindex import page_index_md as M  # noqa: E402

# ── instrumentation state ─────────────────────────────────────────────────────

_LOCK = threading.Lock()
LLM_CALLS: list[dict] = []      # one row per model call
STAGES: dict[str, float] = {}   # wall time per stage
TOK = {"n": 0, "dur": 0.0}      # token_counter aggregate


def _record(kind: str, t0: float, t1: float, out: str) -> None:
    with _LOCK:
        LLM_CALLS.append({"kind": kind, "t0": t0, "t1": t1, "dur": t1 - t0,
                          "out_chars": len(out or "")})


# Patch the two LLM entry points litellm exposes (attribute lookups happen at
# call time, so PageIndex's `litellm.acompletion(...)` picks these up).
_orig_acompletion = litellm.acompletion
_orig_completion = litellm.completion
_orig_tok = litellm.token_counter


async def _timed_acompletion(*a, **k):
    t0 = time.perf_counter()
    r = await _orig_acompletion(*a, **k)
    t1 = time.perf_counter()
    _record("node_summary", t0, t1, r.choices[0].message.content)
    return r


def _timed_completion(*a, **k):
    t0 = time.perf_counter()
    r = _orig_completion(*a, **k)
    t1 = time.perf_counter()
    _record("doc_description", t0, t1, r.choices[0].message.content)
    return r


def _timed_tok(*a, **k):
    t0 = time.perf_counter()
    r = _orig_tok(*a, **k)
    TOK["n"] += 1
    TOK["dur"] += time.perf_counter() - t0
    return r


litellm.acompletion = _timed_acompletion
litellm.completion = _timed_completion
litellm.token_counter = _timed_tok


def _wrap_stage(name: str, is_async: bool = False) -> None:
    """Time a page_index_md function in place, accumulating into STAGES[name]."""
    orig = getattr(M, name)
    if is_async:
        async def w(*a, **k):
            t0 = time.perf_counter()
            r = await orig(*a, **k)
            STAGES[name] = STAGES.get(name, 0.0) + (time.perf_counter() - t0)
            return r
    else:
        def w(*a, **k):
            t0 = time.perf_counter()
            r = orig(*a, **k)
            STAGES[name] = STAGES.get(name, 0.0) + (time.perf_counter() - t0)
            return r
    setattr(M, name, w)


for _fn in ("extract_nodes_from_markdown", "extract_node_text_content",
            "build_tree_from_nodes", "write_node_id", "format_structure",
            "generate_doc_description"):
    _wrap_stage(_fn)
_wrap_stage("generate_summaries_for_structure_md", is_async=True)


# ── synthetic document ────────────────────────────────────────────────────────

_LOREM = (
    "Photosynthesis is the biochemical process by which green plants, algae, and "
    "some bacteria convert light energy into chemical energy stored in glucose. "
    "The light dependent reactions occur in the thylakoid membranes where water is "
    "split and oxygen is released as a by product. Electrons travel through a chain "
    "of carriers, pumping protons across the membrane and driving the synthesis of "
    "adenosine triphosphate. The Calvin cycle then fixes carbon dioxide in the "
    "stroma using the energy carriers produced earlier. Rubisco catalyses the first "
    "major step, joining carbon dioxide to ribulose bisphosphate. Environmental "
    "factors such as temperature, light intensity, and carbon dioxide concentration "
    "all influence the overall rate at which a leaf can fix carbon. "
)


def make_doc(sections: int, words: int) -> tuple[str, str]:
    """Return (title, markdown) with `sections` H2 blocks of ~`words` words each."""
    base = _LOREM.split()
    body = ["A self contained overview used purely to profile the tree builder.\n"]
    for i in range(1, sections + 1):
        body.append(f"\n## Section {i}: mechanism and limiting factors\n")
        chunk: list[str] = []
        while len(chunk) < words:
            chunk.extend(base)
        body.append(" ".join(chunk[:words]) + "\n")
    return f"Profiling Document ({sections} sections)", "\n".join(body)


# ── reporting ─────────────────────────────────────────────────────────────────

def _max_overlap(intervals: list[tuple[float, float]]) -> int:
    """Peak number of simultaneously in-flight calls (1 == fully serialized)."""
    events: list[tuple[float, int]] = []
    for t0, t1 in intervals:
        events.append((t0, 1))
        events.append((t1, -1))
    events.sort()
    cur = peak = 0
    for _, d in events:
        cur += d
        peak = max(peak, cur)
    return peak


def profile_once(sections: int, words: int) -> None:
    LLM_CALLS.clear()
    STAGES.clear()
    TOK["n"] = 0
    TOK["dur"] = 0.0

    title, md = make_doc(sections, words)
    doc_tokens = litellm.token_counter(model=config.LLM_MODEL, text=md)

    print(f"\n{'='*72}")
    print(f"DOC: {sections} sections, ~{words} words/section, "
          f"~{doc_tokens} tokens total, model={config.LLM_MODEL}")
    print('='*72)

    t0 = time.perf_counter()
    tree = pageindex_socket.build_tree_from_markdown_text(md, title=title)
    wall = time.perf_counter() - t0

    summaries = [c for c in LLM_CALLS if c["kind"] == "node_summary"]
    docdesc = [c for c in LLM_CALLS if c["kind"] == "doc_description"]
    n_nodes = len(M.structure_to_list(tree["structure"]))

    print(f"\nTOTAL build wall time .................. {wall:8.2f} s")
    print(f"  tree nodes (headings) ................ {n_nodes:8d}")
    print(f"  LLM calls total ...................... {len(LLM_CALLS):8d}"
          f"   ({len(summaries)} node-summaries + {len(docdesc)} doc-description)")

    print("\n--- stage breakdown (wall time) ------------------------------------")
    order = ["extract_nodes_from_markdown", "extract_node_text_content",
             "build_tree_from_nodes", "write_node_id", "format_structure",
             "generate_summaries_for_structure_md", "generate_doc_description"]
    for name in order:
        secs = STAGES.get(name, 0.0)
        pct = 100 * secs / wall if wall else 0
        bar = "#" * int(pct / 2)
        print(f"  {name:38s} {secs:7.2f} s  {pct:5.1f}%  {bar}")
    overhead = wall - sum(STAGES.get(n, 0.0) for n in order)
    print(f"  {'(asyncio.run + temp file + misc)':38s} {overhead:7.2f} s  "
          f"{100*overhead/wall if wall else 0:5.1f}%")

    print("\n--- token counting (litellm.token_counter) -------------------------")
    print(f"  calls ................................ {TOK['n']:8d}")
    print(f"  total time ........................... {TOK['dur']:8.2f} s"
          f"   ({100*TOK['dur']/wall if wall else 0:.1f}% of wall)")

    if summaries:
        durs = sorted(c["dur"] for c in summaries)
        outs = [c["out_chars"] for c in summaries]
        span0 = min(c["t0"] for c in summaries)
        span1 = max(c["t1"] for c in summaries)
        wall_phase = span1 - span0
        busy = sum(durs)
        overlap = _max_overlap([(c["t0"], c["t1"]) for c in summaries])
        print("\n--- node-summary LLM calls (the fan-out) ---------------------------")
        print(f"  count ................................ {len(summaries):8d}")
        print(f"  per-call  min/median/max ............. "
              f"{durs[0]:.2f} / {statistics.median(durs):.2f} / {durs[-1]:.2f} s")
        print(f"  sum of call time (serial-equivalent) . {busy:8.2f} s")
        print(f"  wall time of the fan-out phase ....... {wall_phase:8.2f} s")
        print(f"  effective concurrency (sum/wall) ..... {busy/wall_phase if wall_phase else 0:8.2f} x")
        print(f"  peak simultaneous in-flight calls .... {overlap:8d}"
              f"   (1 == Ollama is serializing)")
        print(f"  avg summary output ................... {statistics.mean(outs):.0f} chars")

    if docdesc:
        print("\n--- doc-description LLM call (1 per tree, SYNCHRONOUS) --------------")
        print(f"  duration ............................. {docdesc[0]['dur']:8.2f} s")

    # Per-tree instance pressure headline.
    llm_wall = STAGES.get("generate_summaries_for_structure_md", 0.0) + \
        STAGES.get("generate_doc_description", 0.0)
    print("\n--- where the pressure concentrates --------------------------------")
    print(f"  LLM stages are {100*llm_wall/wall if wall else 0:.1f}% of the whole build")
    print(f"  pure-Python (parse+tree+format+tokcount) is "
          f"{100*(wall-llm_wall)/wall if wall else 0:.1f}%")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sections", type=int, nargs="+", default=[10],
                    help="section count(s); pass several for a scaling sweep")
    ap.add_argument("--words", type=int, default=150,
                    help="approx words per section (drives section token size)")
    args = ap.parse_args()
    for s in args.sections:
        profile_once(s, args.words)


if __name__ == "__main__":
    main()
