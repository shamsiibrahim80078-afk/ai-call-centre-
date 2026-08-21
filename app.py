"""
VERIDIQ — Truth Verification Platform
FastAPI entry point: auth, multi-agent orchestration, truth pipeline, workforce APIs.
"""

from __future__ import annotations

import os
from pathlib import Path

# Load .env before modules that read secrets
_env_path = Path(__file__).resolve().parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if not key:
            continue
        # Fill missing or blank so empty placeholders don't block real .env values.
        if not (os.environ.get(key) or "").strip():
            os.environ[key] = val

# Also load via shared helper (idempotent) so connectors imported without app see .env.
from veridiq.integrations.base import ensure_dotenv_loaded  # noqa: E402

ensure_dotenv_loaded()

import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr, Field
import json

from veridiq import (
    APP_NAME,
    ARCHITECTURE,
    GREETING,
    HOST_BRAIN_INTRO,
    TAGLINE,
    VERSION,
)
from veridiq.agents import AGENT_REGISTRY, get_agent
from veridiq.auth.security import (
    authenticate_user,
    create_user,
    ensure_bootstrap_admin,
    get_current_user,
    get_optional_user,
    issue_token,
    security as bearer_security,
)
from veridiq.orchestration.events import global_job_events
from veridiq.orchestration.graph import global_orchestrator
from veridiq.pipeline.truth_pipeline import UPLOAD_DIR, global_pipeline
from veridiq.rag import get_rag
from veridiq.security_uploads import read_validated_upload

from blockchain.deploy_service import (
    contracts_status,
    deploy_contracts,
    list_contracts_from_db,
    verify_contracts,
)
from blockchain.integration import global_blockchain
from veridiq.connectors import connectors_status, jobs_connector, news_connector
from veridiq.workforce import global_worker_pool, identity_for
from veridiq.host_assistant import answer_host_question
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
from scheduler.auto_recovery import global_auto_recovery
from scheduler.event_bus import global_event_bus
from scheduler.heartbeat_monitor import global_heartbeat_monitor
from scheduler.priority_dispatcher import global_priority_dispatcher
from scheduler.task_queue import global_task_queue
from scheduler.task_scheduler import global_scheduler
from scheduler.workflow_engine import global_workflow_engine
from utils.business_analyzer import analyze_business
from utils.system_health import collect_full_health, load_health
from utils.web_scraper import scrape_website

initialize_database()
ensure_bootstrap_admin()


@asynccontextmanager
async def _app_lifespan(_app: FastAPI):
    from veridiq.integrations import telegram as telegram_mod
    from veridiq.integrations.telegram_listener import start_telegram_listener, stop_telegram_listener

    if telegram_mod.listener_in_api_enabled():
        start_telegram_listener()
    # Timed calling worker — enforces per-call max + daily budget without blocking requests.
    _stop_calling_worker = None
    try:
        from veridiq.calling.worker import start_calling_worker, stop_calling_worker as _stop_fn

        start_calling_worker()
        _stop_calling_worker = _stop_fn
    except Exception:
        _stop_calling_worker = None
    # Optional: auto-probe + agency cascade/drafts on boot (no silent outbound sends)
    if os.getenv("VERIDIQ_AUTO_AGENCY_RUN", "").strip().lower() in {"1", "true", "yes", "on"}:
        import threading

        def _boot_agency() -> None:
            try:
                from veridiq.runtime.auto_agency import run_auto_agency

                run_auto_agency(run_cascade=True, run_marketing=True, approve_sends=False)
            except Exception:
                pass

        threading.Thread(target=_boot_agency, daemon=True, name="veridiq-auto-agency").start()
    yield
    stop_telegram_listener()
    if _stop_calling_worker is not None:
        try:
            _stop_calling_worker()
        except Exception:
            pass


app = FastAPI(
    title=APP_NAME,
    description=f"{TAGLINE} — multi-agent truth verification platform",
    version=VERSION,
    lifespan=_app_lifespan,
)

_CORS_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "VERIDIQ_CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000",
    ).split(",")
    if o.strip()
]
# Keep * for local tooling unless explicitly locked down
if os.getenv("VERIDIQ_CORS_STRICT", "0") != "1":
    _CORS_ORIGINS = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Cache CORS preflight responses in the browser. Without this, every GET with
    # a JSON Content-Type / Authorization header (i.e. almost every dashboard
    # poll) re-triggers a full OPTIONS preflight, silently doubling real request
    # volume against the rate limiter below.
    max_age=int(os.getenv("VERIDIQ_CORS_MAX_AGE", "3600")),
)

# Simple in-memory rate limiter (per client IP). Configurable via env so local/dev
# deployments are never starved — a single live dashboard session legitimately
# opens several polling/SSE pages at once (workforce, ops, system, dashboard,
# collaboration...). Historically this defaulted to 120/60s (2 req/s), which was
# far too low and produced a 429 storm under normal single-user use, not abuse;
# the effective value also used to be silently overridden back down to 120 by
# .env, which has been corrected alongside this change.
_RATE_BUCKETS: dict[str, deque[float]] = defaultdict(deque)
_RATE_LIMIT = int(os.getenv("VERIDIQ_RATE_LIMIT", "1200"))
_RATE_WINDOW = float(os.getenv("VERIDIQ_RATE_WINDOW", "60"))
# CORS preflight (OPTIONS) requests and long-lived SSE streams never count
# against the quota: a preflight carries no application work, and a single held
# SSE connection (or its reconnect-on-drop) shouldn't compete with normal polling
# for the same per-IP budget.
_RATE_LIMIT_EXEMPT_PATH_SUBSTRINGS = ("/events",)


def _is_rate_limit_exempt(request: Request) -> bool:
    if request.method == "OPTIONS":
        return True
    path = request.url.path
    return any(s in path for s in _RATE_LIMIT_EXEMPT_PATH_SUBSTRINGS)


@app.middleware("http")
async def rate_limit_and_security_headers(request: Request, call_next):
    if not _is_rate_limit_exempt(request):
        client = request.client.host if request.client else "unknown"
        now = time.time()
        bucket = _RATE_BUCKETS[client]
        while bucket and now - bucket[0] > _RATE_WINDOW:
            bucket.popleft()
        if len(bucket) >= _RATE_LIMIT:
            retry_after = max(1, int(_RATE_WINDOW - (now - bucket[0])))
            return JSONResponse(
                status_code=429,
                content={"detail": "rate limit exceeded", "retry_after_sec": retry_after},
                headers={"Retry-After": str(retry_after)},
            )
        bucket.append(now)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Veridiq-Version"] = VERSION
    return response


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


class OrchestrationEnqueueRequest(BaseModel):
    title: str = Field(..., min_length=1)
    payload: Optional[dict[str, Any]] = None
    priority: int = 100
    required_agent_type: Optional[str] = None
    max_retries: int = Field(default=3, ge=0)


class WorkflowCreateRequest(BaseModel):
    name: str = Field(..., min_length=1)
    steps: list[dict[str, Any]] = Field(..., min_length=1)
    context: Optional[dict[str, Any]] = None
    run_immediately: bool = True


class ContractDeployRequest(BaseModel):
    network: str = Field(default="Hardhat", description="Hardhat, Sepolia, Base, or Ethereum")
    dry_run: bool = Field(default=True, description="Force local Hardhat dry-run when true")


class ContractVerifyRequest(BaseModel):
    network: str = Field(default="Hardhat")
    dry_run: bool = Field(default=True)


class AuthRegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    full_name: str = ""


class AuthLoginRequest(BaseModel):
    email: EmailStr
    password: str


class AuthClerkSyncRequest(BaseModel):
    email: str = ""
    full_name: str = ""


class TelegramWebAppAuthRequest(BaseModel):
    init_data: str = Field(..., min_length=1, description="Telegram.WebApp.initData string")
    issue_session: bool = True
    max_age_sec: int = Field(86400, ge=0, le=604800)


class AgentInvokeRequest(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)
    job_id: Optional[str] = None


class OrchestrateRequest(BaseModel):
    text: str = Field(..., min_length=1)
    title: Optional[str] = "VERIDIQ Verification"
    audio_path: Optional[str] = None
    image_path: Optional[str] = None
    session_id: Optional[str] = None


class VerifyTextRequest(BaseModel):
    text: str = Field(..., min_length=1)
    title: str = "VERIDIQ Verification"
    session_id: Optional[str] = None
    async_mode: bool = False


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
        service=APP_NAME,
    )


@app.get("/api/v1/brand")
def brand_info() -> dict[str, Any]:
    return {
        "name": APP_NAME,
        "tagline": TAGLINE,
        "greeting": GREETING,
        "host_intro": HOST_BRAIN_INTRO,
        "architecture": ARCHITECTURE,
        "version": VERSION,
        "agents": sorted(AGENT_REGISTRY.keys()),
    }


@app.post("/api/v1/auth/register")
def auth_register(payload: AuthRegisterRequest) -> dict[str, Any]:
    try:
        user = create_user(payload.email, payload.password, payload.full_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    token = issue_token(user)
    return {"user": user, "access_token": token, "token_type": "bearer"}


@app.post("/api/v1/auth/login")
def auth_login(payload: AuthLoginRequest) -> dict[str, Any]:
    try:
        user = authenticate_user(payload.email, payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    token = issue_token(user)
    return {"user": user, "access_token": token, "token_type": "bearer"}


@app.get("/api/v1/auth/me")
def auth_me(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    return {"user": user}


@app.get("/api/v1/auth/clerk/status")
def auth_clerk_status() -> dict[str, Any]:
    from veridiq.auth.clerk_jwt import clerk_configured, clerk_frontend_api, clerk_publishable_key, clerk_secret_key

    pk = clerk_publishable_key() or ""
    sk = clerk_secret_key() or ""
    fapi = clerk_frontend_api()
    if pk.startswith("pk_live_"):
        key_mode = "live"
    elif pk.startswith("pk_test_"):
        key_mode = "test"
    elif pk:
        key_mode = "invalid"
    else:
        key_mode = "missing"
    sk_mode = "live" if sk.startswith("sk_live_") else "test" if sk.startswith("sk_test_") else ("set" if sk else "missing")
    if key_mode == "test":
        message = (
            "Clerk development keys (pk_test_) — local sign-in OK. "
            "Production deploys need a Clerk Production instance with pk_live_/sk_live_ "
            "(Dashboard → API Keys). Do not invent live keys."
        )
    elif key_mode == "live" and clerk_configured():
        message = "Clerk production keys (pk_live_) configured — use /sign-in and /sign-up"
    elif clerk_configured():
        message = "Clerk ready — use /sign-in and /sign-up"
    else:
        message = (
            "Set VERIDIQ_CLERK_PUBLISHABLE_KEY + VERIDIQ_CLERK_SECRET_KEY "
            "(and VITE_CLERK_PUBLISHABLE_KEY for the Vite app)"
        )
    return {
        "configured": clerk_configured(),
        "publishable_key_set": bool(pk),
        "secret_key_set": bool(sk),
        "key_mode": key_mode,
        "secret_key_mode": sk_mode,
        "production_ready": key_mode == "live" and sk_mode == "live",
        "frontend_api": fapi,
        "sign_in_path": "/sign-in",
        "sign_up_path": "/sign-up",
        "message": message,
    }


@app.post("/api/v1/auth/clerk/sync")
def auth_clerk_sync(
    payload: AuthClerkSyncRequest,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_security),
) -> dict[str, Any]:
    """Exchange a verified Clerk session JWT for a VERIDIQ access token."""
    from veridiq.auth.clerk_jwt import sync_clerk_session

    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=401, detail="Clerk session token required")
    try:
        return sync_clerk_session(
            credentials.credentials,
            email=payload.email,
            full_name=payload.full_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"invalid Clerk token: {exc}") from exc


from veridiq.orchestration.graph_map import LANGGRAPH_AGENT_MAP, nodes_for_agent  # noqa: E402


# Growth/Marketing Agency specialists are intentionally standalone (not part
# of the truth-verification or market-intelligence LangGraph pipelines) —
# each acts through its own official integration + approval gate instead.
# Reported honestly as "standalone", not "missing".
STANDALONE_AGENT_TYPES = {
    "ai_calling",
    "linkedin_outreach",
    "sales_intelligence",
    "marketing_manager",
    "content_creator",
    "social_poster",
    "telegram_community",
    "x_twitter_voice",
    "influencer_relations",
    "ceo",
    "director_operations",
    "director_growth",
    "director_intelligence",
}


@app.get("/api/v1/veridiq/agents/connectivity")
def veridiq_agent_connectivity() -> dict[str, Any]:
    from veridiq.orchestration.market_graph import MARKET_AGENT_MAP

    wired = sorted(
        {a for agents in LANGGRAPH_AGENT_MAP.values() for a in agents}
        | {a for agents in MARKET_AGENT_MAP.values() for a in agents}
    )
    registered = sorted(AGENT_REGISTRY.keys())
    missing = sorted(set(registered) - set(wired))
    standalone = sorted(set(missing) & STANDALONE_AGENT_TYPES)
    unwired_core = sorted(set(missing) - STANDALONE_AGENT_TYPES)
    return {
        "framework": "LangGraph",
        "registered_count": len(registered),
        "wired_count": len(wired),
        "registered": registered,
        "wired_to_langgraph": wired,
        "graph_nodes": {**LANGGRAPH_AGENT_MAP, **MARKET_AGENT_MAP},
        "unwired": missing,
        "standalone_agents": standalone,
        "ok": len(unwired_core) == 0,
    }


@app.get("/api/v1/veridiq/agents/pipeline/health")
def veridiq_agents_pipeline_health() -> dict[str, Any]:
    """Read-only aggregate: marketing handoff, postings agent, calling budget/worker."""
    out: dict[str, Any] = {"ok": True, "modules": {}}

    # Marketing handoff (artifact dir + import)
    try:
        from veridiq.marketing.postings_handoff import HANDOFF_DIR, _enabled

        handoff_dir = HANDOFF_DIR
        handoff_dir.mkdir(parents=True, exist_ok=True)
        count = len(list(handoff_dir.glob("handoff-*.json")))
        out["modules"]["marketing"] = {
            "ok": True,
            "handoff_enabled": _enabled(),
            "handoff_dir": str(handoff_dir).replace("\\", "/"),
            "artifact_count": count,
        }
    except Exception as exc:  # noqa: BLE001
        out["ok"] = False
        out["modules"]["marketing"] = {"ok": False, "error": str(exc)[:200]}

    # Postings agent persona (no core logic)
    try:
        from veridiq.postings.studio import agent_persona as postings_persona

        persona = postings_persona()
        out["modules"]["postings"] = {
            "ok": True,
            "name": persona.get("name"),
            "agent_type": persona.get("agent_type") or "posting_studio",
        }
    except Exception as exc:  # noqa: BLE001
        out["ok"] = False
        out["modules"]["postings"] = {"ok": False, "error": str(exc)[:200]}

    # Calling budget + LiveKit + worker
    try:
        from veridiq.calling.budget import budget_status
        from veridiq.calling.livekit_tokens import livekit_status
        from veridiq.calling.worker import worker_status

        out["modules"]["calling"] = {
            "ok": True,
            "budget": budget_status(agent_type="ai_calling", user_key="default"),
            "livekit": livekit_status(),
            "worker": worker_status(),
        }
    except Exception as exc:  # noqa: BLE001
        out["ok"] = False
        out["modules"]["calling"] = {"ok": False, "error": str(exc)[:200]}

    return out


@app.get("/api/v1/veridiq/agents")
def veridiq_list_agents() -> dict[str, Any]:
    pool = global_worker_pool.snapshot()
    active_types = {a["agent_type"] for a in pool["assignments"]}
    agents = []
    for key, cls in sorted(AGENT_REGISTRY.items()):
        ident = identity_for(key)
        stats = (pool.get("agent_stats") or {}).get(key) or {}
        agents.append(
            {
                "agent_type": key,
                "class_name": cls().name,
                "name": ident.get("name"),
                "identity": ident,
                "status": "working" if key in active_types else "idle",
                "current_assignment": next(
                    (a for a in pool["assignments"] if a["agent_type"] == key),
                    None,
                ),
                "metrics": {
                    "runs": stats.get("runs", 0),
                    "success_rate": stats.get("success_rate"),
                    "avg_latency_ms": stats.get("avg_latency_ms"),
                    "reliability_score": stats.get("success_rate"),
                },
            }
        )
    return {"count": len(agents), "agents": agents, "workforce": pool}


@app.get("/api/v1/veridiq/agents/{agent_type}")
def veridiq_agent_detail(agent_type: str) -> dict[str, Any]:
    if agent_type not in AGENT_REGISTRY:
        raise HTTPException(status_code=404, detail="unknown agent")
    from veridiq.workforce.departments import department_for_agent
    from veridiq.workforce.roster import BIOS, build_roster

    pool = global_worker_pool.snapshot()
    stats = (pool.get("agent_stats") or {}).get(agent_type) or {}
    history = [h for h in pool.get("recent_history") or [] if h.get("agent_type") == agent_type]
    identity = identity_for(agent_type)
    roster_card = next((c for c in build_roster()["cards"] if c["agent_type"] == agent_type), {})
    current_assignment = next((a for a in pool["assignments"] if a["agent_type"] == agent_type), None)
    working = current_assignment is not None
    return {
        "agent_type": agent_type,
        "identity": identity,
        "name": identity.get("name"),
        "email": identity.get("internal_email"),
        "department": department_for_agent(agent_type),
        "biography": roster_card.get("biography") or BIOS.get(agent_type),
        "status": "working" if working else "idle",
        "status_label": "Working" if working else "Waiting for Assignment",
        "last_status": roster_card.get("last_status"),
        "current_assignment": current_assignment,
        "current_workflow": (current_assignment or {}).get("job_id"),
        "workflow_stage": (current_assignment or {}).get("stage"),
        "responsibilities": identity.get("specialty"),
        "skills": identity.get("skills"),
        "assigned_models": roster_card.get("assigned_models"),
        "connected_tools": roster_card.get("connected_tools"),
        "metrics": {
            "runs": stats.get("runs", 0),
            "ok": stats.get("ok", 0),
            "failed": stats.get("failed", 0),
            "success_rate": stats.get("success_rate"),
            "avg_latency_ms": stats.get("avg_latency_ms"),
            "reliability_score": stats.get("success_rate"),
        },
        "langgraph_nodes": nodes_for_agent(agent_type),
        "api_dependencies": ["/api/v1/veridiq/agents/{agent_type}/run", "/api/v1/veridiq/orchestrate", "/api/v1/veridiq/requests"],
        "backend_services": ["LangGraph", "Qdrant RAG", "SQLite", "SSE event bus", "AI worker pool"],
        "recent_tasks": history[:20],
        "logs": history[:20],
        "execution_history": history[:40],
        "task_history": history[:40],
        "activity_history": history[:20],
    }


@app.post("/api/v1/veridiq/agents/{agent_type}/run")
def veridiq_run_agent(agent_type: str, payload: AgentInvokeRequest) -> dict[str, Any]:
    """Primary "Run" action backing the Agent Workspace / Agent Detail Start-Run-Stop
    controls. Non-blocking: acquires a real worker slot and returns immediately with
    `status: started` + a `run_id` and poll URLs, while the agent executes on a
    background thread. Poll `GET .../agents/{agent_type}` or the workforce SSE stream
    to watch it flip working -> idle, or `GET .../runs/{run_id}` for the final envelope.
    """
    try:
        agent = get_agent(agent_type)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    from veridiq.workforce import control as agent_control

    try:
        agent_control.assert_runnable(agent_type)
    except agent_control.AgentStoppedError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"Agent '{agent_type}' is {exc.status}. Resume it via /api/v1/veridiq/agents/{agent_type}/control/resume first.",
        ) from exc

    # An empty payload would deterministically fail agents that require input
    # (fact_checking, web_search, ...) — fall back to the same representative
    # sample payload "Run Agent Test" uses, so a bare "Run" click always
    # exercises a real, meaningful code path instead of a guaranteed error.
    effective_payload = payload.payload
    if not effective_payload:
        from veridiq.integrations.agent_test import SAMPLE_PAYLOADS

        effective_payload = dict(SAMPLE_PAYLOADS.get(agent_type, {}))

    # Give every run a job_id (even if the caller didn't supply one) so it
    # also surfaces as a live in-flight entry on the Live Agent Runtime page
    # (/dashboard/runtime, /dashboard/live) for the duration of the run —
    # not just in the Agent Workspace / workforce SSE stream.
    run_job_id = payload.job_id or f"agent-run-{uuid.uuid4().hex[:12]}"

    from veridiq.marketing.team_run import MARKETING_AGENT_TYPES, build_run_payload

    if agent_type in MARKETING_AGENT_TYPES and not effective_payload.get("campaign_id"):
        from veridiq.marketing import get_or_create_default_campaign

        campaign = get_or_create_default_campaign()
        effective_payload = {
            **build_run_payload(agent_type, campaign["campaign_id"], team_run=False),
            **effective_payload,
        }

    def _fn():
        return agent.run(effective_payload, job_id=run_job_id)

    min_visible = global_worker_pool.marketing_min_visible_sec() if agent_type in MARKETING_AGENT_TYPES else None
    channel_hint = None
    if agent_type in MARKETING_AGENT_TYPES:
        channels = effective_payload.get("channels") or []
        channel_hint = channels[0] if channels else None
    return global_worker_pool.start_agent_task(
        agent_type=agent_type,
        fn=_fn,
        job_id=run_job_id,
        task=(
            f"Marketing run — drafting {channel_hint} content"
            if channel_hint
            else f"Run {agent_type}"
        ),
        min_visible_sec=min_visible,
        platform=channel_hint,
        channel=channel_hint,
    )


