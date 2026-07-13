"""
tests/test_score_api.py — rigorous tests for the deployable scoring package.

Covers the public integration surface `rag_metrics.score(query_emb, passage_emb)`:
  * CONTRACT      — return type, exact JSON key set, JSON-serialisability, ranges.
  * INVARIANTS    — on-topic answers, off-topic abstains, grounding monotonicity,
                    fragmentation detection, determinism, calibration, policy.
  * EDGE CASES    — n=1/2, identical passages, zero query, list inputs, dim
                    mismatch, empty input, a real parent tree, and a 300-passage
                    load test.

Runs two ways:
    pytest tests/test_score_api.py            # if pytest is installed
    python tests/test_score_api.py            # zero-dependency fallback runner

It uses ONLY synthetic embeddings (controlled cosine), so it needs no Ollama,
no dataset, and no network — exactly how the package is meant to be integrated.
"""

import json
import sys
import time
import types
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sockets import rag_metrics as rm  # noqa: E402

VERDICTS = {"ANSWER", "REVIEW", "ABSTAIN", "ESCALATE"}

# The frozen JSON contract the backend will depend on (semantic/precomputed path).
EXPECTED_KEYS = frozenset({
    "retrieval_confidence", "retrieval_confidence_band", "confidence_band",
    "topical_grounding", "topical_grounding_band",
    "answer_localization", "answer_localization_band",
    "support_cohesion", "support_cohesion_band",
    "evidence_consistency", "evidence_consistency_band",
    "query_robustness", "query_robustness_band",
    "verdict", "verdict_action", "verdict_reason", "primary_risk", "grounding_assessed",
    "evidence.topical_match_cosine", "evidence.n_relevance_clusters",
    "evidence.persistence_margin", "evidence.dominance", "evidence.fragmentation",
    "evidence.focus_depth", "evidence.sheaf_consistency", "evidence.contradiction_loops",
    "evidence.minor_loops", "evidence.contradiction_loop_life", "evidence.stability_move",
    "evidence.embedding_backend", "evidence.n_nodes",
})


# ---------------------------------------------------------------------------
# Synthetic embeddings with a CONTROLLED cosine to the query.
# passage = c*u + sqrt(1-c^2)*v, with v ⟂ u  =>  cosine(u, passage) = c exactly.
# ---------------------------------------------------------------------------
def make_case(target_cos: float, n: int = 8, d: int = 64, spread: float = 0.03, seed: int = 0):
    rng = np.random.default_rng(seed)
    u = rng.normal(size=d)
    u /= np.linalg.norm(u)
    rows = []
    for _ in range(n):
        v = rng.normal(size=d)
        v -= (v @ u) * u                      # make v orthogonal to u
        v /= (np.linalg.norm(v) + 1e-12)
        c = float(np.clip(target_cos + rng.normal(0, spread), -0.98, 0.98))
        rows.append(c * u + np.sqrt(max(0.0, 1 - c * c)) * v)
    return u, np.asarray(rows)


# ===========================================================================
# CONTRACT
# ===========================================================================
def test_returns_metrics_object():
    m = rm.score(*make_case(0.7))
    assert isinstance(m, rm.RagConfidenceMetrics)
    assert m.verdict in VERDICTS
    assert m.verdict_action and m.verdict_reason and m.primary_risk


def test_to_dict_contract_keys():
    d = rm.score(*make_case(0.7)).to_dict()
    missing = EXPECTED_KEYS - d.keys()
    extra = d.keys() - EXPECTED_KEYS
    assert not missing and not extra, f"missing={missing} extra={extra}"


def test_to_dict_is_json_serialisable():
    s = json.dumps(rm.score(*make_case(0.6)).to_dict())
    round_trip = json.loads(s)
    assert round_trip["verdict"] in VERDICTS


def test_all_scores_in_range():
    m = rm.score(*make_case(0.55))
    for v in (m.retrieval_confidence, m.topical_grounding, m.answer_localization,
              m.support_cohesion, m.evidence_consistency, m.query_robustness):
        assert 0.0 <= float(v) <= 100.0


def test_narrate_nonempty():
    text = rm.score(*make_case(0.7)).narrate()
    assert "VERDICT" in text and "Bottom line" in text


def test_bands_are_valid_labels():
    d = rm.score(*make_case(0.7)).to_dict()
    assert d["retrieval_confidence_band"] in {"strong", "good", "mixed", "weak"}
    assert d["topical_grounding_band"] in {"on-topic", "loosely-related", "off-topic"}


# ===========================================================================
# INVARIANTS
# ===========================================================================
def test_on_topic_answers():
    m = rm.score(*make_case(0.72, n=10))
    assert m.verdict == "ANSWER", (m.verdict, m.retrieval_confidence, m.topical_grounding)
    assert m.topical_grounding > 70


def test_off_topic_abstains():
    m = rm.score(*make_case(0.18, n=10))
    assert m.verdict == "ABSTAIN", (m.verdict, m.retrieval_confidence, m.topical_grounding)
    assert m.topical_grounding < 40
    assert m.primary_risk == "topical_grounding"


def test_grounding_is_monotone_in_cosine():
    gs = [rm.score(*make_case(c, n=10, seed=3)).topical_grounding for c in (0.1, 0.3, 0.5, 0.7)]
    assert all(gs[i] <= gs[i + 1] + 1e-6 for i in range(len(gs) - 1)), gs


