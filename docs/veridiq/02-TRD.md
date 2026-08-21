# VERIDIQ — Technical Requirements Document (TRD)

> Status labels: **[CURRENT]**, **[PHASE 5]**, **[PLANNED]**, **[OUT OF V1]** — same meaning as in the PRD.

## 1. Architecture Overview

```
┌────────────────────────┐        HTTP + SSE        ┌──────────────────────────────────┐
│  Frontend (Vite/React)  │ ───────────────────────▶ │  FastAPI backend (app.py)        │
│  localhost:5173          │ ◀─────────────────────── │  localhost:8001 (see §2.3 note)  │
└────────────────────────┘                           └──────────────────┬────────────────┘
                                                                          │
                     ┌───────────────────────────────────────────────────┼───────────────────────────────┐
                     ▼                                                   ▼                                 ▼
           ┌──────────────────┐                              ┌────────────────────┐            ┌────────────────────┐
           │ LangGraph         │                              │ SQLite              │            │ AI Worker Pool      │
           │ orchestration     │                              │ sovereign_swarm_    │            │ (2–50 dynamic       │
           │ (veridiq/orches-  │                              │ core.db (WAL)       │            │ ThreadPoolExecutor  │
           │ tration/*)        │                              └────────────────────┘            │ workers)            │
           └────────┬──────────┘                                                                 └────────────────────┘
                    │
      ┌─────────────┼─────────────────────────────┐
      ▼             ▼                              ▼
┌───────────┐ ┌──────────────┐            ┌─────────────────────┐
│ Qdrant RAG │ │ 30 agent      │            │ Official connectors  │
│ (local,    │ │ types         │            │ NewsAPI, Remotive,    │
│ on-disk,   │ │ (veridiq/     │            │ CoinGecko, Binance,   │
│ in-memory  │ │ agents/*)     │            │ Twilio, LinkedIn, X,  │
│ fallback)  │ └──────────────┘            │ SMTP, CRM, WhatsApp…   │
└───────────┘                              └─────────────────────┘
```

## 2. Frontend

| Aspect | Decision | Reason |
|---|---|---|
| Framework | React 19 + TypeScript, built with Vite 8 | Already in place (`frontend/package.json`); fast dev server, native ESM. |
| Routing | `react-router-dom` v7, single `<Routes>` tree in `App.tsx` | Simple flat route list matches the console's sidebar IA; no nested layouts needed beyond `AppShell`. |
| Styling | Hand-written CSS (`frontend/src/index.css`) with CSS custom properties, "glass" panel utility classes — **no Tailwind/CSS framework** | Matches existing brand system (deep black / midnight blue / electric blue / neon purple) precisely without fighting a utility framework's defaults. |
| Font | `Outfit` (Google Font, loaded via `--font` variable) | Already the house font — keep for consistency. |
| State management | Local component state + `fetch` calls to backend; no Redux/Zustand | App is dashboard-style (mostly server-driven reads); adding a global store would be premature complexity. |
| Real-time | Native `EventSource` (SSE) for job events and workforce roster, with polling fallback | Matches backend's SSE endpoints; avoids WebSocket infra the backend doesn't provide. |
| Blockchain client | `ethers` — **lazy-imported** in `frontend/src/lib/chainClient.ts`, not a hard dependency in `package.json` yet | Keeps the base bundle free of web3 weight until a wallet-connected feature actually ships; `getEthersProvider()` degrades gracefully with `available: false` if `ethers` isn't installed. **[PLANNED]**: add `ethers` to `dependencies` once a live-read/write blockchain UI feature is built. |
| Dev port | `5173` | Vite default; also the CORS-allowed origin baked into the backend. |
| Build output | `frontend/dist/` (static) | Deployable behind any static host / reverse proxy in front of the FastAPI backend. |

## 3. Backend

