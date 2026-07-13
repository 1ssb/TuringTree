"""
sockets/rag_metrics.py — PRODUCT-FACING confidence metrics for a RAG retrieval.

The topological apparatus (sockets/topo_confidence_socket.py) is the *engine*.
This module is the *dashboard*: it turns the theory into a tiny, coherent set of
metrics an engineering team can log per request, alert on, and gate with — with
no overlapping numbers and exactly one action per metric.

The contract (everything is 0..100, higher = healthier, plus one verdict):

    retrieval_confidence  (KPI)   the single headline number =
                                  topical_grounding (gate) x weighted shape score,
                                  so a dip is always explainable.

      topical_grounding           "Is the query even ABOUT this source?" (absolute,
                                  raw-cosine based; gates everything below).
      answer_localization         "Did the query hit ONE coherent region?"
                                  driver of: is there an answer locus at all.
      support_cohesion            "Is the support compact, not scattered?"
                                  driver of: re-retrieve / merge chunks.
      evidence_consistency        "Do the retrieved pieces agree?"
                                  driver of: contradiction / multi-hop flag.
      query_robustness            "Would a paraphrase change the answer?"
                                  driver of: ask-to-clarify / ambiguous query.

    verdict  in {ANSWER, REVIEW, ABSTAIN, ESCALATE}  + reason + primary_risk
                                  the one field your serving code branches on.

Cost note for the team: the first three drivers are FREE (pure post-processing of
the embedding scores you already computed). `query_robustness` costs ~8 extra
embedding calls (the stability probe) and can be turned off.

Calibrate before you trust the absolute number: fit isotonic/Platt regression on a
held-out set mapping the raw KPI -> P(answer correct) and pass it as `calibrator`.
The defaults below are sensible *starting* thresholds, not gospel.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Optional

from . import topo_confidence_socket as _tc


def _clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, x))))


# ---------------------------------------------------------------------------
# Tunable policy — thresholds + KPI weights. Calibrate these per deployment.
# ---------------------------------------------------------------------------
@dataclass
class MetricPolicy:
    # KPI banding (0..100).
    answer_at: float = 65.0          # >= this -> safe to serve
    review_at: float = 45.0          # [review_at, answer_at) -> serve with caveat
    # Per-driver minimums (0..100). Breaching any one forces at least REVIEW.
    localization_min: float = 55.0
    cohesion_min: float = 55.0
    consistency_min: float = 60.0
    robustness_min: float = 60.0
    # An H1 loop only counts as a contradiction if it lives at least this long.
    hole_life_flag: float = 0.10
    # Absolute topical-grounding gate (raw cosine -> [0,1] via sigmoid). These are
    # embedding-model specific; defaults tuned for qwen3-embedding:0.6b (on-topic
    # top-3 cosine ~0.7, off-topic ~0.25). Recalibrate if you change the model.
    grounding_center: float = 0.46
    grounding_scale: float = 0.08
    grounding_min: float = 50.0
    # KPI weights (must matter most -> least). Normalised internally.
    weights: dict = field(default_factory=lambda: {
        "answer_localization": 0.35,
        "support_cohesion": 0.25,
        "evidence_consistency": 0.25,
        "query_robustness": 0.15,
    })


_VERDICT_ACTION = {
    "ANSWER": "serve the answer",
    "REVIEW": "serve with a caveat or trigger re-retrieval",
    "ABSTAIN": "withhold; ask the user to rephrase or return 'not found'",
    "ESCALATE": "route to a human / surface the conflicting sources",
}


# ---------------------------------------------------------------------------
# Preset, range-based explanations. Each metric maps a 0..100 score to a short
# band label + a plain-English meaning, so the same number always reads the same
# way to every engineer. Bands are listed high -> low; the first whose floor the
# value meets wins. Floors line up with the MetricPolicy thresholds on purpose.
# ---------------------------------------------------------------------------
_BANDS: dict[str, list[tuple[float, str, str]]] = {
    "retrieval_confidence": [
        (80, "strong",
         "Strong, coherent support: the question maps cleanly onto a well-defined, "
         "internally-consistent region of the source. Safe to answer directly."),
        (65, "good",
         "Good support with minor noise: there is a clear answer region, but one signal "
         "is softer than ideal. Answer, but a quick sanity-check is worthwhile."),
        (45, "mixed",
         "Mixed signals: support exists but is partly diffuse, fragmented, or phrasing-"
         "sensitive. Serve with a caveat or re-retrieve before trusting it."),
        (0, "weak",
         "Weak support: the question does not land on any trustworthy region of this "
         "source. Prefer to abstain, ask the user to clarify, or widen retrieval."),
    ],
    "topical_grounding": [
        (70, "on-topic",
         "The question clearly matches this source — the best passages are strongly "
         "similar to it."),
        (40, "loosely-related",
         "The question is only loosely related to this source — even the best matches "
         "are weak, so any answer is a stretch."),
        (0, "off-topic",
         "The question doesn't match this source at all — nothing here is genuinely "
         "similar. The answer is elsewhere (or not in this corpus)."),
    ],
    "answer_localization": [
        (85, "sharp",
         "The question pinpoints a single, tightly-defined region — there is a clear "
         "place the answer lives."),
        (60, "fuzzy",
         "The question mostly localizes, but relevance bleeds into neighbouring material "
         "— the answer locus is somewhat fuzzy."),
        (0, "diffuse",
         "The question does not pick out any one region; relevance is spread thin — often "
         "a sign the answer isn't directly present here."),
    ],
    "support_cohesion": [
        (85, "compact",
         "All the relevant material clusters together — the evidence reads as one "
         "coherent passage."),
        (55, "split",
         "Support is split across a few separate clusters — answering may mean stitching "
         "distant pieces together (mild multi-hop)."),
        (0, "scattered",
         "Relevant material is scattered across many disconnected fragments — typical of "
         "an off-topic or poorly-matched query."),
    ],
    "evidence_consistency": [
        (80, "consistent",
         "The retrieved pieces agree with one another — no internal contradiction "
         "detected."),
        (55, "minor-tension",
         "Mostly consistent, with minor tension between pieces — usually harmless, "
         "occasionally worth a glance."),
        (0, "conflicting",
         "The pieces don't glue into one coherent story — a persistent contradiction loop "
         "suggests conflicting sources or a mixed-topic pull."),
    ],
    "query_robustness": [
        (80, "stable",
         "The result is stable — rephrasing the question would retrieve essentially the "
         "same material."),
        (55, "phrasing-sensitive",
         "Somewhat sensitive to wording — a reworded question might surface different "
         "material."),
        (0, "fragile",
         "Fragile — small wording changes flip what's retrieved; the query may be "
         "ambiguous or under-specified."),
    ],
}

# How to phrase each driver when it is the main concern (used in the synthesis).
_RISK_PHRASE = {
    "topical_grounding": "the question isn't really about this source",
    "answer_localization": "the question doesn't pinpoint a single region",
    "support_cohesion": "the supporting material is scattered",
    "evidence_consistency": "the retrieved pieces don't fully agree",
    "query_robustness": "the result is sensitive to how the question is phrased",
}


def band_for(metric: str, value: float) -> tuple[str, str]:
    """Return (label, explanation) for a metric's 0..100 value from its preset bands."""
    for floor, label, explanation in _BANDS[metric]:
        if value >= floor:
            return label, explanation
    return _BANDS[metric][-1][1], _BANDS[metric][-1][2]