def test_kpi_separation_on_vs_off():
    on = rm.score(*make_case(0.72, n=10)).retrieval_confidence
    off = rm.score(*make_case(0.18, n=10)).retrieval_confidence
    assert on - off > 40, (on, off)


def test_fragmentation_detected_in_split_tree():
    # Two relevant branches joined ONLY through a low-relevance root -> the support
    # is genuinely split, so cohesion must drop and >=2 relevance clusters appear.
    u = make_case(0.7, n=1, d=64)[0]
    emb = np.array([
        _vec_at_cos(u, 0.15, 10),                             # 0: low-relevance connector (root)
        _vec_at_cos(u, 0.70, 11), _vec_at_cos(u, 0.70, 12),   # branch A: nodes 1, 2
        _vec_at_cos(u, 0.70, 13), _vec_at_cos(u, 0.70, 14),   # branch B: nodes 3, 4
    ])
    parents = [None, 0, 1, 0, 3]
    m = rm.score(u, emb, parents=parents)
    assert m.support_cohesion < 90, m.support_cohesion
    assert m.to_dict()["evidence.n_relevance_clusters"] >= 2


def test_determinism_with_perturbation():
    q, P = make_case(0.6)
    a = rm.score(q, P, perturb=True).to_dict()
    b = rm.score(q, P, perturb=True).to_dict()
    assert a == b


def test_perturb_false_sets_full_robustness():
    m = rm.score(*make_case(0.6), perturb=False)
    assert abs(m.query_robustness - 100.0) < 1e-6


def test_custom_policy_changes_verdict():
    strict = rm.MetricPolicy(answer_at=99.0)
    m = rm.score(*make_case(0.72, n=10), policy=strict)
    assert m.verdict == "REVIEW", (m.verdict, m.retrieval_confidence)


def test_calibrator_is_applied():
    m = rm.score(*make_case(0.6), calibrator=lambda _x: 0.9)
    assert abs(m.retrieval_confidence - 90.0) < 1e-6


def test_grounding_assessed_true_on_precomputed():
    assert rm.score(*make_case(0.7)).to_dict()["grounding_assessed"] is True


# ===========================================================================
# EDGE CASES
# ===========================================================================
def test_single_passage():
    assert rm.score(*make_case(0.7, n=1)).verdict in VERDICTS


def test_two_passages():
    assert rm.score(*make_case(0.7, n=2)).verdict in VERDICTS


def test_identical_passages_do_not_crash():
    u = make_case(0.7, n=1)[0]
    p = 0.7 * u + np.sqrt(0.51) * _orthogonal(u)
    P = np.tile(p, (5, 1))
    assert rm.score(u, P).verdict in VERDICTS


def test_zero_query_vector():
    _, P = make_case(0.5, d=64)
    m = rm.score(np.zeros(64), P)
    assert m.verdict in VERDICTS               # degenerate but must not crash


def test_python_list_inputs_are_accepted():
    q, P = make_case(0.7, n=6)
    m = rm.score(q.tolist(), P.tolist())
    assert m.verdict in VERDICTS


def test_dim_mismatch_raises_valueerror():
    try:
        rm.score(np.zeros(32), np.zeros((5, 64)))
    except ValueError:
        return
    raise AssertionError("expected ValueError on dim mismatch")


def test_empty_passages_raises_valueerror():
    try:
        rm.score(np.zeros(8), np.zeros((0, 8)))
    except ValueError:
        return
    raise AssertionError("expected ValueError on empty passages")


def test_real_parent_tree():
    u, base = make_case(0.7, n=5, d=64)
    parents = [None, 0, 0, 1, 1]               # 0=root, (1,2) under 0, (3,4) under 1
    m = rm.score(u, base, parents=parents)
    assert m.verdict in VERDICTS


def test_large_n_load():
    q, P = make_case(0.6, n=300, d=48)
    t0 = time.time()
    m = rm.score(q, P, perturb=False)
    assert m.verdict in VERDICTS
    assert time.time() - t0 < 30.0, "300-passage scoring should be well under 30s"


def _orthogonal(u: np.ndarray) -> np.ndarray:
    rng = np.random.default_rng(7)
    v = rng.normal(size=u.shape[0])
    v -= (v @ u) * u
    return v / (np.linalg.norm(v) + 1e-12)


def _vec_at_cos(u: np.ndarray, c: float, seed: int) -> np.ndarray:
    """A unit vector with exactly cosine `c` to the unit vector `u`."""
    rng = np.random.default_rng(seed)
    v = rng.normal(size=u.shape[0])
    v -= (v @ u) * u
    v /= (np.linalg.norm(v) + 1e-12)
    return c * u + np.sqrt(max(0.0, 1 - c * c)) * v


# ---------------------------------------------------------------------------
# Zero-dependency runner (used when pytest is not installed).
# ---------------------------------------------------------------------------
def _run() -> int:
    g = globals()
    tests = sorted(n for n in g if n.startswith("test_") and isinstance(g[n], types.FunctionType))
    passed, fails = 0, []
    for name in tests:
        try:
            g[name]()
            passed += 1
            print(f"  PASS  {name}")
        except Exception as exc:  # noqa: BLE001 - test runner reports everything
            fails.append((name, repr(exc)))
            print(f"  FAIL  {name}: {exc!r}")
    print(f"\n{passed}/{len(tests)} passed")
    for name, err in fails:
        print(f"  FAIL {name}: {err}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(_run())
