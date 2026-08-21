# VERIDIQ — Product Requirements Document (PRD)

> Status labels used throughout this document: **[CURRENT]** implemented and working today, **[PHASE 5]** in progress / partially wired, **[PLANNED]** designed but needs credentials or further build-out, **[OUT OF V1]** explicitly excluded from the current release scope.

## 1. Product Summary

**Name:** VERIDIQ
**Tagline:** "Truth. Verified. Empowered."
**Version (backend constant):** 2.1.0
**One-liner:** VERIDIQ is an enterprise AI operating system that verifies truth claims (text, audio, video, images) through a multi-agent LangGraph pipeline, while running a broader "AI workforce" of specialized agents for market intelligence, investigation, meeting analysis, news corroboration, and growth/outreach — all backed by real, evidence-linked, non-fabricated activity.

VERIDIQ is **not a single chatbot**. It is presented to users as a coordinated digital workforce: named AI personas (Sophia, Noah, Emma, Maya, Daniel, Oliver, Victor, Grace, Clara, Ava, Elena, Kai, Marcus, Talia, Diego, …) organized into departments (Verification, Investigation, Research, Market Intelligence, Marketing, News, Meeting, Voice/Vision Intelligence, Blockchain, Reporting, Customer Success, AI Calling, LinkedIn, Sales), each with clear responsibilities, skills, and a live status of either **Working** or **Waiting for Assignment**.

## 2. Target Users

| Segment | Why they use VERIDIQ |
|---|---|
| **Enterprise trust & safety / compliance teams** | Need auditable, evidence-backed verification of claims, statements, media, and meeting transcripts before acting on them. |
| **Operations / "AI workforce" managers** | Need visibility into a fleet of AI agents doing real work (or explicitly idle), with department-level rollups, not vanity dashboards. |
| **Growth / RevOps / Sales-adjacent teams** | Need AI-assisted outreach (calling, LinkedIn, CRM sync) that is gated by explicit human approval before anything external happens. |
| **Market / research analysts** | Need fast, multi-signal market intelligence snapshots (on-chain readiness, sentiment, macro, technicals) sourced from official public APIs. |
| **Platform/API administrators** | Need a single place to see which official integrations (NewsAPI, Twilio, LinkedIn, CRM, SMTP, etc.) are configured vs. awaiting credentials. |

## 3. Problem Statement

Organizations increasingly rely on unverified claims — public statements, meeting transcripts, news, social narratives, uploaded media — to make decisions, and on ad-hoc scripts or single-model chat tools to triage them. This creates two problems:

1. **No structured, explainable verification path.** Truth assessment needs multiple independent signals (linguistic deception cues, voice/face proxies, fact-checking, source credibility, risk scoring) combined transparently into one score and report — not a single opaque model call.
2. **No honest visibility into "AI employees."** Dashboards built for AI agent platforms tend to fabricate activity ("processing…" spinners that never resolve, fake agent chatter) to look busy. Enterprises evaluating an AI workforce product need the opposite: an honest idle state ("Waiting for Assignment") and real, traceable task history.

## 4. Product Pillars

1. **Evidence-backed truth verification** — every truth score is decomposable into agent-level findings, citations, and a generated PDF report; nothing is asserted without a traceable source.
2. **Real digital workforce, honestly represented** — a bounded worker pool (2–50 dynamic workers) executes tasks; the UI never shows fake "processing" states, and integrations report `configuration_required` rather than invented success.
3. **Official APIs only** — every external platform connector (news, market data, social, calling, CRM, email) uses a documented, official API. **No web scraping of third-party platforms** is used for live product features (a single opt-in Playwright screenshot utility exists for the Live Agent Runtime page only, and only captures a URL the user explicitly supplies).
4. **Human-in-the-loop for anything external** — comms drafts, calling campaigns, and LinkedIn outreach are always generated as drafts first; nothing is sent, dialed, or posted without an explicit approval action.
5. **Blockchain-ready, not blockchain-forced** — verification reports can be attested on-chain (hash + metadata) when a network/wallet is configured; the platform works fully without any blockchain configuration.

## 5. Core Features

### 5.1 Truth Verification **[CURRENT]**
- Submit text, and/or upload video/audio/image (`/api/v1/veridiq/verify`, `/api/v1/veridiq/verify/upload`).
- LangGraph-orchestrated pipeline runs 19 core verification/reasoning agents (see [Backend Schema](05-Backend-Schema.md) and [App Flow](03-App-Flow.md)) producing: truth score, risk level, evidence, citations, and a downloadable PDF report.
- Real-time progress via Server-Sent Events (`/api/v1/veridiq/jobs/{job_uuid}/events`).
- Synchronous and asynchronous (`async_mode`) execution modes.

### 5.2 Investigation Center **[CURRENT]**
- Evidence packaging, timeline construction, risk analysis, citation formatting — surfaced via the Investigation department and its own frontend page.