@app.get("/api/v1/veridiq/agents/{agent_type}/runs/{run_id}")
def veridiq_run_result(agent_type: str, run_id: str) -> dict[str, Any]:
    """Poll the final envelope for a run started via POST .../run (async)."""
    if agent_type not in AGENT_REGISTRY:
        raise HTTPException(status_code=404, detail="unknown agent")
    run = global_worker_pool.get_run(run_id)
    if run is None:
        return {"run_id": run_id, "agent_type": agent_type, "status": "pending_or_unknown"}
    status = "failed" if run.get("error") or run.get("ok") is False else "completed"
    return {"run_id": run_id, "agent_type": agent_type, "status": status, **run}


# ---------------------------------------------------------------------------
# Task 1 — Agent control / runtime layer (start/stop/pause/resume, commands,
# campaign assignment, execution monitoring). Built on the existing worker
# pool + roster/workspace/departments primitives in veridiq/workforce/.
# ---------------------------------------------------------------------------

class AgentCommandRequest(BaseModel):
    command: str = Field(..., min_length=1, description="e.g. 'ping' or 'run_task'")
    payload: Optional[dict[str, Any]] = None


class AgentAssignRequest(BaseModel):
    campaign_type: str = Field(..., min_length=1, description="run_task | verify | market_intelligence | comms | ai_calling")
    payload: Optional[dict[str, Any]] = None


