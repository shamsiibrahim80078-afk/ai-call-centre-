# VERIDIQ — Implementation Plan

> Status labels: **[CURRENT]**, **[PHASE 5]**, **[PLANNED]**, **[OUT OF V1]**.
> **This is an extension plan, not a rebuild plan.** VERIDIQ already has a working FastAPI backend, a 30-agent LangGraph-orchestrated verification/market pipeline, a live workforce/departments/workspace system, a polished React console with 22 routes, official-API integrations, and blockchain readiness. Every phase below builds on top of that — none of it proposes replacing existing modules.

## Phase 1–4 (Already Complete) — What Exists Today

These phases are inferred from the codebase's own phase markers (`PHASE2_AGENT_COLUMNS`, `PHASE3_LEAD_COLUMNS`, `"phase2"` keys in `/dashboard`, `AGENT_MARKETPLACE`-style contracts, etc.) and are **fully implemented**:

- **Phase 1 — Core platform:** FastAPI app, SQLite schema, JWT auth + bootstrap admin, legacy agent registry/scheduler/brain subsystem (`agents/`, `scheduler/`, `brain/`), lead-gen scout agent.
- **Phase 2 — Truth verification core:** 19 core `VeridiqAgent` classes, LangGraph orchestration (`veridiq/orchestration/graph.py`), Qdrant/in-memory RAG, truth pipeline with media ingestion (video→audio extraction, STT heuristic, face/voice proxies), PDF report generation, SSE job events.
- **Phase 3 — Workforce & departments:** persona identities, department taxonomy, dynamic worker pool (2–50), live roster/workspace views, collaboration hub, ops/command-center aggregation, lead scoring enrichment.
- **Phase 4 — Market intelligence, comms, blockchain readiness, integrations board:** 8 market agents + market pipeline, comms draft/approve gate, AI calling draft/approve gate (Twilio-ready), blockchain wallet/transaction/attestation façade with dry-run mode, full official-integrations status board (15 platforms), frontend console with 22 routes across 6 nav groups matching the brand system.

**Do not re-implement any of the above.** If a task looks like "build truth verification," "build the workforce dashboard," or "build the integrations page," stop and re-read the [App Flow](03-App-Flow.md) and [Backend Schema](05-Backend-Schema.md) — it almost certainly already exists and the real task is a specific gap or extension.

## Phase 5 (In Progress) — Hardening & Persistence

Goal: close the gaps between "impressive demo" and "auditable enterprise system," without changing any existing user-facing behavior.

