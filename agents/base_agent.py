"""
Production BaseAgent — reusable autonomous worker primitive.
Persists heartbeats and state into sovereign_swarm_core.db via database.py.
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

from database import (  # noqa: E402
    db_session,
    get_agent_record,
    initialize_database,
    ping_agent,
    save_agent,
    update_agent_record,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class BaseAgent:
    """Reusable production-grade autonomous agent with DB-backed heartbeats."""

    VALID_STATUSES = frozenset({"idle", "active", "paused", "stopped", "error"})

    def __init__(
        self,
        name: str,
        agent_type: str,
        *,
        agent_uuid: Optional[str] = None,
        status: str = "idle",
        registry_id: Optional[int] = None,
        current_task: Optional[str] = None,
        auto_register: bool = True,
    ) -> None:
        if not name or not name.strip():
            raise ValueError("agent name is required.")
        if not agent_type or not agent_type.strip():
            raise ValueError("agent_type is required.")
        if status not in self.VALID_STATUSES:
            raise ValueError(f"Invalid status '{status}'. Allowed: {sorted(self.VALID_STATUSES)}")

        initialize_database()

        self.uuid: str = agent_uuid or str(uuid.uuid4())
        self.name: str = name.strip()
        self.agent_type: str = agent_type.strip()
        self.status: str = status
        self.current_task: Optional[str] = current_task
        self.registry_id: Optional[int] = registry_id
        self.total_cycles: int = 0
        self.last_ping_at: Optional[str] = None
        self._state: dict[str, Any] = {}

        if auto_register:
            self._ensure_registry_row()

    def _ensure_registry_row(self) -> None:
        """Create or bind this agent to an agents_registry row."""
        existing = get_agent_record(agent_uuid=self.uuid)
        if existing:
            self.registry_id = int(existing["id"])
            self.status = str(existing["status"])
            self.current_task = existing["current_task"]
            self.total_cycles = int(existing["total_cycles"] or 0)
            self.last_ping_at = existing["last_ping_at"]
            if existing["agent_name"]:
                self.name = str(existing["agent_name"])
            return

        self.registry_id = save_agent(
            agent_type=self.agent_type,
            status=self.status,
            current_task=self.current_task,
            total_cycles=0,
            agent_uuid=self.uuid,
            agent_name=self.name,
        )

    def heartbeat(
        self,
        *,
        status: Optional[str] = None,
        current_task: Optional[str] = None,
        increment_cycle: bool = True,
    ) -> dict[str, Any]:
        """
        Emit a heartbeat and persist it to agents_registry.
        Updates last_ping_at, optional status/task, and total_cycles.
        """
        if self.registry_id is None:
            self._ensure_registry_row()
        assert self.registry_id is not None

        if status is not None:
            if status not in self.VALID_STATUSES:
                raise ValueError(f"Invalid status '{status}'.")
            self.status = status
        if current_task is not None:
            self.current_task = current_task

        row = ping_agent(
            self.registry_id,
            status=self.status,
            current_task=self.current_task,
            increment_cycle=increment_cycle,
        )
        # Ensure uuid/name stay synchronized on the registry row
        update_agent_record(
            self.registry_id,
            agent_uuid=self.uuid,
            agent_name=self.name,
        )
        refreshed = get_agent_record(agent_id=self.registry_id) or row
        self.total_cycles = int(refreshed.get("total_cycles") or 0)
        self.last_ping_at = refreshed.get("last_ping_at")
        self.status = str(refreshed.get("status") or self.status)
        self.current_task = refreshed.get("current_task")
        return dict(refreshed)

    def execute(self, task: Optional[str] = None, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """
        Execute a unit of work. Marks the agent active, heartbeats, and returns a result envelope.
        Subclasses may override `_run_task` for specialized behavior.
        """
        if self.status == "stopped":
            raise RuntimeError(f"Agent '{self.name}' is stopped and cannot execute.")
        if self.status == "paused":
            raise RuntimeError(f"Agent '{self.name}' is paused; call resume() first.")

        task_name = task or self.current_task or "noop"
        self.status = "active"
        self.current_task = task_name
        self.heartbeat(status="active", current_task=task_name)

        started = _utc_now_iso()
        try:
            result = self._run_task(task_name, payload or {})
            self.status = "idle"
            self.current_task = None
            self.heartbeat(status="idle", current_task=None, increment_cycle=False)
            envelope = {
                "ok": True,
                "agent_uuid": self.uuid,
                "agent_name": self.name,
                "task": task_name,
                "started_at": started,
                "finished_at": _utc_now_iso(),
                "result": result,
            }
            self._state["last_execution"] = envelope
            self.save_state()
            return envelope
        except Exception as exc:
            self.status = "error"
            self.heartbeat(status="error", current_task=task_name, increment_cycle=False)
            raise RuntimeError(f"Agent '{self.name}' failed executing '{task_name}': {exc}") from exc

    def _run_task(self, task: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Default task runner used by BaseAgent; override in subclasses."""
        return {
            "task": task,
            "payload": payload,
            "message": f"BaseAgent '{self.name}' completed '{task}'",
        }

    def pause(self) -> dict[str, Any]:
        """Pause the agent; heartbeats remain allowed but execute() is blocked."""
        if self.status == "stopped":
            raise RuntimeError(f"Agent '{self.name}' is stopped and cannot be paused.")
        self.status = "paused"
        row = self.heartbeat(status="paused", increment_cycle=False)
        self.save_state()
        return row

    def resume(self) -> dict[str, Any]:
        """Resume a paused agent back to idle readiness."""
        if self.status == "stopped":
            raise RuntimeError(f"Agent '{self.name}' is stopped and cannot be resumed.")
        self.status = "idle"
        row = self.heartbeat(status="idle", current_task=None, increment_cycle=False)
        self.save_state()
        return row

    def stop(self) -> dict[str, Any]:
        """Permanently stop the agent for this process lifetime (until re-registered)."""
        self.status = "stopped"
        self.current_task = None
        row = self.heartbeat(status="stopped", current_task=None, increment_cycle=False)
        self.save_state()
        return row

    def save_state(self) -> dict[str, Any]:
        """Persist full agent runtime state into the agent_state table."""
        stamped = _utc_now_iso()
        snapshot = {
            "uuid": self.uuid,
            "name": self.name,
            "agent_type": self.agent_type,
            "status": self.status,
            "registry_id": self.registry_id,
            "current_task": self.current_task,
            "total_cycles": self.total_cycles,
            "last_ping_at": self.last_ping_at,
            "internal_state": self._state,
            "saved_at": stamped,
        }
        with db_session() as conn:
            conn.execute(
                """
                INSERT INTO agent_state
                    (agent_uuid, agent_name, agent_type, status, registry_id,
                     current_task, state_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(agent_uuid) DO UPDATE SET
                    agent_name = excluded.agent_name,
                    agent_type = excluded.agent_type,
                    status = excluded.status,
                    registry_id = excluded.registry_id,
                    current_task = excluded.current_task,
                    state_json = excluded.state_json,
                    updated_at = excluded.updated_at
                """,
                (
                    self.uuid,
                    self.name,
                    self.agent_type,
                    self.status,
                    self.registry_id,
                    self.current_task,
                    json.dumps(snapshot),
                    stamped,
                ),
            )
        return snapshot

    def to_dict(self) -> dict[str, Any]:
        return {
            "uuid": self.uuid,
            "name": self.name,
            "agent_type": self.agent_type,
            "status": self.status,
            "registry_id": self.registry_id,
            "current_task": self.current_task,
            "total_cycles": self.total_cycles,
            "last_ping_at": self.last_ping_at,
        }


