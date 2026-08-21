"""
Task Queue — continuous durable queue layered on TaskScheduler + EventBus.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from database import db_session, initialize_database  # noqa: E402
from scheduler.event_bus import EventBus, global_event_bus  # noqa: E402
from scheduler.task_scheduler import TaskScheduler, global_scheduler  # noqa: E402
from utils.system_health import collect_full_health  # noqa: E402


class TaskQueue:
    """Production orchestration queue with enqueue/dequeue/ack semantics."""

    def __init__(
        self,
        scheduler: Optional[TaskScheduler] = None,
        event_bus: Optional[EventBus] = None,
    ) -> None:
        initialize_database()
        self.scheduler = scheduler or global_scheduler
        self.bus = event_bus or global_event_bus

    def enqueue(
        self,
        title: str,
        *,
        payload: Optional[dict[str, Any]] = None,
        priority: int = 100,
        required_agent_type: Optional[str] = None,
        max_retries: int = 3,
    ) -> dict[str, Any]:
        task = self.scheduler.queue_task(
            title,
            payload=payload,
            priority=priority,
            required_agent_type=required_agent_type,
            max_retries=max_retries,
        )
        self.bus.emit(
            "task.queued",
            {
                "task_uuid": task["task_uuid"],
                "title": task["title"],
                "priority": task["priority"],
            },
            source="task_queue",
        )
        collect_full_health()
        return task

    def dequeue(
        self,
        *,
        agent_type: Optional[str] = None,
        agent_uuid: Optional[str] = None,
        agent_id: Optional[int] = None,
    ) -> Optional[dict[str, Any]]:
        """
        Pull the next queued task and assign it.
        Requires an agent identity for assignment.
        """
        if agent_uuid is None and agent_id is None:
            raise ValueError("Provide agent_uuid or agent_id to dequeue/assign.")

        nxt = self.scheduler.next_queued_task(agent_type=agent_type)
        if nxt is None:
            return None

        assigned = self.scheduler.assign_task(
            nxt["task_uuid"],
            agent_id=agent_id,
            agent_uuid=agent_uuid,
        )
        # Mark running
        from datetime import datetime, timezone

        stamped = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        with db_session() as conn:
            conn.execute(
                """
                UPDATE scheduled_tasks
                SET status = 'running', updated_at = ?
                WHERE task_uuid = ?
                """,
                (stamped, assigned["task_uuid"]),
            )
            row = conn.execute(
                "SELECT * FROM scheduled_tasks WHERE task_uuid = ?",
                (assigned["task_uuid"],)
            ).fetchone()
        task = self.scheduler._row_to_dict(row)
        self.bus.emit(
            "task.started",
            {
                "task_uuid": task["task_uuid"],
                "agent_uuid": task.get("assigned_agent_uuid"),
                "title": task["title"],
            },
            source="task_queue",
        )
        collect_full_health()
        return task

    def acknowledge(
        self,
        task_uuid: str,
        *,
        success: bool = True,
        result: Optional[dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> dict[str, Any]:
        task = self.scheduler.complete_task(
            task_uuid,
            success=success,
            result=result,
            error=error,
        )
        topic = "task.completed" if success else "task.failed"
        self.bus.emit(
            topic,
            {
                "task_uuid": task_uuid,
                "status": task["status"],
                "error": error,
            },
            source="task_queue",
        )
        collect_full_health()
        return task

    def size(self, status: str = "queued") -> int:
        with db_session() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM scheduled_tasks WHERE status = ?",
                (status,),
            ).fetchone()
            return int(row["c"])

    def list_by_status(self, status: str, limit: int = 100) -> list[dict[str, Any]]:
        return self.scheduler.list_tasks(status=status, limit=limit)


global_task_queue = TaskQueue()


def _self_test() -> None:
    print("=" * 60)
    print("TASK QUEUE — SELF-TEST")
    print("=" * 60)
    from agents.base_agent import BaseAgent

    initialize_database()
    queue = TaskQueue()
    worker = BaseAgent(name="Queue-Worker", agent_type="worker")
    worker.resume()
    print(f"[OK] worker uuid={worker.uuid}")

    task = queue.enqueue(
        "queue_probe",
        payload={"n": 1},
        priority=7,
        required_agent_type="worker",
    )
    assert task["status"] == "queued"
    print(f"[OK] enqueue task_uuid={task['task_uuid'][:8]}")

    running = queue.dequeue(agent_uuid=worker.uuid, agent_type="worker")
    assert running is not None
    assert running["status"] == "running"
    assert running["assigned_agent_uuid"] == worker.uuid
    print(f"[OK] dequeue/running status={running['status']}")

    done = queue.acknowledge(running["task_uuid"], success=True, result={"ok": True})
    assert done["status"] == "completed"
    print("[OK] acknowledge completed")

    # Fail path
    task2 = queue.enqueue("queue_fail_probe", priority=8, required_agent_type="worker")
    running2 = queue.dequeue(agent_uuid=worker.uuid, agent_type="worker")
    assert running2 is not None
    failed = queue.acknowledge(running2["task_uuid"], success=False, error="boom")
    assert failed["status"] == "failed"
    print("[OK] acknowledge failed")

    events = queue.bus.list_events(limit=20)
    topics = {e["topic"] for e in events}
    assert "task.queued" in topics
    assert "task.started" in topics
    assert "task.completed" in topics
    assert "task.failed" in topics
    print(f"[OK] event topics observed={sorted(topics)}")
    print("=" * 60)
    print("TASK QUEUE SELF-TEST: PASSED")
    print("=" * 60)


if __name__ == "__main__":
    _self_test()
