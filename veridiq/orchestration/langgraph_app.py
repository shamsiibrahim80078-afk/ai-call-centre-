"""
LangGraph StateGraph for VERIDIQ multi-agent truth orchestration.
"""

from __future__ import annotations

import sys
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from veridiq.agents import get_agent  # noqa: E402
from veridiq.orchestration.events import global_job_events  # noqa: E402
from veridiq.rag import get_rag  # noqa: E402
from veridiq.workforce.pool import global_worker_pool  # noqa: E402


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class OrchestratorState(TypedDict, total=False):
    job_id: str
    payload: dict[str, Any]
    text: str
    shared_memory: dict[str, Any]
    route: dict[str, Any]
    perception: dict[str, Any]
    evidence_out: dict[str, Any]
    rag_hits: list[dict[str, Any]]
    citations: dict[str, Any]
    credibility: dict[str, Any]
    statement: dict[str, Any]
    fact: dict[str, Any]
    risk: dict[str, Any]
    confidence: dict[str, Any]
    truth_score: float
    decision: dict[str, Any]
    report: dict[str, Any]
    trace: list[dict[str, Any]]
    result: dict[str, Any]


def _emit(job_id: str, stage: str, message: str = "", **extra: Any) -> None:
    global_job_events.emit(job_id, stage, message, **extra)
    try:
        from veridiq.workforce.collaboration import global_collaboration_hub

        global_collaboration_hub.record_event(job_id=job_id, stage=stage, message=message, **extra)
    except Exception:
        pass


def _run_agent(agent_type: str, payload: dict[str, Any], job_id: str) -> dict[str, Any]:
    _emit(job_id, "agent_start", f"Starting {agent_type}", agent_type=agent_type)

    def _fn() -> dict[str, Any]:
        return get_agent(agent_type).run(payload, job_id=job_id)

    out = global_worker_pool.run_agent_task(
        agent_type=agent_type,
        fn=_fn,
        job_id=job_id,
        task=f"{agent_type} for job {job_id[:8]}",
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


def _parallel(specs: list[tuple[str, dict[str, Any]]], job_id: str, workers: int = 4) -> dict[str, dict[str, Any]]:
    outputs: dict[str, dict[str, Any]] = {}
    if not specs:
        return outputs
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_run_agent, a, p, job_id): a for a, p in specs}
        for fut in as_completed(futures):
            outputs[futures[fut]] = fut.result()
    return outputs


def node_route(state: OrchestratorState) -> OrchestratorState:
    job_id = state["job_id"]
    payload = state["payload"]
    _emit(job_id, "route", "LangGraph routing specialized agents")
    route = _run_agent("orchestrator", payload, job_id)
    shared = dict(state.get("shared_memory") or {})
    shared["route"] = route
    trace = list(state.get("trace") or [])
    trace.append({"stage": "route", "result": route, "framework": "LangGraph"})
    return {"route": route, "shared_memory": shared, "trace": trace}


def node_perception(state: OrchestratorState) -> OrchestratorState:
    job_id = state["job_id"]
    payload = state["payload"]
    text = state["text"]
    _emit(job_id, "perception", "Running face/voice/emotion/lie perception agents")
    specs: list[tuple[str, dict[str, Any]]] = []
    if text:
        specs.extend(
            [
                ("emotion_detection", {"text": text}),
                ("lie_detection", {"text": text}),
                ("meeting_analysis", {"text": text}),
                ("timeline_builder", {"text": text}),
            ]
        )
    if payload.get("audio_path"):
        specs.append(("voice_analysis", {"audio_path": payload["audio_path"], "text": text}))
    if payload.get("image_path") or payload.get("image_bytes"):
        specs.append(
            (
                "face_analysis",
                {"image_path": payload.get("image_path"), "image_bytes": payload.get("image_bytes")},
            )
        )
    perception = _parallel(specs, job_id)
    if "lie_detection" in perception:
        perception["lie_detection"] = _run_agent(
            "lie_detection",
            {
                "text": text,
                "voice_stress": (perception.get("voice_analysis") or {}).get("result"),
                "face_analysis": (perception.get("face_analysis") or {}).get("result"),
            },
            job_id,
        )
    shared = dict(state.get("shared_memory") or {})
    shared["perception"] = perception
    trace = list(state.get("trace") or [])
    trace.append({"stage": "perception", "agents": list(perception.keys())})
    return {"perception": perception, "shared_memory": shared, "trace": trace}