def _self_test() -> None:
    print("=" * 60)
    print("BASE AGENT — SELF-TEST")
    print("=" * 60)

    initialize_database()
    print("[OK] database connectivity established")

    agent = BaseAgent(name="Scout-Alpha", agent_type="scout")
    print(f"[OK] created agent uuid={agent.uuid} registry_id={agent.registry_id}")
    assert agent.registry_id is not None

    hb = agent.heartbeat(status="active", current_task="probe_network")
    assert hb["agent_uuid"] == agent.uuid or get_agent_record(agent_id=agent.registry_id)["agent_uuid"] == agent.uuid
    assert hb["last_ping_at"]
    print(f"[OK] heartbeat written cycles={agent.total_cycles} ping={agent.last_ping_at}")

    record = get_agent_record(agent_uuid=agent.uuid)
    assert record is not None
    assert record["agent_name"] == "Scout-Alpha"
    assert record["agent_type"] == "scout"
    print(f"[OK] agents_registry row verified id={record['id']}")

    result = agent.execute(task="scan_market", payload={"region": "us-west"})
    assert result["ok"] is True
    print(f"[OK] execute returned task={result['task']}")

    agent.pause()
    assert agent.status == "paused"
    print("[OK] pause()")

    agent.resume()
    assert agent.status == "idle"
    print("[OK] resume()")

    state = agent.save_state()
    assert state["uuid"] == agent.uuid
    print("[OK] save_state()")

    agent.stop()
    assert agent.status == "stopped"
    print("[OK] stop()")

    print("=" * 60)
    print("BASE AGENT SELF-TEST: PASSED")
    print("=" * 60)


if __name__ == "__main__":
    _self_test()