@app.get("/api/v1/veridiq/control")
def veridiq_control_overview(user: Optional[dict[str, Any]] = Depends(get_optional_user)) -> dict[str, Any]:
    """Admin overview of every agent's control status — for the Agent Control panel."""
    from veridiq.workforce.control import list_controls

    controls = list_controls()
    by_status: dict[str, int] = {}
    for c in controls.values():
        by_status[c["status"]] = by_status.get(c["status"], 0) + 1
    return {
        "count": len(controls),
        "controls": controls,
        "by_status": by_status,
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


@app.get("/api/v1/veridiq/agents/{agent_type}/control")
def veridiq_agent_control_get(agent_type: str) -> dict[str, Any]:
    if agent_type not in AGENT_REGISTRY:
        raise HTTPException(status_code=404, detail="unknown agent")
    from veridiq.workforce.control import agent_runtime_overview

    return agent_runtime_overview(agent_type)


def _control_actor(user: Optional[dict[str, Any]]) -> Optional[str]:
    return (user or {}).get("email") if user else None


@app.post("/api/v1/veridiq/agents/{agent_type}/control/start")
def veridiq_agent_control_start(agent_type: str, user: Optional[dict[str, Any]] = Depends(get_optional_user)) -> dict[str, Any]:
    from veridiq.workforce.control import UnknownAgentError, set_status

    try:
        return {"ok": True, "control": set_status(agent_type, "running", actor=_control_actor(user))}
    except UnknownAgentError as exc:
        raise HTTPException(status_code=404, detail="unknown agent") from exc


@app.post("/api/v1/veridiq/agents/{agent_type}/control/stop")
def veridiq_agent_control_stop(agent_type: str, user: Optional[dict[str, Any]] = Depends(get_optional_user)) -> dict[str, Any]:
    from veridiq.workforce.control import UnknownAgentError, set_status

    try:
        return {"ok": True, "control": set_status(agent_type, "stopped", actor=_control_actor(user))}
    except UnknownAgentError as exc:
        raise HTTPException(status_code=404, detail="unknown agent") from exc


@app.post("/api/v1/veridiq/agents/{agent_type}/control/pause")
def veridiq_agent_control_pause(agent_type: str, user: Optional[dict[str, Any]] = Depends(get_optional_user)) -> dict[str, Any]:
    from veridiq.workforce.control import UnknownAgentError, set_status

    try:
        return {"ok": True, "control": set_status(agent_type, "paused", actor=_control_actor(user))}
    except UnknownAgentError as exc:
        raise HTTPException(status_code=404, detail="unknown agent") from exc


@app.post("/api/v1/veridiq/agents/{agent_type}/control/resume")
def veridiq_agent_control_resume(agent_type: str, user: Optional[dict[str, Any]] = Depends(get_optional_user)) -> dict[str, Any]:
    from veridiq.workforce.control import UnknownAgentError, set_status

    try:
        return {"ok": True, "control": set_status(agent_type, "running", actor=_control_actor(user))}
    except UnknownAgentError as exc:
        raise HTTPException(status_code=404, detail="unknown agent") from exc


@app.post("/api/v1/veridiq/agents/{agent_type}/control/command")
def veridiq_agent_control_command(
    agent_type: str, payload: AgentCommandRequest, user: Optional[dict[str, Any]] = Depends(get_optional_user)
) -> dict[str, Any]:
    from veridiq.workforce.control import UnknownAgentError, send_command

    try:
        return send_command(agent_type, payload.command, payload.payload, actor=_control_actor(user))
    except UnknownAgentError as exc:
        raise HTTPException(status_code=404, detail="unknown agent") from exc


@app.post("/api/v1/veridiq/agents/{agent_type}/control/assign")
def veridiq_agent_control_assign(
    agent_type: str, payload: AgentAssignRequest, user: Optional[dict[str, Any]] = Depends(get_optional_user)
) -> dict[str, Any]:
    from veridiq.workforce.control import UnknownAgentError, assign_campaign

    try:
        return assign_campaign(agent_type, payload.campaign_type, payload.payload, actor=_control_actor(user))
    except UnknownAgentError as exc:
        raise HTTPException(status_code=404, detail="unknown agent") from exc


# ---------------------------------------------------------------------------
# Task 2 — "Run Agent Test" admin capability: agent init, platform connection
# check, real task execution, result collection, error reporting.
# ---------------------------------------------------------------------------

class AgentTestRequest(BaseModel):
    platform: Optional[str] = None
    payload: Optional[dict[str, Any]] = None


@app.post("/api/v1/veridiq/agents/{agent_type}/test")
def veridiq_agent_run_test(agent_type: str, payload: AgentTestRequest) -> dict[str, Any]:
    if agent_type not in AGENT_REGISTRY:
        raise HTTPException(status_code=404, detail="unknown agent")
    from veridiq.integrations.agent_test import run_agent_test

    return run_agent_test(agent_type, platform=payload.platform, payload=payload.payload)


@app.get("/api/v1/veridiq/agents/{agent_type}/test/history")
def veridiq_agent_test_history(agent_type: str, limit: int = 20) -> dict[str, Any]:
    if agent_type not in AGENT_REGISTRY:
        raise HTTPException(status_code=404, detail="unknown agent")
    from veridiq.integrations.agent_test import list_test_runs

    runs = list_test_runs(agent_type, limit=limit)
    return {"count": len(runs), "runs": runs}


@app.get("/api/v1/veridiq/agent-tests")
def veridiq_agent_tests_recent(limit: int = 50) -> dict[str, Any]:
    """Cross-agent recent test run feed, for an admin-facing test dashboard."""
    from veridiq.integrations.agent_test import list_test_runs

    runs = list_test_runs(limit=limit)
    return {"count": len(runs), "runs": runs}


# ---------------------------------------------------------------------------
# Agent SDK + OS monitoring — inter-agent tasks, shared memory, live status
# ---------------------------------------------------------------------------

class SdkSendTaskRequest(BaseModel):
    to_agent: str
    task: dict[str, Any] | str
    priority: int = 100
    execute: bool = False
    job_id: Optional[str] = None


class SdkAskRequest(BaseModel):
    to_agent: str
    question: dict[str, Any] | str
    job_id: Optional[str] = None


class SdkMemoryRequest(BaseModel):
    key: str
    value: Optional[Any] = None
    scope: str = "shared"
    tags: Optional[list[str]] = None
    load_only: bool = False


class SdkToolRequest(BaseModel):
    tool: str
    args: Optional[dict[str, Any]] = None


class SdkProgressRequest(BaseModel):
    task_id: Optional[str] = None
    progress: float = 0.0
    stage: Optional[str] = None
    confidence: Optional[float] = None
    eta_sec: Optional[float] = None
    message: Optional[str] = None
    logs: Optional[list[str]] = None


class SdkCompleteRequest(BaseModel):
    task_id: str
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    confidence: Optional[float] = None


class SdkStreamRequest(BaseModel):
    chunk: Any
    task_id: Optional[str] = None
    stream_id: Optional[str] = None
    done: bool = False


@app.get("/api/v1/veridiq/sdk/tools")
def veridiq_sdk_tools() -> dict[str, Any]:
    from veridiq.sdk.tools import list_tools

    tools = list_tools()
    return {"count": len(tools), "tools": tools}


@app.post("/api/v1/veridiq/sdk/{agent_type}/sendTask")
def veridiq_sdk_send_task(agent_type: str, payload: SdkSendTaskRequest) -> dict[str, Any]:
    from veridiq.sdk import get_sdk

    try:
        return get_sdk(agent_type).sendTask(
            payload.to_agent,
            payload.task,
            priority=payload.priority,
            execute=payload.execute,
            job_id=payload.job_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/veridiq/sdk/{agent_type}/receiveTask")
def veridiq_sdk_receive_task(agent_type: str, limit: int = 10, claim: bool = True) -> dict[str, Any]:
    from veridiq.sdk import get_sdk

    try:
        return get_sdk(agent_type).receiveTask(limit=limit, claim_only=claim)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/veridiq/sdk/{agent_type}/askAgent")
def veridiq_sdk_ask_agent(agent_type: str, payload: SdkAskRequest) -> dict[str, Any]:
    from veridiq.sdk import get_sdk

    try:
        return get_sdk(agent_type).askAgent(payload.to_agent, payload.question, job_id=payload.job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/veridiq/sdk/{agent_type}/shareMemory")
def veridiq_sdk_share_memory(agent_type: str, payload: SdkMemoryRequest) -> dict[str, Any]:
    from veridiq.sdk import get_sdk

    try:
        return get_sdk(agent_type).shareMemory(
            payload.key,
            payload.value,
            scope=payload.scope,
            tags=payload.tags,
            load_only=payload.load_only,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/veridiq/sdk/{agent_type}/executeTool")
def veridiq_sdk_execute_tool(agent_type: str, payload: SdkToolRequest) -> dict[str, Any]:
    from veridiq.sdk import get_sdk

    try:
        return get_sdk(agent_type).executeTool(payload.tool, **(payload.args or {}))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/veridiq/sdk/{agent_type}/streamOutput")
def veridiq_sdk_stream_output(agent_type: str, payload: SdkStreamRequest) -> dict[str, Any]:
    from veridiq.sdk import get_sdk

    try:
        return get_sdk(agent_type).streamOutput(
            payload.chunk,
            task_id=payload.task_id,
            stream_id=payload.stream_id,
            done=payload.done,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/veridiq/sdk/{agent_type}/reportProgress")
def veridiq_sdk_report_progress(agent_type: str, payload: SdkProgressRequest) -> dict[str, Any]:
    from veridiq.sdk import get_sdk

    try:
        return get_sdk(agent_type).reportProgress(
            task_id=payload.task_id,
            progress=payload.progress,
            stage=payload.stage,
            confidence=payload.confidence,
            eta_sec=payload.eta_sec,
            message=payload.message,
            logs=payload.logs,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/veridiq/sdk/{agent_type}/completeTask")
def veridiq_sdk_complete_task(agent_type: str, payload: SdkCompleteRequest) -> dict[str, Any]:
    from veridiq.sdk import get_sdk

    try:
        return get_sdk(agent_type).completeTask(
            payload.task_id,
            result=payload.result,
            error=payload.error,
            confidence=payload.confidence,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/veridiq/os/monitor")
def veridiq_os_monitor(agent_type: Optional[str] = None, limit: int = 40) -> dict[str, Any]:
    from veridiq.os.monitoring import live_agent_monitor

    return live_agent_monitor(agent_type=agent_type, limit=limit)


@app.get("/api/v1/veridiq/os/memory")
def veridiq_os_memory(limit: int = 50) -> dict[str, Any]:
    from veridiq.os.shared_memory import shared_memory_snapshot

    return shared_memory_snapshot(limit=limit)


class LeadershipCascadeRequest(BaseModel):
    instruction: str = "Align teams and report readiness"
    job_id: Optional[str] = None


@app.post("/api/v1/veridiq/os/cascade")
def veridiq_os_cascade(payload: LeadershipCascadeRequest) -> dict[str, Any]:
    """CEO → Directors → workers via Agent SDK + worker pool (verified cascade)."""
    from veridiq.orchestration.leadership_cascade import run_leadership_cascade
    from veridiq.workforce.control import AgentStoppedError, UnknownAgentError

    try:
        return run_leadership_cascade(payload.instruction, job_id=payload.job_id)
    except UnknownAgentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentStoppedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


class AutoAgencyRequest(BaseModel):
    instruction: str = "Auto agency run: probe platforms, cascade leadership, queue marketing drafts"
    run_cascade: bool = True
    run_marketing: bool = True


@app.post("/api/v1/veridiq/os/auto-agency")
def veridiq_os_auto_agency(payload: AutoAgencyRequest) -> dict[str, Any]:
    """Probe connectors + run agencies on whatever is configured. Never fabricates OAuth."""
    from veridiq.runtime.auto_agency import run_auto_agency

    return run_auto_agency(
        instruction=payload.instruction,
        run_cascade=payload.run_cascade,
        run_marketing=payload.run_marketing,
        approve_sends=False,
    )


@app.get("/api/v1/veridiq/os/platform-probe")
def veridiq_os_platform_probe() -> dict[str, Any]:
    from veridiq.runtime.auto_agency import probe_all_platforms

    return probe_all_platforms()


@app.post("/api/v1/veridiq/sdk/{agent_type}/processInbox")
def veridiq_sdk_process_inbox(agent_type: str, limit: int = 5, execute: bool = True) -> dict[str, Any]:
    from veridiq.sdk import get_sdk

    return get_sdk(agent_type).processInbox(limit=limit, execute=execute)


class PlatformActionRequest(BaseModel):
    args: Optional[dict[str, Any]] = None
    agent_type: Optional[str] = None


@app.get("/api/v1/veridiq/platforms")
def veridiq_platforms() -> dict[str, Any]:
    from veridiq.integrations.platform_api import list_platforms

    return list_platforms()


@app.get("/api/v1/veridiq/platforms/{platform}")
def veridiq_platform_detail(platform: str) -> dict[str, Any]:
    from veridiq.integrations.platform_api import PLATFORM_ACTIONS, MODULE_ALIASES, dispatch

    key = platform.strip().lower()
    aliases = {"browser": "browser_playwright", "webrtc": "webrtc_signaling", "email_smtp": "email", "twilio_calling": "ai_calling"}
    key = aliases.get(key, key)
    if key not in PLATFORM_ACTIONS:
        raise HTTPException(status_code=404, detail="unknown platform")
    return {
        "platform": key,
        "module": MODULE_ALIASES.get(key, key),
        "actions": sorted(PLATFORM_ACTIONS[key].keys()),
        "status": dispatch(key, "status"),
    }


@app.post("/api/v1/veridiq/platforms/{platform}/{action}")
def veridiq_platform_action(platform: str, action: str, payload: PlatformActionRequest) -> dict[str, Any]:
    """Unified internal API — agents and UI call platforms only through VERIDIQ."""
    from veridiq.integrations.platform_api import dispatch

    return dispatch(platform, action, args=payload.args or {}, agent_type=payload.agent_type)


class WebRtcRoomRequest(BaseModel):
    label: Optional[str] = None
    agent_type: Optional[str] = None


class WebRtcSignalRequest(BaseModel):
    room_id: str
    sdp: str
    from_peer: str = "client"


@app.post("/api/v1/veridiq/webrtc/rooms")
def veridiq_webrtc_create_room(payload: WebRtcRoomRequest) -> dict[str, Any]:
    from veridiq.integrations import webrtc_signaling

    return webrtc_signaling.create_room(label=payload.label, agent_type=payload.agent_type)


@app.post("/api/v1/veridiq/webrtc/offer")
def veridiq_webrtc_offer(payload: WebRtcSignalRequest) -> dict[str, Any]:
    from veridiq.integrations import webrtc_signaling

    return webrtc_signaling.create_offer(room_id=payload.room_id, sdp=payload.sdp, from_peer=payload.from_peer)


@app.post("/api/v1/veridiq/webrtc/answer")
def veridiq_webrtc_answer(payload: WebRtcSignalRequest) -> dict[str, Any]:
    from veridiq.integrations import webrtc_signaling

    return webrtc_signaling.create_answer(room_id=payload.room_id, sdp=payload.sdp, from_peer=payload.from_peer)


@app.get("/api/v1/veridiq/webrtc/rooms/{room_id}/signals")
def veridiq_webrtc_signals(room_id: str, limit: int = 50) -> dict[str, Any]:
    from veridiq.integrations import webrtc_signaling

    return webrtc_signaling.list_signals(room_id=room_id, limit=limit)


@app.get("/api/v1/veridiq/workforce")
def veridiq_workforce() -> dict[str, Any]:
    return global_worker_pool.snapshot()


@app.get("/api/v1/veridiq/workforce/roster")
def veridiq_workforce_roster(department: Optional[str] = None, q: Optional[str] = None) -> dict[str, Any]:
    from veridiq.workforce.roster import build_roster

    return build_roster(department=department, q=q)


@app.get("/api/v1/veridiq/workspace")
def veridiq_workspace() -> dict[str, Any]:
    """Agent Workspace — departments -> agents, with queues, logs, and connected APIs."""
    from veridiq.workforce.workspace import build_workspace

    return build_workspace()


@app.get("/api/v1/veridiq/workspace/{agent_type}")
def veridiq_workspace_agent(agent_type: str) -> dict[str, Any]:
    if agent_type not in AGENT_REGISTRY:
        raise HTTPException(status_code=404, detail="unknown agent")
    from veridiq.workforce.workspace import build_workspace

    return build_workspace(agent_type=agent_type)


@app.get("/api/v1/veridiq/workforce/events")
async def veridiq_workforce_events(request: Request, interval: float = 2.0) -> StreamingResponse:
    """SSE stream of live roster snapshots + collaboration + active assignments.

    Frontend subscribes for a live workforce view without polling; falls back
    to polling automatically if the connection drops. Nothing here is
    fabricated — every field mirrors the same pool/collaboration state used
    by the plain HTTP roster endpoint.
    """
    import asyncio

    from database import db_session
    from veridiq.comms import list_drafts
    from veridiq.integrations.activity import global_platform_activity
    from veridiq.marketing.team_run import pending_count
    from veridiq.workforce.collaboration import global_collaboration_hub
    from veridiq.workforce.roster import build_roster

    poll_interval = max(0.5, min(10.0, interval))

    async def event_generator():
        while True:
            if await request.is_disconnected():
                break
            roster = build_roster()
            pool = roster.get("workforce") or {}
            pending_n = 0
            pending_preview: list[dict[str, Any]] = []
            sdk_running: list[dict[str, Any]] = []
            try:
                pending_n = int(pending_count() or 0)
            except Exception:
                pending_n = 0
            try:
                pending_preview = list_drafts(
                    kind_prefix="marketing_", status="draft_only", limit=12
                )
            except Exception:
                pending_preview = []
            try:
                with db_session() as conn:
                    rows = conn.execute(
                        """
                        SELECT task_id, from_agent, to_agent, status, updated_at, created_at
                        FROM veridiq_sdk_tasks
                        WHERE status IN ('pending', 'queued', 'running')
                        ORDER BY id DESC LIMIT 20
                        """
                    ).fetchall()
                sdk_running = [dict(r) for r in rows]
            except Exception:
                sdk_running = []
            payload = {
                "type": "snapshot",
                "roster": roster,
                "cards": roster.get("cards", []),
                "departments": roster.get("departments", []),
                "active_assignments": pool.get("assignments", []),
                "collaboration": global_collaboration_hub.recent(limit=20),
                "platform_activity": global_platform_activity.recent(limit=20),
                "pending_drafts_count": pending_n,
                "pending_drafts": pending_preview,
                "sdk_tasks": sdk_running,
                "waiting_for_tasks": pool.get("waiting_for_tasks"),
                "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            }
            yield f"data: {json.dumps(payload, default=str)}\n\n"
            await asyncio.sleep(poll_interval)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/v1/veridiq/ops")
def veridiq_ops_center() -> dict[str, Any]:
    started = time.perf_counter()
    system = veridiq_system_status()
    pool = global_worker_pool.snapshot()
    jobs = global_pipeline.list_jobs(limit=100)
    hist = pool.get("recent_history") or []
    latencies = [float(h["latency_ms"]) for h in hist if h.get("latency_ms") is not None]
    avg_exec = round(sum(latencies) / len(latencies), 2) if latencies else None
    return {
        "workforce": pool,
        "active_ai_workers": pool.get("active_workers", 0),
        "idle_workers": pool.get("idle_workers", 0),
        "queue_depth": pool.get("queue_depth", 0),
        "status_label": pool.get("status_label", "Waiting for Tasks"),
        "workflows": {
            "running": sum(1 for j in jobs if j.get("status") == "processing"),
            "completed": sum(1 for j in jobs if j.get("status") == "completed"),
            "failed": sum(1 for j in jobs if j.get("status") == "failed"),
            "queued": sum(1 for j in jobs if j.get("status") == "queued"),
        },
        "retry_queue": pool.get("queue_depth", 0),
        "average_execution_ms": avg_exec,
        "langgraph": LANGGRAPH_AGENT_MAP,
        "system": system,
        "sse": {
            "transport": "SSE",
            "endpoint": "/api/v1/veridiq/jobs/{job_uuid}/events",
            "status": "ready",
        },
        "rag": system.get("rag"),
        "resources": system.get("resources"),
        "api_latency_ms": system.get("latency_ms"),
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        "timestamp": pool.get("timestamp"),
    }


@app.get("/api/v1/veridiq/pages/verify-metrics")
def page_verify_metrics() -> dict[str, Any]:
    jobs = global_pipeline.list_jobs(limit=200)
    completed = [j for j in jobs if j.get("status") == "completed"]
    running = [j for j in jobs if j.get("status") in {"processing", "queued"}]
    scores = [float(j["truth_score"]) for j in completed if j.get("truth_score") is not None]
    evidence = 0
    for j in completed[:30]:
        full = global_pipeline.get_job(j["job_uuid"])
        result = (full or {}).get("result") or {}
        ev = ((result.get("evidence") or {}).get("evidence")) or []
        evidence += len(ev)
    return {
        "running_verifications": len(running),
        "completed_verifications": len(completed),
        "average_confidence": round(sum(scores) / len(scores), 4) if scores else None,
        "evidence_collected": evidence,
        "waiting_for_tasks": global_worker_pool.snapshot()["waiting_for_tasks"],
    }


@app.get("/api/v1/veridiq/pages/news-metrics")
def page_news_metrics() -> dict[str, Any]:
    pool = global_worker_pool.snapshot()
    news_active = [a for a in pool["assignments"] if a["agent_type"] in {"news_verification", "web_search"}]
    connector = news_connector()
    return {
        "active_news_analyses": len(news_active),
        "sources_checked": connector.get("count", 0) if connector.get("status") == "ok" else 0,
        "articles_processed": connector.get("count", 0) if connector.get("status") == "ok" else 0,
        "connector": connector,
        "waiting_for_tasks": len(news_active) == 0,
    }


@app.get("/api/v1/veridiq/pages/meeting-metrics")
def page_meeting_metrics() -> dict[str, Any]:
    pool = global_worker_pool.snapshot()
    meeting_active = [a for a in pool["assignments"] if a["agent_type"] in {"meeting_analysis", "timeline_builder"}]
    jobs = global_pipeline.list_jobs(limit=50)
    return {
        "live_meetings": len(meeting_active),
        "speakers_detected": 0 if not meeting_active else None,
        "statements_extracted": sum(1 for j in jobs if j.get("status") == "completed"),
        "verification_progress": meeting_active[0]["progress"] if meeting_active else 0,
        "waiting_for_tasks": len(meeting_active) == 0,
        "status_label": "Waiting for Tasks" if not meeting_active else "Processing",
        "assignments": meeting_active,
    }


@app.get("/api/v1/veridiq/pages/reports-metrics")
def page_reports_metrics() -> dict[str, Any]:
    jobs = global_pipeline.list_jobs(limit=200)
    completed = [j for j in jobs if j.get("status") == "completed"]
    pending = [j for j in jobs if j.get("status") in {"queued", "processing"}]
    with_reports = [j for j in completed if j.get("job_uuid")]
    return {
        "reports_generated": len(completed),
        "pending_reports": len(pending),
        "blockchain_ready_reports": len(with_reports),
        "export_history": [
            {"job_uuid": j["job_uuid"], "title": j.get("title"), "completed_at": j.get("completed_at")}
            for j in completed[:20]
        ],
    }


@app.get("/api/v1/veridiq/connectors")
def veridiq_connectors() -> dict[str, Any]:
    return connectors_status()


@app.get("/api/v1/veridiq/connectors/jobs")
def veridiq_connector_jobs() -> dict[str, Any]:
    return jobs_connector()


@app.get("/api/v1/veridiq/connectors/news")
def veridiq_connector_news() -> dict[str, Any]:
    return news_connector()


@app.get("/api/v1/veridiq/integrations")
def veridiq_integrations() -> dict[str, Any]:
    """Status of all modular platform connectors — official APIs only, no scraping."""
    from veridiq.integrations.registry import all_integrations

    return all_integrations()


@app.get("/api/v1/veridiq/integrations/activity")
def veridiq_integrations_activity(
    agent_type: Optional[str] = None, platform: Optional[str] = None, limit: int = 60
) -> dict[str, Any]:
    from veridiq.integrations.activity import global_platform_activity

    items = global_platform_activity.recent(limit=limit, platform=platform, agent_type=agent_type)
    return {
        "count": len(items),
        "activity": items,
        "note": (
            "No integration calls recorded yet — this list is never simulated."
            if not items
            else "Derived from real integration/connector calls only — not simulated."
        ),
    }


class ThreadsOAuthExchangeRequest(BaseModel):
    code: str
    write_env: bool = False
    long_lived: bool = True


def _upsert_dotenv(path: Path, updates: dict[str, str]) -> None:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = text.splitlines()
    keys = set(updates)
    out: list[str] = []
    seen: set[str] = set()
    for line in lines:
        raw = line.strip()
        if raw and not raw.startswith("#") and "=" in raw:
            k = raw.split("=", 1)[0].strip()
            if k in keys:
                out.append(f"{k}={updates[k]}")
                seen.add(k)
                continue
        out.append(line)
    for k, v in updates.items():
        if k not in seen:
            out.append(f"{k}={v}")
    path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")


def _client_is_loopback(request: Request) -> bool:
    host = (request.client.host if request.client else "") or ""
    return host in {"127.0.0.1", "::1", "localhost"}


@app.get("/api/v1/veridiq/integrations/threads/oauth/authorize-url")
def veridiq_threads_oauth_authorize_url() -> dict[str, Any]:
    """Return the Threads authorize URL using VERIDIQ_THREADS_* from .env (no secrets)."""
    from veridiq.integrations import threads

    try:
        url = threads.authorize_url()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "authorize_url": url,
        "redirect_uri": threads.redirect_uri(),
        "client_id": (os.getenv(threads.APP_ID) or "").strip(),
        "scopes": threads.DEFAULT_SCOPES,
        "facebook_login_note": (
            "In Meta App Dashboard → Facebook Login → Settings: enable Client OAuth Login "
            "and Web OAuth Login. Paste the same redirect_uri into Valid OAuth Redirect URIs "
            "and Threads → settings Authorize callback URL."
        ),
    }


@app.post("/api/v1/veridiq/integrations/threads/oauth/exchange")
def veridiq_threads_oauth_exchange(
    payload: ThreadsOAuthExchangeRequest, request: Request
) -> dict[str, Any]:
    """Exchange Threads OAuth code for token. write_env only from loopback clients."""
    from veridiq.integrations import threads

    result = threads.exchange_code(payload.code, long_lived=payload.long_lived)
    if result.get("status") != "ok":
        return result

    wrote = False
    if payload.write_env:
        if not _client_is_loopback(request):
            result["wrote_env"] = False
            result["write_env_error"] = "write_env allowed only from localhost/loopback."
            return result
        updates = {threads.ACCESS_TOKEN: str(result["access_token"])}
        if result.get("user_id"):
            updates[threads.THREADS_USER_ID] = str(result["user_id"])
        env_path = Path(__file__).resolve().parent / ".env"
        _upsert_dotenv(env_path, updates)
        for k, v in updates.items():
            os.environ[k] = v
        wrote = True
    result["wrote_env"] = wrote
    # Do not echo app secret; token is intentional for local setup UX.
    return result


@app.get("/api/v1/veridiq/integrations/{platform}")
def veridiq_integration_detail(platform: str) -> dict[str, Any]:
    from veridiq.integrations.registry import integration_detail

    detail = integration_detail(platform)
    if not detail:
        raise HTTPException(status_code=404, detail="unknown platform")
    return detail


@app.post("/api/v1/veridiq/integrations/{platform}/test")
def veridiq_integration_test(platform: str) -> dict[str, Any]:
    from veridiq.integrations.registry import test_integration

    return test_integration(platform)


@app.get("/api/v1/veridiq/integrations/telegram/listener")
def veridiq_telegram_listener_status() -> dict[str, Any]:
    """One-line Telegram listener + connectivity status (no secrets)."""
    from veridiq.integrations.telegram_listener import listener_status

    status = listener_status(include_webhook=True, probe_api=True)
    reachable = status.get("api_reachable")
    running = status.get("running")
    failures = int(status.get("consecutive_failures") or 0)
    if reachable and running:
        line = f"OK — listener running, api.telegram.org reachable (@{status.get('bot_username') or '?'})."
    elif reachable:
        line = "API reachable but listener not running — check VERIDIQ_TELEGRAM_AUTO_REPLY."
    elif status.get("enabled") or status.get("proxy_configured") is not None:
        suffix = f" ({failures} consecutive listener failures)" if failures else ""
        line = (
            f"BLOCKED — api.telegram.org unreachable{suffix}. "
            "Set VERIDIQ_TELEGRAM_PROXY or use VPN."
        )
    else:
        line = status.get("connectivity_message") or "Telegram listener status unknown."
    return {"summary": line, **status}


@app.post("/api/v1/veridiq/telegram/webapp/auth")
def veridiq_telegram_webapp_auth(payload: TelegramWebAppAuthRequest) -> dict[str, Any]:
    """Validate Telegram Mini App ``initData`` (HMAC) and optionally issue a VERIDIQ JWT."""
    from veridiq.integrations.telegram_webapp import authenticate_webapp

    result = authenticate_webapp(
        payload.init_data,
        issue_session=payload.issue_session,
        max_age_sec=payload.max_age_sec,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=401, detail=result.get("error") or "invalid initData")
    return result


@app.get("/api/v1/veridiq/telegram/miniapp")
def veridiq_telegram_miniapp_status() -> dict[str, Any]:
    """Public Mini App config snapshot (no secrets) — URL + menu button hint."""
    from veridiq.integrations import telegram as telegram_mod

    url = telegram_mod.miniapp_url()
    return {
        "configured": bool(url),
        "miniapp_url": url or None,
        "menu_button_script": "python scripts/set_telegram_menu_button.py",
        "docs": "docs/TELEGRAM_MINI_APP.md",
        "message": (
            f"Mini App URL set — open bot Menu to launch {url}"
            if url
            else f"Set {telegram_mod.MINIAPP_URL} to a public HTTPS frontend URL."
        ),
    }


@app.get("/api/v1/veridiq/runtime/jobs")
def veridiq_runtime_jobs(limit: int = 20) -> dict[str, Any]:
    """Live Agent Runtime — merges persisted verification jobs with any in-flight job_ids."""
    from veridiq.runtime.jobs import list_runtime_jobs

    jobs = list_runtime_jobs(limit=limit)
    return {"count": len(jobs), "jobs": jobs}


@app.get("/api/v1/veridiq/runtime/status")
def veridiq_runtime_status() -> dict[str, Any]:
    from veridiq.runtime.browser_recorder import runtime_status

    return runtime_status()


@app.get("/api/v1/veridiq/runtime/visual-proof")
def veridiq_runtime_visual_proof(limit: int = 12) -> dict[str, Any]:
    """Recent Playwright screenshots for Live Runtime 'Visual proof' strip.
    Empty when browser runtime never captured anything — never fabricates images."""
    from veridiq.runtime.browser_recorder import list_recent_sessions, runtime_status

    sessions = list_recent_sessions(limit=limit)
    status = runtime_status()
    return {
        "count": len(sessions),
        "sessions": sessions,
        "browser_runtime": status,
        "note": (
            "Screenshots only appear after a real Playwright capture on a URL you provide. "
            "This is visual proof of a browser session — not a fake webcam of bots posting."
        ),
    }


class BrowserSessionRequest(BaseModel):
    url: str = Field(..., min_length=4, max_length=2000)
    job_id: Optional[str] = None
    agent_type: Optional[str] = None


@app.post("/api/v1/veridiq/runtime/browser-session")
def veridiq_runtime_browser_session(payload: BrowserSessionRequest) -> dict[str, Any]:
    from veridiq.runtime.browser_recorder import capture_session

    return capture_session(url=payload.url, job_id=payload.job_id, agent_type=payload.agent_type)


@app.get("/api/v1/veridiq/runtime/browser-session/{session_id}")
def veridiq_runtime_browser_session_image(session_id: str) -> FileResponse:
    from veridiq.runtime.browser_recorder import screenshot_path

    path = screenshot_path(session_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="session not found")
    return FileResponse(str(path), media_type="image/png")


class CallCampaignRequest(BaseModel):
    to_number: str = Field(..., min_length=3, max_length=32)
    purpose: str = "AI calling campaign"
    script: str = Field(..., min_length=1, max_length=4000)
    contact_name: str = ""


class CallApproveRequest(BaseModel):
    approved: bool


class CallSummaryRequest(BaseModel):
    summary: str = Field(..., min_length=1, max_length=4000)


class CallFollowupRequest(BaseModel):
    recipient_email: str


class CallingAgentCommandRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    history: list[dict[str, str]] = Field(default_factory=list)


class PostingsAgentCommandRequest(BaseModel):
    message: str = Field(default="", max_length=2000)
    history: list[dict[str, Any]] = Field(default_factory=list)
    attachments: list[str] = Field(
        default_factory=list,
        description="Uploaded image filenames, paths, or /marketing/upload/file/ URLs",
        max_length=8,
    )
    chat_id: str = Field(
        default="",
        max_length=64,
        description="Active Mira chat id — messages + media URLs are appended when set",
    )


class PostingsChatCreateRequest(BaseModel):
    title: str = Field(default="", max_length=200)


class PostingsFeedbackRequest(BaseModel):
    """Thumbs up/down or 1–5 rating on a generated image/video."""

    rating: Optional[int] = Field(default=None, ge=1, le=5)
    thumbs: Optional[str] = Field(
        default=None,
        max_length=16,
        description="up|down — maps to rating 5|1 when rating omitted",
    )
    prompt: str = Field(default="", max_length=2000)
    style: str = Field(default="", max_length=120)
    media_url: str = Field(default="", max_length=800)
    media_type: str = Field(default="image", max_length=32)
    chat_id: str = Field(default="", max_length=64)
    topic: str = Field(default="", max_length=400)
    notes: str = Field(default="", max_length=500)


class MeetingScheduleRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=400)
    scheduled_at_pkt: str = Field(..., min_length=1, max_length=64, description="Asia/Karachi local time")
    agenda: list[str] = Field(default_factory=list)
    agent_types: list[str] = Field(default_factory=list)


class MeetingHubMessageRequest(BaseModel):
    body: str = Field(..., min_length=1, max_length=4000)
    meeting_id: str = ""
    thread_id: str = ""


class PersonalMeetingRequest(BaseModel):
    specialist_query: str = Field(default="canva daily posts", max_length=400)
    topic: str = Field(default="", max_length=400)


class OpenDmRequest(BaseModel):
    agent_type: str = Field(..., min_length=1, max_length=80)


class MeetingJoinConfirmRequest(BaseModel):
    yes: bool = True


class LiveKitTokenRequest(BaseModel):
    meeting_id: str = Field(..., min_length=1, max_length=80)
    identity: str = Field(default="veridiq-user", max_length=64)
    name: str = Field(default="You", max_length=64)
    role: str = Field(default="user", description="user|agent")


class AgoraTokenRequest(BaseModel):
    channel: str = Field(..., min_length=1, max_length=64)
    uid: int | str = Field(default=0, description="Numeric uid or 0 for any")
    identity: str = Field(default="", max_length=255, description="Optional string account (overrides uid)")
    role: str = Field(default="publisher", description="publisher|subscriber")
    ttl_sec: int = Field(default=3600, ge=60, le=86400)


@app.get("/api/v1/veridiq/calling/agent")
def veridiq_calling_agent_persona() -> dict[str, Any]:
    """Persona + LiveKit status for the AI Calling / Meetings page."""
    from veridiq.calling.agent import agent_persona
    from veridiq.calling.agora import agora_status
    from veridiq.calling.budget import budget_status
    from veridiq.calling.livekit_tokens import livekit_status
    from veridiq.calling.worker import worker_status
    from veridiq.integrations import ai_gateway

    persona = agent_persona()
    gw = ai_gateway.status()
    return {
        "agent": persona,
        "llm": {
            "configured": bool(gw.get("configured")),
            "status": gw.get("status"),
            "message": gw.get("message"),
            "configured_providers": gw.get("configured_providers") or [],
        },
        "livekit": livekit_status(),
        "agora": agora_status(),
        "budget": budget_status(agent_type="ai_calling", user_key="default"),
        "worker": worker_status(),
        "mode": "livekit_meetings",
        "message": (
            "Call Marcus to arrange a personal meeting with a specialist (e.g. Canva/daily posts). "
            "Watch live agent threads in Collaboration Hub (observer). Accept invites to join LiveKit. "
            "Timed voice windows enforce VERIDIQ_CALLING_MAX_SECONDS + daily budget. "
            "Agora App ID/Agent ID are optional sidecar."
        ),
    }


@app.post("/api/v1/veridiq/calling/agent")
def veridiq_calling_agent_command(payload: CallingAgentCommandRequest) -> dict[str, Any]:
    """Parse a command via LLM (ai_gateway) + keywords; execute real marketing/influencer actions."""
    from veridiq.calling.agent import handle_command

    return handle_command(payload.message, history=payload.history or None)


@app.get("/api/v1/veridiq/postings/agent")
def veridiq_postings_agent_persona() -> dict[str, Any]:
    """Postings Studio — Mira drafts posts, Canva designs, video storyboards."""
    from veridiq.postings import studio_status

    return studio_status()


@app.get("/api/v1/veridiq/postings/chats")
def veridiq_postings_chats_list(limit: int = 80) -> dict[str, Any]:
    """List Mira Postings chats (newest first)."""
    from veridiq.postings.chats import list_chats

    return list_chats(limit=limit)


@app.post("/api/v1/veridiq/postings/chats")
def veridiq_postings_chats_create(payload: PostingsChatCreateRequest) -> dict[str, Any]:
    """Create a new Mira Postings chat thread."""
    from veridiq.postings.chats import create_chat

    return create_chat(title=payload.title or "")


@app.get("/api/v1/veridiq/postings/chats/{chat_id}")
def veridiq_postings_chats_get(chat_id: str) -> dict[str, Any]:
    """Full chat with messages and media URLs."""
    from veridiq.postings.chats import get_chat

    data = get_chat(chat_id)
    if not data.get("ok"):
        raise HTTPException(status_code=404, detail=data.get("error") or "not_found")
    return data


@app.delete("/api/v1/veridiq/postings/chats/{chat_id}")
def veridiq_postings_chats_delete(chat_id: str) -> dict[str, Any]:
    """Delete a Mira Postings chat and its messages."""
    from veridiq.postings.chats import delete_chat

    data = delete_chat(chat_id)
    if not data.get("ok"):
        raise HTTPException(status_code=404, detail=data.get("error") or "not_found")
    return data


@app.post("/api/v1/veridiq/postings/upload")
async def veridiq_postings_upload(
    files: list[UploadFile] = File(default=[]),
    file: Optional[UploadFile] = File(default=None),
) -> dict[str, Any]:
    """Multipart image upload for Mira Postings — saved under marketing_out/uploads/."""
    from veridiq.postings.uploads import save_image_bytes

    uploads: list[UploadFile] = []
    if files:
        uploads.extend([f for f in files if f is not None])
    if file is not None:
        uploads.append(file)
    if not uploads:
        raise HTTPException(status_code=400, detail="no image files provided (use files or file)")

    saved: list[dict[str, Any]] = []
    for item in uploads[:8]:
        data, name = await read_validated_upload(item, "image")
        if data is None or not name:
            continue
        meta = save_image_bytes(data, name)
        saved.append(meta)
    if not saved:
        raise HTTPException(status_code=400, detail="no valid image uploads")
    return {
        "ok": True,
        "count": len(saved),
        "uploads": saved,
        "urls": [u["url"] for u in saved],
        "paths": [u["relative_path"] for u in saved],
        "filenames": [u["filename"] for u in saved],
    }


@app.post("/api/v1/veridiq/postings/agent")
def veridiq_postings_agent_command(payload: PostingsAgentCommandRequest) -> dict[str, Any]:
    """Postings Studio agent — create_video returns job_id immediately (poll for result).

    When ``chat_id`` is set, user + assistant turns (with media URLs) are appended
    to the SQLite chat. Video jobs also persist the final artifact on completion.
    """
    from veridiq.postings import handle_command
    from veridiq.postings.chats import append_turn_from_agent_result, get_chat

    message = (payload.message or "").strip()
    attachments = list(payload.attachments or [])
    if not message and not attachments:
        raise HTTPException(status_code=400, detail="message or attachments required")
    if not message and attachments:
        message = "Use my uploaded image"

    chat_id = (payload.chat_id or "").strip()
    if chat_id:
        existing = get_chat(chat_id)
        if not existing.get("ok"):
            raise HTTPException(status_code=404, detail="chat not found")

    result = handle_command(
        message,
        history=payload.history or None,
        async_video=True,
        attachments=attachments,
        chat_id=chat_id or None,
    )

    if chat_id and isinstance(result, dict):
        try:
            persist = append_turn_from_agent_result(chat_id, user_text=message, result=result)
            result = {**result, "chat_id": chat_id, "persisted": persist.get("ok", False)}
            if persist.get("title"):
                result["chat_title"] = persist["title"]
        except Exception as exc:
            result = {**result, "chat_id": chat_id, "persisted": False, "persist_error": str(exc)[:200]}

    return result


@app.post("/api/v1/veridiq/postings/feedback")
def veridiq_postings_feedback(payload: PostingsFeedbackRequest) -> dict[str, Any]:
    """Record thumbs up/down (or 1–5) so Mira biases future prompts toward successes."""
    from veridiq.postings.learning import record_feedback

    if payload.rating is None and not (payload.thumbs or "").strip():
        raise HTTPException(status_code=400, detail="rating (1–5) or thumbs (up|down) required")
    return record_feedback(
        prompt=payload.prompt,
        style=payload.style,
        media_url=payload.media_url,
        rating=int(payload.rating or 3),
        chat_id=payload.chat_id or None,
        media_type=payload.media_type or "image",
        topic=payload.topic,
        notes=payload.notes or None,
        thumbs=payload.thumbs,
    )


@app.get("/api/v1/veridiq/postings/feedback/stats")
def veridiq_postings_feedback_stats() -> dict[str, Any]:
    """Learning loop stats — rated examples, preferred styles, honest disclaimer."""
    from veridiq.postings.learning import feedback_stats

    return feedback_stats()


@app.get("/api/v1/veridiq/postings/learning")
def veridiq_postings_learning_status() -> dict[str, Any]:
    """Learns from ratings + uploads only — free, no Unsplash/Meta."""
    from veridiq.postings.learning import learning_status

    return learning_status()


@app.post("/api/v1/veridiq/postings/references/unsplash")
def veridiq_postings_unsplash_references(topic: str = "", per_page: int = 3) -> dict[str, Any]:
    """Unsplash is not used — returns disabled; learning uses ratings + uploads only."""
    from veridiq.postings.learning import fetch_unsplash_references

    q = (topic or "").strip()
    if len(q) < 2:
        raise HTTPException(status_code=400, detail="topic required")
    return fetch_unsplash_references(q, per_page=per_page, save=True)


@app.get("/api/v1/veridiq/postings/video/jobs/{job_id}")
def veridiq_postings_video_job(job_id: str) -> dict[str, Any]:
    """Poll async Mira create_video job status / result."""
    from veridiq.postings.video_jobs import get_job

    return get_job(job_id)


@app.post("/api/v1/veridiq/postings/video/jobs")
def veridiq_postings_video_jobs_start(payload: PostingsAgentCommandRequest) -> dict[str, Any]:
    """Optional explicit video-job start (same as agent POST create_video path)."""
    from veridiq.postings import handle_command
    from veridiq.postings.chats import append_turn_from_agent_result, get_chat

    message = (payload.message or "").strip()
    attachments = list(payload.attachments or [])
    if not message and not attachments:
        raise HTTPException(status_code=400, detail="message or attachments required")
    if not message and attachments:
        message = "Create a video from my uploaded image"

    chat_id = (payload.chat_id or "").strip()
    if chat_id:
        existing = get_chat(chat_id)
        if not existing.get("ok"):
            raise HTTPException(status_code=404, detail="chat not found")

    result = handle_command(
        message,
        history=payload.history or None,
        async_video=True,
        attachments=attachments,
        chat_id=chat_id or None,
    )
    if chat_id and isinstance(result, dict):
        try:
            persist = append_turn_from_agent_result(chat_id, user_text=message, result=result)
            result = {**result, "chat_id": chat_id, "persisted": persist.get("ok", False)}
        except Exception as exc:
            result = {**result, "chat_id": chat_id, "persisted": False, "persist_error": str(exc)[:200]}
    return result


@app.get("/api/v1/veridiq/calling/meetings/hub")
def veridiq_calling_meetings_hub() -> dict[str, Any]:
    """Live Collaboration Hub snapshot — always 200 with empty threads on failure."""
    try:
        from veridiq.calling.meetings import get_hub

        return get_hub()
    except Exception as exc:
        return {
            "ok": True,
            "hub_id": "default",
            "messages": [],
            "live_threads": [],
            "invites": [],
            "observer_mode": True,
            "user_can_chat": False,
            "error": str(exc)[:240],
            "timezone": "Asia/Karachi",
        }


@app.post("/api/v1/veridiq/calling/meetings/hub/enter")
def veridiq_calling_meetings_hub_enter() -> dict[str, Any]:
    """Legacy CEO enter — also ensures live agent threads are running."""
    from veridiq.calling.live_threads import ensure_live_threads, list_live_threads
    from veridiq.calling.meetings import enter_ceo

    ensure_live_threads()
    hub = enter_ceo()
    live = list_live_threads(include_messages=True, tick=True)
    hub["live_threads"] = live.get("threads") or []
    hub["invites"] = live.get("invites") or []
    return hub


@app.post("/api/v1/veridiq/calling/meetings/hub/start-conversation")
def veridiq_calling_meetings_hub_start_conversation(force: bool = False) -> dict[str, Any]:
    """Bootstrap / refresh the live agent swarm (many working rooms)."""
    from veridiq.calling.live_threads import ensure_live_threads, list_live_threads, tick_all_live
    from veridiq.calling.meetings import get_hub

    ensure_live_threads(force_new=False)
    if force:
        tick_all_live(force=True, use_llm=False, batch=12)
    else:
        tick_all_live(force=False, use_llm=False, batch=8)
    live = list_live_threads(include_messages=False, tick=False)
    hub = get_hub()
    hub["live_threads"] = live.get("threads") or hub.get("live_threads") or []
    hub["invites"] = live.get("invites") or hub.get("invites") or []
    hub["swarm"] = live.get("swarm") or hub.get("swarm") or {}
    hub["started"] = True
    hub["seeded"] = True
    return hub


@app.get("/api/v1/veridiq/calling/hub/threads")
def veridiq_calling_hub_threads() -> dict[str, Any]:
    from veridiq.calling.live_threads import list_live_threads

    return list_live_threads(include_messages=False, tick=True)


@app.get("/api/v1/veridiq/calling/hub/dms")
def veridiq_calling_hub_dms() -> dict[str, Any]:
    """WhatsApp-style agent DM contact list (1:1 threads)."""
    from veridiq.calling.live_threads import list_agent_dms

    return list_agent_dms()


@app.post("/api/v1/veridiq/calling/hub/dms/open")
def veridiq_calling_hub_dms_open(payload: OpenDmRequest) -> dict[str, Any]:
    """Open (or create) a dedicated DM with one workforce agent."""
    from veridiq.calling.live_threads import open_dm

    result = open_dm(payload.agent_type)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error") or "open dm failed")
    return result


@app.get("/api/v1/veridiq/calling/hub/threads/{thread_id}")
def veridiq_calling_hub_thread_detail(thread_id: str) -> dict[str, Any]:
    from veridiq.calling.live_threads import get_live_thread

    data = get_live_thread(thread_id, tick=True)
    if not data:
        raise HTTPException(status_code=404, detail="unknown thread")
    return data


@app.post("/api/v1/veridiq/calling/hub/threads")
def veridiq_calling_hub_thread_create(force: bool = False) -> dict[str, Any]:
    from veridiq.calling.live_threads import create_live_thread, ensure_live_threads

    if force:
        return create_live_thread()
    threads = ensure_live_threads()
    return {"ok": True, "threads": threads}


@app.get("/api/v1/veridiq/calling/hub/invites")
def veridiq_calling_hub_invites() -> dict[str, Any]:
    from veridiq.calling.live_threads import list_invites

    invites = list_invites(status="pending")
    return {"count": len(invites), "invites": invites}


@app.post("/api/v1/veridiq/calling/hub/invites/{invite_id}/accept")
def veridiq_calling_hub_invite_accept(invite_id: str) -> dict[str, Any]:
    from veridiq.calling.live_threads import accept_invite

    result = accept_invite(invite_id=invite_id)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error") or "accept failed")
    return result


@app.post("/api/v1/veridiq/calling/hub/invites/{invite_id}/decline")
def veridiq_calling_hub_invite_decline(invite_id: str) -> dict[str, Any]:
    from veridiq.calling.live_threads import decline_invite

    result = decline_invite(invite_id=invite_id)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error") or "decline failed")
    return result


@app.post("/api/v1/veridiq/calling/hub/request-personal-meeting")
def veridiq_calling_hub_request_personal_meeting(payload: PersonalMeetingRequest) -> dict[str, Any]:
    """Calling-agent path: request specialist personal meeting → hub invite."""
    from veridiq.calling.live_threads import request_personal_meeting

    return request_personal_meeting(
        specialist_query=payload.specialist_query or payload.topic or "canva daily posts",
        topic=payload.topic or None,
    )


@app.post("/api/v1/veridiq/calling/meetings/hub/messages")
def veridiq_calling_meetings_hub_message(payload: MeetingHubMessageRequest) -> dict[str, Any]:
    """Hub compose: meeting work chat when admitted, or collab→Mira/postings bridge."""
    if payload.meeting_id:
        from veridiq.calling.live_threads import post_meeting_work_chat

        result = post_meeting_work_chat(meeting_id=payload.meeting_id, body=payload.body)
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("message") or result.get("error") or "message failed")
        return result
    from veridiq.calling.live_threads import post_collab_user_message

    return post_collab_user_message(body=payload.body, thread_id=payload.thread_id or None)


@app.get("/api/v1/veridiq/calling/meetings")
def veridiq_calling_meetings_list() -> dict[str, Any]:
    from veridiq.calling.meetings import list_meetings

    meetings = list_meetings()
    return {"count": len(meetings), "meetings": meetings, "timezone": "Asia/Karachi"}


@app.post("/api/v1/veridiq/calling/meetings")
def veridiq_calling_meetings_schedule(payload: MeetingScheduleRequest) -> dict[str, Any]:
    from veridiq.calling.meetings import schedule_meeting

    result = schedule_meeting(
        topic=payload.topic,
        scheduled_at_pkt=payload.scheduled_at_pkt,
        agenda=payload.agenda or None,
        agent_types=payload.agent_types or None,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("message") or result.get("error") or "schedule failed")
    return result


@app.get("/api/v1/veridiq/calling/meetings/{meeting_id}")
def veridiq_calling_meeting_detail(meeting_id: str) -> dict[str, Any]:
    from veridiq.calling.meetings import get_meeting

    meeting = get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="unknown meeting")
    return meeting


@app.post("/api/v1/veridiq/calling/meetings/{meeting_id}/start")
def veridiq_calling_meeting_start(meeting_id: str) -> dict[str, Any]:
    from veridiq.calling.meetings import start_meeting

    result = start_meeting(meeting_id=meeting_id)
    if not result.get("ok"):
        code = 400
        if result.get("error") == "unknown_meeting":
            code = 404
        raise HTTPException(status_code=code, detail=result.get("message") or result.get("error") or "start failed")
    return result


@app.post("/api/v1/veridiq/calling/meetings/{meeting_id}/request-join")
def veridiq_calling_meeting_request_join(meeting_id: str) -> dict[str, Any]:
    from veridiq.calling.meetings import request_join

    result = request_join(meeting_id=meeting_id)
    if not result.get("ok"):
        code = 404 if result.get("error") == "unknown_meeting" else 400
        raise HTTPException(status_code=code, detail=result.get("error") or "request-join failed")
    return result


@app.post("/api/v1/veridiq/calling/meetings/{meeting_id}/confirm-join")
def veridiq_calling_meeting_confirm_join(meeting_id: str, payload: MeetingJoinConfirmRequest) -> dict[str, Any]:
    from veridiq.calling.meetings import confirm_join

    result = confirm_join(meeting_id=meeting_id, yes=payload.yes)
    if not result.get("ok"):
        code = 404 if result.get("error") == "unknown_meeting" else 400
        raise HTTPException(status_code=code, detail=result.get("message") or result.get("error") or "confirm failed")
    return result


@app.post("/api/v1/veridiq/calling/meetings/{meeting_id}/end")
def veridiq_calling_meeting_end(meeting_id: str) -> dict[str, Any]:
    from veridiq.calling.meetings import end_meeting

    result = end_meeting(meeting_id=meeting_id)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail="unknown meeting")
    return result


@app.post("/api/v1/veridiq/calling/livekit/token")
def veridiq_calling_livekit_token(payload: LiveKitTokenRequest) -> dict[str, Any]:
    """Mint a LiveKit JWT (API key/secret) for an admitted user or agent identity."""
    from veridiq.calling.meetings import mint_meeting_token

    result = mint_meeting_token(
        meeting_id=payload.meeting_id,
        identity=payload.identity,
        name=payload.name,
        role=payload.role,
    )
    if not result.get("ok"):
        err = result.get("error") or "token_failed"
        code = 404 if err == "unknown_meeting" else 400
        raise HTTPException(status_code=code, detail=result.get("message") or err)
    return result


@app.get("/api/v1/veridiq/calling/livekit/status")
def veridiq_calling_livekit_status() -> dict[str, Any]:
    from veridiq.calling.livekit_tokens import livekit_status

    return livekit_status()


@app.get("/api/v1/veridiq/calling/agora/status")
def veridiq_calling_agora_status() -> dict[str, Any]:
    """Optional Agora Conversational AI / RTC presence (does not block LiveKit)."""
    from veridiq.calling.agora import agora_status

    return agora_status()


@app.post("/api/v1/veridiq/calling/agora/token")
def veridiq_calling_agora_token(payload: AgoraTokenRequest) -> dict[str, Any]:
    """Mint an Agora RTC AccessToken2 (optional agent-assist). LiveKit stays primary."""
    from veridiq.calling.agora import mint_agora_rtc_token

    result = mint_agora_rtc_token(
        channel=payload.channel,
        uid=payload.uid,
        role=payload.role,
        ttl_sec=payload.ttl_sec,
        identity=payload.identity or None,
    )
    if not result.get("ok"):
        err = result.get("error") or "token_failed"
        raise HTTPException(status_code=400, detail=result.get("message") or err)
    return result


@app.post("/api/v1/veridiq/calling/campaigns")
def veridiq_calling_create(payload: CallCampaignRequest) -> dict[str, Any]:
    from veridiq.calling.campaigns import create_campaign

    return create_campaign(
        to_number=payload.to_number, purpose=payload.purpose, script=payload.script, contact_name=payload.contact_name
    )


@app.get("/api/v1/veridiq/calling/campaigns")
def veridiq_calling_list() -> dict[str, Any]:
    from veridiq.calling.campaigns import list_campaigns

    campaigns = list_campaigns()
    return {"count": len(campaigns), "campaigns": campaigns}


@app.get("/api/v1/veridiq/calling/campaigns/{campaign_id}")
def veridiq_calling_detail(campaign_id: str) -> dict[str, Any]:
    from veridiq.calling.campaigns import get_campaign

    campaign = get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="unknown campaign")
    return campaign


@app.post("/api/v1/veridiq/calling/campaigns/{campaign_id}/approve")
def veridiq_calling_approve(campaign_id: str, payload: CallApproveRequest) -> dict[str, Any]:
    from veridiq.calling.campaigns import approve_campaign

    result = approve_campaign(campaign_id, approved=payload.approved)
    if not result.get("ok") and result.get("error") == "unknown campaign_id":
        raise HTTPException(status_code=404, detail="unknown campaign")
    return result


@app.post("/api/v1/veridiq/calling/campaigns/{campaign_id}/summary")
def veridiq_calling_summary(campaign_id: str, payload: CallSummaryRequest) -> dict[str, Any]:
    from veridiq.calling.campaigns import get_campaign, sync_summary_to_crm

    campaign = get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="unknown campaign")
    crm_result = sync_summary_to_crm(campaign_id, summary=payload.summary)
    return {"ok": True, "campaign": get_campaign(campaign_id), "crm_sync": crm_result}


@app.post("/api/v1/veridiq/calling/campaigns/{campaign_id}/followup")
def veridiq_calling_followup(campaign_id: str, payload: CallFollowupRequest) -> dict[str, Any]:
    from veridiq.calling.campaigns import draft_followup

    result = draft_followup(campaign_id, recipient_email=payload.recipient_email)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail="unknown campaign")
    return result


