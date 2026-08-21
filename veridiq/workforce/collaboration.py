"""Agent Collaboration Hub — messages derived from real workflow events only."""

from __future__ import annotations

import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any, Optional

from veridiq.workforce.identities import identity_for

_STAGE_TEMPLATES = {
    "route": ("orchestrator", "Planning agent assignments for this request."),
    "agent_start": (None, "Beginning specialized analysis."),
    "agent_complete": (None, "Completed analysis step."),
    "perception": ("orchestrator", "Delegating perception and signal extraction."),
    "evidence_rag": ("evidence_collection", "Requesting corroborating evidence and RAG recall."),
    "rag": ("conversation_memory", "Retrieving related knowledge from vector memory."),
    "rag_hits": ("conversation_memory", "Shared retrieved context with verification peers."),
    "verification": ("statement_verification", "Requesting independent verification of claims."),
    "reasoning": ("confidence_scoring", "Merging evidence into confidence and risk reasoning."),
    "confidence": ("confidence_scoring", "Updated probabilistic confidence estimate."),
    "report_ready": ("report_generator", "Assembling structured truth report."),
    "market_plan": ("market_research", "Breaking market request into specialist subtasks."),
    "market_evidence": ("market_research", "Gathering market evidence from official APIs."),
    "market_reasoning": ("market_risk", "Synthesizing risks and alternative scenarios."),
    "delegation": (None, "Delegating subtask to specialist."),
    "evidence_request": ("evidence_collection", "Requesting additional supporting sources."),
    "verification_request": ("fact_checking", "Requesting independent verification."),
    "progress": (None, "Progress update."),
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class CollaborationHub:
    def __init__(self, maxlen: int = 400) -> None:
        self._lock = threading.Lock()
        self._messages: deque[dict[str, Any]] = deque(maxlen=maxlen)

    def record_event(
        self,
        *,
        job_id: Optional[str],
        stage: str,
        message: str = "",
        agent_type: Optional[str] = None,
        **extra: Any,
    ) -> dict[str, Any]:
        template_agent, template_msg = _STAGE_TEMPLATES.get(stage, (None, message or stage))
        agent = agent_type or template_agent or "orchestrator"
        ident = identity_for(agent)
        body = message.strip() or template_msg
        if stage == "agent_complete" and extra.get("confidence") is not None:
            try:
                pct = round(float(extra["confidence"]) * 100)
                body = f"{body} Confidence signal: {pct}%."
            except Exception:
                pass
        if stage == "confidence" and extra.get("truth_score") is not None:
            try:
                pct = round(float(extra["truth_score"]) * 100)
                body = f"Confidence updated to approximately {pct}% (probabilistic, not a guarantee)."
            except Exception:
                pass
        entry = {
            "id": f"{job_id or 'sys'}-{stage}-{_utc_now()}-{len(self._messages)}",
            "job_id": job_id,
            "stage": stage,
            "speaker": {
                "agent_type": agent,
                "name": ident.get("name"),
                "role": ident.get("role"),
                "avatar_hue": ident.get("avatar_hue"),
            },
            "message": body,
            "kind": _kind_for_stage(stage),
            "extra": {k: v for k, v in extra.items() if k not in {"message"}},
            "timestamp": _utc_now(),
        }
        with self._lock:
            self._messages.append(entry)
        return entry

    def recent(self, *, limit: int = 80, job_id: Optional[str] = None) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._messages)
        if job_id:
            items = [m for m in items if m.get("job_id") == job_id]
        return list(reversed(items[-limit:]))

    def snapshot(self) -> dict[str, Any]:
        msgs = self.recent(limit=80)
        return {
            "count": len(msgs),
            "messages": msgs,
            "note": "Messages are derived from real workflow/SSE events — not fabricated chat.",
            "timestamp": _utc_now(),
        }


def _kind_for_stage(stage: str) -> str:
    if stage in {"delegation", "route", "market_plan"}:
        return "task_delegation"
    if stage in {"evidence_rag", "rag", "rag_hits", "evidence_request"}:
        return "evidence_request"
    if stage in {"verification", "verification_request"}:
        return "verification_request"
    if stage in {"reasoning", "confidence", "market_reasoning"}:
        return "reasoning_summary"
    if stage in {"agent_start", "agent_complete", "progress"}:
        return "progress_update"
    if stage in {"decision"}:
        return "workflow_decision"
    return "workflow_event"


global_collaboration_hub = CollaborationHub()
