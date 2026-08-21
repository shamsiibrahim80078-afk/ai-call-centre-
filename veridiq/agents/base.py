"""
VERIDIQ agent base — structured JSON results, confidence, logging, retries.
"""

from __future__ import annotations

import json
import sys
import time
import traceback
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from database import db_session, initialize_database  # noqa: E402


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class VeridiqAgent(ABC):
    agent_type: str = "generic"
    max_retries: int = 2

    def __init__(self, name: Optional[str] = None) -> None:
        initialize_database()
        self.name = name or self.__class__.__name__
        self.agent_id = str(uuid.uuid4())

    @abstractmethod
    def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Return structured analysis fields (without envelope)."""

    def run(self, payload: dict[str, Any], *, job_id: Optional[str] = None) -> dict[str, Any]:
        attempt = 0
        last_error: Optional[str] = None
        started = time.perf_counter()
        while attempt <= self.max_retries:
            attempt += 1
            try:
                result = self.process(payload or {})
                confidence = float(result.get("confidence", 0.0))
                confidence = max(0.0, min(1.0, confidence))
                envelope = {
                    "ok": True,
                    "agent_id": self.agent_id,
                    "agent_name": self.name,
                    "agent_type": self.agent_type,
                    "job_id": job_id,
                    "attempt": attempt,
                    "confidence": confidence,
                    "result": result,
                    "error": None,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                    "timestamp": _utc_now_iso(),
                }
                self._log_run(envelope, payload)
                return envelope
            except Exception as exc:
                last_error = f"{exc}"
                if attempt > self.max_retries:
                    break
                time.sleep(0.15 * attempt)

        envelope = {
            "ok": False,
            "agent_id": self.agent_id,
            "agent_name": self.name,
            "agent_type": self.agent_type,
            "job_id": job_id,
            "attempt": attempt,
            "confidence": 0.0,
            "result": {},
            "error": last_error or "unknown_error",
            "traceback": traceback.format_exc(limit=3),
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "timestamp": _utc_now_iso(),
        }
        self._log_run(envelope, payload)
        return envelope

    def _log_run(self, envelope: dict[str, Any], payload: dict[str, Any]) -> None:
        with db_session() as conn:
            conn.execute(
                """
                INSERT INTO veridiq_agent_runs
                    (run_uuid, job_id, agent_type, agent_name, ok, confidence,
                     request_json, response_json, error, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    envelope.get("job_id"),
                    self.agent_type,
                    self.name,
                    1 if envelope.get("ok") else 0,
                    float(envelope.get("confidence") or 0),
                    json.dumps(payload, default=str)[:20000],
                    json.dumps(envelope, default=str)[:50000],
                    envelope.get("error"),
                    envelope.get("timestamp"),
                ),
            )