| Aspect | Decision | Reason |
|---|---|---|
| Framework | FastAPI (`app.py`), Python 3.12 | Async-friendly, automatic OpenAPI docs (`/docs`), Pydantic validation already used throughout `app.py`. |
| Server port | **`.env.example` declares `VERIDIQ_BACKEND_PORT=8001`**, but `app.py`'s `if __name__ == "__main__":` block hardcodes `uvicorn.run("app:app", host="0.0.0.0", port=8000, ...)`. | **Known inconsistency — flag, don't silently "fix" without confirming with the team.** In practice the app should be run as `uvicorn app:app --port 8001 --reload` to match `.env.example` and the CORS origins/README expectations. An implementing agent should either (a) launch uvicorn explicitly on 8001, or (b) update the `__main__` block to read `VERIDIQ_BACKEND_PORT` — **do not just change the port without also updating CORS/docs consistently.** |
| ORM / DB | Raw `sqlite3` via `database.py`, no ORM | Already implemented, WAL mode + `busy_timeout` for light concurrency; adding SQLAlchemy now would be a rewrite, not an extension. Keep raw SQL, add tables the same way (`SCHEMA_SQL` + `_ensure_column` migration helper). |
| Orchestration | LangGraph (`langgraph==1.2.10`) via `veridiq/orchestration/graph.py`, `market_graph.py`, `graph_map.py` | Already the chosen framework; provides node/edge routing across the 19 truth-verification agents and 8 market agents. Growth agents (`ai_calling`, `linkedin_outreach`, `sales_intelligence`) are **intentionally standalone**, not LangGraph nodes, because each is a single-step, approval-gated action rather than a multi-stage reasoning pipeline. |
| Vector memory / RAG | Qdrant, **local on-disk mode** (`qdrant_client.QdrantClient(path=...)`), with an in-process cosine-similarity fallback if the client fails to init | Avoids requiring a running Qdrant server for local dev while keeping the same API surface (`upsert`/`query`) if a hosted Qdrant is swapped in later. Collection `veridiq_evidence`, 64-dim embeddings (`veridiq/rag/embeddings.py` — a lightweight deterministic embedder, **not** a hosted embedding API). |
| Real-time transport | Server-Sent Events (`StreamingResponse` + `text/event-stream`) | One-directional server→client push is sufficient for job progress and workforce snapshots; simpler than WebSockets, works through most proxies with `X-Accel-Buffering: no`. |
| Concurrency model | `AIWorkerPool` (`veridiq/workforce/pool.py`) — a `ThreadPoolExecutor`-backed pool that scales worker *slots* (not agent instances) between `VERIDIQ_WORKER_MIN` (default 2) and `VERIDIQ_WORKER_MAX` (default 50) | Agents are stateless heuristic/IO-bound Python classes; threads are sufficient (most work is network I/O or light CPU), and the pool's honesty invariant (`waiting_for_tasks`, no fabricated `active_workers`) is a product requirement, not just a performance choice. |
| Auth | JWT (`PyJWT`), `HS256`, secret from `VERIDIQ_JWT_SECRET`, 24h expiry (`VERIDIQ_JWT_EXPIRE_HOURS`), bcrypt password hashing | Stateless auth suits a single-backend deployment; bcrypt is the standard for password storage. **Gap [PLANNED]:** almost no route currently depends on `get_current_user`; most use `get_optional_user` (attributes `user_id` if present, works anonymously otherwise) or no auth dependency at all. Route-level enforcement + role checks must be added without breaking the currently-open dashboard endpoints used by an unauthenticated demo/ops view (needs a product decision documented before implementation — see Implementation Plan §Phase 5). |
| Blockchain readiness | `blockchain/` package: `wallet.py`, `transaction_service.py`, `event_listener.py`, `config_loader.py`, `abi_registry.py`, `deploy_service.py`, integration façade (`blockchain/integration.py`) | Modular so that "attestation-only" mode works with zero chain config (`dry_run`), and can be pointed at Hardhat/Sepolia/Base/Ethereum via `deployments/*.json` + `.env` without code changes. **No route auto-deploys contracts.** |
| Connectors | Official REST APIs only via `requests`, each with an explicit `configuration_required` fallback (`veridiq/connectors.py`, `veridiq/integrations/*.py`) | Product requirement: never fabricate connector data. Each connector call also (optionally) writes to `global_platform_activity` for full traceability. |
| File uploads | `veridiq/security_uploads.py` — extension allow-list per media kind, `VERIDIQ_MAX_UPLOAD_MB` (default 25MB) size cap, filename sanitization (`safe_filename`) | Prevents path traversal and arbitrary file type uploads; size cap avoids resource exhaustion from a single upload. |
| Rate limiting | In-memory per-IP sliding window middleware in `app.py` (`VERIDIQ_RATE_LIMIT`, default 600/min; `VERIDIQ_RATE_WINDOW`, default 60s) | Single-process deployment; a live dashboard opens several SSE/polling connections at once, so the limit is generous by design — **not** meant as a strong anti-abuse control. **[PLANNED]** for a multi-instance deployment: replace with a shared store (Redis) rate limiter. |
| Security headers | `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy` set in the same middleware | Baseline hardening with near-zero cost; no CSP yet **[PLANNED]**. |
| CORS | Explicit allow-list by default (`5173`, `3000` variants); **`VERIDIQ_CORS_STRICT=1` required to actually enforce it**, otherwise the code forces `allow_origins=["*"]` | Convenient for local tooling; **must be set to `1` with a real allow-list before any non-local deployment** — call this out in deployment runbooks. |

