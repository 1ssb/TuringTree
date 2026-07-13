"""
backend/app/jobs.py — a tiny in-process job registry for long-running work.

Index builds are ~100% local LLM inference and can take a minute, so running
them inside the request would tie up a worker thread and leave the client
waiting with no progress. This module runs a build in a background daemon thread
and exposes its status/progress so the API can return immediately and the
frontend can poll.

It is deliberately a *single-process* registry (no Celery/Redis): the app is a
local, single-user tool. For a multi-worker deployment, swap this for a real
queue — the router only depends on :func:`run` and :func:`get`.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Callable, Optional

_LOCK = threading.Lock()
_JOBS: dict[str, dict] = {}
_MAX_JOBS = 50  # keep the registry bounded; oldest finished jobs are evicted

# Rolling estimate of seconds-per-document, learned across builds in this process
# so the ETA is honest even for a single-document build (where a done/total bar
# would otherwise jump straight from 0% to 100%). Resets when the process restarts.
_DEFAULT_PER_UNIT = 30.0
_AVG_LOCK = threading.Lock()
_avg_per_unit = _DEFAULT_PER_UNIT
_avg_samples = 0


def _learned_per_unit() -> float:
    with _AVG_LOCK:
        return _avg_per_unit


def _record_per_unit(seconds: float) -> None:
    """Fold a finished build's per-document time into the rolling average."""
    global _avg_per_unit, _avg_samples
    if seconds <= 0:
        return
    with _AVG_LOCK:
        _avg_samples += 1
        k = min(_avg_samples, 8)  # cap so one slow build can't dominate forever
        _avg_per_unit += (seconds - _avg_per_unit) / k


def estimate(job: dict) -> tuple[float, Optional[float]]:
    """
    Compute (elapsed_seconds, eta_seconds) for a job AT READ TIME from the wall
    clock, so a long single-document build still reports a steadily rising elapsed
    and a falling ETA between the discrete per-document progress updates.
    """
    started = job.get("started") or time.time()
    if job.get("status") != "running":
        finished = job.get("finished") or time.time()
        return max(0.0, finished - started), 0.0
    elapsed = max(0.0, time.time() - started)
    prog = job.get("progress") or {}
    done, total = int(prog.get("done", 0)), int(prog.get("total", 0))
    if done > 0:
        # Real measured rate once at least one document has finished.
        eta = max(0.0, (elapsed / done) * (total - done))
    else:
        # Nothing finished yet: estimate from the learned per-document rate.
        eta = max(0.0, _learned_per_unit() * max(total, 1) - elapsed)
    return elapsed, eta


def _prune_locked() -> None:
    if len(_JOBS) <= _MAX_JOBS:
        return
    finished = sorted(
        (j for j in _JOBS.values() if j["status"] in ("done", "error")),
        key=lambda j: j.get("finished") or 0.0,
    )
    for job in finished[: len(_JOBS) - _MAX_JOBS]:
        _JOBS.pop(job["id"], None)


def get(job_id: str) -> Optional[dict]:
    """Return a shallow copy of the job record, or None if unknown."""
    with _LOCK:
        job = _JOBS.get(job_id)
        return dict(job) if job else None


def _update(job_id: str, **fields: Any) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job:
            job.update(fields)


def run(target: Callable[[Callable[[int, int], None]], Any]) -> str:
    """
    Start ``target(on_progress)`` in a daemon thread and return a job id.

    ``target`` receives an ``on_progress(done, total)`` callback and returns the
    job result (stored on the record). Exceptions are captured into ``error`` so
    the status endpoint can surface them.
    """
    job_id = uuid.uuid4().hex
    with _LOCK:
        _JOBS[job_id] = {
            "id": job_id,
            "status": "running",
            "progress": {"done": 0, "total": 0},
            "result": None,
            "error": None,
            "started": time.time(),
            "finished": None,
        }
        _prune_locked()

    def on_progress(done: int, total: int) -> None:
        _update(job_id, progress={"done": int(done), "total": int(total)})

    def worker() -> None:
        try:
            result = target(on_progress)
            now = time.time()
            with _LOCK:
                job = _JOBS.get(job_id)
                started = (job or {}).get("started") or now
                total = ((job or {}).get("progress") or {}).get("total") or 0
            if total > 0:
                _record_per_unit((now - started) / total)
            _update(job_id, status="done", result=result, finished=now)
        except Exception as exc:  # surfaced via the status endpoint
            _update(job_id, status="error", error=str(exc), finished=time.time())

    threading.Thread(target=worker, name=f"ragindex-job-{job_id}", daemon=True).start()
    return job_id