@dataclass
class RagConfidenceMetrics:
    """The product card emitted for every retrieval."""
    retrieval_confidence: float          # 0..100 headline KPI
    confidence_band: str                 # HIGH / MEDIUM / LOW
    topical_grounding: float             # 0..100 absolute: is the query about this source?
    answer_localization: float           # 0..100 driver
    support_cohesion: float              # 0..100 driver
    evidence_consistency: float          # 0..100 driver
    query_robustness: float              # 0..100 driver
    verdict: str                         # ANSWER / REVIEW / ABSTAIN / ESCALATE
    verdict_action: str                  # what to actually do
    verdict_reason: str                  # human-readable "why"
    primary_risk: str                    # weakest driver (triage pointer)
    evidence: dict                       # raw underlying numbers for drill-down
    grounding_assessed: bool = True      # False on the offline lexical backend

    def to_dict(self) -> dict:
        """Flat, log-friendly key/values (drop straight into structured logs)."""
        d = {
            "retrieval_confidence": round(self.retrieval_confidence, 1),
            "confidence_band": self.confidence_band,
            "topical_grounding": round(self.topical_grounding, 1),
            "answer_localization": round(self.answer_localization, 1),
            "support_cohesion": round(self.support_cohesion, 1),
            "evidence_consistency": round(self.evidence_consistency, 1),
            "query_robustness": round(self.query_robustness, 1),
            "verdict": self.verdict,
            "verdict_action": self.verdict_action,
            "verdict_reason": self.verdict_reason,
            "primary_risk": self.primary_risk,
        }
        for name in ("retrieval_confidence", "topical_grounding", "answer_localization",
                     "support_cohesion", "evidence_consistency", "query_robustness"):
            d[f"{name}_band"] = band_for(name, getattr(self, name))[0]
        if not self.grounding_assessed:
            d["topical_grounding"] = None
            d["topical_grounding_band"] = "n/a"
        d["grounding_assessed"] = self.grounding_assessed
        d.update({f"evidence.{k}": v for k, v in self.evidence.items()})
        return d

    def explain(self) -> str:
        """A compact, human-readable confidence card for logs / review UIs."""
        star = {
            "topical_grounding": self.topical_grounding,
            "answer_localization": self.answer_localization,
            "support_cohesion": self.support_cohesion,
            "evidence_consistency": self.evidence_consistency,
            "query_robustness": self.query_robustness,
        }
        lines = [
            f"RETRIEVAL CONFIDENCE  {self.retrieval_confidence:5.1f}/100  [{self.confidence_band}]"
            f"   verdict: {self.verdict}  ->  {self.verdict_action}",
            "-" * 70,
        ]
        for name, val in star.items():
            if name == "topical_grounding" and not self.grounding_assessed:
                lines.append(f"  {name:22s}   n/a (offline backend)")
                continue
            mark = "  <-- primary risk" if name == self.primary_risk else ""
            lines.append(f"  {name:22s} {val:5.1f}{mark}")
        lines.append("-" * 70)
        lines.append(f"  reason: {self.verdict_reason}")
        return "\n".join(lines)

    def narrate(self) -> str:
        """
        A deep, range-based explanation: the verdict, the KPI in words, then every
        driver with its preset band meaning, and a one-line synthesis. This is the
        block to show a human when a question is asked.
        """
        kpi_label, kpi_expl = band_for("retrieval_confidence", self.retrieval_confidence)
        lines = [
            f"VERDICT: {self.verdict}   ->   {self.verdict_action}",
            f"Confidence {self.retrieval_confidence:.0f}/100 ({kpi_label}). {kpi_expl}",
            "",
            "Why — each signal, explained:",
        ]
        for name in ("topical_grounding", "answer_localization", "support_cohesion",
                     "evidence_consistency", "query_robustness"):
            if name == "topical_grounding" and not self.grounding_assessed:
                lines.append("  - topical grounding: n/a (offline lexical backend — not assessed)")
                lines.append("      Absolute topical match needs the semantic embedding model;")
                lines.append("      the offline fallback scores SHAPE only.")
                continue
            val = getattr(self, name)
            label, expl = band_for(name, val)
            flag = "  (main concern)" if name == self.primary_risk and self.verdict != "ANSWER" else ""
            lines.append(f"  - {name.replace('_', ' ')}: {val:.0f}/100 [{label}]{flag}")
            lines.append(f"      {expl}")
        lines.append("")
        lines.append(f"Bottom line: {self._bottom_line()}")
        return "\n".join(lines)

    def _bottom_line(self) -> str:
        """One-sentence synthesis that reconciles the KPI with the verdict."""
        risk = _RISK_PHRASE.get(self.primary_risk, "a weak signal")
        if self.verdict == "ANSWER":
            return ("Support is strong and coherent; you can answer directly from the "
                    "retrieved passages.")
        if self.verdict == "REVIEW":
            return (f"There is a usable answer region, but {risk}. Treat the answer as "
                    f"provisional — {self.verdict_action}.")
        if self.verdict == "ABSTAIN":
            return ("No trustworthy region of the source matches this question; better to "
                    "say so or ask for a rephrase than to guess.")
        return ("The evidence contains a genuine contradiction; surface the conflicting "
                "sources rather than silently picking one.")


