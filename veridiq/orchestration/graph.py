"""
VERIDIQ orchestration façade — LangGraph-backed multi-agent execution.
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from database import db_session, initialize_database  # noqa: E402
from veridiq.orchestration.events import global_job_events  # noqa: E402
from veridiq.orchestration.langgraph_app import run_langgraph  # noqa: E402


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class SharedMemory:
    def __init__(self) -> None:
        self.state: dict[str, Any] = {}

    def update(self, **kwargs: Any) -> None:
        self.state.update(kwargs)

    def get(self, key: str, default: Any = None) -> Any:
        return self.state.get(key, default)


class VeridiqOrchestrator:
    """Production multi-agent orchestrator powered by LangGraph."""

    def __init__(self, max_workers: int = 4) -> None:
        initialize_database()
        self.max_workers = max_workers
        self.memory = SharedMemory()
        self.framework = "LangGraph"

    def execute(self, payload: dict[str, Any], *, job_id: Optional[str] = None) -> dict[str, Any]:
        job_id = job_id or str(uuid.uuid4())
        text = str(payload.get("text") or payload.get("transcript") or "")
        self.memory.update(job_id=job_id, text=text, input=payload, framework=self.framework)
        try:
            result = run_langgraph(payload, job_id=job_id)
            self._persist_trace(job_id, result)
            self.memory.update(result=result, shared=result.get("shared_memory") or {})
            global_job_events.emit(
                job_id,
                "orchestration_complete",
                "LangGraph orchestration completed",
                truth_score=result.get("truth_score"),
            )
            return result
        except Exception as exc:
            global_job_events.emit(job_id, "failed", str(exc))
            raise

    def _persist_trace(self, job_id: str, result: dict[str, Any]) -> None:
        with db_session() as conn:
            conn.execute(
                """
                INSERT INTO veridiq_traces (trace_uuid, job_id, graph_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    job_id,
                    json.dumps(
                        {
                            "framework": "LangGraph",
                            "trace": result.get("trace"),
                            "rag_hits": len(result.get("rag_hits") or []),
                        },
                        default=str,
                    ),
                    _utc_now_iso(),
                ),
            )


global_orchestrator = VeridiqOrchestrator()
