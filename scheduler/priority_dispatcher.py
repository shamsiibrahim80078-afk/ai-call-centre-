"""
Priority Dispatcher — continuously assign highest-priority queued work to best agents.
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
from brain.decision_engine import DecisionEngine, global_brain  # noqa: E402
from database import initialize_database  # noqa: E402
from scheduler.event_bus import EventBus, global_event_bus  # noqa: E402
from scheduler.task_queue import TaskQueue, global_task_queue  # noqa: E402
from utils.system_health import bump_orchestration, collect_full_health  # noqa: E402


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class PriorityDispatcher:
    """Dispatch queued tasks to idle agents using brain prioritization."""

    def __init__(
        self,
        *,
        brain: Optional[DecisionEngine] = None,
        task_queue: Optional[TaskQueue] = None,
        registry: Optional[AgentRegistry] = None,
        event_bus: Optional[EventBus] = None,
    ) -> None:
        initialize_database()
        self.brain = brain or global_brain
        self.queue = task_queue or global_task_queue
        self.registry = registry or global_registry
        self.bus = event_bus or global_event_bus

    def dispatch_once(self) -> Optional[dict[str, Any]]:
        decision = self.brain.choose_next_action()
        if decision.get("action") != "assign_task":
            self.bus.emit(
                "dispatch.idle",
                {"reason": decision.get("reason"), "action": decision.get("action")},
                source="priority_dispatcher",
            )
            return None

        task = decision.get("task") or {}
        agent = decision.get("agent") or {}
        # Ensure task is marked running if still assigned
        task_uuid = task.get("task_uuid")
        if task_uuid and task.get("status") == "assigned":
            from database import db_session

            with db_session() as conn:
                conn.execute(
                    "UPDATE scheduled_tasks SET status='running' WHERE task_uuid = ? AND status='assigned'",
                    (task_uuid,),
                )

        payload = {
            "task_uuid": task_uuid,
            "title": task.get("title"),
            "priority": task.get("priority"),
            "agent_uuid": agent.get("uuid"),
            "agent_name": agent.get("name"),
            "reason": decision.get("reason"),
            "dispatched_at": _utc_now_iso(),
        }
        self.bus.emit("dispatch.assigned", payload, source="priority_dispatcher")
        bump_orchestration("dispatches", 1)
        collect_full_health()
        return payload

    def dispatch_batch(self, max_items: int = 10) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for _ in range(max(1, int(max_items))):
            item = self.dispatch_once()
            if item is None:
                break
            results.append(item)
        return results

    def execute_assigned(
        self,
        *,
        agent_uuid: str,
        task_uuid: str,
        title: str,
        payload: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Actually execute a task on a live agent and acknowledge completion."""
        agent = self.registry.get_agent(agent_uuid)
        if agent is None:
            raise LookupError(f"Agent {agent_uuid} not loaded.")
        if not isinstance(agent, BaseAgent):
            raise TypeError("Registry agent is not a BaseAgent.")

        try:
            result = agent.execute(task=title, payload=payload or {"task_uuid": task_uuid})
            ack = self.queue.acknowledge(task_uuid, success=True, result=result)
            self.bus.emit(
                "dispatch.executed",
                {"task_uuid": task_uuid, "agent_uuid": agent_uuid, "ok": True},
                source="priority_dispatcher",
            )
            return {"execution": result, "task": ack}
        except Exception as exc:
            ack = self.queue.acknowledge(task_uuid, success=False, error=str(exc))
            self.bus.emit(
                "dispatch.executed",
                {"task_uuid": task_uuid, "agent_uuid": agent_uuid, "ok": False, "error": str(exc)},
                source="priority_dispatcher",
            )
            raise


global_priority_dispatcher = PriorityDispatcher()


def _self_test() -> None:
    print("=" * 60)
    print("PRIORITY DISPATCHER — SELF-TEST")
    print("=" * 60)

    initialize_database()
    registry = AgentRegistry()
    queue = TaskQueue()
    brain = DecisionEngine(registry=registry, scheduler=queue.scheduler)
    dispatcher = PriorityDispatcher(brain=brain, task_queue=queue, registry=registry)

    worker = registry.register_agent("Dispatch-Worker", "worker")
    worker.resume()
    scout = registry.register_agent("Dispatch-Scout", "scout")
    scout.resume()

    queue.enqueue("sync_crm", priority=50, required_agent_type="worker")
    queue.enqueue("critical_incident", priority=1, required_agent_type="worker")
    queue.enqueue("ingest_leads", priority=40, required_agent_type="scout")

    first = dispatcher.dispatch_once()
    assert first is not None
    assert first["title"] == "critical_incident"
    print(f"[OK] dispatch_once selected {first['title']} -> {first['agent_name']}")

    # Execute the assigned critical task on the worker if assigned to our worker
    if first.get("agent_uuid") == worker.uuid and first.get("task_uuid"):
        executed = dispatcher.execute_assigned(
            agent_uuid=worker.uuid,
            task_uuid=first["task_uuid"],
            title=first["title"],
            payload={"source": "dispatcher_test"},
        )
        assert executed["task"]["status"] == "completed"
        print("[OK] execute_assigned completed critical_incident")

    batch = dispatcher.dispatch_batch(max_items=5)
    print(f"[OK] dispatch_batch assigned={len(batch)}")
    print("=" * 60)
    print("PRIORITY DISPATCHER SELF-TEST: PASSED")
    print("=" * 60)


if __name__ == "__main__":
    _self_test()