class TimedCallScheduleRequest(BaseModel):
    purpose: str = Field(default="Timed AI calling session", max_length=400)
    script: str = Field(default="", max_length=4000)
    to_number: str = Field(default="", max_length=40)
    requested_seconds: Optional[int] = Field(default=None, ge=1, le=3600)
    user_key: str = Field(default="default", max_length=64)
    auto_start: bool = True
    record_chain: bool = True


@app.get("/api/v1/veridiq/calling/budget")
def veridiq_calling_budget(user_key: str = "default") -> dict[str, Any]:
    """Daily + per-call timed calling budget status."""
    from veridiq.calling.budget import budget_status
    from veridiq.calling.worker import worker_status

    return {
        **budget_status(agent_type="ai_calling", user_key=user_key or "default"),
        "worker": worker_status(),
    }


@app.post("/api/v1/veridiq/calling/budget/reset")
def veridiq_calling_budget_reset(user_key: str = "default") -> dict[str, Any]:
    """Admin/dev: zero today's UTC daily calling budget for a user (or all if user_key=*)."""
    from veridiq.calling.budget import reset_daily_budget

    key = (user_key or "default").strip()
    if key in {"*", "all"}:
        return reset_daily_budget(agent_type="ai_calling", user_key=None)
    return reset_daily_budget(agent_type="ai_calling", user_key=key)


