"""Live platform activity log — populated only by real connector/integration calls.

Never fabricated: entries are written exclusively at the point a real outbound
call is attempted (or explicitly skipped due to missing configuration). When no
integration has been exercised yet, the log is empty.

Phase 5.1: persisted to `veridiq_integration_activity` (SQLite) instead of an
in-memory ring buffer, so the activity feed survives a backend restart. The
public `PlatformActivityLog` interface (`record`, `recent`, `snapshot`) and
`global_platform_activity` singleton are unchanged — callers across
`app.py`/`veridiq/*` need zero changes.
"""

from __future__ import annotations

import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from database import db_session, initialize_database  # noqa: E402


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class PlatformActivityLog:
    """SQLite-backed activity log. `maxlen` is retained for API compatibility
    and used as a soft cap (rolling prune) instead of a bounded in-memory deque.
    """

    def __init__(self, maxlen: int = 300) -> None:
        self._lock = threading.Lock()
        self._maxlen = maxlen
        self._ready = False

    def _ensure_ready(self) -> None:
        if not self._ready:
            initialize_database()
            self._ready = True

    def record(
        self,
        *,
        platform: str,
        task: str,
        agent_type: Optional[str] = None,
        job_id: Optional[str] = None,
        workflow_stage: Optional[str] = None,
        started_at: Optional[str] = None,
        progress: Optional[float] = None,
        completion_status: str = "completed",
        api_response_status: Optional[str] = None,
        recent_activity: Optional[str] = None,
        errors: Optional[str] = None,
    ) -> dict[str, Any]:
        self._ensure_ready()
        started = started_at or _utc_now()
        finished = _utc_now()
        resolved_progress = progress if progress is not None else (1.0 if completion_status == "completed" else 0.5)
        resolved_activity = recent_activity or task
        with self._lock, db_session() as conn:
            cur = conn.execute(
                """
                INSERT INTO veridiq_integration_activity
                    (platform, agent_type, job_id, task, workflow_stage, started_at, finished_at,
                     progress, completion_status, api_response_status, recent_activity, errors)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    platform,
                    agent_type,
                    job_id,
                    task,
                    workflow_stage,
                    started,
                    finished,
                    resolved_progress,
                    completion_status,
                    api_response_status,
                    resolved_activity,
                    errors,
                ),
            )
            row_id = cur.lastrowid
            # Rolling prune keeps the table bounded, mirroring the old deque(maxlen=...).
            conn.execute(
                "DELETE FROM veridiq_integration_activity WHERE id < (SELECT MAX(id) - ? FROM veridiq_integration_activity)",
                (self._maxlen,),
            )
        return {
            "id": row_id,
            "agent_type": agent_type,
            "job_id": job_id,
            "platform": platform,
            "task": task,
            "workflow_stage": workflow_stage,
            "started_at": started,
            "finished_at": finished,
            "progress": resolved_progress,
            "completion_status": completion_status,
            "api_response_status": api_response_status,
            "recent_activity": resolved_activity,
            "errors": errors,
        }

    def recent(
        self,
        *,
        limit: int = 60,
        platform: Optional[str] = None,
        agent_type: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        self._ensure_ready()
        query = "SELECT * FROM veridiq_integration_activity"
        clauses = []
        params: list[Any] = []
        if platform:
            clauses.append("platform = ?")
            params.append(platform)
        if agent_type:
            clauses.append("agent_type = ?")
            params.append(agent_type)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(max(1, limit))
        with db_session() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [dict(r) for r in rows]

    def snapshot(self) -> dict[str, Any]:
        items = self.recent(limit=100)
        return {
            "count": len(items),
            "activity": items,
            "note": (
                "No integration calls recorded yet — this list is never simulated."
                if not items
                else "Derived from real integration/connector calls only — not simulated."
            ),
            "timestamp": _utc_now(),
        }


global_platform_activity = PlatformActivityLog()