## 4. Data Layer Decisions

- **Single SQLite file** (`sovereign_swarm_core.db`, WAL journal mode) — sufficient for the current single-process deployment; the schema/migration pattern (`_ensure_column`) allows additive columns without a full migration framework.
- **JSON columns** (`input_json`, `result_json`, `payload`, `state_json`, `context_json`, `graph_json`) are used deliberately for agent/job payloads whose shape varies per pipeline — avoids a rigid relational schema for inherently semi-structured agent I/O, while still keeping strongly-typed columns for anything queried/filtered/joined (status, timestamps, scores, foreign-key-like string IDs).
- **UUID string identifiers** (`job_uuid`, `run_uuid`, `trace_uuid`, `task_uuid`, `event_uuid`, `workflow_uuid`, `agent_uuid`) are used as the externally-visible/joinable IDs, with integer `AUTOINCREMENT` `id` kept as the internal primary key — lets internal code use fast integer PKs while API responses/URLs use non-guessable UUIDs.
- See [Backend Schema Document](05-Backend-Schema.md) for full table-by-table detail, including planned tables for calling campaigns, comms drafts, and integration activity persistence.

## 5. Non-Functional Requirements

| Category | Requirement | Current status |
|---|---|---|
| Performance | Verification job (text-only, sync) should return in low single-digit seconds under normal load | **[CURRENT]** — heuristic agents are fast (no external LLM calls in the hot path except optional DuckDuckGo instant-answer lookups). |
| Scalability | Worker pool should scale to `VERIDIQ_WORKER_MAX` under queue pressure and scale back down when idle | **[CURRENT]**, single-process only — horizontal scaling (multiple backend processes/instances) is **[PLANNED]** and would require moving the worker pool, SSE fan-out, and rate limiter to shared/external state. |
| Availability | No formal SLA; single-process dev/staging posture | **[CURRENT]** — health probe at `/api/v1/health` (`SELECT 1` against SQLite). |
| Observability | `logs/system_health.json`, `/api/v1/orchestration/health`, `/api/v1/orchestration/status`, `veridiq_traces` table for LangGraph run traces | **[CURRENT]**; structured external log shipping (e.g. to a log aggregator) is **[PLANNED]**. |
| Security | JWT auth exists; bcrypt hashing; upload validation; rate limiting; security headers | **[CURRENT]** as listed; **route-level authorization and CSRF considerations for cookie-based flows are [PLANNED]** (currently header-bearer JWT only, no cookies, so CSRF risk is low but not formally assessed). |
| Data integrity | Foreign keys enabled (`PRAGMA foreign_keys = ON`) but **most tables don't declare `FOREIGN KEY` constraints** (relationships are convention-based via string IDs, e.g. `veridiq_jobs.job_uuid` ↔ `veridiq_agent_runs.job_id`) | **[CURRENT — gap]**: acceptable for a single-tenant SQLite deployment; formal FK constraints are **[PLANNED]** if/when moving to Postgres (see Implementation Plan). |

## 6. Deployment

| Environment | Frontend | Backend | Notes |
|---|---|---|---|
| Local dev **[CURRENT]** | `npm run dev` → `http://localhost:5173` | `uvicorn app:app --reload --port 8001` (see §3 port note) | `.env` loaded manually by `app.py` at import time (simple line-parser, not `python-dotenv`, so it's dependency-free but doesn't support advanced `.env` syntax). |
| Frontend build **[CURRENT]** | `npm run build` → `frontend/dist/` (static) | — | Can be served by any static host or by the FastAPI app itself via a `StaticFiles` mount — **not currently wired** (`app.py` has no `StaticFiles` mount for `frontend/dist`) — **[PLANNED]** if a single-origin deployment is desired. |
| Production **[PLANNED]** | Static hosting (e.g. behind a CDN/reverse proxy) | `uvicorn`/`gunicorn` behind a reverse proxy, `VERIDIQ_CORS_STRICT=1`, real `VERIDIQ_JWT_SECRET`, Postgres migration considered if multi-instance | Needs: process manager, HTTPS termination, secrets management, and the RBAC + persistence gaps closed first (see Implementation Plan Phase 5+). |
| Smart contracts **[PLANNED / developer-run only]** | — | Hardhat project at repo root (`hardhat.config.ts`, `contracts/*.sol`, `scripts/deploy*.ts`) | Deploy scripts target Hardhat/Sepolia/Base/Ethereum; **never invoked automatically by the running application** — `blockchain/deploy_service.py` requires an explicit `dry_run=False` call with configured network credentials. |

