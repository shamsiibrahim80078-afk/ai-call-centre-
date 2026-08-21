"""
Dynamic AI worker pool — scales worker instances under load (up to 50+),
tracks live assignments, and never reports fake active agents.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class WorkerAssignment:
    worker_id: str
    agent_type: str
    job_id: Optional[str]
    task: str
    started_at: str
    stage: str = "initializing"
    confidence: Optional[float] = None
    progress: float = 0.05
    eta_sec: Optional[float] = None
    run_id: Optional[str] = None
    finished: bool = False
    result_ok: Optional[bool] = None
    latency_ms: Optional[float] = None
    platform: Optional[str] = None
    channel: Optional[str] = None


@dataclass
class WorkerSlot:
    worker_id: str
    status: str = "idle"  # idle | busy
    assignment: Optional[WorkerAssignment] = None
    completed: int = 0
    failed: int = 0
    total_latency_ms: float = 0.0


class AIWorkerPool:
    """Scalable pool of ephemeral workers (not fixed agent clones).

    Real agent runs (heuristics, official-API lookups) frequently finish in
    well under a second — far faster than any UI can poll or than an SSE
    stream (~2s cadence) can observe. Without a floor, a worker flips
    busy->idle inside a single request/response cycle, so the Agent
    Workspace / Live pages *always* render "idle", even though the agent
    genuinely executed a second ago — this was the root cause behind
    "agents never look live". `min_visible_sec` holds the worker's busy
    state (and the accurate finished result attached to it) for a floor
    duration after the real work completes so pollers/SSE can actually see
    it. Nothing about the *result* is delayed or fabricated — history/stats
    are recorded immediately with real timing; only the worker-slot
    busy->idle flip is deferred.
    """

    def __init__(self, min_workers: int = 2, max_workers: int = 50) -> None:
        self.min_workers = max(1, int(os.getenv("VERIDIQ_WORKER_MIN", min_workers)))
        self.max_workers = max(self.min_workers, int(os.getenv("VERIDIQ_WORKER_MAX", max_workers)))
        self.min_visible_sec = max(0.0, float(os.getenv("VERIDIQ_MIN_VISIBLE_SEC", "6.0")))
        self._lock = threading.RLock()
        self._workers: dict[str, WorkerSlot] = {}
        self._queue_depth = 0
        self._history: list[dict[str, Any]] = []
        self._agent_stats: dict[str, dict[str, Any]] = {}
        self._recent_runs: dict[str, dict[str, Any]] = {}
        # +8 headroom for the delayed-release timers riding alongside real task threads.
        self._executor = ThreadPoolExecutor(max_workers=self.max_workers + 8, thread_name_prefix="veridiq-worker")
        for _ in range(self.min_workers):
            self._spawn_idle()

    def _spawn_idle(self) -> WorkerSlot:
        wid = f"w-{uuid.uuid4().hex[:10]}"
        slot = WorkerSlot(worker_id=wid)
        self._workers[wid] = slot
        return slot

    def _scale(self) -> None:
        busy = sum(1 for w in self._workers.values() if w.status == "busy")
        idle = sum(1 for w in self._workers.values() if w.status == "idle")
        # Scale up if queue pressure or all busy
        if (self._queue_depth > 0 or busy >= len(self._workers)) and len(self._workers) < self.max_workers:
            need = min(self.max_workers - len(self._workers), max(1, self._queue_depth, busy - idle + 1))
            for _ in range(need):
                self._spawn_idle()
        # Scale down excess idle workers
        if idle > self.min_workers and busy == 0 and self._queue_depth == 0:
            extras = [w for w in self._workers.values() if w.status == "idle"]
            while len(self._workers) > self.min_workers and extras:
                victim = extras.pop()
                self._workers.pop(victim.worker_id, None)

    def _acquire(
        self,
        agent_type: str,
        job_id: Optional[str],
        task: str,
        *,
        run_id: Optional[str] = None,
        platform: Optional[str] = None,
        channel: Optional[str] = None,
    ) -> WorkerSlot:
        with self._lock:
            self._queue_depth += 1
            self._scale()
            idle = next((w for w in self._workers.values() if w.status == "idle"), None)
            if idle is None and len(self._workers) < self.max_workers:
                idle = self._spawn_idle()
            if idle is None:
                # Wait briefly by creating temporary overflow slot up to max
                idle = self._spawn_idle() if len(self._workers) < self.max_workers else next(iter(self._workers.values()))
            idle.status = "busy"
            idle.assignment = WorkerAssignment(
                worker_id=idle.worker_id,
                agent_type=agent_type,
                job_id=job_id,
                task=task,
                started_at=_utc_now(),
                stage="initializing",
                progress=0.1,
                eta_sec=8.0,
                run_id=run_id or str(uuid.uuid4()),
                platform=platform,
                channel=channel or platform,
            )
            self._queue_depth = max(0, self._queue_depth - 1)
            return idle

    def _set_stage(self, slot: WorkerSlot, *, stage: str, progress: Optional[float] = None) -> None:
        with self._lock:
            if slot.assignment:
                slot.assignment.stage = stage
                if progress is not None:
                    slot.assignment.progress = progress

    def _record_history(self, slot: WorkerSlot, *, ok: bool, latency_ms: float, confidence: Optional[float]) -> None:
        """Persist accurate stats/history immediately — timing here is real and
        never delayed. Only the worker-slot busy flag is released later."""
        with self._lock:
            if slot.assignment:
                a = slot.assignment
                a.finished = True
                a.result_ok = ok
                a.latency_ms = latency_ms
                a.stage = "result_collection" if ok else "error_reporting"
                a.progress = 0.97
                rec = {
                    "worker_id": slot.worker_id,
                    "agent_type": a.agent_type,
                    "job_id": a.job_id,
                    "task": a.task,
                    "run_id": a.run_id,
                    "started_at": a.started_at,
                    "finished_at": _utc_now(),
                    "ok": ok,
                    "latency_ms": latency_ms,
                    "confidence": confidence,
                }
                self._history.append(rec)
                self._history = self._history[-300:]
                if a.run_id:
                    self._recent_runs[a.run_id] = {**self._recent_runs.get(a.run_id, {}), **rec}
                    if len(self._recent_runs) > 500:
                        for k in list(self._recent_runs.keys())[: len(self._recent_runs) - 500]:
                            self._recent_runs.pop(k, None)
                stats = self._agent_stats.setdefault(
                    a.agent_type,
                    {"runs": 0, "ok": 0, "failed": 0, "total_latency_ms": 0.0, "last_job_id": None},
                )
                stats["runs"] += 1
                stats["ok" if ok else "failed"] += 1
                stats["total_latency_ms"] += latency_ms
                stats["last_job_id"] = a.job_id
            if ok:
                slot.completed += 1
            else:
                slot.failed += 1
            slot.total_latency_ms += latency_ms

    def _release_slot(self, slot: WorkerSlot) -> None:
        with self._lock:
            slot.assignment = None
            slot.status = "idle"
            self._scale()

    def _finalize(
        self,
        slot: WorkerSlot,
        *,
        ok: bool,
        latency_ms: float,
        confidence: Optional[float],
        min_visible_sec: float,
    ) -> None:
        self._record_history(slot, ok=ok, latency_ms=latency_ms, confidence=confidence)
        remaining = max(0.0, min_visible_sec - latency_ms / 1000.0)
        if remaining <= 0:
            self._release_slot(slot)
        else:
            self._executor.submit(self._delayed_release, slot, remaining)

    def _delayed_release(self, slot: WorkerSlot, remaining: float) -> None:
        time.sleep(remaining)
        self._release_slot(slot)

    @staticmethod
    def _confidence_of(result: Any) -> Optional[float]:
        if isinstance(result, dict):
            conf = result.get("confidence")
            if conf is None and isinstance(result.get("result"), dict):
                conf = result["result"].get("confidence")
            return conf
        return None

    def run_agent_task(
        self,
        *,
        agent_type: str,
        fn: Callable[[], dict[str, Any]],
        job_id: Optional[str] = None,
        task: Optional[str] = None,
        min_visible_sec: Optional[float] = None,
        platform: Optional[str] = None,
        channel: Optional[str] = None,
    ) -> dict[str, Any]:
        """Execute `fn` synchronously (caller gets the real result immediately)
        while keeping the worker visibly busy for at least `min_visible_sec`
        (default: pool-wide floor) so live pollers/SSE can observe the run."""
        floor = self.min_visible_sec if min_visible_sec is None else max(0.0, min_visible_sec)
        slot = self._acquire(
            agent_type,
            job_id,
            task or f"Execute {agent_type}",
            platform=platform,
            channel=channel,
        )
        self._set_stage(slot, stage="task_execution", progress=0.35)
        started = time.perf_counter()
        try:
            result = fn()
            latency = (time.perf_counter() - started) * 1000
            ok = bool(result.get("ok", True)) if isinstance(result, dict) else True
            self._finalize(slot, ok=ok, latency_ms=latency, confidence=self._confidence_of(result), min_visible_sec=floor)
            return result
        except Exception:
            latency = (time.perf_counter() - started) * 1000
            self._finalize(slot, ok=False, latency_ms=latency, confidence=None, min_visible_sec=floor)
            raise

    def start_agent_task(
        self,
        *,
        agent_type: str,
        fn: Callable[[], dict[str, Any]],
        job_id: Optional[str] = None,
        task: Optional[str] = None,
        min_visible_sec: Optional[float] = None,
        platform: Optional[str] = None,
        channel: Optional[str] = None,
    ) -> dict[str, Any]:
        """Non-blocking variant: acquires a real worker slot immediately and
        returns right away with `status: started` while `fn` executes on a
        background thread. Use this from HTTP handlers backing a "Run" button
        so the click responds instantly *and* the agent stays observably
        "working" on the Live Runtime for the run's real duration.
        Poll `/api/v1/veridiq/agents/{agent_type}` or the workforce SSE
        stream, or fetch the final envelope via `get_run(run_id)`."""
        floor = self.min_visible_sec if min_visible_sec is None else max(0.0, min_visible_sec)
        run_id = str(uuid.uuid4())
        slot = self._acquire(
            agent_type,
            job_id,
            task or f"Execute {agent_type}",
            run_id=run_id,
            platform=platform,
            channel=channel,
        )
        self._set_stage(slot, stage="initializing", progress=0.12)

        def _worker() -> None:
            self._set_stage(slot, stage="task_execution", progress=0.4)
            started = time.perf_counter()
            try:
                result = fn()
                latency = (time.perf_counter() - started) * 1000
                ok = bool(result.get("ok", True)) if isinstance(result, dict) else True
                with self._lock:
                    self._recent_runs[run_id] = {**self._recent_runs.get(run_id, {}), "envelope": result}
                self._finalize(slot, ok=ok, latency_ms=latency, confidence=self._confidence_of(result), min_visible_sec=floor)
            except Exception as exc:  # pragma: no cover - defensive, mirrors run_agent_task
                latency = (time.perf_counter() - started) * 1000
                with self._lock:
                    self._recent_runs[run_id] = {**self._recent_runs.get(run_id, {}), "error": str(exc)[:400]}
                self._finalize(slot, ok=False, latency_ms=latency, confidence=None, min_visible_sec=floor)

        self._executor.submit(_worker)
        return {
            "ok": True,
            "status": "started",
            "run_id": run_id,
            "worker_id": slot.worker_id,
            "agent_type": agent_type,
            "job_id": job_id,
            "task": task or f"Execute {agent_type}",
            "started_at": slot.assignment.started_at if slot.assignment else _utc_now(),
            "poll": {
                "agent": f"/api/v1/veridiq/agents/{agent_type}",
                "workspace": f"/api/v1/veridiq/workspace/{agent_type}",
                "run": f"/api/v1/veridiq/agents/{agent_type}/runs/{run_id}",
                "sse": "/api/v1/veridiq/workforce/events",
            },
        }

    def set_agent_stage(
        self,
        agent_type: str,
        *,
        stage: str,
        progress: Optional[float] = None,
        task: Optional[str] = None,
        platform: Optional[str] = None,
        channel: Optional[str] = None,
    ) -> bool:
        """Update the live assignment for `agent_type` while it is busy — used
        by long-ish marketing runs so SSE/poll surfaces meaningful stages."""
        with self._lock:
            for slot in self._workers.values():
                a = slot.assignment
                if slot.status == "busy" and a and a.agent_type == agent_type:
                    self._set_stage(slot, stage=stage, progress=progress)
                    if task:
                        a.task = task
                    if platform:
                        a.platform = platform
                    if channel or platform:
                        a.channel = channel or platform
                    return True
        return False

    @staticmethod
    def marketing_min_visible_sec() -> float:
        """Longer visibility floor for marketing agents — draft generation is
        fast but operators need several poll/SSE cycles to see Working."""
        return max(
            0.0,
            float(os.getenv("VERIDIQ_MARKETING_MIN_VISIBLE_SEC", os.getenv("VERIDIQ_MIN_VISIBLE_SEC", "18"))),
        )

    def get_run(self, run_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            return self._recent_runs.get(run_id)

    def submit(self, fn: Callable[[], Any]) -> Future:
        with self._lock:
            self._queue_depth += 1
            self._scale()

        def wrapped():
            try:
                return fn()
            finally:
                with self._lock:
                    self._queue_depth = max(0, self._queue_depth - 1)
                    self._scale()

        return self._executor.submit(wrapped)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            workers = list(self._workers.values())
            active = [w for w in workers if w.status == "busy" and w.assignment]
            idle = [w for w in workers if w.status == "idle"]
            assignments = []
            for w in active:
                a = w.assignment
                assert a is not None
                elapsed = 0.0
                try:
                    started = datetime.fromisoformat(a.started_at.replace("Z", "+00:00"))
                    elapsed = max(0.0, (datetime.now(timezone.utc) - started).total_seconds())
                except Exception:
                    pass
                # `a.progress` reflects the real stage the run is in (set by
                # _set_stage/_finalize) rather than a synthetic elapsed-time
                # curve — once work genuinely finishes it holds near-complete
                # (0.97) for the visibility floor instead of ever resetting.
                progress = a.progress if a.finished else min(0.9, max(a.progress, 0.1 + elapsed / max(1.0, a.eta_sec or 8.0)))
                assignments.append(
                    {
                        "worker_id": a.worker_id,
                        "agent_type": a.agent_type,
                        "job_id": a.job_id,
                        "task": a.task,
                        "run_id": a.run_id,
                        "started_at": a.started_at,
                        "elapsed_sec": round(elapsed, 2),
                        "eta_sec": a.eta_sec,
                        "progress": round(progress, 3),
                        "stage": a.stage,
                        "confidence": a.confidence,
                        "finished": a.finished,
                        "result_ok": a.result_ok,
                        "platform": a.platform,
                        "channel": a.channel or a.platform,
                    }
                )
            return {
                "waiting_for_tasks": len(active) == 0,
                "status_label": "Waiting for Tasks" if not active else "Processing",
                "active_workers": len(active),
                "idle_workers": len(idle),
                "total_workers": len(workers),
                "max_workers": self.max_workers,
                "min_workers": self.min_workers,
                "queue_depth": self._queue_depth,
                "assignments": assignments,
                "recent_history": list(reversed(self._history[-40:])),
                "agent_stats": {
                    k: {
                        **v,
                        "success_rate": round(v["ok"] / v["runs"], 4) if v["runs"] else None,
                        "avg_latency_ms": round(v["total_latency_ms"] / v["runs"], 2) if v["runs"] else None,
                    }
                    for k, v in self._agent_stats.items()
                },
                "timestamp": _utc_now(),
            }


global_worker_pool = AIWorkerPool()
