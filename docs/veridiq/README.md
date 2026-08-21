# VERIDIQ — Pre-Build Documentation Set

This folder contains the six essential pre-build documents for VERIDIQ, produced by grounding every claim in the **existing codebase** (not a greenfield spec). Read them in this order:

1. **[01-PRD.md](01-PRD.md)** — Product Requirements Document: what VERIDIQ is, who it's for, features, roles, user stories, success metrics, MVP scope.
2. **[02-TRD.md](02-TRD.md)** — Technical Requirements Document: stack choices and *why*, architecture diagram, non-functional requirements, deployment.
3. **[03-App-Flow.md](03-App-Flow.md)** — every route, user journey, empty/error/success state, and the approval-gate pattern used for all outbound actions.
4. **[04-UI-UX-Brief.md](04-UI-UX-Brief.md)** — the existing brand system (colors, type, components) and the non-negotiable "honesty rules" for UI states.
5. **[05-Backend-Schema.md](05-Backend-Schema.md)** — every real SQLite table today, plus the three planned tables needed to persist calling campaigns, comms drafts, and integration activity.
6. **[06-Implementation-Plan.md](06-Implementation-Plan.md)** — what's done (Phases 1–4), what's in progress (Phase 5: persistence + RBAC), and what's next (Phase 6+), in build order.

See also **[AGENT_BRIEF.md](AGENT_BRIEF.md)** — a short must-read for any AI coding agent picking up this codebase.

## Recommended Build Order (for anyone picking up new work)

1. Read `AGENT_BRIEF.md`, then this README's "Current System Summary" below.
2. Read the PRD to understand product intent and what's explicitly out of scope.
3. Read the TRD for the *why* behind existing technical decisions — don't relitigate settled choices without cause.
4. Read the App Flow doc for the exact journey/state you're touching.
5. Read the Backend Schema doc before writing any SQL — check if the table already exists.
6. Check the Implementation Plan to see which phase your task belongs to, and follow its "Definition of Done" checklist.
7. Only then start coding, following the UI/UX Brief for anything user-facing.

## Current System Summary (as of this documentation pass)

- **Brand:** VERIDIQ — "Truth. Verified. Empowered." Enterprise AI truth-verification + AI workforce platform. Colors: deep black `#05070F`, midnight blue `#0B1224`, electric blue `#4F8CFF`, neon purple `#B14DFF`, white `#F7F9FC`, soft gray `#9AA6BF`. Font: Outfit.
- **Backend:** FastAPI (`app.py`), SQLite (`sovereign_swarm_core.db`, WAL), LangGraph orchestration, Qdrant RAG (local, in-memory fallback), dynamic worker pool (2–50), SSE for job progress + live workforce roster, JWT auth (bcrypt, 24h expiry, **not yet enforced per-route**), blockchain attestation readiness (dry-run capable, no auto-deploy), official-API-only connectors (NewsAPI, Remotive, CoinGecko, Binance public, Twilio, LinkedIn, X, Instagram, Telegram, WhatsApp, SMTP, CRM, Marketing).
- **Frontend:** Vite + React 19 + TypeScript on port 5173, `react-router-dom` v7, 22 routes across 6 sidebar nav groups (Overview, Intelligence, AI Organization, Domains, Outputs, System), hand-written CSS design system (no Tailwind), `ethers` lazy-loaded for future wallet reads.
- **Agents:** 30 registered agent types — 19 core truth-verification/reasoning agents, 8 market-intelligence agents, 3 growth/standalone agents (AI Calling, LinkedIn Outreach, Sales Intelligence). Each has a human-style persona (name, role, avatar hue, internal `@veridiq.ai` email) explicitly labeled as an AI persona, not a real person. Idle status label: **"Waiting for Assignment."**
- **Phase status:** Phases 1–4 (core platform, truth pipeline, workforce/departments, market intel + comms/calling drafts + blockchain readiness + integrations board) are **complete**. Phase 5 (in progress) is about **persistence** (calling campaigns, comms drafts, integration activity currently in-memory only) and **RBAC enforcement** (roles exist in the DB but aren't checked on routes yet).

## Key Assumptions Made Across This Documentation

- **AI Calling** uses Twilio Voice (explicit in code/env var names) — no alternative provider should be substituted.
- **LinkedIn/X/Instagram/Telegram/WhatsApp** integrations require their official OAuth/Bot/Graph APIs only — scraping is explicitly disallowed by product policy, even as a fallback.
- **`operator`/`viewer` roles** are inferred target-state roles for enterprise RBAC; today the `role` column only has `admin` and `analyst` values in practice, with no route enforcement.
- **Backend port**: `.env.example` specifies `8001`; `app.py`'s `__main__` block hardcodes `8000`. Treat `8001` (with `uvicorn app:app --port 8001`) as the intended dev port unless told otherwise — flagged as a fix item in the Implementation Plan.
- **`veridiq_agent_runs`/`veridiq_traces`** are confirmed actively written (not dormant) — verified by reading `veridiq/agents/base.py` and `veridiq/orchestration/graph.py` directly rather than assuming from the schema alone.
