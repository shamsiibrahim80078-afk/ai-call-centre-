"""
Autonomous Digital Workforce Platform — FastAPI Application Entry Point
Primary HTTP server with CORS, health routing, voice ingestion, and agent control APIs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from agents.registry import global_registry
from agents.scout_agent import ScoutAgent, get_scout_runtime, update_scout_runtime
from brain.decision_engine import global_brain
from brain.lead_prioritizer import prioritize_leads, priority_summary
from database import (
    execute_select_one,
    initialize_database,
    list_agent_records,
    list_leads,
)
from scheduler.task_scheduler import global_scheduler
from utils.business_analyzer import analyze_business
from utils.web_scraper import scrape_website

initialize_database()

app = FastAPI(
    title="Autonomous Digital Workforce Platform",
    description="Sovereign Swarm Core API — enterprise digital workforce control plane",
    version="1.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class VoiceCommandRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Transcribed voice command text")
    source: Optional[str] = Field(
        default="voice_pipeline",
        description="Originating voice system identifier",
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Optional session correlation id",
    )
    metadata: Optional[dict[str, Any]] = Field(
        default=None,
        description="Optional structured metadata from the voice stack",
    )


class VoiceCommandResponse(BaseModel):
    accepted: bool
    received_at: str
    source: str
    session_id: Optional[str]
    character_count: int
    message: str


class HealthResponse(BaseModel):
    status: str
    database: str
    select_one: int
    timestamp: str
    service: str


class AgentRegisterRequest(BaseModel):
    name: str = Field(..., min_length=1)
    agent_type: str = Field(..., min_length=1)
    status: str = Field(default="idle")


class AgentTaskRequest(BaseModel):
    title: str = Field(..., min_length=1)
    payload: Optional[dict[str, Any]] = None
    priority: int = Field(default=100)
    required_agent_type: Optional[str] = None
    agent_uuid: Optional[str] = Field(
        default=None,
        description="Optional explicit agent UUID; otherwise brain assigns best idle agent",
    )
    max_retries: int = Field(default=3, ge=0)
    auto_assign: bool = Field(default=True)


class ScoutStartRequest(BaseModel):
    businesses: list[dict[str, Any]] = Field(
        ...,
        min_length=1,
        description="List of business job payloads for the scout agent",
    )
    scout_name: str = Field(default="Scout-API")
    live_scrape: bool = Field(
        default=False,
        description="If true, scrape each business website live during the run",
    )


class ScoutAnalyzeRequest(BaseModel):
    website: Optional[str] = None
    business: Optional[dict[str, Any]] = None
    live_scrape: bool = True


@app.get("/api/v1/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    """
    Cluster health endpoint.
    Explicitly executes SELECT 1 against sovereign_swarm_core.db via database.py.
    """
    try:
        result = execute_select_one()
        if result != 1:
            raise HTTPException(
                status_code=503,
                detail=f"Database probe returned unexpected value: {result}",
            )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Database connectivity failure: {exc}",
        ) from exc

    return HealthResponse(
        status="ok",
        database="connected",
        select_one=result,
        timestamp=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        service="Autonomous Digital Workforce Platform",
    )


@app.post("/api/v1/voice-command", response_model=VoiceCommandResponse)
def voice_command(payload: VoiceCommandRequest) -> VoiceCommandResponse:
    """Receive text logs from voice systems and print them to the server console."""
    received_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    source = payload.source or "voice_pipeline"

    print("=" * 60)
    print("VOICE COMMAND RECEIVED")
    print(f"  time:        {received_at}")
    print(f"  source:      {source}")
    print(f"  session_id:  {payload.session_id}")
    print(f"  text:        {payload.text}")
    if payload.metadata:
        print(f"  metadata:    {payload.metadata}")
    print("=" * 60)

    return VoiceCommandResponse(
        accepted=True,
        received_at=received_at,
        source=source,
        session_id=payload.session_id,
        character_count=len(payload.text),
        message="Voice command logged successfully",
    )


@app.get("/api/v1/agents")
def list_agents() -> dict[str, Any]:
    """List all agents from the in-process registry merged with agents_registry."""
    agents = global_registry.list_agents(refresh_from_db=True)
    return {
        "count": len(agents),
        "agents": agents,
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


@app.post("/api/v1/agents/register")
def register_agent(payload: AgentRegisterRequest) -> dict[str, Any]:
    """Register a new autonomous agent into memory + agents_registry."""
    try:
        agent = global_registry.register_agent(
            name=payload.name,
            agent_type=payload.agent_type,
            status=payload.status,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Registration failed: {exc}") from exc

    return {
        "registered": True,
        "agent": agent.to_dict(),
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


@app.post("/api/v1/agents/task")
def create_agent_task(payload: AgentTaskRequest) -> dict[str, Any]:
    """
    Queue a task and optionally assign it immediately.
    If agent_uuid is omitted and auto_assign=True, the decision engine picks the best idle agent.
    """
    try:
        task = global_scheduler.queue_task(
            title=payload.title,
            payload=payload.payload,
            priority=payload.priority,
            required_agent_type=payload.required_agent_type,
            max_retries=payload.max_retries,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    assignment: Optional[dict[str, Any]] = None
    decision: Optional[dict[str, Any]] = None

    if payload.auto_assign:
        try:
            if payload.agent_uuid:
                assignment = global_scheduler.assign_task(
                    task["task_uuid"],
                    agent_uuid=payload.agent_uuid,
                )
            else:
                decision = global_brain.assign_best_agent(task, auto_assign=True)
                if decision is not None:
                    assignment = decision.get("task")
        except (LookupError, RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return {
        "queued": True,
        "task": assignment or task,
        "assigned": assignment is not None and (assignment or {}).get("status") == "assigned",
        "decision_reason": (decision or {}).get("reason"),
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


@app.get("/api/v1/agents/status")
def agents_status() -> dict[str, Any]:
    """Aggregate agent fleet status plus next brain recommendation."""
    agents = global_registry.list_agents(refresh_from_db=True)
    by_status: dict[str, int] = {}
    for agent in agents:
        key = str(agent.get("status") or "unknown")
        by_status[key] = by_status.get(key, 0) + 1

    queued = global_scheduler.list_tasks(status="queued", limit=50)
    decision = global_brain.choose_next_action()

    return {
        "total_agents": len(agents),
        "by_status": by_status,
        "queued_tasks": len(queued),
        "idle_agents": global_brain.detect_idle_agents(),
        "next_action": decision,
        "db_registry_count": len(list_agent_records()),
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


@app.get("/api/v1/leads")
def get_leads(limit: int = 200) -> dict[str, Any]:
    """Return prioritized leads from SQLite."""
    leads = prioritize_leads(list_leads(limit=limit))
    return {
        "count": len(leads),
        "leads": leads,
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


@app.post("/api/v1/scout/start")
def scout_start(payload: ScoutStartRequest) -> dict[str, Any]:
    """Run the scout agent against a batch of businesses and persist leads."""
    started = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    scout = ScoutAgent(name=payload.scout_name)
    global_registry.register_agent(
        name=scout.name,
        agent_type="scout",
        agent=scout,
    )
    update_scout_runtime(
        running=True,
        agent_uuid=scout.uuid,
        started_at=started,
        finished_at=None,
        jobs_processed=0,
        leads_created=0,
        duplicates_skipped=0,
        last_result=None,
    )

    jobs = []
    for business in payload.businesses:
        job = dict(business)
        if payload.live_scrape:
            job["live_scrape"] = True
        jobs.append(job)

    try:
        results = scout.scout_batch(jobs)
    except Exception as exc:
        update_scout_runtime(running=False, last_result={"error": str(exc)})
        raise HTTPException(status_code=500, detail=f"Scout run failed: {exc}") from exc

    finished = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    update_scout_runtime(
        running=False,
        jobs_processed=scout.jobs_processed,
        leads_created=scout.leads_created,
        duplicates_skipped=scout.duplicates_skipped,
        last_result={"batch_size": len(results)},
        finished_at=finished,
    )
    return {
        "started": True,
        "agent": scout.to_dict(),
        "processed": len(results),
        "leads_created": scout.leads_created,
        "duplicates_skipped": scout.duplicates_skipped,
        "results": results,
        "timestamp": finished,
    }


@app.post("/api/v1/scout/analyze")
def scout_analyze(payload: ScoutAnalyzeRequest) -> dict[str, Any]:
    """Scrape (optional) and analyze a single website/business payload."""
    try:
        if payload.live_scrape and payload.website:
            parsed = scrape_website(payload.website)
        elif payload.business:
            parsed = dict(payload.business)
            if payload.website and not parsed.get("website"):
                parsed["website"] = payload.website
        elif payload.website:
            parsed = scrape_website(payload.website)
        else:
            raise HTTPException(status_code=400, detail="Provide website and/or business payload.")

        report = analyze_business(parsed)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Analyze failed: {exc}") from exc

    return {
        "analyzed": True,
        "parsed": {
            "business_name": parsed.get("business_name"),
            "website": parsed.get("website"),
            "phone": parsed.get("phone"),
            "email": parsed.get("email"),
            "industry": parsed.get("industry"),
            "city": parsed.get("city"),
            "country": parsed.get("country"),
        },
        "report": report,
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


@app.get("/api/v1/scout/status")
def scout_status() -> dict[str, Any]:
    """Scout runtime status plus lead priority dashboard snapshot."""
    runtime = get_scout_runtime()
    dashboard = priority_summary(list_leads(limit=1000))
    # Avoid returning full lead dump in status; keep aggregates
    dashboard_view = {
        key: dashboard[key]
        for key in (
            "total_leads",
            "high_priority",
            "medium_priority",
            "low_priority",
            "average_opportunity_score",
            "average_automation_score",
            "average_priority_score",
        )
    }
    return {
        "runtime": runtime,
        "dashboard": dashboard_view,
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


@app.get("/")
def root() -> dict[str, str]:
    return {
        "service": "Autonomous Digital Workforce Platform",
        "docs": "/docs",
        "health": "/api/v1/health",
        "agents": "/api/v1/agents",
        "leads": "/api/v1/leads",
        "scout_status": "/api/v1/scout/status",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)
