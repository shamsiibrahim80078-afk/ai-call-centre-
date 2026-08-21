"""Job progress event bus for SSE streaming."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Iterator, Optional


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class JobEventBus:
    def __init__(self, maxlen: int = 500) -> None:
        self._lock = threading.Lock()
        self._events: dict[str, deque[dict[str, Any]]] = defaultdict(lambda: deque(maxlen=maxlen))
        self._subscribers: dict[str, list[threading.Event]] = defaultdict(list)
        self._completed: set[str] = set()

    def emit(self, job_id: str, stage: str, message: str = "", **extra: Any) -> dict[str, Any]:
        event = {
            "job_id": job_id,
            "stage": stage,
            "message": message,
            "timestamp": _utc_now_iso(),
            **extra,
        }
        with self._lock:
            self._events[job_id].append(event)
            if stage in {"completed", "failed"}:
                self._completed.add(job_id)
            waiters = list(self._subscribers.get(job_id, []))
        for w in waiters:
            w.set()
        return event

    def history(self, job_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._events.get(job_id, []))

    def is_done(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._completed

    def stream(self, job_id: str, *, poll_timeout: float = 0.5) -> Iterator[dict[str, Any]]:
        idx = 0
        while True:
            with self._lock:
                events = list(self._events.get(job_id, []))
                done = job_id in self._completed
            while idx < len(events):
                yield events[idx]
                idx += 1
            if done and idx >= len(events):
                break
            waiter = threading.Event()
            with self._lock:
                self._subscribers[job_id].append(waiter)
            waiter.wait(timeout=poll_timeout)
            with self._lock:
                subs = self._subscribers.get(job_id, [])
                if waiter in subs:
                    subs.remove(waiter)


global_job_events = JobEventBus()
