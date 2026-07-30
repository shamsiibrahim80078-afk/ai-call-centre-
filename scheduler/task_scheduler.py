"""
Task Scheduler — durable job queue backed by scheduled_tasks in sovereign_swarm_core.db.
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from database import db_session, get_agent_record, initialize_database  # noqa: E402


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class TaskScheduler:
    """Production task queue with assign / complete / retry semantics."""

    VALID_STATUSES = frozenset(
        {"queued", "assigned", "running", "completed", "failed", "cancelled"}
    )

    def __init__(self) -> None:
        initialize_database()

    def queue_task(
        self,
        title: str,
        *,
        payload: Optional[dict[str, Any]] = None,
        priority: int = 100,
        required_agent_type: Optional[str] = None,
        max_retries: int = 3,
    ) -> dict[str, Any]:
        """Enqueue a new task. Lower priority numbers run first."""
        if not title or not title.strip():
            raise ValueError("title is required.")
        if max_retries < 0:
            raise ValueError("max_retries must be >= 0.")

        task_uuid = str(uuid.uuid4())
        stamped = _utc_now_iso()
        payload_json = json.dumps(payload or {}, default=str)

        with db_session() as conn:
            cur = conn.execute(
                """
                INSERT INTO scheduled_tasks
                    (task_uuid, title, payload, priority, status, required_agent_type,
                     attempts, max_retries, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'queued', ?, 0, ?, ?, ?)
                """,
                (
                    task_uuid,
                    title.strip(),
                    payload_json,
                    int(priority),
                    required_agent_type,
                    int(max_retries),
                    stamped,
                    stamped,
                ),
            )
            row_id = int(cur.lastrowid)
            row = conn.execute(
                "SELECT * FROM scheduled_tasks WHERE id = ?",
                (row_id,),
            ).fetchone()
        return self._row_to_dict(row)

    def assign_task(
        self,
        task_uuid: str,
        *,
        agent_id: Optional[int] = None,
        agent_uuid: Optional[str] = None,
    ) -> dict[str, Any]:
        """Assign a queued (or failed-for-retry) task to an agent."""
        if not task_uuid or not task_uuid.strip():
            raise ValueError("task_uuid is required.")
        if agent_id is None and not agent_uuid:
            raise ValueError("Provide agent_id or agent_uuid.")

        agent = get_agent_record(agent_id=agent_id, agent_uuid=agent_uuid)
        if agent is None:
            raise LookupError("Target agent not found in agents_registry.")

        stamped = _utc_now_iso()
        with db_session() as conn:
            task = conn.execute(
                "SELECT * FROM scheduled_tasks WHERE task_uuid = ?",
                (task_uuid.strip(),),
            ).fetchone()
            if task is None:
                raise LookupError(f"Task '{task_uuid}' not found.")
            if task["status"] not in {"queued", "failed"}:
                raise RuntimeError(
                    f"Task '{task_uuid}' status '{task['status']}' cannot be assigned."
                )

            required = task["required_agent_type"]
            if required and agent["agent_type"] != required:
                raise RuntimeError(
                    f"Agent type '{agent['agent_type']}' does not match required '{required}'."
                )

            conn.execute(
                """
                UPDATE scheduled_tasks
                SET status = 'assigned',
                    assigned_agent_id = ?,
                    assigned_agent_uuid = ?,
                    attempts = attempts + 1,
                    updated_at = ?,
                    last_error = NULL
                WHERE task_uuid = ?
                """,
                (
                    int(agent["id"]),
                    agent.get("agent_uuid"),
                    stamped,
                    task_uuid.strip(),
                ),
            )
            # Mark agent busy
            conn.execute(
                """
                UPDATE agents_registry
                SET status = 'active', current_task = ?, last_ping_at = ?
                WHERE id = ?
                """,
                (task["title"], stamped, int(agent["id"])),
            )
            row = conn.execute(
                "SELECT * FROM scheduled_tasks WHERE task_uuid = ?",
                (task_uuid.strip(),),
            ).fetchone()
        return self._row_to_dict(row)

    def complete_task(
        self,
        task_uuid: str,
        *,
        result: Optional[dict[str, Any]] = None,
        success: bool = True,
        error: Optional[str] = None,
    ) -> dict[str, Any]:
        """Mark a task completed or failed and free the assigned agent."""
        if not task_uuid or not task_uuid.strip():
            raise ValueError("task_uuid is required.")

        stamped = _utc_now_iso()
        new_status = "completed" if success else "failed"
        with db_session() as conn:
            task = conn.execute(
                "SELECT * FROM scheduled_tasks WHERE task_uuid = ?",
                (task_uuid.strip(),),
            ).fetchone()
            if task is None:
                raise LookupError(f"Task '{task_uuid}' not found.")
            if task["status"] in {"completed", "cancelled"}:
                raise RuntimeError(f"Task '{task_uuid}' is already {task['status']}.")

            payload = {}
            if task["payload"]:
                try:
                    payload = json.loads(task["payload"])
                except json.JSONDecodeError:
                    payload = {"raw": task["payload"]}
            if result is not None:
                payload["result"] = result

            conn.execute(
                """
                UPDATE scheduled_tasks
                SET status = ?,
                    payload = ?,
                    last_error = ?,
                    updated_at = ?,
                    completed_at = CASE WHEN ? = 'completed' THEN ? ELSE completed_at END
                WHERE task_uuid = ?
                """,
                (
                    new_status,
                    json.dumps(payload, default=str),
                    error,
                    stamped,
                    new_status,
                    stamped,
                    task_uuid.strip(),
                ),
            )

            if task["assigned_agent_id"] is not None:
                conn.execute(
                    """
                    UPDATE agents_registry
                    SET status = 'idle', current_task = NULL, last_ping_at = ?
                    WHERE id = ?
                    """,
                    (stamped, int(task["assigned_agent_id"])),
                )

            row = conn.execute(
                "SELECT * FROM scheduled_tasks WHERE task_uuid = ?",
                (task_uuid.strip(),),
            ).fetchone()
        return self._row_to_dict(row)

    def retry_failed_task(self, task_uuid: str) -> dict[str, Any]:
        """Re-queue a failed task when attempts remain under max_retries."""
        if not task_uuid or not task_uuid.strip():
            raise ValueError("task_uuid is required.")

        stamped = _utc_now_iso()
        with db_session() as conn:
            task = conn.execute(
                "SELECT * FROM scheduled_tasks WHERE task_uuid = ?",
                (task_uuid.strip(),),
            ).fetchone()
            if task is None:
                raise LookupError(f"Task '{task_uuid}' not found.")
            if task["status"] != "failed":
                raise RuntimeError(
                    f"Only failed tasks can be retried (current={task['status']})."
                )
            if int(task["attempts"]) >= int(task["max_retries"]):
                raise RuntimeError(
                    f"Task '{task_uuid}' exhausted retries "
                    f"({task['attempts']}/{task['max_retries']})."
                )

            conn.execute(
                """
                UPDATE scheduled_tasks
                SET status = 'queued',
                    assigned_agent_id = NULL,
                    assigned_agent_uuid = NULL,
                    updated_at = ?,
                    last_error = NULL
                WHERE task_uuid = ?
                """,
                (stamped, task_uuid.strip()),
            )
            row = conn.execute(
                "SELECT * FROM scheduled_tasks WHERE task_uuid = ?",
                (task_uuid.strip(),),
            ).fetchone()
        return self._row_to_dict(row)

    def list_tasks(
        self,
        *,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List tasks ordered by priority ASC then created_at ASC."""
        with db_session() as conn:
            if status:
                rows = conn.execute(
                    """
                    SELECT * FROM scheduled_tasks
                    WHERE status = ?
                    ORDER BY priority ASC, created_at ASC
                    LIMIT ?
                    """,
                    (status, int(limit)),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM scheduled_tasks
                    ORDER BY priority ASC, created_at ASC
                    LIMIT ?
                    """,
                    (int(limit),),
                ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def next_queued_task(self, *, agent_type: Optional[str] = None) -> Optional[dict[str, Any]]:
        """Peek the highest-priority queued task, optionally filtered by agent type."""
        with db_session() as conn:
            if agent_type:
                row = conn.execute(
                    """
                    SELECT * FROM scheduled_tasks
                    WHERE status = 'queued'
                      AND (required_agent_type IS NULL OR required_agent_type = ?)
                    ORDER BY priority ASC, created_at ASC
                    LIMIT 1
                    """,
                    (agent_type,),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT * FROM scheduled_tasks
                    WHERE status = 'queued'
                    ORDER BY priority ASC, created_at ASC
                    LIMIT 1
                    """
                ).fetchone()
        return self._row_to_dict(row) if row else None

    @staticmethod
    def _row_to_dict(row: Any) -> dict[str, Any]:
        data = dict(row)
        raw_payload = data.get("payload")
        if isinstance(raw_payload, str) and raw_payload:
            try:
                data["payload"] = json.loads(raw_payload)
            except json.JSONDecodeError:
                data["payload"] = {"raw": raw_payload}
        elif raw_payload is None:
            data["payload"] = {}
        return data