@app.get("/api/v1/veridiq/calling/timed")
def veridiq_calling_timed_list(
    user_key: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
) -> dict[str, Any]:
    from veridiq.calling.timed_calls import list_sessions

    sessions = list_sessions(agent_type="ai_calling", user_key=user_key, status=status, limit=limit)
    return {"count": len(sessions), "sessions": sessions}


@app.post("/api/v1/veridiq/calling/timed")
def veridiq_calling_timed_schedule(payload: TimedCallScheduleRequest) -> dict[str, Any]:
    """Schedule (and optionally start) a budget-capped timed call — async worker enforces max duration."""
    from veridiq.calling.timed_calls import schedule_timed_call, start_session

    result = schedule_timed_call(
        purpose=payload.purpose,
        script=payload.script,
        to_number=payload.to_number,
        requested_seconds=payload.requested_seconds,
        agent_type="ai_calling",
        user_key=payload.user_key or "default",
        record_chain=payload.record_chain,
    )
    if not result.get("ok"):
        return result
    if payload.auto_start:
        sid = (result.get("session") or {}).get("session_id")
        if sid:
            started = start_session(sid)
            result["start"] = started
            if started.get("session"):
                result["session"] = started["session"]
            result["status"] = started.get("status") or result.get("status")
            if started.get("message"):
                result["message"] = f"{result.get('message', '')} {started['message']}".strip()
    return result


@app.get("/api/v1/veridiq/calling/timed/{session_id}")
def veridiq_calling_timed_detail(session_id: str) -> dict[str, Any]:
    from veridiq.calling.timed_calls import get_session

    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="unknown timed call session")
    return session


@app.post("/api/v1/veridiq/calling/timed/{session_id}/start")
def veridiq_calling_timed_start(session_id: str) -> dict[str, Any]:
    from veridiq.calling.timed_calls import start_session

    result = start_session(session_id)
    if result.get("message") == "unknown session_id":
        raise HTTPException(status_code=404, detail="unknown timed call session")
    return result


@app.post("/api/v1/veridiq/calling/timed/{session_id}/end")
def veridiq_calling_timed_end(session_id: str, reason: str = "completed") -> dict[str, Any]:
    from veridiq.calling.timed_calls import end_session

    result = end_session(session_id, reason=reason or "completed")
    if result.get("message") == "unknown session_id":
        raise HTTPException(status_code=404, detail="unknown timed call session")
    return result


@app.get("/api/v1/veridiq/calling/worker/status")
def veridiq_calling_worker_status() -> dict[str, Any]:
    from veridiq.calling.worker import worker_status

    return {"ok": True, **worker_status()}


class MeetingEnterRequest(BaseModel):
    identity: str = Field(default="veridiq-user", max_length=64)
    name: str = Field(default="You", max_length=64)
    user_key: str = Field(default="default", max_length=64)


class MeetingQuickRequest(BaseModel):
    topic: str = Field(default="Timed call with Marcus", max_length=400)
    scheduled_at_pkt: str = Field(default="", max_length=64, description="Empty = now PKT")
    agenda: list[str] = Field(default_factory=list)
    identity: str = Field(default="veridiq-user", max_length=64)
    name: str = Field(default="You", max_length=64)
    user_key: str = Field(default="default", max_length=64)


@app.post("/api/v1/veridiq/calling/meetings/{meeting_id}/enter")
def veridiq_calling_meeting_enter(meeting_id: str, payload: MeetingEnterRequest) -> dict[str, Any]:
    """Start (if needed) + admit + mint user token + prepare Marcus voice presence."""
    from veridiq.calling.agent_presence import enter_meeting_with_agent

    result = enter_meeting_with_agent(
        meeting_id=meeting_id,
        identity=payload.identity,
        name=payload.name,
        user_key=payload.user_key or "default",
        announce_telegram=False,
    )
    if not result.get("ok"):
        err = result.get("error") or "enter_failed"
        code = 404 if err == "unknown_meeting" else 400
        raise HTTPException(status_code=code, detail=result.get("message") or err)
    return result


@app.post("/api/v1/veridiq/calling/meetings/{meeting_id}/agent-presence")
def veridiq_calling_agent_presence(meeting_id: str, user_key: str = "default") -> dict[str, Any]:
    """Mint publishable Marcus token + TTS greeting for an already-live meeting."""
    from veridiq.calling.agent_presence import prepare_agent_presence

    result = prepare_agent_presence(
        meeting_id=meeting_id,
        agent_type="ai_calling",
        open_budget=True,
        user_key=user_key or "default",
        speak=True,
    )
    if not result.get("ok"):
        err = result.get("error") or "presence_failed"
        code = 404 if err == "unknown_meeting" else 400
        raise HTTPException(status_code=code, detail=result.get("message") or err)
    return result


@app.post("/api/v1/veridiq/calling/timed/{session_id}/activate")
def veridiq_calling_timed_activate(session_id: str) -> dict[str, Any]:
    """Start timed budget clock after Marcus successfully joins LiveKit."""
    from veridiq.calling.agent_presence import activate_presence_budget

    result = activate_presence_budget(session_id=session_id)
    if result.get("message") == "unknown session_id" or result.get("status") == "unknown_session":
        raise HTTPException(status_code=404, detail="unknown timed call session")
    return result


@app.post("/api/v1/veridiq/calling/timed/{session_id}/cancel-uncharged")
def veridiq_calling_timed_cancel_uncharged(session_id: str) -> dict[str, Any]:
    """Cancel a timed session with zero charge (failed / abandoned agent join)."""
    from veridiq.calling.agent_presence import cancel_presence_budget

    return cancel_presence_budget(session_id=session_id, reason="cancelled")


@app.post("/api/v1/veridiq/calling/meetings/quick")
def veridiq_calling_meeting_quick(payload: MeetingQuickRequest) -> dict[str, Any]:
    """Schedule (default: now) and enter a LiveKit call with Marcus speaking."""
    from veridiq.calling.agent_presence import schedule_and_enter

    result = schedule_and_enter(
        topic=payload.topic,
        scheduled_at_pkt=payload.scheduled_at_pkt or None,
        agenda=payload.agenda or None,
        identity=payload.identity,
        name=payload.name,
        user_key=payload.user_key or "default",
    )
    # When LiveKit missing we still return 200 with scheduled meeting + clear message
    if result.get("error") == "livekit_not_configured":
        return result
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("message") or result.get("error") or "quick meet failed")
    return result


# --- Agent-to-agent meetings (hub propose → approve → countdown → LiveKit) ---


class AgentMeetProposeRequest(BaseModel):
    proposer_agent: str = Field(default="x_twitter_voice", max_length=64)
    invitee_agent: str = Field(default="influencer_relations", max_length=64)
    topic: str = Field(default="", max_length=400)
    thread_id: Optional[str] = Field(default=None, max_length=64)
    countdown: Optional[int] = Field(default=None, ge=1, le=3600)


