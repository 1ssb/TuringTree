"""Unit tests for the background-job ETA estimation (backend/app/jobs.py)."""

from __future__ import annotations

import time

from backend.app import jobs


def test_estimate_running_no_progress_uses_learned_rate():
    # Nothing finished yet (e.g. a single long document): elapsed rises and the
    # ETA is derived from the learned per-document rate, so the bar still moves.
    job = {
        "status": "running",
        "started": time.time() - 5,
        "finished": None,
        "progress": {"done": 0, "total": 1},
    }
    elapsed, eta = jobs.estimate(job)
    assert elapsed >= 4.5
    assert eta is not None and eta >= 0.0


def test_estimate_running_with_progress_uses_measured_rate():
    # One of three docs done in ~10s -> ~10s/doc, two remaining -> ~20s ETA.
    job = {
        "status": "running",
        "started": time.time() - 10,
        "finished": None,
        "progress": {"done": 1, "total": 3},
    }
    _, eta = jobs.estimate(job)
    assert eta is not None and 15.0 <= eta <= 25.0


def test_estimate_finished_reports_zero_eta_and_total_elapsed():
    started = 1000.0
    job = {
        "status": "done",
        "started": started,
        "finished": started + 42.0,
        "progress": {"done": 2, "total": 2},
    }
    elapsed, eta = jobs.estimate(job)
    assert eta == 0.0
    assert abs(elapsed - 42.0) < 1e-6


def test_record_per_unit_moves_the_learned_average():
    before = jobs._learned_per_unit()
    jobs._record_per_unit(before + 40.0)  # a slow build nudges the average up
    after = jobs._learned_per_unit()
    assert after > before