def node_evidence_rag(state: OrchestratorState) -> OrchestratorState:
    job_id = state["job_id"]
    text = state["text"]
    _emit(job_id, "rag", "Semantic evidence retrieval via Qdrant RAG")
    rag = get_rag()
    rag_hits = rag.query(text, top_k=5)
    _emit(job_id, "rag_hits", f"Retrieved {len(rag_hits)} semantic neighbors", count=len(rag_hits))

    evidence_out = _parallel(
        [
            ("evidence_collection", {"text": text, "rag_hits": rag_hits}),
            ("web_search", {"query": text[:180] or "verification"}),
            ("news_verification", {"text": text[:180]}),
        ],
        job_id,
    )
    # Ingest fresh evidence into vector store
    evidence_items = (evidence_out.get("evidence_collection") or {}).get("result", {}).get("evidence", []) or []
    rag.ingest_evidence_items(evidence_items)

    citations = _run_agent(
        "citation",
        {"evidence": evidence_items},
        job_id,
    )
    credibility = _run_agent(
        "source_credibility",
        {
            "sources": [
                {"url": e.get("url")}
                for e in evidence_items
                if e.get("url")
            ]
            + [
                {"url": s.get("url")}
                for s in (evidence_out.get("news_verification") or {}).get("result", {}).get("sources", [])
            ]
            + [{"url": h.get("source")} for h in rag_hits if h.get("source")]
        },
        job_id,
    )
    shared = dict(state.get("shared_memory") or {})
    shared["rag_hits"] = rag_hits
    shared["evidence_out"] = evidence_out
    trace = list(state.get("trace") or [])
    trace.append({"stage": "evidence_rag", "agents": list(evidence_out.keys()), "rag_hits": len(rag_hits)})
    return {
        "rag_hits": rag_hits,
        "evidence_out": evidence_out,
        "citations": citations,
        "credibility": credibility,
        "shared_memory": shared,
        "trace": trace,
    }


def node_verification(state: OrchestratorState) -> OrchestratorState:
    job_id = state["job_id"]
    text = state["text"]
    evidence_out = state.get("evidence_out") or {}
    rag_hits = state.get("rag_hits") or []
    _emit(job_id, "verification", "Statement verification and fact checking")
    evidence_map = {
        e["claim"]: e
        for e in (evidence_out.get("evidence_collection") or {}).get("result", {}).get("evidence", [])
        if e.get("claim")
    }
    for hit in rag_hits:
        if hit.get("text"):
            evidence_map[str(hit["text"])[:120]] = {
                "claim": hit.get("text"),
                "url": hit.get("source"),
                "support": float(hit.get("score") or 0),
            }
    statement = _run_agent("statement_verification", {"text": text, "evidence_map": evidence_map}, job_id)
    top_claim = text
    claims = (statement.get("result") or {}).get("claims") or []
    if claims:
        top_claim = claims[0]["claim"]
    fact = _run_agent(
        "fact_checking",
        {"claim": top_claim, "rag_hits": rag_hits},
        job_id,
    )
    trace = list(state.get("trace") or [])
    trace.append({"stage": "verification", "claim": top_claim})
    return {"statement": statement, "fact": fact, "trace": trace}


def node_reasoning(state: OrchestratorState) -> OrchestratorState:
    job_id = state["job_id"]
    payload = state["payload"]
    perception = state.get("perception") or {}
    evidence_out = state.get("evidence_out") or {}
    credibility = state.get("credibility") or {}
    citations = state.get("citations") or {}
    fact = state.get("fact") or {}
    _emit(job_id, "reasoning", "Risk analysis, confidence scoring, decision")

    risk = _run_agent(
        "risk_analysis",
        {
            "lie_detection": (perception.get("lie_detection") or {}).get("result"),
            "credibility": credibility.get("result"),
            "emotion": (perception.get("emotion_detection") or {}).get("result"),
        },
        job_id,
    )
    confidence = _run_agent(
        "confidence_scoring",
        {
            "lie_detection": perception.get("lie_detection"),
            "fact_checking": fact,
            "news_verification": evidence_out.get("news_verification"),
            "source_credibility": credibility,
        },
        job_id,
    )
    deception = float(((perception.get("lie_detection") or {}).get("result") or {}).get("deception_score") or 0)
    support = float((fact.get("result") or {}).get("support_score") or 0.4)
    # Boost support slightly when RAG neighbors are strong
    rag_boost = 0.0
    hits = state.get("rag_hits") or []
    if hits:
        rag_boost = min(0.12, float(hits[0].get("score") or 0) * 0.12)
    cred = float((credibility.get("result") or {}).get("average_credibility") or 0.5)
    conf = float((confidence.get("result") or {}).get("overall_confidence") or 0.5)
    truth_score = max(
        0.0,
        min(1.0, (1 - deception) * 0.35 + (support + rag_boost) * 0.35 + cred * 0.15 + conf * 0.15),
    )
    decision = _run_agent(
        "decision",
        {"truth_score": truth_score, "risk_analysis": risk.get("result")},
        job_id,
    )
    report = _run_agent(
        "report_generator",
        {
            "title": payload.get("title") or "VERIDIQ Truth Report",
            "truth_score": round(truth_score, 4),
            "risk_analysis": risk.get("result"),
            "key_findings": [
                f"Deception score: {deception}",
                f"Fact-check verdict: {(fact.get('result') or {}).get('verdict')}",
                f"Decision: {(decision.get('result') or {}).get('decision')}",
                f"RAG neighbors: {len(hits)}",
                "Orchestrator: LangGraph",
            ],
            "citations": (citations.get("result") or {}).get("citations") or [],
        },
        job_id,
    )
    if payload.get("session_id"):
        _run_agent(
            "conversation_memory",
            {
                "session_id": payload["session_id"],
                "turn": {
                    "job_id": job_id,
                    "truth_score": truth_score,
                    "decision": (decision.get("result") or {}).get("decision"),
                    "at": _utc_now_iso(),
                },
            },
            job_id,
        )
    _emit(job_id, "confidence", "Confidence and truth score computed", truth_score=round(truth_score, 4))
    return {
        "risk": risk,
        "confidence": confidence,
        "truth_score": round(truth_score, 4),
        "decision": decision,
        "report": report,
    }