class AgentMeetInviteRequest(BaseModel):
    agent_type: str = Field(..., min_length=1, max_length=64)


class ExternalMeetJoinRequest(BaseModel):
    url: str = Field(..., min_length=8, max_length=2000)
    instructions: str = Field(default="", max_length=2000)
    thread_id: Optional[str] = Field(default=None, max_length=64)


@app.get("/api/v1/veridiq/calling/agent-meetings")
def veridiq_agent_meetings_list(status: Optional[str] = None, thread_id: Optional[str] = None) -> dict[str, Any]:
    from veridiq.calling.agent_meetings import (
        countdown_seconds,
        duration_seconds,
        extended_seconds,
        list_proposals,
    )

    proposals = list_proposals(status=status, thread_id=thread_id)
    return {
        "ok": True,
        "count": len(proposals),
        "proposals": proposals,
        "defaults": {
            "countdown_seconds": countdown_seconds(),
            "duration_seconds": duration_seconds(),
            "extended_seconds": extended_seconds(),
        },
    }


@app.post("/api/v1/veridiq/calling/agent-meetings/propose")
def veridiq_agent_meetings_propose(payload: AgentMeetProposeRequest) -> dict[str, Any]:
    from veridiq.calling.agent_meetings import propose_meeting

    result = propose_meeting(
        proposer_agent=payload.proposer_agent,
        invitee_agent=payload.invitee_agent,
        topic=payload.topic,
        thread_id=payload.thread_id,
        countdown=payload.countdown,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("message") or result.get("error") or "propose failed")
    return result


@app.post("/api/v1/veridiq/calling/agent-meetings/external-join")
def veridiq_agent_meetings_external_join(payload: ExternalMeetJoinRequest) -> dict[str, Any]:
    from veridiq.calling.external_meet import schedule_external_join

    result = schedule_external_join(
        url=payload.url,
        instructions=payload.instructions,
        thread_id=payload.thread_id,
    )
    if not result.get("ok") and result.get("status") in ("disabled", "invalid_url"):
        raise HTTPException(status_code=400, detail=result.get("message") or result.get("status"))
    return result


@app.get("/api/v1/veridiq/calling/agent-meetings/external/{job_id}")
def veridiq_agent_meetings_external_status(job_id: str) -> dict[str, Any]:
    from veridiq.calling.external_meet import get_job

    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="unknown external meet job")
    return {"ok": True, "job": job}


@app.post("/api/v1/veridiq/calling/agent-meetings/daily-standup")
def veridiq_agent_meetings_daily_standup(force: bool = False) -> dict[str, Any]:
    from veridiq.calling.agent_meetings import ensure_daily_standup

    return ensure_daily_standup(force=force)


@app.get("/api/v1/veridiq/calling/agent-meetings/{proposal_id}")
def veridiq_agent_meetings_get(proposal_id: str) -> dict[str, Any]:
    from veridiq.calling.agent_meetings import get_live_bundle

    result = get_live_bundle(proposal_id=proposal_id)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error") or "unknown proposal")
    return result


@app.post("/api/v1/veridiq/calling/agent-meetings/{proposal_id}/approve")
def veridiq_agent_meetings_approve(proposal_id: str) -> dict[str, Any]:
    from veridiq.calling.agent_meetings import approve_proposal

    result = approve_proposal(proposal_id=proposal_id)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("message") or result.get("error") or "approve failed")
    return result


@app.post("/api/v1/veridiq/calling/agent-meetings/{proposal_id}/decline")
def veridiq_agent_meetings_decline(proposal_id: str) -> dict[str, Any]:
    from veridiq.calling.agent_meetings import decline_proposal

    result = decline_proposal(proposal_id=proposal_id)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("message") or result.get("error") or "decline failed")
    return result


@app.post("/api/v1/veridiq/calling/agent-meetings/{proposal_id}/start")
def veridiq_agent_meetings_start(proposal_id: str, force: bool = False) -> dict[str, Any]:
    """Start when countdown elapsed (or force=1 for tests)."""
    from veridiq.calling.agent_meetings import start_agent_meeting

    result = start_agent_meeting(proposal_id=proposal_id, force=force)
    if not result.get("ok"):
        code = 400
        if result.get("error") == "countdown_active":
            code = 409
        raise HTTPException(status_code=code, detail=result.get("message") or result.get("error") or "start failed")
    return result


@app.post("/api/v1/veridiq/calling/agent-meetings/{proposal_id}/invite-agent")
def veridiq_agent_meetings_invite_agent(proposal_id: str, payload: AgentMeetInviteRequest) -> dict[str, Any]:
    from veridiq.calling.agent_meetings import invite_agent

    result = invite_agent(proposal_id=proposal_id, agent_type=payload.agent_type)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("message") or result.get("error") or "invite failed")
    return result


@app.post("/api/v1/veridiq/calling/agent-meetings/{proposal_id}/extend")
def veridiq_agent_meetings_extend(proposal_id: str) -> dict[str, Any]:
    from veridiq.calling.agent_meetings import extend_meeting

    result = extend_meeting(proposal_id=proposal_id, reason="manual")
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("message") or result.get("error") or "extend failed")
    return result


@app.post("/api/v1/veridiq/calling/agent-meetings/{proposal_id}/end")
def veridiq_agent_meetings_end(proposal_id: str) -> dict[str, Any]:
    from veridiq.calling.agent_meetings import end_agent_meeting

    return end_agent_meeting(proposal_id=proposal_id)


@app.post("/api/v1/veridiq/calling/agent-meetings/{proposal_id}/spectator")
def veridiq_agent_meetings_spectator(proposal_id: str, name: str = "Spectator") -> dict[str, Any]:
    """Subscribe-only LiveKit token to watch agent↔agent call."""
    from veridiq.calling.spectator import spectator_for_proposal

    result = spectator_for_proposal(proposal_id=proposal_id, name=name or "Spectator")
    if not result.get("ok"):
        code = 409 if result.get("error") == "countdown_active" else 400
        if result.get("error") == "unknown_proposal":
            code = 404
        raise HTTPException(status_code=code, detail=result.get("message") or result.get("error") or "spectator failed")
    return result


@app.get("/api/v1/veridiq/calling/agent-tts/{clip_id}")
def veridiq_calling_agent_tts(clip_id: str) -> FileResponse:
    """Serve edge-tts greeting clip for agent LiveKit publish."""
    from veridiq.calling.agent_presence import get_tts_clip

    safe = (clip_id or "").strip()
    if not safe or "/" in safe or "\\" in safe or ".." in safe:
        raise HTTPException(status_code=400, detail="invalid clip_id")
    meta = get_tts_clip(safe)
    if not meta or not meta.get("path"):
        raise HTTPException(status_code=404, detail="unknown clip")
    path = Path(str(meta["path"]))
    if not path.is_file():
        raise HTTPException(status_code=404, detail="clip file missing")
    return FileResponse(str(path), media_type="audio/mpeg", filename=f"{safe}.mp3")


class LiveRequestPayload(BaseModel):
    text: str = Field(..., min_length=1, max_length=20000)
    title: str = "Live AI request"
    async_mode: bool = True
    coin_id: str = "bitcoin"


class CommsDraftRequest(BaseModel):
    kind: str = Field(default="email", description="email|agenda|follow_up|meeting_summary|contact_notes")
    context: str = Field(..., min_length=1, max_length=8000)
    recipient_hint: str = ""


class MarketingCampaignRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    product_brief: str = Field(default="", max_length=4000)
    channels: Optional[list[str]] = None


class MarketingCampaignStatusRequest(BaseModel):
    status: str = Field(..., description="active|paused|archived")


class MarketingDailyRunRequest(BaseModel):
    campaign_id: str
    channels: Optional[list[str]] = None
    features: Optional[list[str]] = None


class MarketingTeamAssignRequest(BaseModel):
    agent_type: str
    campaign_id: Optional[str] = None
    channels: Optional[list[str]] = None


class MarketingCommentRequest(BaseModel):
    channel: str = Field(..., description="x_twitter|linkedin|instagram|telegram")
    text: str = Field(default="", max_length=4000, description="Leave empty to auto-generate Adrian/influencer humanized reply")
    target_ref: str = Field(default="", description="tweet id / post URN / comment id / chat_id[:message_id] being replied to")
    campaign_id: Optional[str] = None
    feature: str = Field(default="truth_verification", description="Feature key for auto-generated engagement copy")
    agent_type: str = Field(default="influencer_relations", description="Persona for auto-generated engagement copy")


class InfluencerResearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500, description="Creator / niche research query")
    niche: Optional[str] = Field(default=None, max_length=200)
    max_results: int = Field(default=8, ge=1, le=15)
    summarize: bool = True


class MarketingCanvaDesignRequest(BaseModel):
    title: str = Field(default="VeriDiQ Marketing Creative", max_length=255)
    design_type: str = "custom"
    width: int = 1080
    height: int = 1080


class MarketingStoryboardRequest(BaseModel):
    campaign_id: Optional[str] = None
    feature: str = "truth_verification"
    style: str = "explainer"
    duration_sec: int = 30
    product_brief: Optional[str] = None


class MarketingRenderRequest(BaseModel):
    storyboard_id: str


class CommsApproveRequest(BaseModel):
    draft_id: str
    approved: bool
    channel: str = "email"


class CommsApproveBatchItem(BaseModel):
    draft_id: str
    channel: str = "email"


class CommsApproveBatchRequest(BaseModel):
    drafts: list[CommsApproveBatchItem]
    approved: bool = True
    cadence: Optional[bool] = None


@app.get("/api/v1/veridiq/collaboration")
def veridiq_collaboration(job_id: Optional[str] = None, limit: int = 80) -> dict[str, Any]:
    from veridiq.workforce.collaboration import global_collaboration_hub

    if job_id:
        return {
            "job_id": job_id,
            "messages": global_collaboration_hub.recent(limit=limit, job_id=job_id),
            "note": "Derived from real workflow events.",
        }
    return global_collaboration_hub.snapshot()


@app.get("/api/v1/veridiq/departments")
def veridiq_departments() -> dict[str, Any]:
    from veridiq.workforce.departments import department_snapshot

    return department_snapshot()


@app.get("/api/v1/veridiq/command-center")
def veridiq_command_center() -> dict[str, Any]:
    """Live multi-agent command center — real pool + workflow metrics only."""
    ops = veridiq_ops_center()
    depts = veridiq_departments()
    collab = veridiq_collaboration(limit=40)
    return {
        **ops,
        "departments": depts,
        "collaboration_preview": collab.get("messages", [])[:12],
        "agent_health": {
            "waiting_for_tasks": ops.get("workforce", {}).get("waiting_for_tasks"),
            "status_label": ops.get("status_label"),
            "active": ops.get("active_ai_workers"),
            "idle": ops.get("idle_workers"),
        },
        "performance": ops.get("workforce", {}).get("agent_stats") or {},
    }


@app.get("/api/v1/veridiq/market")
def veridiq_market() -> dict[str, Any]:
    from veridiq.market import market_connectors_status, market_overview

    overview = market_overview()
    return {**overview, "connectors": market_connectors_status()}


@app.get("/api/v1/veridiq/market/history/{coin_id}")
def veridiq_market_history(coin_id: str, days: int = 7) -> dict[str, Any]:
    from veridiq.market import coin_history, simple_indicators

    hist = coin_history(coin_id=coin_id, days=days)
    prices = [float(p["price"]) for p in (hist.get("prices") or []) if p.get("price") is not None]
    return {**hist, "indicators": simple_indicators(prices)}


@app.post("/api/v1/veridiq/requests")
def veridiq_live_request(
    payload: LiveRequestPayload,
    user: Optional[dict[str, Any]] = Depends(get_optional_user),
) -> dict[str, Any]:
    """Assign work to AI teams via intelligent orchestrator routing."""
    from veridiq.comms import draft_communication
    from veridiq.orchestration.market_graph import run_market_intelligence
    from veridiq.orchestration.task_router import emit_plan, new_job_id, plan_request

    plan = plan_request(payload.text)
    job_id = new_job_id()

    if plan["pipeline"] == "comms":
        emit_plan(job_id, plan)
        draft = draft_communication(kind="email", context=payload.text)
        return {
            "ok": True,
            "job_id": job_id,
            "plan": plan,
            "mode": "comms",
            "draft": draft,
            "message": "Communication draft prepared — external send requires explicit approval.",
            "workflow": plan["workflow_stages"],
        }

    if plan["pipeline"] == "market_intelligence":
        emit_plan(job_id, plan)
        result = run_market_intelligence(payload.text, job_id=job_id, coin_id=payload.coin_id)
        return {
            "ok": True,
            "job_uuid": job_id,
            "job_id": job_id,
            "plan": plan,
            "mode": "market",
            "result": result,
            "async_mode": False,
            "events_url": f"/api/v1/veridiq/jobs/{job_id}/events",
        }

    # Default: truth verification pipeline
    user_id = int(user["id"]) if user else None
    if payload.async_mode:
        out = global_pipeline.run_async(
            title=payload.title,
            text=payload.text,
            user_id=user_id,
        )
        real_id = out.get("job_uuid") or job_id
        emit_plan(real_id, plan)
        return {"ok": True, "plan": plan, "mode": "truth", **out}

    out = global_pipeline.run(
        title=payload.title,
        text=payload.text,
        user_id=user_id,
    )
    real_id = out.get("job_uuid") or job_id
    emit_plan(real_id, plan)
    return {"ok": True, "plan": plan, "mode": "truth", **out}


@app.post("/api/v1/veridiq/comms/draft")
def veridiq_comms_draft(payload: CommsDraftRequest) -> dict[str, Any]:
    from veridiq.comms import draft_communication

    return draft_communication(kind=payload.kind, context=payload.context, recipient_hint=payload.recipient_hint)


@app.post("/api/v1/veridiq/comms/approve")
def veridiq_comms_approve(payload: CommsApproveRequest) -> dict[str, Any]:
    from veridiq.comms import approve_external_action

    return approve_external_action(payload.draft_id, approved=payload.approved, channel=payload.channel)


@app.post("/api/v1/veridiq/comms/approve-batch")
def veridiq_comms_approve_batch(payload: CommsApproveBatchRequest) -> dict[str, Any]:
    """Approve multiple drafts with optional human cadence jitter between sends.

    Default: 30–180s spacing between sends (VERIDIQ_MARKETING_SEND_JITTER_*).
    Set jitter min/max to 0 or cadence=false to approve immediately."""
    from veridiq.marketing.cadence import approve_batch_with_cadence

    specs = [{"draft_id": d.draft_id, "channel": d.channel} for d in payload.drafts]
    if not specs:
        raise HTTPException(status_code=400, detail="drafts list is required")
    return approve_batch_with_cadence(specs, approved=payload.approved, cadence=payload.cadence)


# ---------------------------------------------------------------------------
# Marketing Agency — campaigns, daily content packs, comment engagement,
# Canva creatives, video storyboards. Every post/comment is queued as a
# comms draft (see veridiq/comms/assistant.py) and requires the same
# explicit approve step as the rest of the platform before anything sends.
# ---------------------------------------------------------------------------


@app.get("/api/v1/veridiq/marketing/features")
def veridiq_marketing_features() -> dict[str, Any]:
    from veridiq.marketing.content import CORE_FEATURES

    return {"count": len(CORE_FEATURES), "features": CORE_FEATURES}


@app.post("/api/v1/veridiq/marketing/campaigns")
def veridiq_marketing_create_campaign(payload: MarketingCampaignRequest) -> dict[str, Any]:
    from veridiq.marketing import create_campaign

    return create_campaign(name=payload.name, product_brief=payload.product_brief, channels=payload.channels)


@app.get("/api/v1/veridiq/marketing/campaigns")
def veridiq_marketing_list_campaigns(status: Optional[str] = None) -> dict[str, Any]:
    from veridiq.marketing import list_campaigns

    campaigns = list_campaigns(status=status)
    return {"count": len(campaigns), "campaigns": campaigns}


@app.get("/api/v1/veridiq/marketing/campaigns/{campaign_id}")
def veridiq_marketing_campaign_detail(campaign_id: str) -> dict[str, Any]:
    from veridiq.marketing import daily_status, get_campaign

    campaign = get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="unknown campaign_id")
    return {**campaign, "today_queue": daily_status(campaign_id=campaign_id)}


@app.post("/api/v1/veridiq/marketing/campaigns/{campaign_id}/status")
def veridiq_marketing_set_campaign_status(campaign_id: str, payload: MarketingCampaignStatusRequest) -> dict[str, Any]:
    from veridiq.marketing.campaigns import set_campaign_status

    result = set_campaign_status(campaign_id, payload.status)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error", "unknown campaign_id"))
    return result


@app.post("/api/v1/veridiq/marketing/daily/run")
def veridiq_marketing_daily_run(payload: MarketingDailyRunRequest) -> dict[str, Any]:
    """Generate today's content pack and queue it as comms drafts. Not a
    silent cron — this is the explicit "run daily posting" action; approval
    is still required per draft before any live send."""
    from veridiq.marketing import generate_daily_pack

    result = generate_daily_pack(payload.campaign_id, channels=payload.channels, features=payload.features)
    if not result.get("ok"):
        err = result.get("error", "generation failed")
        raise HTTPException(status_code=404 if "unknown" in err else 400, detail=err)
    return result


@app.get("/api/v1/veridiq/marketing/daily/status")
def veridiq_marketing_daily_status(campaign_id: Optional[str] = None) -> dict[str, Any]:
    from veridiq.marketing import daily_status

    return daily_status(campaign_id=campaign_id)