## 7. Key Backend Modules (Reference Map)

| Module | Responsibility |
|---|---|
| `app.py` | FastAPI route definitions, middleware, request/response models. |
| `database.py` | SQLite schema (`SCHEMA_SQL`), connection/session helpers, typed writers/readers for legacy tables (`leads`, `agents_registry`, `deployed_contracts`, `financial_bills`). |
| `veridiq/agents/` | `base.py` (agent base class), `__init__.py` (19 core agent classes + `AGENT_REGISTRY`), `market.py` (8 market agents), `growth.py` (3 growth agents), `signals.py` (shared heuristic helpers). |
| `veridiq/orchestration/` | `graph.py` (`VeridiqOrchestrator` — truth pipeline LangGraph), `market_graph.py` (market pipeline), `graph_map.py` (agent↔node wiring introspection), `task_router.py` (intent classification for `/requests`), `events.py` (`global_job_events` SSE emitter). |
| `veridiq/pipeline/truth_pipeline.py` | End-to-end job lifecycle: create → media ingest → STT → orchestration → PDF → persist. |
| `veridiq/workforce/` | `pool.py` (worker pool), `identities.py` (personas), `departments.py` (department taxonomy + live rollups), `roster.py` (per-agent live cards), `workspace.py` (department→agent workspace view), `collaboration.py` (collaboration feed). |
| `veridiq/rag/` | `__init__.py` (`EvidenceRAG` Qdrant/in-memory store), `embeddings.py` (deterministic local embedder). |
| `veridiq/reports/pdf.py` | ReportLab PDF generation for truth reports. |
| `veridiq/auth/security.py` | JWT issuance/verification, bcrypt hashing, bootstrap admin. |
| `veridiq/connectors.py` | NewsAPI + Remotive connectors. |
| `veridiq/market/` | Market data (CoinGecko/Binance/CoinMarketCap) + overview/indicators. |
| `veridiq/integrations/` | Per-platform official-API clients (LinkedIn, X, Instagram, Telegram, WhatsApp, SMTP, CRM, Marketing, Twilio) + `registry.py` (status board) + `activity.py` (in-memory activity log). |
| `veridiq/calling/campaigns.py` | AI calling campaign lifecycle (in-memory). |
| `veridiq/comms/assistant.py` | Draft + approve communications (in-memory). |
| `veridiq/runtime/` | `jobs.py` (unified live job list), `browser_recorder.py` (opt-in Playwright screenshot). |
| `blockchain/` | Wallet identity, transaction/attestation service, event listener, ABI/config loaders, deploy/verify service, integration façade. |
| `scheduler/`, `brain/`, `agents/` (legacy top-level) | Older/parallel task-queue + decision-engine + generic-agent-registry subsystem (pre-dating the `veridiq/` package) still wired into `app.py` under `/api/v1/agents*`, `/api/v1/orchestration/*`, `/api/v1/scout/*`, `/api/v1/leads`. Treated as **[CURRENT, legacy]** — keep working, don't merge into `veridiq/` without a dedicated migration task. |

## 8. Assumptions

- Twilio is assumed as the calling provider (explicit in code/env names) — no alternative (e.g. Vonage) should be introduced without a new decision record.
- LinkedIn/X/Instagram/Telegram/WhatsApp integrations are assumed to require their respective **official OAuth/Bot/Graph APIs**; no scraping fallback is acceptable even if an official API is rate-limited or slow to approve.
- Postgres migration is a **future** option, not a current requirement — do not introduce SQLAlchemy/Postgres speculatively; only act on this when the Implementation Plan's Phase 6+ explicitly calls for it (e.g. multi-instance horizontal scaling).
