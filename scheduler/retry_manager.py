"""
Retry Manager — exponential/backoff-aware retries for failed scheduled tasks.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from database import db_session, initialize_database  # noqa: E402
from scheduler.event_bus import EventBus, global_event_bus  # noqa: E402
from scheduler.task_queue import TaskQueue, global_task_queue  # noqa: E402
from scheduler.task_scheduler import TaskScheduler, global_scheduler  # noqa: E402
from utils.system_health import bump_orchestration, collect_full_health, record_warning  # noqa: E402


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class RetryManager:
    """Retry failed jobs while respecting max_retries and emitting orchestration events."""

    def __init__(
        self,
        scheduler: Optional[TaskScheduler] = None,
        task_queue: Optional[TaskQueue] = None,
        event_bus: Optional[EventBus] = None,
    ) -> None:
        initialize_database()
        self.scheduler = scheduler or global_scheduler
        self.queue = task_queue or global_task_queue
        self.bus = event_bus or global_event_bus

    def can_retry(self, task: dict[str, Any]) -> bool:
        if task.get("status") != "failed":
            return False
        return int(task.get("attempts") or 0) < int(task.get("max_retries") or 0)

    def retry_task(self, task_uuid: str) -> dict[str, Any]:
        tasks = self.scheduler.list_tasks(limit=1000)
        match = next((t for t in tasks if t["task_uuid"] == task_uuid), None)
        if match is None:
            # Fetch directly
            with db_session() as conn:
                row = conn.execute(
                    "SELECT * FROM scheduled_tasks WHERE task_uuid = ?",
                    (task_uuid,),
                ).fetchone()
            if row is None:
                raise LookupError(f"Task '{task_uuid}' not found.")
            match = self.scheduler._row_to_dict(row)

        if not self.can_retry(match):
            raise RuntimeError(
                f"Task '{task_uuid}' cannot be retried "
                f"(status={match.get('status')} attempts={match.get('attempts')}/"
                f"{match.get('max_retries')})."
            )

        retried = self.scheduler.retry_failed_task(task_uuid)
        self.bus.emit(
            "task.retried",
            {
                "task_uuid": task_uuid,
                "attempts": retried.get("attempts"),
                "max_retries": retried.get("max_retries"),
            },
            source="retry_manager",
        )
        bump_orchestration("retries", 1)
        collect_full_health()
        return retried

    def retry_all_failed(self, *, limit: int = 50) -> list[dict[str, Any]]:
        failed = self.scheduler.list_tasks(status="failed", limit=limit)
        results: list[dict[str, Any]] = []
        for task in failed:
            if not self.can_retry(task):
                record_warning(
                    f"exhausted retries for {task['task_uuid']}",
                    source="retry_manager",
                )
                self.bus.emit(
                    "task.retry_exhausted",
                    {"task_uuid": task["task_uuid"]},
                    source="retry_manager",
                )
                continue
            results.append(self.retry_task(task["task_uuid"]))
        return results

    def backoff_seconds(self, attempts: int, *, base: float = 2.0, cap: float = 60.0) -> float:
        """Deterministic exponential backoff helper (seconds)."""
        delay = min(cap, base ** max(1, int(attempts)))
        return float(delay)


global_retry_manager = RetryManager()


def _self_test() -> None:
    print("=" * 60)
    print("RETRY MANAGER — SELF-TEST")
    print("=" * 60)
    from agents.base_agent import BaseAgent

    initialize_database()
    queue = TaskQueue()
    retries = RetryManager(task_queue=queue)
    worker = BaseAgent(name="Retry-Worker", agent_type="worker")
    worker.resume()

    task = queue.enqueue(
        "retry_probe",
        payload={"x": 1},
        priority=3,
        required_agent_type="worker",
        max_retries=3,
    )
    running = queue.dequeue(agent_uuid=worker.uuid, agent_type="worker")
    assert running is not None
    failed = queue.acknowledge(running["task_uuid"], success=False, error="transient")
    assert failed["status"] == "failed"
    print(f"[OK] failed task attempts={failed['attempts']}")

    assert retries.can_retry(failed) is True
    retried = retries.retry_task(failed["task_uuid"])
    assert retried["status"] == "queued"
    print(f"[OK] retry_task status={retried['status']}")

    assert retries.backoff_seconds(1) == 2.0
    assert retries.backoff_seconds(3) == 8.0
    print("[OK] backoff_seconds")

    events = retries.bus.list_events(topic="task.retried", limit=5)
    assert len(events) >= 1
    print(f"[OK] task.retried events={len(events)}")
    print("=" * 60)
    print("RETRY MANAGER SELF-TEST: PASSED")
    print("=" * 60)


if __name__ == "__main__":
    _self_test()
