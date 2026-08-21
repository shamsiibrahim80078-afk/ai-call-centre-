"""Leadership cascade workflow — CEO → Directors → one worker each (SDK + pool).

Extends the existing Agent SDK / worker pool; does not replace LangGraph truth/market graphs.
When cascade=True, directors execute synchronously so the chain is verifiable end-to-end.
"""

from __future__ import annotations

from typing import Any, Optional

from scheduler.event_bus import global_event_bus
from veridiq.agents import get_agent
from veridiq.workforce import control as agent_control
from veridiq.workforce.pool import global_worker_pool


def run_leadership_cascade(
    instruction: str = "Align teams and report readiness",
    *,
    job_id: Optional[str] = None,
) -> dict[str, Any]:
    """Run CEO with cascade=True so Directors execute and each runs one worker."""
    agent_control.assert_runnable("ceo")
    payload = {
        "instruction": instruction,
        "text": instruction,
        "cascade": True,
        "execute_directors": True,
    }

    def _runner() -> dict[str, Any]:
        return get_agent("ceo").run(payload, job_id=job_id)

    envelope = global_worker_pool.run_agent_task(
        agent_type="ceo",
        task=f"leadership_cascade:{instruction[:80]}",
        fn=_runner,
        job_id=job_id,
        min_visible_sec=0.0,
    )
    global_event_bus.emit(
        "leadership.cascade.completed",
        {
            "ok": bool(isinstance(envelope, dict) and envelope.get("ok")),
            "job_id": job_id,
            "instruction": instruction[:200],
        },
        source="leadership_cascade",
    )
    result = envelope.get("result") if isinstance(envelope, dict) else {}
    return {
        "ok": bool(isinstance(envelope, dict) and envelope.get("ok")),
        "framework": "AgentSDK+WorkerPool",
        "langgraph_note": "Truth/market pipelines remain on LangGraph; leadership uses SDK cascade on the same pool.",
        "envelope": envelope,
        "cascade": (result or {}).get("cascade"),
        "director_assignments": (result or {}).get("director_assignments"),
        "summary": (result or {}).get("summary"),
    }
