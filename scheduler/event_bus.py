"""
Event Bus — in-process pub/sub with durable orchestration_events persistence.
"""

from __future__ import annotations

import json
import sys
import threading
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from database import db_session, initialize_database  # noqa: E402
from utils.system_health import bump_orchestration, record_error  # noqa: E402

EventHandler = Callable[[dict[str, Any]], None]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class EventBus:
    """Thread-safe event bus that persists every emission to SQLite."""

    def __init__(self) -> None:
        initialize_database()
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)
        self._lock = threading.RLock()
        self._emitted = 0

    def subscribe(self, topic: str, handler: EventHandler) -> None:
        if not topic or not topic.strip():
            raise ValueError("topic is required.")
        if not callable(handler):
            raise TypeError("handler must be callable.")
        with self._lock:
            self._handlers[topic.strip()].append(handler)

    def unsubscribe(self, topic: str, handler: EventHandler) -> bool:
        with self._lock:
            handlers = self._handlers.get(topic.strip(), [])
            if handler in handlers:
                handlers.remove(handler)
                return True
            return False

    def emit(
        self,
        topic: str,
        payload: Optional[dict[str, Any]] = None,
        *,
        source: str = "system",
    ) -> dict[str, Any]:
        if not topic or not topic.strip():
            raise ValueError("topic is required.")
        event = {
            "event_uuid": str(uuid.uuid4()),
            "topic": topic.strip(),
            "payload": payload or {},
            "source": source,
            "created_at": _utc_now_iso(),
        }
        with db_session() as conn:
            conn.execute(
                """
                INSERT INTO orchestration_events
                    (event_uuid, topic, payload, source, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    event["event_uuid"],
                    event["topic"],
                    json.dumps(event["payload"], default=str),
                    source,
                    event["created_at"],
                ),
            )

        with self._lock:
            handlers = list(self._handlers.get(event["topic"], []))
            handlers.extend(self._handlers.get("*", []))
            self._emitted += 1

        for handler in handlers:
            try:
                handler(event)
            except Exception as exc:
                record_error(f"event handler failed on {event['topic']}: {exc}", source="event_bus")

        bump_orchestration("events_emitted", 1)
        return event

    def list_events(
        self,
        *,
        topic: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with db_session() as conn:
            if topic:
                rows = conn.execute(
                    """
                    SELECT * FROM orchestration_events
                    WHERE topic = ?
                    ORDER BY id DESC LIMIT ?
                    """,
                    (topic, int(limit)),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM orchestration_events
                    ORDER BY id DESC LIMIT ?
                    """,
                    (int(limit),),
                ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            try:
                item["payload"] = json.loads(item["payload"])
            except (json.JSONDecodeError, TypeError):
                pass
            results.append(item)
        return results

    @property
    def emitted_count(self) -> int:
        return self._emitted


global_event_bus = EventBus()


def _self_test() -> None:
    print("=" * 60)
    print("EVENT BUS — SELF-TEST")
    print("=" * 60)
    initialize_database()
    bus = EventBus()
    received: list[dict[str, Any]] = []

    def on_task(event: dict[str, Any]) -> None:
        received.append(event)

    bus.subscribe("task.queued", on_task)
    event = bus.emit("task.queued", {"task_uuid": "test-1"}, source="self_test")
    assert event["event_uuid"]
    assert len(received) == 1
    print(f"[OK] emit+subscribe event_uuid={event['event_uuid']}")

    stored = bus.list_events(topic="task.queued", limit=5)
    assert any(e["event_uuid"] == event["event_uuid"] for e in stored)
    print(f"[OK] durable events in DB count_topic={len(stored)}")

    with db_session() as conn:
        total = conn.execute("SELECT COUNT(*) FROM orchestration_events").fetchone()[0]
    assert total >= 1
    print(f"[OK] orchestration_events rows={total}")
    print("=" * 60)
    print("EVENT BUS SELF-TEST: PASSED")
    print("=" * 60)


if __name__ == "__main__":
    _self_test()