# ---------------------------------------------------------------------------
# The mapping: topological report -> product metrics
# ---------------------------------------------------------------------------
def from_report(
    report: "_tc.TopoConfidenceReport",
    policy: Optional[MetricPolicy] = None,
    calibrator: Optional[Callable[[float], float]] = None,
) -> RagConfidenceMetrics:
    """
    Translate a TopoConfidenceReport into the four product drivers + KPI + verdict.

    `calibrator` (optional) maps the raw KPI fraction in [0,1] to a calibrated
    probability in [0,1]; fit it once on held-out (margin -> correctness) data.
    """
    policy = policy or MetricPolicy()
    s = report.scores

    # --- the four orthogonal, same-direction drivers (0..100) ---------------
    localization = 100.0 * _clip(0.6 * s["margin"] + 0.4 * s["dominance"])
    cohesion = 100.0 * _clip(1.0 / (1.0 + s["fragmentation"]))

    n_holes = report.holes["n_holes"] if report.holes else 0
    hole_life = report.holes["max_persistence"] if report.holes else 0.0
    holes_list = report.holes["holes"] if report.holes else []
    # Only loops that live past the significance bar count as contradictions; a
    # tiny loop is embedding noise and must NOT tank the consistency driver.
    n_significant = sum(1 for (b, d) in holes_list if (d - b) >= policy.hole_life_flag)
    significant_hole = n_significant > 0
    consistency = 100.0 * _clip(report.sheaf["consistency"] / (1.0 + n_significant))

    robustness = 100.0 * _clip(report.stability["stability"])

    drivers = {
        "answer_localization": localization,
        "support_cohesion": cohesion,
        "evidence_consistency": consistency,
        "query_robustness": robustness,
    }

    # --- absolute topical grounding: is the query even ABOUT this source? -----
    # min-max relevance ALWAYS manufactures a peak, so the SHAPE can look confident
    # for an off-topic query. The raw cosine does not lie: gate the KPI on it. The
    # lexical fallback's absolute cosines don't separate on/off-topic reliably, so
    # we only gate on real (semantic) embeddings and run shape-only otherwise.
    is_semantic = report.backend != "lexical-fallback"
    raw_sorted = sorted((float(x) for x in report.raw_cosine), reverse=True)
    top = raw_sorted[:3] or [0.0]
    grounding_raw = sum(top) / len(top)
    if is_semantic:
        grounding = 100.0 * _clip(_sigmoid((grounding_raw - policy.grounding_center) / policy.grounding_scale))
    else:
        grounding = 100.0  # no reliable absolute signal offline -> don't gate

    # --- headline KPI = topical_grounding GATE x weighted shape score ---------
    w = policy.weights
    wsum = sum(w.values()) or 1.0
    shape_kpi = sum(w[k] * drivers[k] for k in w) / wsum
    kpi = shape_kpi * (grounding / 100.0)
    if calibrator is not None:
        kpi = 100.0 * _clip(calibrator(kpi / 100.0))

    band = "HIGH" if kpi >= policy.answer_at else "MEDIUM" if kpi >= policy.review_at else "LOW"

    # --- primary risk = signal (incl. grounding) with the least head-room -----
    risk_vals = {"topical_grounding": grounding, **drivers}
    mins = {
        "topical_grounding": policy.grounding_min,
        "answer_localization": policy.localization_min,
        "support_cohesion": policy.cohesion_min,
        "evidence_consistency": policy.consistency_min,
        "query_robustness": policy.robustness_min,
    }
    primary_risk = min(risk_vals, key=lambda k: risk_vals[k] - mins[k])
    breached = [k for k in drivers if drivers[k] < mins[k]]

    # --- verdict policy ------------------------------------------------------
    if consistency < policy.consistency_min and significant_hole:
        verdict = "ESCALATE"
        reason = (f"evidence_consistency {consistency:.0f} < {policy.consistency_min:.0f} with a "
                  f"persistent contradiction loop (H1 life {hole_life:.2f}) -> conflicting sources")
    elif kpi < policy.review_at:
        verdict = "ABSTAIN"
        if grounding < policy.grounding_min:
            reason = (f"topical_grounding {grounding:.0f} < {policy.grounding_min:.0f}: the query isn't "
                      f"about this source (best-match cosine {grounding_raw:.2f})")
        else:
            reason = f"retrieval_confidence {kpi:.0f} < {policy.review_at:.0f}: no trustworthy support region"
    elif kpi < policy.answer_at or breached:
        verdict = "REVIEW"
        if breached:
            reason = (f"{primary_risk} {drivers[primary_risk]:.0f} < {mins[primary_risk]:.0f} "
                      f"(KPI {kpi:.0f})")
        else:
            reason = f"retrieval_confidence {kpi:.0f} in caveat band [{policy.review_at:.0f},{policy.answer_at:.0f})"
    else:
        verdict = "ANSWER"
        reason = f"retrieval_confidence {kpi:.0f} >= {policy.answer_at:.0f} and all drivers healthy"

    evidence = {
        "topical_match_cosine": round(grounding_raw, 3),
        "n_relevance_clusters": s["n_features"],
        "persistence_margin": round(s["margin"], 3),
        "dominance": round(s["dominance"], 3),
        "fragmentation": round(s["fragmentation"], 3),
        "focus_depth": round(s["focus"], 3),
        "sheaf_consistency": round(report.sheaf["consistency"], 3),
        "contradiction_loops": n_significant,
        "minor_loops": n_holes - n_significant,
        "contradiction_loop_life": round(hole_life, 3),
        "stability_move": round(report.stability["mean_distance"], 3),
        "embedding_backend": report.backend,
        "n_nodes": report.n_nodes,
    }

    return RagConfidenceMetrics(
        retrieval_confidence=kpi, confidence_band=band,
        topical_grounding=grounding,
        answer_localization=localization, support_cohesion=cohesion,
        evidence_consistency=consistency, query_robustness=robustness,
        verdict=verdict, verdict_action=_VERDICT_ACTION[verdict],
        verdict_reason=reason, primary_risk=primary_risk, evidence=evidence,
        grounding_assessed=is_semantic,
    )


