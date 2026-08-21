"""
Heartbeat Monitor — detects stale/missing agent heartbeats and emits alerts.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from database import initialize_database, list_agent_records, ping_agent  # noqa: E402
from scheduler.event_bus import EventBus, global_event_bus  # noqa: E402
from utils.system_health import collect_full_health, record_warning  # noqa: E402


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class HeartbeatMonitor:
    """Scan agents_registry for stale heartbeats and force pings when requested."""

    def __init__(
        self,
        *,
        stale_after_seconds: int = 120,
        event_bus: Optional[EventBus] = None,
    ) -> None:
        if stale_after_seconds < 1:
            raise ValueError("stale_after_seconds must be >= 1")
        initialize_database()
        self.stale_after_seconds = int(stale_after_seconds)
        self.bus = event_bus or global_event_bus

    def age_seconds(self, agent: dict[str, Any]) -> Optional[float]:
        pinged = _parse_ts(agent.get("last_ping_at"))
        if pinged is None:
            return None
        return max(0.0, (_utc_now() - pinged).total_seconds())

    def is_stale(self, agent: dict[str, Any]) -> bool:
        status = str(agent.get("status") or "").lower()
        if status in {"stopped"}:
            return False
        age = self.age_seconds(agent)
        if age is None:
            return True
        return age > self.stale_after_seconds

    def scan(self) -> dict[str, Any]:
        agents = list_agent_records()
        healthy: list[dict[str, Any]] = []
        stale: list[dict[str, Any]] = []
        for agent in agents:
            entry = {
                "id": agent.get("id"),
                "uuid": agent.get("agent_uuid"),
                "name": agent.get("agent_name"),
                "status": agent.get("status"),
                "last_ping_at": agent.get("last_ping_at"),
                "age_seconds": self.age_seconds(agent),
            }
            if self.is_stale(agent):
                stale.append(entry)
            else:
                healthy.append(entry)

        report = {
            "scanned": len(agents),
            "healthy": healthy,
            "stale": stale,
            "stale_count": len(stale),
            "threshold_seconds": self.stale_after_seconds,
            "scanned_at": _utc_now().replace(microsecond=0).isoformat(),
        }

        if stale:
            self.bus.emit("agent.heartbeat_stale", {"stale": stale}, source="heartbeat_monitor")
            record_warning(f"{len(stale)} stale agent heartbeat(s)", source="heartbeat_monitor")
        else:
            self.bus.emit("agent.heartbeat_ok", {"scanned": len(agents)}, source="heartbeat_monitor")

        collect_full_health()
        return report

    def pulse_agent(self, agent_id: int, *, status: Optional[str] = None) -> dict[str, Any]:
        row = ping_agent(agent_id, status=status, increment_cycle=True)
        self.bus.emit(
            "agent.heartbeat",
            {
                "agent_id": agent_id,
                "agent_uuid": row.get("agent_uuid"),
                "status": row.get("status"),
                "last_ping_at": row.get("last_ping_at"),
            },
            source="heartbeat_monitor",
        )
        return row

    def pulse_all_active(self) -> list[dict[str, Any]]:
        results = []
        for agent in list_agent_records():
            if str(agent.get("status") or "").lower() in {"stopped"}:
                continue
            if not agent.get("id"):
                continue
            results.append(self.pulse_agent(int(agent["id"]), status=agent.get("status")))
        collect_full_health()
        return results


global_heartbeat_monitor = HeartbeatMonitor()


def _self_test() -> None:
    print("=" * 60)
    print("HEARTBEAT MONITOR — SELF-TEST")
    print("=" * 60)
    from agents.base_agent import BaseAgent

    initialize_database()
    monitor = HeartbeatMonitor(stale_after_seconds=2)
    agent = BaseAgent(name="HB-Monitor-Agent", agent_type="ops")
    agent.heartbeat(status="active", current_task="watch")
    print(f"[OK] agent started id={agent.registry_id}")

    report = monitor.scan()
    assert report["scanned"] >= 1
    print(f"[OK] scan scanned={report['scanned']} stale={report['stale_count']}")

    pulsed = monitor.pulse_agent(int(agent.registry_id), status="active")
    assert pulsed["last_ping_at"]
    print(f"[OK] pulse_agent ping={pulsed['last_ping_at']}")

    # Force stale detection with tiny threshold against a never-updated legacy if any;
    # create a dedicated stale-looking agent by writing an old ping via DB.
    from database import db_session

    with db_session() as conn:
        conn.execute(
            """
            UPDATE agents_registry
            SET last_ping_at = '2000-01-01T00:00:00+00:00', status = 'active'
            WHERE id = ?
            """,
            (agent.registry_id,),
        )
    stale_report = monitor.scan()
    assert any(s.get("id") == agent.registry_id for s in stale_report["stale"])
    print("[OK] stale detection triggered")

    events = monitor.bus.list_events(topic="agent.heartbeat_stale", limit=5)
    assert len(events) >= 1
    print(f"[OK] stale events={len(events)}")
    print("=" * 60)
    print("HEARTBEAT MONITOR SELF-TEST: PASSED")
    print("=" * 60)


if __name__ == "__main__":
    _self_test()
