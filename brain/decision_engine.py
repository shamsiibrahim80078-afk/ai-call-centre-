"""
Decision Engine — deterministic AI brain for action selection and agent assignment.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agents.registry import AgentRegistry, global_registry  # noqa: E402
from database import initialize_database  # noqa: E402
from scheduler.task_scheduler import TaskScheduler, global_scheduler  # noqa: E402


# Lower number = higher urgency for known action families
ACTION_PRIORITY = {
    "critical_incident": 1,
    "deploy_contract": 10,
    "close_lead": 20,
    "enrich_leads": 30,
    "ingest_leads": 40,
    "sync_crm": 50,
    "heartbeat": 90,
    "idle_wait": 1000,
}

# Preferred agent types for known actions
ACTION_AGENT_TYPE = {
    "critical_incident": "ops",
    "deploy_contract": "crypto",
    "close_lead": "closer",
    "enrich_leads": "scout",
    "ingest_leads": "scout",
    "sync_crm": "worker",
    "heartbeat": None,
}


class DecisionEngine:
    """Deterministic brain that prioritizes work and assigns the best idle agent."""

    def __init__(
        self,
        registry: Optional[AgentRegistry] = None,
        scheduler: Optional[TaskScheduler] = None,
    ) -> None:
        initialize_database()
        self.registry = registry or global_registry
        self.scheduler = scheduler or global_scheduler

    def prioritize_tasks(self, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Sort tasks by explicit priority, then known action family weight, then created_at.
        """
        def sort_key(task: dict[str, Any]) -> tuple[int, int, str]:
            title = str(task.get("title") or "")
            family = ACTION_PRIORITY.get(title, 500)
            explicit = int(task.get("priority") or 100)
            created = str(task.get("created_at") or "")
            return (explicit, family, created)

        return sorted(tasks, key=sort_key)

    def detect_idle_agents(
        self,
        *,
        agent_type: Optional[str] = None,
        include_db: bool = True,
    ) -> list[dict[str, Any]]:
        """Return agents currently idle (optionally filtered by type)."""
        agents = self.registry.list_agents(refresh_from_db=include_db)
        idle: list[dict[str, Any]] = []
        for agent in agents:
            if str(agent.get("status") or "").lower() != "idle":
                continue
            if agent_type and agent.get("agent_type") != agent_type:
                continue
            # Prefer agents with a real uuid
            if not agent.get("uuid"):
                continue
            idle.append(agent)

        # Stable deterministic order: fewest cycles first, then name
        idle.sort(
            key=lambda a: (
                int(a.get("total_cycles") or 0),
                str(a.get("name") or ""),
                str(a.get("uuid") or ""),
            )
        )
        return idle

    def assign_best_agent(
        self,
        task: dict[str, Any],
        *,
        auto_assign: bool = True,
    ) -> Optional[dict[str, Any]]:
        """
        Choose the best idle agent for a task.
        Preference order:
          1) required_agent_type match
          2) ACTION_AGENT_TYPE preference for the title
          3) any idle agent
        Within a cohort, fewest total_cycles wins.
        """
        required = task.get("required_agent_type")
        preferred = required or ACTION_AGENT_TYPE.get(str(task.get("title") or ""))

        candidates = self.detect_idle_agents(agent_type=preferred if preferred else None)
        if not candidates and preferred:
            candidates = self.detect_idle_agents()

        if not candidates:
            return None

        best = candidates[0]
        assignment: Optional[dict[str, Any]] = None
        if auto_assign and task.get("task_uuid") and task.get("status") == "queued":
            assignment = self.scheduler.assign_task(
                task["task_uuid"],
                agent_uuid=best["uuid"],
            )

        return {
            "agent": best,
            "task": assignment or task,
            "reason": (
                f"selected idle agent '{best.get('name')}' "
                f"type={best.get('agent_type')} cycles={best.get('total_cycles')}"
            ),
        }

    def choose_next_action(self) -> dict[str, Any]:
        """
        Decide the next platform action:
          - If queued work exists, prioritize and assign the best agent.
          - Else if idle agents exist, recommend a heartbeat sweep.
          - Else recommend idle_wait.
        """
        queued = self.scheduler.list_tasks(status="queued", limit=100)
        prioritized = self.prioritize_tasks(queued)

        if prioritized:
            top = prioritized[0]
            decision = self.assign_best_agent(top, auto_assign=True)
            if decision is None:
                return {
                    "action": "wait_for_agent",
                    "reason": "Queued work exists but no idle agents are available.",
                    "task": top,
                    "idle_agents": [],
                }
            return {
                "action": "assign_task",
                "reason": decision["reason"],
                "task": decision["task"],
                "agent": decision["agent"],
            }

        idle = self.detect_idle_agents()
        if idle:
            return {
                "action": "heartbeat",
                "reason": f"{len(idle)} idle agent(s) available; no queued work.",
                "task": None,
                "agent": idle[0],
                "idle_agents": idle,
            }

        active = [
            a
            for a in self.registry.list_agents()
            if str(a.get("status") or "").lower() in {"active", "paused", "error"}
        ]
        return {
            "action": "idle_wait",
            "reason": "No queued tasks and no idle agents.",
            "task": None,
            "agent": None,
            "busy_agents": active,
        }


# Process-wide singleton for API routes
global_brain = DecisionEngine()


def _self_test() -> None:
    print("=" * 60)
    print("DECISION ENGINE — SELF-TEST")
    print("=" * 60)

    initialize_database()
    registry = AgentRegistry()
    scheduler = TaskScheduler()
    brain = DecisionEngine(registry=registry, scheduler=scheduler)

    scout = registry.register_agent("Brain-Scout", "scout")
    worker = registry.register_agent("Brain-Worker", "worker")
    # Ensure idle
    scout.resume()
    worker.resume()
    print(f"[OK] agents ready scout={scout.uuid[:8]} worker={worker.uuid[:8]}")

    # Seed mixed-priority queue
    scheduler.queue_task("sync_crm", priority=50, required_agent_type="worker")
    scheduler.queue_task("ingest_leads", priority=40, required_agent_type="scout")
    scheduler.queue_task("critical_incident", priority=1, required_agent_type="worker")

    queued = scheduler.list_tasks(status="queued")
    ordered = brain.prioritize_tasks(queued)
    assert ordered[0]["title"] == "critical_incident"
    print(f"[OK] prioritize_tasks top={ordered[0]['title']}")

    idle = brain.detect_idle_agents()
    assert len(idle) >= 2
    print(f"[OK] detect_idle_agents count={len(idle)}")

    decision = brain.choose_next_action()
    assert decision["action"] == "assign_task"
    assert decision["task"]["title"] == "critical_incident"
    assert decision["agent"]["agent_type"] == "worker"
    print(
        f"[OK] choose_next_action assigned "
        f"{decision['task']['title']} -> {decision['agent']['name']}"
    )

    best = brain.assign_best_agent(
        {
            "task_uuid": None,
            "title": "ingest_leads",
            "required_agent_type": "scout",
            "status": "queued",
        },
        auto_assign=False,
    )
    assert best is not None
    assert best["agent"]["agent_type"] == "scout"
    print(f"[OK] assign_best_agent chose {best['agent']['name']}")

    print("=" * 60)
    print("DECISION ENGINE SELF-TEST: PASSED")
    print("=" * 60)


if __name__ == "__main__":
    _self_test()