### 5.1 Persist ephemeral state **[PLANNED, highest priority]**
- Add `veridiq_calling_campaigns`, `veridiq_comms_drafts`, `veridiq_integration_activity` tables per [Backend Schema §4](05-Backend-Schema.md#4-in-memory-state-not-persisted-today--phase-5--persistence-needed).
- Refactor `veridiq/calling/campaigns.py`, `veridiq/comms/assistant.py`, `veridiq/integrations/activity.py` to read/write SQLite instead of module-level dicts/deques, preserving every existing function signature so `app.py` and dependent modules need zero changes.
- **Testing:** restart the backend mid-campaign/mid-draft in a manual test and confirm state survives; add a pytest that creates a draft, restarts the DB session (not the process, but a fresh `db_session()`), and re-reads it.

### 5.2 Route-level RBAC **[PLANNED]**
- Decide (product decision, not purely technical) which routes should require: (a) any authenticated user, (b) `admin` role specifically, (c) remain public/optional-auth (e.g. dashboard reads for a demo/kiosk mode).
- Add an `require_role(*roles)` FastAPI dependency alongside the existing `get_current_user`/`get_optional_user` in `veridiq/auth/security.py`.
- Introduce `operator` and `viewer` as real, enforced role values (update `create_user` default handling + a migration note, not a schema change since `role` is already a free-text column).
- **Do not break currently-open endpoints silently** — ship this behind a clear checklist of "before: open, after: requires X" per route, reviewed before merge.

### 5.3 Populate/verify `veridiq_agent_runs` and `veridiq_traces` coverage **[PLANNED verification]**
- These tables ARE actively written (`VeridiqAgent._log_run()`, `VeridiqOrchestrator._persist_trace()`) — Phase 5 work here is to (a) confirm the market-intelligence pipeline (`market_graph.py`) also logs runs/traces with the same rigor as the truth pipeline, and (b) surface this audit trail in the UI (e.g. an "Agent Run History" or "Job Trace" detail view) since it's currently write-only.

### 5.4 CORS/rate-limit production posture **[PLANNED]**
- Document and default `VERIDIQ_CORS_STRICT=1` for any non-local deployment; move the in-memory rate limiter to a shared store if/when the backend runs as more than one process (Phase 6).

### 5.5 Backend port consistency **[PLANNED — quick fix]**
- Resolve the `.env.example` (`8001`) vs. `app.py __main__` (`8000`) mismatch documented in [TRD §3](02-TRD.md). Prefer making `__main__` read `VERIDIQ_BACKEND_PORT`, then re-verify the CORS allow-list and any hardcoded `localhost:8001`/`:8000` references across `frontend/src/api/client.ts` and docs.

## Phase 6 (Planned) — Department Workspaces & Live Runtime Depth

### 6.1 Department Workspaces deepening **[PLANNED]**
- Extend `veridiq/workforce/workspace.py` so each department view supports department-specific KPIs beyond the generic active/idle counts already returned (e.g. Market Intelligence department showing connector freshness, AI Calling department showing campaign funnel counts once 5.1 lands).
- Frontend: enrich `AgentWorkspacePage.tsx` per-department sections using the new KPIs — additive to the existing `build_workspace()` payload shape, not a redesign.

### 6.2 Live Agent Runtime, real depth **[PLANNED]**
- `veridiq/runtime/jobs.py` already merges persisted + in-flight jobs; extend it to include market-intelligence and comms/calling "jobs" (currently only truth-verification jobs are in `veridiq_jobs`) so the Runtime page is a true unified view. This likely means either (a) writing market/comms/calling runs into `veridiq_jobs` with a `mode` discriminator column, or (b) a lightweight `veridiq_runtime_events` table — evaluate against the existing `veridiq_jobs.status`/`truth_score`/`risk_level` columns which are truth-pipeline-specific and shouldn't be overloaded for unrelated pipelines. **Needs a schema decision before implementation** — flag to the team rather than guessing.
- If the opt-in browser screenshot recorder is promoted from demo-only, add `veridiq_runtime_sessions` (see Backend Schema §5) and a session list UI.

### 6.3 Platform connectors — activate configured, add requested **[PLANNED — needs credentials]**
- No new connector code should be required for platforms already implemented (LinkedIn, X, Instagram, Telegram, WhatsApp, SMTP, CRM, Marketing, Twilio) — the work here is **operational** (obtaining and setting API keys) plus **verification** (running `POST /integrations/{platform}/test` against real credentials in a staging environment) rather than new development.
- If a genuinely new platform is requested (e.g. Slack, Salesforce), follow the existing pattern in `veridiq/integrations/*.py` exactly: a `status()` function (config-check, never fabricates), a `test_connection()` function, and registration in `veridiq/integrations/registry.py`'s `_social_messaging_entries()` or `_internal_entries()`. **Official API/OAuth only — no scraping fallback, ever**, per the PRD's non-negotiable policy.

## Phase 7 (Planned) — Multi-Instance / Production Scaling

**Only pursue this phase when there is an actual need for more than one backend process** (e.g. real concurrent user load). Do not do this speculatively.

- Move worker-pool state, rate limiting, and SSE fan-out to a shared backend (e.g. Redis) since `AIWorkerPool`, `_RATE_BUCKETS`, and `global_job_events` are all currently single-process, in-memory singletons.
- Evaluate SQLite → Postgres migration only if write concurrency or multi-instance access becomes a real bottleneck; SQLite WAL mode is adequate for a single-process deployment and should not be replaced pre-emptively.
- Add a reverse proxy + TLS termination + process manager (e.g. `gunicorn -k uvicorn.workers.UvicornWorker`) runbook.

## Explicit Out-of-Scope / Do-Not-Build (Unless Re-Scoped)

- **[OUT OF V1]** Any scraping-based data source for a live product feature (the single opt-in Playwright screenshot utility is the only exception, and it never feeds a metric).
- **[OUT OF V1]** Auto-dialing, auto-sending, or auto-posting without the existing draft→approve gate, for any current or future channel.
- **[OUT OF V1]** Auto-deploying smart contracts from any user-triggered API call (deploy scripts remain a manual, developer-run operation).
- **[OUT OF V1]** Rebuilding the frontend design system, the sidebar IA, or the brand palette — see [UI/UX Brief](04-UI-UX-Brief.md).
- **[OUT OF V1]** Introducing a second database technology, ORM, or state-management library speculatively (see TRD §8) before an actual scaling need is confirmed.

## Definition of Done (per Phase 5+ deliverable)

1. No existing endpoint's response shape changes in a breaking way (additive fields only, unless a version bump + migration note is explicitly agreed).
2. New tables follow the migration discipline in [Backend Schema §6](05-Backend-Schema.md#6-migration-discipline).
3. Any new external-facing action (send/dial/post/deploy) implements the draft→approve gate pattern from [App Flow §2.6](03-App-Flow.md#26-comms--calling--draft--approve-approval-gate-pattern-current-pattern-reused-across-features).
4. Any new UI honors the Honesty Rules in [UI/UX Brief §6](04-UI-UX-Brief.md#6-honesty-rules-non-negotiable-ux-constraints-current-product-requirement) — no fabricated activity, correct idle/empty/configuration_required states.
5. A manual smoke test (or pytest where feasible) confirms the feature behaves correctly with **zero credentials configured** (must degrade to `configuration_required`, never crash or fabricate) and, separately, with credentials configured in a sandbox/test account.