def evaluate(
    tree: dict,
    query: str,
    policy: Optional[MetricPolicy] = None,
    calibrator: Optional[Callable[[float], float]] = None,
    **report_kwargs,
) -> RagConfidenceMetrics:
    """One-shot: run the topological analysis and return the product metrics."""
    report = _tc.topo_confidence_report(tree, query, **report_kwargs)
    return from_report(report, policy=policy, calibrator=calibrator)


def score(
    query_embedding,
    passage_embeddings,
    texts: Optional[list] = None,
    parents: Optional[list] = None,
    policy: Optional[MetricPolicy] = None,
    calibrator: Optional[Callable[[float], float]] = None,
    perturb: bool = True,
) -> RagConfidenceMetrics:
    """
    INTEGRATION ENTRY POINT — score a retrieval straight from embeddings.

    A host that already embedded its query and retrieved passages (it did, to do
    retrieval) passes them in here; gets back a RagConfidenceMetrics. No Ollama,
    no dataset, no PageIndex, no workspace config required at call time.

        m = rag_metrics.score(query_vec, passage_vecs, texts=passages)
        log(m.to_dict())          # the stable JSON contract for dashboards/gating
        if m.verdict == "ANSWER": ...
        print(m.narrate())        # the explained, range-based card for humans

    Parameters
    ----------
    query_embedding    : (d,) vector for the question.
    passage_embeddings : (n, d) matrix, one row per retrieved passage.
    texts              : optional passage texts (only used for support snippets).
    parents            : optional tree structure; omit for a flat top-k list.
    """
    report = _tc.report_from_embeddings(
        query_embedding, passage_embeddings, texts=texts, parents=parents, perturb=perturb,
    )
    return from_report(report, policy=policy, calibrator=calibrator)