def node_finalize(state: OrchestratorState) -> OrchestratorState:
    job_id = state["job_id"]
    perception = state.get("perception") or {}
    evidence_out = state.get("evidence_out") or {}
    result = {
        "job_id": job_id,
        "truth_score": state.get("truth_score"),
        "risk_analysis": (state.get("risk") or {}).get("result"),
        "decision": (state.get("decision") or {}).get("result"),
        "confidence": (state.get("confidence") or {}).get("result"),
        "lie_detection": (perception.get("lie_detection") or {}).get("result"),
        "emotion": (perception.get("emotion_detection") or {}).get("result"),
        "voice": (perception.get("voice_analysis") or {}).get("result"),
        "face": (perception.get("face_analysis") or {}).get("result"),
        "statement_verification": (state.get("statement") or {}).get("result"),
        "fact_checking": (state.get("fact") or {}).get("result"),
        "news_verification": (evidence_out.get("news_verification") or {}).get("result"),
        "evidence": (evidence_out.get("evidence_collection") or {}).get("result"),
        "citations": (state.get("citations") or {}).get("result"),
        "source_credibility": (state.get("credibility") or {}).get("result"),
        "timeline": (perception.get("timeline_builder") or {}).get("result"),
        "meeting": (perception.get("meeting_analysis") or {}).get("result"),
        "report": (state.get("report") or {}).get("result"),
        "rag_hits": state.get("rag_hits") or [],
        "shared_memory": state.get("shared_memory") or {},
        "orchestrator": "LangGraph",
        "trace": state.get("trace") or [],
        "timestamp": _utc_now_iso(),
    }
    _emit(job_id, "report_ready", "Truth report assembled", truth_score=result["truth_score"])
    return {"result": result}


def build_langgraph_app():
    graph = StateGraph(OrchestratorState)
    graph.add_node("route", node_route)
    graph.add_node("perception", node_perception)
    graph.add_node("evidence_rag", node_evidence_rag)
    graph.add_node("verification", node_verification)
    graph.add_node("reasoning", node_reasoning)
    graph.add_node("finalize", node_finalize)
    graph.add_edge(START, "route")
    graph.add_edge("route", "perception")
    graph.add_edge("perception", "evidence_rag")
    graph.add_edge("evidence_rag", "verification")
    graph.add_edge("verification", "reasoning")
    graph.add_edge("reasoning", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()


_compiled = None


def get_compiled_graph():
    global _compiled
    if _compiled is None:
        _compiled = build_langgraph_app()
    return _compiled


def run_langgraph(payload: dict[str, Any], *, job_id: Optional[str] = None) -> dict[str, Any]:
    job_id = job_id or str(uuid.uuid4())
    text = str(payload.get("text") or payload.get("transcript") or "")
    _emit(job_id, "orchestrator", "LangGraph multi-agent run started", framework="LangGraph")
    initial: OrchestratorState = {
        "job_id": job_id,
        "payload": payload,
        "text": text,
        "shared_memory": {"job_id": job_id, "text": text, "input": payload},
        "trace": [],
    }
    final_state = get_compiled_graph().invoke(initial)
    result = final_state.get("result") or {}
    return result
