"""
Agent Registry — in-process agent catalog synchronized with agents_registry SQLite table.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agents.base_agent import BaseAgent  # noqa: E402
from database import (  # noqa: E402
    delete_agent_record,
    get_agent_record,
    initialize_database,
    list_agent_records,
    ping_agent,
)


class AgentRegistry:
    """Process-local registry that stays synchronized with agents_registry."""

    def __init__(self) -> None:
        initialize_database()
        self._agents: dict[str, BaseAgent] = {}

    def register_agent(
        self,
        name: str,
        agent_type: str,
        *,
        agent: Optional[BaseAgent] = None,
        status: str = "idle",
    ) -> BaseAgent:
        """
        Register a new agent (or adopt an existing BaseAgent instance).
        Persists into agents_registry via BaseAgent auto-registration.
        """
        if agent is not None:
            if not isinstance(agent, BaseAgent):
                raise TypeError("agent must be a BaseAgent instance.")
            instance = agent
        else:
            instance = BaseAgent(name=name, agent_type=agent_type, status=status)

        self._agents[instance.uuid] = instance
        instance.heartbeat(status=instance.status, increment_cycle=False)
        instance.save_state()
        return instance

    def unregister_agent(self, agent_uuid: str) -> bool:
        """Remove an agent from memory and delete its agents_registry row."""
        if not agent_uuid or not agent_uuid.strip():
            raise ValueError("agent_uuid is required.")
        uid = agent_uuid.strip()
        agent = self._agents.pop(uid, None)
        if agent is not None and agent.status != "stopped":
            try:
                agent.stop()
            except Exception:
                pass
        deleted = delete_agent_record(agent_uuid=uid)
        return deleted or agent is not None

    def list_agents(self, *, refresh_from_db: bool = True) -> list[dict[str, Any]]:
        """
        List registered agents.
        When refresh_from_db=True, include DB rows even if not loaded in-process.
        DB status/task/cycle fields win over stale in-memory snapshots.
        """
        if refresh_from_db:
            db_rows = list_agent_records()
            merged: dict[str, dict[str, Any]] = {}
            for row in db_rows:
                uid = row.get("agent_uuid") or f"legacy-{row['id']}"
                merged[str(uid)] = {
                    "uuid": row.get("agent_uuid"),
                    "name": row.get("agent_name"),
                    "agent_type": row.get("agent_type"),
                    "status": row.get("status"),
                    "registry_id": row.get("id"),
                    "current_task": row.get("current_task"),
                    "total_cycles": row.get("total_cycles"),
                    "last_ping_at": row.get("last_ping_at"),
                    "in_memory": str(uid) in self._agents,
                }
            for uid, agent in self._agents.items():
                if uid in merged:
                    # Keep authoritative DB operational fields; refresh local object.
                    agent.status = str(merged[uid].get("status") or agent.status)
                    agent.current_task = merged[uid].get("current_task")
                    agent.total_cycles = int(merged[uid].get("total_cycles") or 0)
                    agent.last_ping_at = merged[uid].get("last_ping_at")
                    merged[uid]["in_memory"] = True
                    if not merged[uid].get("name"):
                        merged[uid]["name"] = agent.name
                else:
                    payload = agent.to_dict()
                    payload["in_memory"] = True
                    merged[uid] = payload
            return list(merged.values())

        return [{**agent.to_dict(), "in_memory": True} for agent in self._agents.values()]

    def get_agent(self, agent_uuid: str) -> Optional[BaseAgent]:
        """Return an in-memory BaseAgent, hydrating from DB when possible."""
        if not agent_uuid or not agent_uuid.strip():
            raise ValueError("agent_uuid is required.")
        uid = agent_uuid.strip()
        if uid in self._agents:
            return self._agents[uid]

        record = get_agent_record(agent_uuid=uid)
        if record is None:
            return None

        agent = BaseAgent(
            name=record.get("agent_name") or f"agent-{record['id']}",
            agent_type=record["agent_type"],
            agent_uuid=uid,
            status=record.get("status") or "idle",
            registry_id=int(record["id"]),
            current_task=record.get("current_task"),
            auto_register=False,
        )
        agent.total_cycles = int(record.get("total_cycles") or 0)
        agent.last_ping_at = record.get("last_ping_at")
        self._agents[uid] = agent
        return agent

    def heartbeat_all(self, *, increment_cycle: bool = True) -> list[dict[str, Any]]:
        """Heartbeat every in-memory agent; fall back to DB ping for orphan rows with uuid."""
        results: list[dict[str, Any]] = []
        seen: set[str] = set()

        for uid, agent in list(self._agents.items()):
            row = agent.heartbeat(increment_cycle=increment_cycle)
            results.append(row)
            seen.add(uid)

        for record in list_agent_records():
            uid = record.get("agent_uuid")
            if not uid or uid in seen:
                continue
            if record.get("status") == "stopped":
                continue
            row = ping_agent(
                int(record["id"]),
                status=record.get("status"),
                current_task=record.get("current_task"),
                increment_cycle=increment_cycle,
            )
            results.append(row)

        return results


# Process-wide singleton used by API routes
global_registry = AgentRegistry()


def _self_test() -> None:
    print("=" * 60)
    print("AGENT REGISTRY — SELF-TEST")
    print("=" * 60)

    initialize_database()
    registry = AgentRegistry()

    a1 = registry.register_agent("Closer-One", "closer")
    a2 = registry.register_agent("Scout-Beta", "scout")
    print(f"[OK] registered {a1.name} uuid={a1.uuid}")
    print(f"[OK] registered {a2.name} uuid={a2.uuid}")

    listed = registry.list_agents()
    assert any(item.get("uuid") == a1.uuid for item in listed)
    assert any(item.get("uuid") == a2.uuid for item in listed)
    print(f"[OK] list_agents count={len(listed)}")

    fetched = registry.get_agent(a1.uuid)
    assert fetched is not None
    assert fetched.name == "Closer-One"
    print("[OK] get_agent")

    beats = registry.heartbeat_all()
    assert len(beats) >= 2
    print(f"[OK] heartbeat_all updated={len(beats)}")

    db_row = get_agent_record(agent_uuid=a2.uuid)
    assert db_row is not None
    assert db_row["agent_name"] == "Scout-Beta"
    print(f"[OK] SQLite agents_registry contains Scout-Beta id={db_row['id']}")

    removed = registry.unregister_agent(a1.uuid)
    assert removed is True
    assert get_agent_record(agent_uuid=a1.uuid) is None
    print("[OK] unregister_agent removed SQLite row")

    print("=" * 60)
    print("AGENT REGISTRY SELF-TEST: PASSED")
    print("=" * 60)


if __name__ == "__main__":
    _self_test()
