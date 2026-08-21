"""
Auto Recovery — restore failed/stale agents and re-queue interrupted work.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agents.base_agent import BaseAgent  # noqa: E402
from agents.registry import AgentRegistry, global_registry  # noqa: E402
from database import db_session, get_agent_record, initialize_database, update_agent_record  # noqa: E402
from scheduler.event_bus import EventBus, global_event_bus  # noqa: E402
from scheduler.heartbeat_monitor import HeartbeatMonitor, global_heartbeat_monitor  # noqa: E402
from scheduler.retry_manager import RetryManager, global_retry_manager  # noqa: E402
from utils.system_health import bump_orchestration, collect_full_health, record_error  # noqa: E402


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class AutoRecovery:
    """Recover stale/error agents and interrupted running tasks."""

    def __init__(
        self,
        *,
        registry: Optional[AgentRegistry] = None,
        monitor: Optional[HeartbeatMonitor] = None,
        retry_manager: Optional[RetryManager] = None,
        event_bus: Optional[EventBus] = None,
    ) -> None:
        initialize_database()
        self.registry = registry or global_registry
        self.monitor = monitor or global_heartbeat_monitor
        self.retries = retry_manager or global_retry_manager
        self.bus = event_bus or global_event_bus

    def recover_agent(self, agent_uuid: str) -> dict[str, Any]:
        record = get_agent_record(agent_uuid=agent_uuid)
        if record is None:
            raise LookupError(f"Agent uuid={agent_uuid} not found.")

        agent = self.registry.get_agent(agent_uuid)
        if agent is None:
            agent = BaseAgent(
                name=record.get("agent_name") or f"recovered-{record['id']}",
                agent_type=record["agent_type"],
                agent_uuid=agent_uuid,
                status="idle",
                registry_id=int(record["id"]),
                auto_register=True,
            )
            self.registry.register_agent(agent.name, agent.agent_type, agent=agent)

        # Clear error/stale active states back to idle and heartbeat
        update_agent_record(
            int(record["id"]),
            status="idle",
            current_task=None,
            last_ping_at=_utc_now_iso(),
        )
        agent.status = "idle"
        agent.current_task = None
        hb = agent.heartbeat(status="idle", current_task=None, increment_cycle=True)
        agent.save_state()

        payload = {
            "agent_uuid": agent_uuid,
            "registry_id": record["id"],
            "previous_status": record.get("status"),
            "new_status": "idle",
            "last_ping_at": hb.get("last_ping_at"),
        }
        self.bus.emit("agent.recovered", payload, source="auto_recovery")
        bump_orchestration("recoveries", 1)
        collect_full_health()
        return payload

    def release_interrupted_tasks(self) -> list[dict[str, Any]]:
        """Move stuck running/assigned tasks back to failed so retry manager can reclaim them."""
        released: list[dict[str, Any]] = []
        stamped = _utc_now_iso()
        with db_session() as conn:
            rows = conn.execute(
                """
                SELECT * FROM scheduled_tasks
                WHERE status IN ('running', 'assigned')
                """
            ).fetchall()
            for row in rows:
                conn.execute(
                    """
                    UPDATE scheduled_tasks
                    SET status = 'failed',
                        last_error = coalesce(last_error, 'auto_recovery: interrupted'),
                        updated_at = ?
                    WHERE task_uuid = ?
                    """,
                    (stamped, row["task_uuid"]),
                )
                if row["assigned_agent_id"] is not None:
                    conn.execute(
                        """
                        UPDATE agents_registry
                        SET status = 'idle', current_task = NULL, last_ping_at = ?
                        WHERE id = ?
                        """,
                        (stamped, int(row["assigned_agent_id"])),
                    )
                released.append(
                    {
                        "task_uuid": row["task_uuid"],
                        "title": row["title"],
                        "previous_status": row["status"],
                    }
                )
        for item in released:
            self.bus.emit("task.interrupted_released", item, source="auto_recovery")
        return released

    def run_recovery_cycle(self) -> dict[str, Any]:
        scan = self.monitor.scan()
        recovered_agents: list[dict[str, Any]] = []
        for stale in scan["stale"]:
            uid = stale.get("uuid")
            if not uid:
                continue
            try:
                recovered_agents.append(self.recover_agent(uid))
            except Exception as exc:
                record_error(f"recover_agent({uid}) failed: {exc}", source="auto_recovery")

        released = self.release_interrupted_tasks()
        retried = self.retries.retry_all_failed(limit=100)

        report = {
            "stale_detected": scan["stale_count"],
            "agents_recovered": recovered_agents,
            "tasks_released": released,
            "tasks_retried": [t["task_uuid"] for t in retried],
            "completed_at": _utc_now_iso(),
        }
        self.bus.emit("recovery.cycle_complete", report, source="auto_recovery")
        collect_full_health()
        return report


global_auto_recovery = AutoRecovery()


def _self_test() -> None:
    print("=" * 60)
    print("AUTO RECOVERY — SELF-TEST")
    print("=" * 60)
    from scheduler.task_queue import TaskQueue

    initialize_database()
    registry = AgentRegistry()
    monitor = HeartbeatMonitor(stale_after_seconds=2)
    recovery = AutoRecovery(registry=registry, monitor=monitor)
    queue = TaskQueue()

    agent = registry.register_agent("Recovery-Agent", "ops")
    agent.heartbeat(status="error", current_task="broken_job")

    # Create interrupted running task first, then force a stale heartbeat.
    task = queue.enqueue("recovery_probe", priority=1, required_agent_type="ops")
    running = queue.dequeue(agent_uuid=agent.uuid, agent_type="ops")
    assert running is not None
    print(f"[OK] interrupted setup task={running['task_uuid'][:8]}")

    with db_session() as conn:
        conn.execute(
            "UPDATE agents_registry SET last_ping_at = '2000-01-01T00:00:00+00:00', status = 'error' WHERE id = ?",
            (agent.registry_id,),
        )

    report = recovery.run_recovery_cycle()
    assert report["stale_detected"] >= 1
    assert any(a["agent_uuid"] == agent.uuid for a in report["agents_recovered"])
    print(f"[OK] recovered agents={len(report['agents_recovered'])}")
    assert any(t["task_uuid"] == running["task_uuid"] for t in report["tasks_released"])
    print(f"[OK] released tasks={len(report['tasks_released'])}")
    assert running["task_uuid"] in report["tasks_retried"]
    print(f"[OK] retried={len(report['tasks_retried'])}")

    refreshed = get_agent_record(agent_uuid=agent.uuid)
    assert refreshed is not None
    assert refreshed["status"] == "idle"
    print("[OK] agent status restored to idle")
    print("=" * 60)
    print("AUTO RECOVERY SELF-TEST: PASSED")
    print("=" * 60)


if __name__ == "__main__":
    _self_test()
