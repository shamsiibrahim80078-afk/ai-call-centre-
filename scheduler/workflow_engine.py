"""
Workflow Engine — multi-step orchestration across queue, agents, recovery, and events.
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

from agents.registry import AgentRegistry, global_registry  # noqa: E402
from database import db_session, initialize_database  # noqa: E402
from scheduler.auto_recovery import AutoRecovery, global_auto_recovery  # noqa: E402
from scheduler.event_bus import EventBus, global_event_bus  # noqa: E402
from scheduler.priority_dispatcher import PriorityDispatcher, global_priority_dispatcher  # noqa: E402
from scheduler.retry_manager import RetryManager, global_retry_manager  # noqa: E402
from scheduler.task_queue import TaskQueue, global_task_queue  # noqa: E402
from utils.system_health import bump_orchestration, collect_full_health  # noqa: E402


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class WorkflowEngine:
    """
    Execute ordered workflow steps:
      - enqueue
      - dispatch
      - execute
      - retry_failed
      - recover
      - heartbeat_scan
    """

    def __init__(
        self,
        *,
        task_queue: Optional[TaskQueue] = None,
        dispatcher: Optional[PriorityDispatcher] = None,
        retry_manager: Optional[RetryManager] = None,
        auto_recovery: Optional[AutoRecovery] = None,
        registry: Optional[AgentRegistry] = None,
        event_bus: Optional[EventBus] = None,
    ) -> None:
        initialize_database()
        self.queue = task_queue or global_task_queue
        self.dispatcher = dispatcher or global_priority_dispatcher
        self.retries = retry_manager or global_retry_manager
        self.recovery = auto_recovery or global_auto_recovery
        self.registry = registry or global_registry
        self.bus = event_bus or global_event_bus

    def create_workflow(
        self,
        name: str,
        steps: list[dict[str, Any]],
        *,
        context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        if not name or not name.strip():
            raise ValueError("workflow name is required.")
        if not steps:
            raise ValueError("workflow steps are required.")

        workflow_uuid = str(uuid.uuid4())
        stamped = _utc_now_iso()
        with db_session() as conn:
            conn.execute(
                """
                INSERT INTO workflow_runs
                    (workflow_uuid, name, status, steps_json, current_step,
                     context_json, created_at, updated_at)
                VALUES (?, ?, 'pending', ?, 0, ?, ?, ?)
                """,
                (
                    workflow_uuid,
                    name.strip(),
                    json.dumps(steps, default=str),
                    json.dumps(context or {}, default=str),
                    stamped,
                    stamped,
                ),
            )
        self.bus.emit(
            "workflow.created",
            {"workflow_uuid": workflow_uuid, "name": name, "steps": len(steps)},
            source="workflow_engine",
        )
        bump_orchestration("workflows_running", 1)
        return self.get_workflow(workflow_uuid)

    def get_workflow(self, workflow_uuid: str) -> dict[str, Any]:
        with db_session() as conn:
            row = conn.execute(
                "SELECT * FROM workflow_runs WHERE workflow_uuid = ?",
                (workflow_uuid,),
            ).fetchone()
        if row is None:
            raise LookupError(f"Workflow '{workflow_uuid}' not found.")
        data = dict(row)
        data["steps"] = json.loads(data.pop("steps_json"))
        data["context"] = json.loads(data.pop("context_json") or "{}")
        return data

    def _save_workflow(
        self,
        workflow_uuid: str,
        *,
        status: Optional[str] = None,
        current_step: Optional[int] = None,
        context: Optional[dict[str, Any]] = None,
        last_error: Optional[str] = None,
        completed: bool = False,
    ) -> dict[str, Any]:
        stamped = _utc_now_iso()
        current = self.get_workflow(workflow_uuid)
        with db_session() as conn:
            conn.execute(
                """
                UPDATE workflow_runs
                SET status = ?,
                    current_step = ?,
                    context_json = ?,
                    last_error = ?,
                    updated_at = ?,
                    completed_at = CASE WHEN ? THEN ? ELSE completed_at END
                WHERE workflow_uuid = ?
                """,
                (
                    status if status is not None else current["status"],
                    current_step if current_step is not None else current["current_step"],
                    json.dumps(context if context is not None else current["context"], default=str),
                    last_error,
                    stamped,
                    1 if completed else 0,
                    stamped,
                    workflow_uuid,
                ),
            )
        return self.get_workflow(workflow_uuid)

    def _run_step(self, step: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        action = str(step.get("action") or "").strip()
        if not action:
            raise ValueError("step.action is required.")

        if action == "enqueue":
            task = self.queue.enqueue(
                step["title"],
                payload=step.get("payload") or {},
                priority=int(step.get("priority", 100)),
                required_agent_type=step.get("required_agent_type"),
                max_retries=int(step.get("max_retries", 3)),
            )
            context.setdefault("task_uuids", []).append(task["task_uuid"])
            return {"action": action, "task": task}

        if action == "dispatch":
            assigned = self.dispatcher.dispatch_batch(max_items=int(step.get("max_items", 1)))
            context.setdefault("dispatches", []).extend(assigned)
            return {"action": action, "assigned": assigned}

        if action == "execute_last_dispatch":
            dispatches = context.get("dispatches") or []
            if not dispatches:
                raise RuntimeError("No dispatch available to execute.")
            last = dispatches[-1]
            agent_uuid = last.get("agent_uuid")
            task_uuid = last.get("task_uuid")
            title = last.get("title") or "workflow_task"
            if not agent_uuid or not task_uuid:
                raise RuntimeError("Dispatch payload missing agent/task identifiers.")
            result = self.dispatcher.execute_assigned(
                agent_uuid=agent_uuid,
                task_uuid=task_uuid,
                title=title,
                payload=step.get("payload") or {"workflow": True},
            )
            context.setdefault("executions", []).append(result)
            return {"action": action, "result": result}

        if action == "retry_failed":
            retried = self.retries.retry_all_failed(limit=int(step.get("limit", 50)))
            context.setdefault("retries", []).extend([t["task_uuid"] for t in retried])
            return {"action": action, "retried": retried}

        if action == "recover":
            report = self.recovery.run_recovery_cycle()
            context["last_recovery"] = report
            return {"action": action, "report": report}

        if action == "heartbeat_scan":
            report = self.recovery.monitor.scan()
            context["last_heartbeat_scan"] = report
            return {"action": action, "report": report}

        raise ValueError(f"Unsupported workflow action '{action}'.")

    def run_workflow(self, workflow_uuid: str) -> dict[str, Any]:
        workflow = self.get_workflow(workflow_uuid)
        steps = workflow["steps"]
        context = dict(workflow.get("context") or {})
        self._save_workflow(workflow_uuid, status="running")
        self.bus.emit(
            "workflow.started",
            {"workflow_uuid": workflow_uuid, "name": workflow["name"]},
            source="workflow_engine",
        )

        results: list[dict[str, Any]] = []
        try:
            for index, step in enumerate(steps):
                step_result = self._run_step(step, context)
                results.append(step_result)
                context["last_step_result"] = {
                    "index": index,
                    "action": step_result.get("action"),
                }
                self._save_workflow(
                    workflow_uuid,
                    status="running",
                    current_step=index + 1,
                    context=context,
                )
                self.bus.emit(
                    "workflow.step_completed",
                    {
                        "workflow_uuid": workflow_uuid,
                        "step_index": index,
                        "action": step.get("action"),
                    },
                    source="workflow_engine",
                )

            final = self._save_workflow(
                workflow_uuid,
                status="completed",
                current_step=len(steps),
                context={**context, "results": results},
                completed=True,
            )
            self.bus.emit(
                "workflow.completed",
                {"workflow_uuid": workflow_uuid, "steps": len(steps)},
                source="workflow_engine",
            )
            collect_full_health()
            return final
        except Exception as exc:
            failed = self._save_workflow(
                workflow_uuid,
                status="failed",
                context=context,
                last_error=str(exc),
                completed=True,
            )
            self.bus.emit(
                "workflow.failed",
                {"workflow_uuid": workflow_uuid, "error": str(exc)},
                source="workflow_engine",
            )
            collect_full_health()
            raise RuntimeError(f"Workflow '{workflow_uuid}' failed: {exc}") from exc


global_workflow_engine = WorkflowEngine()


def _self_test() -> None:
    print("=" * 60)
    print("WORKFLOW ENGINE — SELF-TEST")
    print("=" * 60)

    initialize_database()
    registry = AgentRegistry()
    queue = TaskQueue()
    from brain.decision_engine import DecisionEngine
    from scheduler.priority_dispatcher import PriorityDispatcher

    brain = DecisionEngine(registry=registry, scheduler=queue.scheduler)
    dispatcher = PriorityDispatcher(brain=brain, task_queue=queue, registry=registry)
    engine = WorkflowEngine(
        task_queue=queue,
        dispatcher=dispatcher,
        registry=registry,
    )

    worker = registry.register_agent("Workflow-Worker", "worker")
    worker.resume()

    workflow = engine.create_workflow(
        "phase4_orchestration_probe",
        steps=[
            {
                "action": "enqueue",
                "title": "sync_crm",
                "priority": 5,
                "required_agent_type": "worker",
                "payload": {"phase": 4},
            },
            {"action": "dispatch", "max_items": 1},
            {"action": "execute_last_dispatch", "payload": {"verify": True}},
            {"action": "heartbeat_scan"},
        ],
    )
    print(f"[OK] created workflow={workflow['workflow_uuid'][:8]}")

    final = engine.run_workflow(workflow["workflow_uuid"])
    assert final["status"] == "completed"
    assert final["current_step"] == 4
    print(f"[OK] workflow completed steps={final['current_step']}")

    with db_session() as conn:
        row = conn.execute(
            "SELECT status FROM workflow_runs WHERE workflow_uuid = ?",
            (workflow["workflow_uuid"],),
        ).fetchone()
    assert row["status"] == "completed"
    print("[OK] workflow_runs DB status=completed")
    print("=" * 60)
    print("WORKFLOW ENGINE SELF-TEST: PASSED")
    print("=" * 60)


if __name__ == "__main__":
    _self_test()