### 5.3 AI Requests (Universal Intent Router) **[CURRENT]**
- Single natural-language entry point (`POST /api/v1/veridiq/requests`) that plans and routes a request to one of three pipelines: **truth verification**, **market intelligence**, or **comms drafting** — returning a `plan` object describing the routing decision.

### 5.4 AI Workforce / Agent Workspace **[CURRENT]**
- Live roster of all registered agents with persona identity (name, role, specialty, avatar hue, internal email), department membership, live status (`working` / `Waiting for Assignment`), metrics (runs, success rate, avg latency), and recent task history.
- Agent Workspace groups agents by department with task queues, live logs, and per-agent "connected APIs" status.
- Live SSE roster stream (`/api/v1/veridiq/workforce/events`) with automatic polling fallback.
- Dynamic worker pool (`min=2`, `max=50` by default, env-configurable) that scales with real load — never simulated.

### 5.5 Collaboration Hub **[CURRENT]**
- Cross-agent "conversation" feed derived from real workflow events (not scripted chatter).

### 5.6 Market Intelligence **[CURRENT]**
- 8 market specialist agents (market research, on-chain, news correlation, sentiment, macro trend, technical analysis, market risk, portfolio intelligence) producing a combined market overview + coin history + simple indicators, sourced from CoinGecko (no key) and Binance public endpoints; CoinMarketCap **[PLANNED / needs credentials]**.

### 5.7 News & Meeting Intelligence **[CURRENT]**
- News: corroboration signal scanning + live headlines via NewsAPI **[PLANNED / needs `VERIDIQ_NEWSAPI_KEY`]** (functions and returns `configuration_required` honestly without it).
- Meeting: transcript decomposition into speakers, decisions, and confidence — no live audio meeting capture yet **[OUT OF V1]**.

### 5.8 Comms Assistant (Draft + Approve) **[CURRENT]**
- Drafts email/agenda/follow-up/meeting-summary/contact-notes content; sending requires an explicit `/comms/approve` call. Real SMTP send only occurs when SMTP is configured **[PLANNED / needs credentials]** and a valid recipient is supplied.

### 5.9 AI Calling **[PHASE 5 / PLANNED — needs Twilio credentials]**
- Campaign creation queues a call for approval; approval only dials via Twilio Voice when `VERIDIQ_TWILIO_*` env vars are set. Call summaries can sync to CRM and generate follow-up drafts. **Campaigns are currently in-memory only (lost on backend restart) — persistence is a Phase 5 backend task, see [Implementation Plan](06-Implementation-Plan.md).**

### 5.10 Platform Integrations Center **[CURRENT status board / PLANNED live connectivity]**
- Single page listing every official connector (LinkedIn, X/Twitter, Instagram, Telegram, WhatsApp, Email/SMTP, CRM, Marketing, Twilio Calling, NewsAPI, Remotive, CoinGecko, Binance, CoinMarketCap, Qdrant RAG, Blockchain) with `configured` / `configuration_required` / `ok` status and a "Test connection" action per platform. Values are never fabricated — an unconfigured platform always reports `configuration_required`.

### 5.11 Live Agent Runtime **[PHASE 5]**
- Unified live job list merging persisted verification jobs with any in-flight worker-pool assignment.
- Optional (flag-gated, off by default) single-URL Playwright screenshot capture for demoing runtime activity — never used for scraping third-party data.

### 5.12 Blockchain Attestation Readiness **[CURRENT readiness / PLANNED live deploy]**
- Report-hash attestation service, contract status/ABI registry, wallet identity — all designed to work in a `dry_run`/simulated mode until a real network + deployer key + contract addresses are configured. **No auto-deploy** to any live network.

### 5.13 Reports & Jobs **[CURRENT]**
- PDF report generation per verification job (ReportLab), job history list/detail, report download.

### 5.14 Auth & Account **[CURRENT, partial]**
- Email/password registration & login issuing a JWT (24h default expiry, bcrypt password hashing).
- Bootstrap admin account auto-created (`admin@veridiq.ai`, role `admin`) on first run.
- **Gap:** most API routes do not currently require or check the JWT/role — auth is enforced only on `/api/v1/auth/me` and is *optional* (used to attribute jobs to a user) elsewhere. Route-level RBAC enforcement is **[PLANNED]**, see TRD §7 and Implementation Plan.

### 5.15 Ops / Command Center **[CURRENT]**
- Aggregate live metrics: worker pool state, job throughput, LangGraph wiring health, RAG status, blockchain status, department rollups, collaboration preview.

## 6. Roles

| Role | Status | Intended capabilities |
|---|---|---|
| **admin** | **[CURRENT — data model only]** | Full access; bootstrap account uses this role. No route currently restricts by role. |
| **analyst** (default) | **[CURRENT — data model only]** | Default role assigned at registration. Functionally identical access to admin today. |
| **operator** | **[PLANNED]** | Intended to run verifications, approve comms/calling drafts, manage workforce — needs new role value + route guards. |
| **viewer** | **[PLANNED]** | Intended read-only access to dashboards/reports — needs new role value + route guards. |