@app.get("/api/v1/veridiq/marketing/queue")
def veridiq_marketing_queue(
    campaign_id: Optional[str] = None, channel: Optional[str] = None, status: Optional[str] = None, limit: int = 100
) -> dict[str, Any]:
    from veridiq.marketing import list_queue

    items = list_queue(campaign_id=campaign_id, channel=channel, status=status, limit=limit)
    return {"count": len(items), "queue": items}


@app.get("/api/v1/veridiq/marketing/team")
def veridiq_marketing_team() -> dict[str, Any]:
    from veridiq.workforce.roster import build_roster

    return build_roster(department="marketing_agency")


@app.get("/api/v1/veridiq/marketing/default-campaign")
def veridiq_marketing_default_campaign() -> dict[str, Any]:
    """The always-on 'Market VeriDiQ' campaign every marketing agent's Run
    now targets by default. The frontend calls this once so the Marketing
    Agency page never has to show a campaign-create form up front."""
    from veridiq.marketing import get_or_create_default_campaign

    return get_or_create_default_campaign()


@app.post("/api/v1/veridiq/marketing/run-now")
def veridiq_marketing_run_now() -> dict[str, Any]:
    """One-click "Run marketing team now" — starts every Marketing Agency
    agent against the default campaign with coordinated draft limits (one
    capped daily pack + one draft per specialist, not 6× full packs)."""
    from veridiq.marketing import build_run_payload, get_or_create_default_campaign
    from veridiq.workforce import control as agent_control
    from veridiq.workforce.departments import DEPARTMENTS

    campaign = get_or_create_default_campaign()
    agent_types = DEPARTMENTS["marketing_agency"]["agents"]
    team_run_id = f"team-{uuid.uuid4().hex[:12]}"
    sample_payload = build_run_payload(agent_types[0], campaign["campaign_id"], team_run=True, team_run_id=team_run_id)
    started: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    min_visible = global_worker_pool.marketing_min_visible_sec()
    for agent_type in agent_types:
        try:
            agent_control.assert_runnable(agent_type)
        except agent_control.AgentStoppedError as exc:
            skipped.append({"agent_type": agent_type, "reason": f"agent is {exc.status}"})
            continue
        agent = get_agent(agent_type)
        run_job_id = f"agent-run-{uuid.uuid4().hex[:12]}"
        run_payload = build_run_payload(agent_type, campaign["campaign_id"], team_run=True, team_run_id=team_run_id)

        def _fn(agent=agent, run_job_id=run_job_id, run_payload=run_payload):
            return agent.run(run_payload, job_id=run_job_id)

        channel_hint = (run_payload.get("channels") or ["content"])[0]
        result = global_worker_pool.start_agent_task(
            agent_type=agent_type,
            fn=_fn,
            job_id=run_job_id,
            task=f"Marketing team run — drafting {channel_hint} content ({agent_type})",
            min_visible_sec=min_visible,
            platform=channel_hint,
            channel=channel_hint,
        )
        started.append({"agent_type": agent_type, **result})

    message = f"Started {len(started)}/{len(agent_types)} marketing agent(s) on '{campaign['name']}'."
    if skipped:
        message += f" {len(skipped)} skipped (stopped/paused)."
    if sample_payload.get("skip_draft_generation"):
        message += f" {sample_payload.get('skip_reason')}"
    else:
        message += " Coordinated run — capped new drafts (manager pack + one per specialist)."
    return {
        "ok": True,
        "campaign_id": campaign["campaign_id"],
        "campaign_name": campaign["name"],
        "team_run_id": team_run_id,
        "started": started,
        "skipped": skipped,
        "min_visible_sec": min_visible,
        "message": message,
    }


@app.get("/api/v1/veridiq/marketing/go-live-checklist")
def veridiq_marketing_go_live_checklist() -> dict[str, Any]:
    from veridiq.marketing import go_live_checklist

    return go_live_checklist()


@app.post("/api/v1/veridiq/influencer/research")
def veridiq_influencer_research(payload: InfluencerResearchRequest) -> dict[str, Any]:
    """Public creator research via multi_search + optional AI summary — no fabricated metrics."""
    from veridiq.influencer.research import research_creators

    return research_creators(
        query=payload.query,
        niche=payload.niche,
        max_results=payload.max_results,
        summarize=payload.summarize,
    )


class DeepResearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500, description="Topic or question to research")
    max_results: int = Field(8, ge=1, le=15)
    summarize: bool = True


@app.post("/api/v1/veridiq/research")
def veridiq_deep_research(payload: DeepResearchRequest) -> dict[str, Any]:
    """Deep research via multi_search + optional LLM extract — never invents sources."""
    from veridiq.research.deep_research import deep_research

    return deep_research(
        query=payload.query,
        max_results=payload.max_results,
        summarize=payload.summarize,
    )


@app.post("/api/v1/veridiq/marketing/queue/clear-pending")
def veridiq_marketing_clear_pending(campaign_id: Optional[str] = None, keep_recent: int = 20) -> dict[str, Any]:
    from veridiq.marketing import clear_pending_drafts, get_or_create_default_campaign

    cid = campaign_id or get_or_create_default_campaign()["campaign_id"]
    return clear_pending_drafts(campaign_id=cid, keep_recent=max(5, min(100, keep_recent)))


@app.post("/api/v1/veridiq/marketing/team/assign")
def veridiq_marketing_team_assign(payload: MarketingTeamAssignRequest) -> dict[str, Any]:
    from veridiq.marketing import get_or_create_default_campaign
    from veridiq.workforce.control import UnknownAgentError, assign_campaign

    campaign_id = payload.campaign_id or get_or_create_default_campaign()["campaign_id"]
    try:
        return assign_campaign(
            payload.agent_type,
            "marketing",
            {"campaign_id": campaign_id, "channels": payload.channels},
        )
    except UnknownAgentError:
        raise HTTPException(status_code=404, detail=f"unknown agent_type '{payload.agent_type}'")


@app.get("/api/v1/veridiq/marketing/comments/preview")
def veridiq_marketing_comment_preview(
    channel: str,
    feature: str = "truth_verification",
    agent_type: str = "influencer_relations",
) -> dict[str, Any]:
    """Preview humanized engagement copy offline — no draft persisted."""
    from veridiq.marketing.human_voice import render_engagement_comment

    if channel not in ("x_twitter", "linkedin", "instagram", "telegram", "threads"):
        raise HTTPException(
            status_code=400,
            detail="channel must be one of x_twitter, linkedin, instagram, telegram, threads",
        )
    text = render_engagement_comment(agent_type, channel, feature)
    return {"ok": True, "channel": channel, "agent_type": agent_type, "feature": feature, "text": text}


@app.post("/api/v1/veridiq/marketing/comments")
def veridiq_marketing_comment(payload: MarketingCommentRequest) -> dict[str, Any]:
    """Draft a comment/reply on an existing post on another platform. Queued
    as a comms draft — approving it attempts a real reply where the official
    API supports it (X, Telegram, Threads) and reports configuration_required /
    unsupported honestly for LinkedIn/Instagram platform limitations."""
    from veridiq.comms import draft_marketing_content
    from veridiq.marketing.human_voice import render_engagement_comment

    if payload.channel not in ("x_twitter", "linkedin", "instagram", "telegram", "threads"):
        raise HTTPException(
            status_code=400,
            detail="channel must be one of x_twitter, linkedin, instagram, telegram, threads",
        )
    text = (payload.text or "").strip()
    if not text:
        text = render_engagement_comment(payload.agent_type, payload.channel, payload.feature)
    if not text.strip():
        raise HTTPException(status_code=400, detail="text is required when auto-generation fails")
    draft = draft_marketing_content(
        channel=f"{payload.channel}_comment",
        body=text,
        recipient_hint=payload.target_ref,
        campaign_id=payload.campaign_id,
        created_by_agent=payload.agent_type or "influencer_relations",
    )
    return {
        "ok": True,
        "draft": draft,
        "generated": not (payload.text or "").strip(),
        "message": f"Comment drafted for {payload.channel} — approve via POST /api/v1/veridiq/comms/approve "
        f"(channel={payload.channel}_comment) to publish.",
    }


@app.get("/api/v1/veridiq/marketing/canva/status")
def veridiq_marketing_canva_status() -> dict[str, Any]:
    from veridiq.integrations import canva

    return canva.status()


@app.post("/api/v1/veridiq/marketing/canva/design")
def veridiq_marketing_canva_design(payload: MarketingCanvaDesignRequest) -> dict[str, Any]:
    from veridiq.integrations import canva
    from veridiq.integrations.activity import global_platform_activity

    result = canva.create_design(
        title=payload.title, design_type=payload.design_type, width=payload.width, height=payload.height
    )
    status_val = result.get("status")
    global_platform_activity.record(
        platform="canva",
        task=f"Create Canva design '{payload.title}'",
        workflow_stage="canva_design",
        completion_status="completed" if status_val == "ok" else ("configuration_required" if status_val == "configuration_required" else "failed"),
        api_response_status=status_val,
        recent_activity=result.get("message"),
        errors=result.get("message") if status_val == "error" else None,
    )
    return result


@app.post("/api/v1/veridiq/marketing/video/storyboard")
def veridiq_marketing_video_storyboard(payload: MarketingStoryboardRequest) -> dict[str, Any]:
    """Always-available storyboard + VO script + shot list generator. Never
    claims a rendered video exists — see /marketing/video/render for the
    honestly-gated optional render step."""
    from veridiq.marketing import generate_storyboard

    return generate_storyboard(
        campaign_id=payload.campaign_id,
        feature_key=payload.feature,
        style=payload.style,
        duration_sec=payload.duration_sec,
        product_brief=payload.product_brief,
    )


@app.get("/api/v1/veridiq/marketing/video/storyboard/{storyboard_id}")
def veridiq_marketing_video_storyboard_get(storyboard_id: str) -> dict[str, Any]:
    from veridiq.marketing import get_storyboard

    data = get_storyboard(storyboard_id)
    if not data:
        raise HTTPException(status_code=404, detail="unknown storyboard_id")
    return data


@app.post("/api/v1/veridiq/marketing/video/render")
def veridiq_marketing_video_render(payload: MarketingRenderRequest) -> dict[str, Any]:
    from veridiq.marketing import render_storyboard

    result = render_storyboard(payload.storyboard_id)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error", "unknown storyboard_id"))
    return result


@app.api_route("/api/v1/veridiq/marketing/image/file/{filename}", methods=["GET", "HEAD"])
def veridiq_marketing_image_file(filename: str):
    """Serve generated free images from marketing_out/images/."""
    from fastapi.responses import FileResponse

    safe = Path(filename).name
    if ".." in safe or not any(safe.lower().endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp")):
        raise HTTPException(status_code=400, detail="invalid image filename")
    path = Path(__file__).resolve().parent / "marketing_out" / "images" / safe
    if not path.is_file():
        raise HTTPException(status_code=404, detail="image not found")
    media = "image/jpeg" if safe.lower().endswith((".jpg", ".jpeg")) else "image/png"
    if safe.lower().endswith(".webp"):
        media = "image/webp"
    return FileResponse(
        path,
        media_type=media,
        filename=safe,
        content_disposition_type="inline",
    )


@app.api_route("/api/v1/veridiq/marketing/video/file/{filename}", methods=["GET", "HEAD"])
def veridiq_marketing_video_file(filename: str):
    """Serve locally rendered free GIF/MP4s (and poster stills) from marketing_out/videos/.

    Uses inline disposition + GET/HEAD so HTML5 <video> can probe metadata and seek
    (Range requests via Starlette FileResponse). Attachment disposition caused some
    browsers to paint a black frame while still showing duration.
    """
    from fastapi.responses import FileResponse

    safe = Path(filename).name
    lower = safe.lower()
    allowed_ext = (".mp4", ".gif", ".jpg", ".jpeg", ".png", ".webp")
    if ".." in safe or not any(lower.endswith(ext) for ext in allowed_ext):
        raise HTTPException(status_code=400, detail="invalid video filename")
    path = Path(__file__).resolve().parent / "marketing_out" / "videos" / safe
    if not path.is_file():
        raise HTTPException(status_code=404, detail="video not found")
    if lower.endswith(".mp4"):
        media = "video/mp4"
    elif lower.endswith(".gif"):
        media = "image/gif"
    elif lower.endswith(".png"):
        media = "image/png"
    elif lower.endswith(".webp"):
        media = "image/webp"
    else:
        media = "image/jpeg"
    return FileResponse(
        path,
        media_type=media,
        filename=safe,
        content_disposition_type="inline",
    )


@app.api_route("/api/v1/veridiq/marketing/audio/file/{filename}", methods=["GET", "HEAD"])
def veridiq_marketing_audio_file(filename: str):
    """Serve generated song/TTS audio from marketing_out/audio/."""
    from fastapi.responses import FileResponse

    safe = Path(filename).name
    allowed = (".mp3", ".wav", ".ogg", ".m4a", ".webm")
    if ".." in safe or not any(safe.lower().endswith(ext) for ext in allowed):
        raise HTTPException(status_code=400, detail="invalid audio filename")
    path = Path(__file__).resolve().parent / "marketing_out" / "audio" / safe
    if not path.is_file():
        raise HTTPException(status_code=404, detail="audio not found")
    lower = safe.lower()
    if lower.endswith(".mp3"):
        media = "audio/mpeg"
    elif lower.endswith(".wav"):
        media = "audio/wav"
    elif lower.endswith(".ogg"):
        media = "audio/ogg"
    elif lower.endswith(".m4a"):
        media = "audio/mp4"
    else:
        media = "audio/webm"
    return FileResponse(
        path,
        media_type=media,
        filename=safe,
        content_disposition_type="inline",
    )


@app.get("/api/v1/veridiq/marketing/upload/file/{filename}")
def veridiq_marketing_upload_file(filename: str):
    """Serve user-uploaded Mira Postings images from marketing_out/uploads/."""
    from fastapi.responses import FileResponse

    from veridiq.security_uploads import ALLOWED_EXT, safe_filename

    safe = safe_filename(Path(filename).name)
    ext = Path(safe).suffix.lower()
    if ".." in safe or ext not in ALLOWED_EXT["image"]:
        raise HTTPException(status_code=400, detail="invalid upload filename")
    path = Path(__file__).resolve().parent / "marketing_out" / "uploads" / safe
    if not path.is_file():
        raise HTTPException(status_code=404, detail="upload not found")
    media = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(ext, "application/octet-stream")
    return FileResponse(path, media_type=media, filename=safe)


@app.get("/api/v1/veridiq/marketing/reference/file/{filename}")
def veridiq_marketing_reference_file(filename: str):
    """Serve brand/reference images from marketing_out/references/ (legal library)."""
    from fastapi.responses import FileResponse

    from veridiq.security_uploads import ALLOWED_EXT, safe_filename

    safe = safe_filename(Path(filename).name)
    ext = Path(safe).suffix.lower()
    if ".." in safe or ext not in ALLOWED_EXT["image"]:
        raise HTTPException(status_code=400, detail="invalid reference filename")
    path = Path(__file__).resolve().parent / "marketing_out" / "references" / safe
    if not path.is_file():
        raise HTTPException(status_code=404, detail="reference not found")
    media = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(ext, "application/octet-stream")
    return FileResponse(path, media_type=media, filename=safe)


@app.get("/api/v1/veridiq/orchestrator/plan")
def veridiq_orchestrator_plan(text: str) -> dict[str, Any]:
    from veridiq.orchestration.task_router import plan_request

    return plan_request(text)

@app.post("/api/v1/veridiq/orchestrate")
def veridiq_orchestrate(
    payload: OrchestrateRequest,
    user: Optional[dict[str, Any]] = Depends(get_optional_user),
) -> dict[str, Any]:
    result = global_orchestrator.execute(
        {
            "text": payload.text,
            "title": payload.title,
            "audio_path": payload.audio_path,
            "image_path": payload.image_path,
            "session_id": payload.session_id or (str(user["id"]) if user else None),
        }
    )
    return result


@app.post("/api/v1/veridiq/verify")
def veridiq_verify_text(
    payload: VerifyTextRequest,
    user: Optional[dict[str, Any]] = Depends(get_optional_user),
) -> dict[str, Any]:
    user_id = int(user["id"]) if user else None
    if payload.async_mode:
        return global_pipeline.run_async(
            title=payload.title,
            text=payload.text,
            session_id=payload.session_id,
            user_id=user_id,
        )
    return global_pipeline.run(
        title=payload.title,
        text=payload.text,
        session_id=payload.session_id,
        user_id=user_id,
    )


@app.get("/api/v1/veridiq/jobs/{job_uuid}/events")
def veridiq_job_events(job_uuid: str) -> StreamingResponse:
    def event_generator():
        for event in global_job_events.stream(job_uuid):
            yield f"data: {json.dumps(event, default=str)}\n\n"
        yield f"data: {json.dumps({'job_id': job_uuid, 'stage': 'stream_end'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/v1/veridiq/verify/upload")
