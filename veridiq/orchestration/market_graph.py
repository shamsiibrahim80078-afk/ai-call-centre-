"""Market Intelligence LangGraph-style pipeline (parallel specialists → merge)."""

from __future__ import annotations

import json
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from veridiq.agents import get_agent
from veridiq.market.data import market_overview
from veridiq.orchestration.events import global_job_events
from veridiq.workforce.collaboration import global_collaboration_hub
from veridiq.workforce.pool import global_worker_pool

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from database import db_session  # noqa: E402


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _persist_market_trace(job_id: str, results: dict[str, Any], final: dict[str, Any]) -> None:
    """Mirror VeridiqOrchestrator._persist_trace() so the market pipeline gets
    the same veridiq_traces audit-trail coverage as the truth pipeline
    (Implementation Plan §5.3)."""
    try:
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
                            "framework": "LangGraph-Market",
                            "trace": {k: {"ok": v.get("ok"), "confidence": v.get("confidence")} for k, v in results.items()},
                            "confidence": final.get("confidence"),
                        },
                        default=str,
                    ),
                    _utc_now_iso(),
                ),
            )
    except Exception:
        pass  # audit trace persistence must never break the market pipeline response

MARKET_AGENT_MAP = {
    "market_plan": ["market_research"],
    "market_evidence": [
        "market_research",
        "technical_analysis",
        "sentiment_analysis",
        "news_correlation",
        "macro_trend",
        "onchain_analysis",
    ],
    "market_reasoning": ["market_risk", "portfolio_intelligence"],
}


def _emit(job_id: str, stage: str, message: str = "", **extra: Any) -> None:
    global_job_events.emit(job_id, stage, message, **extra)
    global_collaboration_hub.record_event(job_id=job_id, stage=stage, message=message, **extra)


def _run(agent_type: str, payload: dict[str, Any], job_id: str) -> dict[str, Any]:
    _emit(job_id, "agent_start", f"Starting {agent_type}", agent_type=agent_type)

    def _fn() -> dict[str, Any]:
        return get_agent(agent_type).run(payload, job_id=job_id)

    out = global_worker_pool.run_agent_task(
        agent_type=agent_type,
        fn=_fn,
        job_id=job_id,
        task=f"{agent_type} market job {job_id[:8]}",
    )
    _emit(
        job_id,
        "agent_complete",
        f"Completed {agent_type}",
        agent_type=agent_type,
        ok=out.get("ok"),
        confidence=out.get("confidence"),
    )
    return out


def run_market_intelligence(
    text: str,
    *,
    job_id: Optional[str] = None,
    coin_id: str = "bitcoin",
) -> dict[str, Any]:
    job_id = job_id or str(uuid.uuid4())
    overview = market_overview(per_page=20, agent_type="market_research", job_id=job_id)
    payload = {"text": text, "coin_id": coin_id, "market_overview": overview, "mode": "market", "job_id": job_id}

    _emit(job_id, "route", "User request received — market intelligence mode")
    _emit(job_id, "market_plan", "Task planner splitting market request into specialist subtasks")
    plan = _run("market_research", payload, job_id)

    _emit(job_id, "market_evidence", "Assigning parallel market evidence agents")
    evidence_agents = [
        "technical_analysis",
        "sentiment_analysis",
        "news_correlation",
        "macro_trend",
        "onchain_analysis",
    ]
    results: dict[str, Any] = {"market_research": plan}
    with ThreadPoolExecutor(max_workers=5) as pool:
        futs = {pool.submit(_run, a, payload, job_id): a for a in evidence_agents}
        for fut in as_completed(futs):
            results[futs[fut]] = fut.result()

    _emit(job_id, "market_reasoning", "Merging specialist outputs into risk + portfolio framing")
    risk = _run("market_risk", {**payload, "specialists": results}, job_id)
    portfolio = _run("portfolio_intelligence", {**payload, "specialists": results}, job_id)
    results["market_risk"] = risk
    results["portfolio_intelligence"] = portfolio

    confidences = [float(v.get("confidence") or 0) for v in results.values() if isinstance(v, dict)]
    avg_conf = round(sum(confidences) / len(confidences), 4) if confidences else 0.0

    evidence: list[Any] = []
    sources: list[str] = []
    risks: list[str] = []
    alts: list[str] = []
    for v in results.values():
        r = (v or {}).get("result") or {}
        evidence.extend(r.get("evidence") or [])
        sources.extend(r.get("sources") or [])
        risks.extend(r.get("risks") or [])
        alts.extend(r.get("alternative_scenarios") or [])

    final = {
        "ok": True,
        "mode": "market_intelligence",
        "job_id": job_id,
        "request": text,
        "confidence": avg_conf,
        "evidence": evidence[:40],
        "sources": sorted(set(sources)),
        "risks": sorted(set(risks)),
        "alternative_scenarios": sorted(set(alts))[:8],
        "specialists": {k: {"ok": v.get("ok"), "confidence": v.get("confidence"), "result": v.get("result")} for k, v in results.items()},
        "market_overview": overview,
        "disclaimer": "Probabilistic market analysis only — not financial advice, predictions, or guarantees.",
        "workflow": [
            "user_request",
            "task_planner",
            "agent_assignment",
            "evidence_retrieval",
            "verification",
            "reasoning",
            "report_generation",
            "completed",
        ],
    }
    _emit(job_id, "report_ready", "Market intelligence brief ready", truth_score=avg_conf)
    _emit(job_id, "completed", "Market intelligence workflow completed", truth_score=avg_conf)
    _persist_market_trace(job_id, results, final)
    return final