> The PRD's target-audience framing (admin/operator/viewer) reflects the **intended** enterprise RBAC model. The current schema stores an arbitrary `role` string (`admin` | `analyst` seen today) with **no enforcement**. This is called out explicitly so an implementing agent does not assume RBAC already works.

## 7. User Stories

1. As a **compliance analyst**, I submit a statement's transcript and receive a truth score with cited evidence and a downloadable PDF, so I can justify a decision to stakeholders. **[CURRENT]**
2. As an **ops manager**, I open the AI Workforce page and see exactly which agents are working vs. waiting, with real success rates — not a fake "5 agents active" banner. **[CURRENT]**
3. As a **growth operator**, I ask VERIDIQ to draft a follow-up email after a call, review it, and explicitly approve the send. **[CURRENT for email draft/approve; CURRENT-but-Twilio-pending for the call itself]**
4. As a **platform admin**, I open Integrations and immediately see which of the 15+ connectors need API keys, with links to get them. **[CURRENT]**
5. As an **analyst**, I ask a natural-language question ("what's the market sentiment on BTC today") and the router sends it to the market-intelligence pipeline automatically. **[CURRENT]**
6. As a **compliance lead**, I want a report's hash attested on-chain for tamper-evidence once we have a production wallet. **[PLANNED — needs chain credentials]**
7. As an **admin**, I want to restrict the Settings/Integrations pages to admin-role users only. **[PLANNED]**
8. As a **sales rep**, I want an AI agent to queue an outbound call, and only dial after I approve it, then log the outcome to our CRM. **[PHASE 5 — needs Twilio + CRM credentials, and campaign persistence]**

## 8. Success Metrics

| Metric | Target framing |
|---|---|
| Verification throughput | Jobs completed / hour under real worker-pool load, tracked via `veridiq_jobs` + pool `agent_stats`. |
| Truth pipeline accuracy proxy | `average_confidence` / `truth_score` trend across completed jobs (directional signal, not ground truth accuracy). |
| Agent reliability | Per-agent `success_rate` and `avg_latency_ms` from `agent_stats`, surfaced per department. |
| Integration coverage | % of listed platforms with `status = ok/configured` vs. `configuration_required`. |
| Time-to-approval | Time between a comms/calling draft being created and an approve/reject decision (not yet tracked — **[PLANNED]** metric requiring persisted drafts/campaigns). |
| Honesty guarantee | Zero instances of fabricated "active" agents/integrations when the pool/log is actually empty (structural guarantee via `waiting_for_tasks` / `configuration_required` fields, verified by code review, not a runtime metric). |

## 9. MVP Scope (What Exists Today)

**In scope / already shipped:**
- Text/audio/video/image truth verification pipeline with PDF report.
- 19 core agents + 8 market agents + 3 growth agents = **30 registered agent types**.
- Live workforce roster, departments, workspace, collaboration hub, worker pool scaling.
- Market intelligence overview + coin history (CoinGecko/Binance public).
- News/meeting/investigation pages backed by real (if sometimes unconfigured) data.
- Comms draft + approval flow.
- AI calling draft + approval flow (Twilio-gated, in-memory).
- Platform integrations status board with per-platform connectivity tests.
- JWT auth (register/login), bootstrap admin.
- Blockchain status/readiness + attestation endpoint (dry-run capable).
- SQLite persistence for jobs, users, agent runs, traces, leads, contracts, scheduled tasks, workflows, orchestration events.

## 10. Not in V1 / Out of Scope

- **Web scraping of third-party platforms for live data.** Only official APIs; the one exception (Playwright screenshot) is opt-in, single-URL, and not a data source for any metric.
- **Multi-tenant organizations / billing.** Single-tenant, single SQLite file, no subscription/billing enforcement (Solidity `SubscriptionManager.sol` exists as a contracts-folder artifact but is not wired into the app).
- **Real-time collaborative multi-user editing** of drafts/reports.
- **Mobile native apps.** Web-only (responsive, but no dedicated mobile app).
- **Automatic outbound messaging without approval**, on any channel, under any condition.
- **Auto-deployment of smart contracts to a live network** as part of any user-facing flow (deploy scripts exist for developers to run manually).
- **RBAC enforcement** (admin/operator/viewer route guards) — planned, not shipped.
- **Persisted comms drafts / calling campaigns / integration activity log** across backend restarts — currently in-memory only.

## 11. Assumptions Made in This Document

- "Operator" and "viewer" roles are **inferred target-state roles** based on the user's request; they do not exist in the current `role` column values.
- AI Calling is assumed to use **Twilio Voice** because `veridiq/integrations/twilio_calling.py` and `VERIDIQ_TWILIO_*` env vars already name Twilio explicitly.
- LinkedIn outreach is assumed to require **official LinkedIn OAuth 2.0** (per `.env.example` comments) — no scraping fallback should ever be implemented.
- "Truth score" and "risk level" are heuristic composite signals (weighted combinations of sub-agent scores), not a certified fact-checking authority — this framing should be preserved in any user-facing copy to avoid overclaiming.