async def veridiq_verify_upload(
    title: str = Form("VERIDIQ Verification"),
    text: str = Form(""),
    session_id: Optional[str] = Form(None),
    video: Optional[UploadFile] = File(None),
    audio: Optional[UploadFile] = File(None),
    image: Optional[UploadFile] = File(None),
    user: Optional[dict[str, Any]] = Depends(get_optional_user),
) -> dict[str, Any]:
    # Validate uploads BEFORE creating a job row. Creating the job first meant a
    # rejected upload (bad extension, too large, empty) still left a permanent
    # orphan row stuck at status='queued' forever — exactly the "23 running
    # jobs that don't match reality" symptom on the dashboard.
    video_bytes, video_name = await read_validated_upload(video, "video")
    audio_bytes, audio_name = await read_validated_upload(audio, "audio")
    image_bytes, image_name = await read_validated_upload(image, "image")

    if not text.strip() and not video_bytes and not audio_bytes:
        raise HTTPException(status_code=400, detail="provide text, audio, or video")

    job_stub = global_pipeline.create_job(
        title=title,
        user_id=int(user["id"]) if user else None,
        input_payload={"text": text, "has_video": bool(video), "has_audio": bool(audio)},
    )
    job_uuid = job_stub["job_uuid"]
    work = UPLOAD_DIR / job_uuid
    work.mkdir(parents=True, exist_ok=True)

    video_path = audio_path = image_path = None
    if video_bytes and video_name:
        video_path = work / video_name
        video_path.write_bytes(video_bytes)
        video_path = str(video_path)
    if audio_bytes and audio_name:
        audio_path = work / audio_name
        audio_path.write_bytes(audio_bytes)
        audio_path = str(audio_path)
    if image_bytes and image_name:
        image_path = work / image_name
        image_path.write_bytes(image_bytes)
        image_path = str(image_path)

    return global_pipeline.run(
        title=title,
        text=text,
        video_path=video_path,
        audio_path=audio_path,
        image_path=image_path,
        session_id=session_id or job_uuid,
        user_id=int(user["id"]) if user else None,
        job_uuid=job_uuid,
    )


@app.get("/api/v1/veridiq/system")
def veridiq_system_status() -> dict[str, Any]:
    started = time.perf_counter()
    health = execute_select_one()
    try:
        rag = get_rag().status()
    except Exception as exc:
        rag = {"backend": "error", "error": str(exc)}
    jobs = global_pipeline.list_jobs(limit=20)
    queued = sum(1 for j in jobs if j.get("status") in {"queued", "processing"})
    try:
        import psutil  # optional

        proc = psutil.Process()
        resources = {
            "cpu_percent": psutil.cpu_percent(interval=0.0),
            "memory_mb": round(proc.memory_info().rss / (1024 * 1024), 2),
        }
    except Exception:
        resources = {"cpu_percent": None, "memory_mb": None}
    return {
        "service": APP_NAME,
        "version": VERSION,
        "database": "ok" if health == 1 else "degraded",
        "rag": rag,
        "blockchain": global_blockchain.status(),
        "architecture": ARCHITECTURE,
        "agents": len(AGENT_REGISTRY),
        "workforce": global_worker_pool.snapshot(),
        "queue": {"recent_active": queued, "recent_total": len(jobs)},
        "resources": resources,
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


class HostChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)


@app.post("/api/v1/veridiq/host/chat")
def veridiq_host_chat(payload: HostChatRequest) -> dict[str, Any]:
    return answer_host_question(payload.question)


@app.get("/api/v1/blockchain/status")
def blockchain_status_api() -> dict[str, Any]:
    return global_blockchain.status()


@app.get("/api/v1/blockchain/contracts/{name}")
def blockchain_contract_info(name: str) -> dict[str, Any]:
    return global_blockchain.contract_info(name)


class AttestRequest(BaseModel):
    job_id: str
    report_path: Optional[str] = None


@app.post("/api/v1/blockchain/attest")
def blockchain_attest(payload: AttestRequest) -> dict[str, Any]:
    report_path = payload.report_path
    if not report_path:
        job = global_pipeline.get_job(payload.job_id)
        if not job or not job.get("report_path"):
            raise HTTPException(status_code=404, detail="job report not found")
        report_path = job["report_path"]
    return global_blockchain.attest_job_report(job_id=payload.job_id, report_path=report_path)


@app.get("/api/v1/veridiq/jobs")
def veridiq_jobs(limit: int = 50) -> dict[str, Any]:
    jobs = global_pipeline.list_jobs(limit=limit)
    return {"count": len(jobs), "jobs": jobs}


@app.get("/api/v1/veridiq/jobs/{job_uuid}")
def veridiq_job(job_uuid: str) -> dict[str, Any]:
    job = global_pipeline.get_job(job_uuid)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@app.get("/api/v1/veridiq/jobs/{job_uuid}/report")
def veridiq_job_report(job_uuid: str) -> FileResponse:
    job = global_pipeline.get_job(job_uuid)
    if job is None or not job.get("report_path"):
        raise HTTPException(status_code=404, detail="report not found")
    path = Path(job["report_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="report file missing")
    return FileResponse(path, media_type="application/pdf", filename=f"veridiq-{job_uuid}.pdf")


@app.get("/api/v1/veridiq/home-overview")
def veridiq_home_overview() -> dict[str, Any]:
    """Lightweight, public-safe snapshot for the marketing Home page — brand +
    high-level counts only. The full ops console lives at /dashboard/*.
    """
    from veridiq.calling.campaigns import list_campaigns
    from veridiq.integrations.registry import all_integrations
    from veridiq.workforce.departments import department_snapshot

    pool = global_worker_pool.snapshot()
    depts = department_snapshot()
    jobs = global_pipeline.list_jobs(limit=50)
    completed = sum(1 for j in jobs if j.get("status") == "completed")
    integrations = all_integrations()
    configured = sum(1 for i in integrations["integrations"] if i.get("configured"))
    try:
        campaigns = list_campaigns()
    except Exception:
        campaigns = []

    return {
        "brand": {
            "name": APP_NAME,
            "tagline": TAGLINE,
            "greeting": GREETING,
            "version": VERSION,
        },
        "system_status": "operational" if execute_select_one() == 1 else "degraded",
        "agents": {
            "total": len(AGENT_REGISTRY),
            "active": pool.get("active_workers", 0),
            "idle": pool.get("idle_workers", 0),
            "waiting_for_tasks": pool.get("waiting_for_tasks"),
            "status_label": pool.get("status_label"),
        },
        "departments": {"total": depts.get("count", 0)},
        "verification": {"recent_jobs": len(jobs), "completed": completed},
        "campaigns": {
            "total": len(campaigns),
            "queued": sum(1 for c in campaigns if c.get("status") == "queued_for_approval"),
            "dialed": sum(1 for c in campaigns if c.get("status") == "dialed"),
        },
        "integrations": {"total": integrations["count"], "configured": configured},
        "quick_links": [
            {"id": "dashboard", "label": "Enter Dashboard", "path": "/dashboard"},
            {"id": "verify", "label": "Verify a claim", "path": "/dashboard/verify"},
            {"id": "workforce", "label": "Meet the Workforce", "path": "/dashboard/workforce"},
            {"id": "integrations", "label": "Platform Integrations", "path": "/dashboard/integrations"},
        ],
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


_TEST_JOB_TITLES = frozenset({"API verify", "Pipeline test", "SSE test", "attest-test"})


def _is_test_job(job: dict[str, Any]) -> bool:
    return (job.get("title") or "").strip() in _TEST_JOB_TITLES


@app.get("/api/v1/veridiq/dashboard")
def veridiq_dashboard() -> dict[str, Any]:
    jobs = [j for j in global_pipeline.list_jobs(limit=100) if not _is_test_job(j)]
    completed = [j for j in jobs if j.get("status") == "completed"]
    failed = [j for j in jobs if j.get("status") == "failed"]
    running = [j for j in jobs if j.get("status") in {"processing", "queued"}]
    scores = [float(j["truth_score"]) for j in completed if j.get("truth_score") is not None]
    avg = round(sum(scores) / len(scores), 4) if scores else None
    pool = global_worker_pool.snapshot()
    try:
        rag = get_rag().status()
    except Exception as exc:
        rag = {"backend": "error", "error": str(exc)}
    connectivity = veridiq_agent_connectivity()
    news = page_news_metrics()
    meeting = page_meeting_metrics()
    reports = page_reports_metrics()
    from veridiq.workforce.departments import department_snapshot
    from veridiq.workforce.collaboration import global_collaboration_hub

    departments = department_snapshot()
    return {
        "brand": {
            "name": APP_NAME,
            "tagline": TAGLINE,
            "greeting": GREETING,
        },
        "architecture": ARCHITECTURE,
        "rag": rag,
        "blockchain": global_blockchain.status(),
        "agents": {
            "count": len(AGENT_REGISTRY),
            "types": sorted(AGENT_REGISTRY.keys()),
            "langgraph": {
                "wired_count": connectivity.get("wired_count"),
                "registered_count": connectivity.get("registered_count"),
                "ok": connectivity.get("ok"),
            },
        },
        "workforce": pool,
        "jobs": {
            "total": len(jobs),
            "completed": len(completed),
            "failed": len(failed),
            "running": len(running),
            "average_truth_score": avg,
            "recent": jobs[:12],
        },
        "verification": {
            "running": len(running),
            "completed": len(completed),
            "average_confidence": avg,
        },
        "news": news,
        "meeting": meeting,
        "reports": reports,
        "departments": departments,
        "collaboration_preview": global_collaboration_hub.recent(limit=8),
        "system": {
            "database": "ok" if execute_select_one() == 1 else "degraded",
            "langgraph": "operational" if connectivity.get("ok") else "degraded",
            "rag_backend": rag.get("backend"),
            "blockchain_mode": (global_blockchain.status() or {}).get("mode"),
        },
        "quick_actions": [
            {"id": "verify", "label": "Verification Center", "path": "/dashboard/verify"},
            {"id": "investigation", "label": "Investigation Center", "path": "/dashboard/investigation"},
            {"id": "requests", "label": "AI Requests", "path": "/dashboard/requests"},
            {"id": "workforce", "label": "AI Workforce", "path": "/dashboard/workforce"},
            {"id": "collab", "label": "Collaboration Hub", "path": "/dashboard/collaboration"},
            {"id": "ops", "label": "Operations Center", "path": "/dashboard/ops"},
            {"id": "market", "label": "Market Intelligence", "path": "/dashboard/market"},
            {"id": "blockchain", "label": "Blockchain", "path": "/dashboard/blockchain"},
        ],
        "phase2": {
            "command_center": "/api/v1/veridiq/command-center",
            "collaboration": "/api/v1/veridiq/collaboration",
            "departments": "/api/v1/veridiq/departments",
            "market": "/api/v1/veridiq/market",
            "requests": "/api/v1/veridiq/requests",
        },
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


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


@app.get("/api/v1/orchestration/health")
def orchestration_health() -> dict[str, Any]:
    """Refresh and return logs/system_health.json snapshot."""
    health = collect_full_health(running_ports=[8001, 8000])
    return {
        "ok": True,
        "health": health,
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


@app.get("/api/v1/orchestration/status")
def orchestration_status() -> dict[str, Any]:
    """Compact orchestration status for dashboards."""
    health = load_health()
    return {
        "queued_tasks": health.get("queued_tasks"),
        "active_tasks": health.get("active_tasks"),
        "completed_tasks": health.get("completed_tasks"),
        "failed_tasks": health.get("failed_tasks"),
        "active_agents": health.get("active_agents"),
        "orchestration": health.get("orchestration"),
        "service_health": health.get("service_health"),
        "updated_at": health.get("updated_at"),
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


@app.get("/api/v1/orchestration/events")
def orchestration_events(topic: Optional[str] = None, limit: int = 50) -> dict[str, Any]:
    events = global_event_bus.list_events(topic=topic, limit=limit)
    return {
        "count": len(events),
        "events": events,
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


@app.post("/api/v1/orchestration/enqueue")
def orchestration_enqueue(payload: OrchestrationEnqueueRequest) -> dict[str, Any]:
    task = global_task_queue.enqueue(
        payload.title,
        payload=payload.payload,
        priority=payload.priority,
        required_agent_type=payload.required_agent_type,
        max_retries=payload.max_retries,
    )
    return {
        "queued": True,
        "task": task,
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


@app.post("/api/v1/orchestration/dispatch")
def orchestration_dispatch(max_items: int = 5) -> dict[str, Any]:
    assigned = global_priority_dispatcher.dispatch_batch(max_items=max_items)
    return {
        "dispatched": len(assigned),
        "assignments": assigned,
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


@app.post("/api/v1/orchestration/recover")
def orchestration_recover() -> dict[str, Any]:
    report = global_auto_recovery.run_recovery_cycle()
    return {
        "recovered": True,
        "report": report,
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


@app.post("/api/v1/orchestration/heartbeat")
def orchestration_heartbeat() -> dict[str, Any]:
    pulsed = global_heartbeat_monitor.pulse_all_active()
    scan = global_heartbeat_monitor.scan()
    return {
        "pulsed": len(pulsed),
        "scan": scan,
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


@app.post("/api/v1/orchestration/workflow")
def orchestration_workflow(payload: WorkflowCreateRequest) -> dict[str, Any]:
    try:
        workflow = global_workflow_engine.create_workflow(
            payload.name,
            payload.steps,
            context=payload.context,
        )
        if payload.run_immediately:
            workflow = global_workflow_engine.run_workflow(workflow["workflow_uuid"])
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "workflow": workflow,
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


@app.get("/api/v1/contracts")
def get_contracts() -> dict[str, Any]:
    contracts = list_contracts_from_db()
    return {
        "count": len(contracts),
        "contracts": contracts,
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


@app.post("/api/v1/contracts/deploy")
def post_contracts_deploy(payload: ContractDeployRequest) -> dict[str, Any]:
    try:
        result = deploy_contracts(network=payload.network, dry_run=payload.dry_run)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return result


@app.get("/api/v1/contracts/status")
def get_contracts_status() -> dict[str, Any]:
    return contracts_status()


@app.post("/api/v1/contracts/verify")
def post_contracts_verify(payload: ContractVerifyRequest) -> dict[str, Any]:
    try:
        result = verify_contracts(network=payload.network, dry_run=payload.dry_run)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return result


# ---------------------------------------------------------------------------
# Token Launchpad — live feed + VERIDIQ launch pipeline
# ---------------------------------------------------------------------------

class LaunchpadLaunchRequest(BaseModel):
    token_name: str
    token_symbol: str
    network: str = "Base"
    initial_supply: int = 1_000_000
    decimals: int = 18


@app.get("/api/v1/veridiq/launchpad")
def veridiq_launchpad(
    q: Optional[str] = None,
    sort: str = "trending",
    network: Optional[str] = None,
) -> dict[str, Any]:
    from veridiq.launchpad import launchpad_snapshot

    return launchpad_snapshot(q=q, sort=sort, network=network)


@app.get("/api/v1/veridiq/launchpad/chart/{coin_id}")
def veridiq_launchpad_chart(coin_id: str, days: int = 1) -> dict[str, Any]:
    from veridiq.launchpad import launchpad_token_chart

    return launchpad_token_chart(coin_id, days=days)


@app.post("/api/v1/veridiq/launchpad/launch")
def veridiq_launchpad_launch(payload: LaunchpadLaunchRequest) -> dict[str, Any]:
    from veridiq.launchpad import launch_token

    try:
        return launch_token(
            token_name=payload.token_name,
            token_symbol=payload.token_symbol,
            network=payload.network,
            initial_supply=payload.initial_supply,
            decimals=payload.decimals,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)[:400]) from exc


@app.get("/api/v1/dashboard/overview")
def dashboard_overview() -> dict[str, Any]:
    """Aggregate live backend metrics for the premium frontend dashboard."""
    health = collect_full_health(running_ports=[8001, 8000, 5173])
    leads = list_leads(limit=1000)
    contracts = list_contracts_from_db()
    agents = global_registry.list_agents(refresh_from_db=True)
    return {
        "agents": {
            "total": len(agents),
            "active": sum(1 for a in agents if str(a.get("status")).lower() in {"active", "idle"}),
            "items": agents[:50],
        },
        "leads": {
            "total": len(leads),
            "items": prioritize_leads(leads)[:20],
        },
        "contracts": {
            "total": len(contracts),
            "items": contracts[:20],
        },
        "orchestration": health.get("orchestration"),
        "tasks": {
            "queued": health.get("queued_tasks"),
            "active": health.get("active_tasks"),
            "completed": health.get("completed_tasks"),
            "failed": health.get("failed_tasks"),
        },
        "database": health.get("database_health"),
        "service_health": health.get("service_health"),
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


@app.get("/")
def root():
    """Browser hits on the API port should land on the Vite UI, not raw JSON."""
    from fastapi.responses import RedirectResponse

    frontend = (
        os.getenv("VERIDIQ_FRONTEND_URL")
        or os.getenv("FRONTEND_URL")
        or "http://127.0.0.1:5173"
    ).rstrip("/")
    return RedirectResponse(url=f"{frontend}/", status_code=307)


@app.get("/api")
def api_index() -> dict[str, str]:
    return {
        "service": APP_NAME,
        "tagline": TAGLINE,
        "docs": "/docs",
        "health": "/api/v1/health",
        "brand": "/api/v1/brand",
        "frontend": (os.getenv("VERIDIQ_FRONTEND_URL") or "http://127.0.0.1:5173").rstrip("/"),
        "veridiq_dashboard": "/api/v1/veridiq/dashboard",
        "veridiq_agents": "/api/v1/veridiq/agents",
        "veridiq_sdk": "/api/v1/veridiq/sdk/tools",
        "veridiq_launchpad": "/api/v1/veridiq/launchpad",
        "veridiq_os_monitor": "/api/v1/veridiq/os/monitor",
        "verify": "/api/v1/veridiq/verify",
        "auth": "/api/v1/auth/login",
        "workforce_dashboard": "/api/v1/dashboard/overview",
        "postings": "/dashboard/postings",
    }


if __name__ == "__main__":
    import uvicorn

    # Matches .env.example (VERIDIQ_BACKEND_PORT=8001) and the CORS allow-list /
    # frontend VITE_API_BASE default — previously hardcoded to 8000, which drifted
    # from the documented dev port (see docs/veridiq/02-TRD.md §3).
    _port = int(os.environ.get("VERIDIQ_BACKEND_PORT", "8001"))
    uvicorn.run("app:app", host="0.0.0.0", port=_port, reload=False)