# Process-wide singleton for API routes
global_scheduler = TaskScheduler()


def _self_test() -> None:
    print("=" * 60)
    print("TASK SCHEDULER — SELF-TEST")
    print("=" * 60)

    initialize_database()
    from agents.base_agent import BaseAgent

    scheduler = TaskScheduler()
    worker = BaseAgent(name="Scheduler-Worker", agent_type="worker")
    print(f"[OK] worker ready uuid={worker.uuid} id={worker.registry_id}")

    t1 = scheduler.queue_task("ingest_leads", payload={"batch": 1}, priority=10, required_agent_type="worker")
    t2 = scheduler.queue_task("enrich_leads", payload={"batch": 2}, priority=20)
    t3 = scheduler.queue_task("sync_crm", payload={"batch": 3}, priority=5, required_agent_type="worker")
    print(
        "[OK] queued 3 tasks: "
        f"{t1['task_uuid'][:8]}, {t2['task_uuid'][:8]}, {t3['task_uuid'][:8]}"
    )

    queued = scheduler.list_tasks(status="queued")
    assert len(queued) >= 3
    assert queued[0]["priority"] <= queued[1]["priority"]
    print(f"[OK] list_tasks queued={len(queued)} top_priority={queued[0]['priority']}")

    assigned = scheduler.assign_task(t3["task_uuid"], agent_uuid=worker.uuid)
    assert assigned["status"] == "assigned"
    assert assigned["assigned_agent_uuid"] == worker.uuid
    print(f"[OK] assign_task title={assigned['title']}")

    completed = scheduler.complete_task(
        t3["task_uuid"],
        success=True,
        result={"rows": 42},
    )
    assert completed["status"] == "completed"
    print("[OK] complete_task success")

    # Fail + retry path
    assigned2 = scheduler.assign_task(t1["task_uuid"], agent_id=worker.registry_id)
    failed = scheduler.complete_task(t1["task_uuid"], success=False, error="transient network")
    assert failed["status"] == "failed"
    print("[OK] complete_task failure")

    retried = scheduler.retry_failed_task(t1["task_uuid"])
    assert retried["status"] == "queued"
    print("[OK] retry_failed_task re-queued")

    nxt = scheduler.next_queued_task(agent_type="worker")
    assert nxt is not None
    print(f"[OK] next_queued_task={nxt['title']} priority={nxt['priority']}")

    print("=" * 60)
    print("TASK SCHEDULER SELF-TEST: PASSED")
    print("=" * 60)


if __name__ == "__main__":
    _self_test()
