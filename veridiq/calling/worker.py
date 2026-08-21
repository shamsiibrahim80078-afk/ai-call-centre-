"""Background worker for timed calling sessions — does not block FastAPI."""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Optional

logger = logging.getLogger("veridiq.calling.worker")

_lock = threading.Lock()
_thread: Optional[threading.Thread] = None
_stop = threading.Event()
_stats: dict[str, Any] = {
    "running": False,
    "ticks": 0,
    "last_tick_at": None,
    "last_error": None,
    "closed_total": 0,
    "agent_meet_started_total": 0,
}


def _interval_sec() -> float:
    return max(0.5, float(os.getenv("VERIDIQ_CALLING_WORKER_INTERVAL_SEC", "2") or "2"))


def _loop() -> None:
    from veridiq.calling.timed_calls import tick_active_sessions

    logger.info("calling timed-call worker started (interval=%.1fs)", _interval_sec())
    consecutive_errors = 0
    while not _stop.is_set():
        try:
            result = tick_active_sessions()
            agent_meet_started = 0
            try:
                from veridiq.calling.agent_meetings import tick_agent_meetings

                am = tick_agent_meetings()
                agent_meet_started = int(am.get("started_count") or 0)
            except Exception:  # noqa: BLE001
                logger.exception("agent-meetings tick failed")
            consecutive_errors = 0
            with _lock:
                _stats["ticks"] += 1
                _stats["last_tick_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                _stats["closed_total"] += int(result.get("closed_count") or 0)
                _stats["agent_meet_started_total"] = int(_stats.get("agent_meet_started_total") or 0) + agent_meet_started
                _stats["last_error"] = None
            # Steady cadence — never busy-spin
            _stop.wait(_interval_sec())
        except Exception as exc:  # noqa: BLE001
            consecutive_errors += 1
            logger.exception("calling worker tick failed (streak=%s)", consecutive_errors)
            with _lock:
                _stats["last_error"] = str(exc)[:300]
            # Exponential backoff on failure so FastAPI isn't starved by a tight error loop
            backoff = min(30.0, _interval_sec() * (2 ** min(consecutive_errors, 4)))
            _stop.wait(backoff)
    with _lock:
        _stats["running"] = False
    logger.info("calling timed-call worker stopped")


def start_calling_worker() -> dict[str, Any]:
    """Idempotent daemon start."""
    global _thread
    enabled = (os.getenv("VERIDIQ_CALLING_WORKER", "1") or "1").strip().lower()
    if enabled in {"0", "false", "no", "off"}:
        return {"ok": True, "status": "disabled", "message": "VERIDIQ_CALLING_WORKER is off."}
    with _lock:
        if _thread and _thread.is_alive():
            return {"ok": True, "status": "already_running", **dict(_stats)}
        _stop.clear()
        _stats["running"] = True
        _thread = threading.Thread(target=_loop, daemon=True, name="veridiq-calling-worker")
        _thread.start()
    return {"ok": True, "status": "started", **worker_status()}


def stop_calling_worker() -> dict[str, Any]:
    global _thread
    _stop.set()
    t = _thread
    if t and t.is_alive():
        t.join(timeout=5.0)
    with _lock:
        _stats["running"] = False
        _thread = None
    return {"ok": True, "status": "stopped", **worker_status()}


def worker_status() -> dict[str, Any]:
    with _lock:
        alive = bool(_thread and _thread.is_alive())
        return {
            "running": alive or bool(_stats.get("running")),
            "thread_alive": alive,
            "ticks": _stats.get("ticks", 0),
            "last_tick_at": _stats.get("last_tick_at"),
            "last_error": _stats.get("last_error"),
            "closed_total": _stats.get("closed_total", 0),
            "interval_sec": _interval_sec(),
        }
