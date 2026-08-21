# VERIDIQ — App Flow Document

> Status labels: **[CURRENT]**, **[PHASE 5]**, **[PLANNED]**, **[OUT OF V1]**.

## 1. Route Map (Frontend)

All routes below exist today in `frontend/src/App.tsx` and are **[CURRENT]** unless noted.

| Path | Page component | Nav group |
|---|---|---|
| `/` | `Landing` | — (public splash) |
| `/dashboard` | `Dashboard` | Overview |
| `/dashboard/runtime` | `LiveRuntimePage` | Intelligence |
| `/dashboard/verify` | `VerifyPage` | Intelligence |
| `/dashboard/investigation` | `InvestigationPage` | Intelligence |
| `/dashboard/requests` | `LiveRequestsPage` | Intelligence |
| `/dashboard/workforce` | `WorkforcePage` | AI Organization |
| `/dashboard/workspace` | `AgentWorkspacePage` | AI Organization |
| `/dashboard/integrations` | `IntegrationsPage` | AI Organization |
| `/dashboard/collaboration` | `CollaborationHubPage` | AI Organization |
| `/dashboard/ops` | `OpsCenterPage` | AI Organization |
| `/dashboard/command-center` | `CommandCenterPage` | AI Organization |
| `/dashboard/market` | `MarketIntelPage` | Domains |
| `/dashboard/meeting` | `MeetingPage` | Domains |
| `/dashboard/news` | `NewsPage` | Domains |
| `/dashboard/comms` | `CommsAssistantPage` | Domains |
| `/dashboard/calling` | `AICallingPage` | Domains |
| `/dashboard/reports` | `ReportsPage` | Outputs |
| `/dashboard/jobs` | `JobsPage` | Outputs |
| `/dashboard/blockchain` | `BlockchainPage` | Outputs |
| `/dashboard/agents/:agentType` | `AgentDetailPage` | (linked from Workforce/Workspace cards, not in sidebar) |
| `/dashboard/account` | `AccountPage` | System |
| `/dashboard/settings` | `SettingsPage` | System |
| `*` | redirect → `/` | — |

Nav groups (from `AppShell.tsx`): **Overview → Intelligence → AI Organization → Domains → Outputs → System**, each collapsible and filterable via the sidebar search box.

## 2. Primary Journeys

### 2.1 Splash → Dashboard **[CURRENT]**
1. User lands on `/` (`Landing.tsx`) — brand splash, tagline, CTA into the console.
2. Navigates to `/dashboard`, which calls `GET /api/v1/veridiq/dashboard` — a single aggregate payload: brand info, architecture, RAG status, blockchain status, agent registry summary, workforce pool snapshot, job stats (`total/completed/failed/running/average_truth_score`), news/meeting/reports metrics, department snapshot, collaboration preview, system health, and quick-action links.
3. Dashboard renders quick-action tiles (Verification Center, Investigation Center, AI Requests, AI Workforce, Collaboration Hub, Ops Center, Market Intelligence, Blockchain) that route to the corresponding pages.
4. **Empty/first-run state:** all counts are `0`, `waiting_for_tasks: true`, `average_confidence: null` — the dashboard must render this as genuinely idle (e.g. "Waiting for Assignment" banners), never as a loading spinner stuck mid-animation.

### 2.2 Verify → SSE Progress → Report **[CURRENT]**
1. User opens `/dashboard/verify`.
2. Submits text and/or uploads video/audio/image via a form.
   - **Text-only, synchronous:** `POST /api/v1/veridiq/verify` with `async_mode: false` → blocks until the pipeline finishes, returns the full result in one response.
   - **Text-only or media, asynchronous (recommended for UX):** `POST /api/v1/veridiq/verify` (`async_mode: true`) or `POST /api/v1/veridiq/verify/upload` (multipart, always runs synchronously server-side today but the client should still treat it as a job with an `events_url`) → returns `{ job_uuid, status: "queued", events_url }`.
3. Client opens `EventSource` to `GET /api/v1/veridiq/jobs/{job_uuid}/events`, receiving a stream of stage events: `pipeline_start` → `video_ingest`/`audio_extraction` (if media) → `speech_to_text` → `speaker_detection` → `face_detection`/`face_tracking`/`emotion_detection`/`micro_expression_detection` (if image) → `voice_stress_analysis` (if audio) → `statement_extraction` → `orchestration_complete` → `pdf_report` → `completed` (or `failed` with an error message) → terminal `stream_end` sentinel.
4. On `completed`, the client fetches `GET /api/v1/veridiq/jobs/{job_uuid}` for the full stored record (`truth_score`, `risk_level`, `result_json` parsed to `result`) and offers `GET /api/v1/veridiq/jobs/{job_uuid}/report` (PDF download).
5. **Error state:** upload validation errors return `400`/`413` with a specific reason (bad extension, empty file, over size limit) — surface these verbatim, don't generalize to "upload failed."
6. **Approval gate:** none — verification itself is a read-style analysis action and does not require approval (approval gates are reserved for *outbound* actions, see §2.6).

### 2.3 AI Requests (router) **[CURRENT]**
1. User opens `/dashboard/requests` and types a free-text ask (e.g. "verify this claim…", "what's BTC sentiment today", "draft a follow-up email to the client").
2. `POST /api/v1/veridiq/requests` internally calls `plan_request(text)` to classify intent into `truth` | `market_intelligence` | `comms`, then routes:
   - `comms` → returns a ready-to-review draft immediately (no async job), with `message: "Communication draft prepared — external send requires explicit approval."`
   - `market_intelligence` → runs synchronously and returns the full market result plus an `events_url` for consistency (job registered under `job_id` even though it already completed).
   - default (`truth`) → same as the Verify flow (sync or async based on `async_mode`).
3. Every branch returns a `plan` object (`{ pipeline, workflow_stages, ... }`) so the UI can show *why* the router chose that path — never hide the routing decision from the user.

### 2.4 Workforce → Workspace → Agent Detail **[CURRENT]**
1. `/dashboard/workforce` calls `GET /api/v1/veridiq/agents` (flat list with identity + live status) and/or `GET /api/v1/veridiq/workforce/roster` (persona cards, filterable by `department`/`q`), plus subscribes to `GET /api/v1/veridiq/workforce/events` (SSE) for live updates; falls back to polling `roster`/`workforce` on disconnect.
2. Clicking an agent card routes to `/dashboard/agents/:agentType`, which calls `GET /api/v1/veridiq/agents/{agent_type}` for full detail: identity, department, biography, current assignment, LangGraph node wiring, recent task/execution history, connected backend services.
3. `/dashboard/workspace` calls `GET /api/v1/veridiq/workspace` (all departments → agents → task queues/logs/connected APIs) or `GET /api/v1/veridiq/workspace/{agent_type}` for a single-agent deep view — this is the operational console view (vs. Workforce's roster/HR view).
4. **Idle state (critical UX rule):** any agent with no current assignment renders `status_label: "Waiting for Assignment"`, an empty `task_queue`, and empty `live_logs` — the UI must never invent a queue item, a fake "thinking…" state, or synthetic logs for an idle agent.
5. **Working state:** shows `progress` (0–0.95, computed from elapsed time vs. `eta_sec`), `current_task`, `job_id`, `worker_id` — all sourced from the real `AIWorkerPool` snapshot.

### 2.5 Market Intelligence **[CURRENT]**
1. `/dashboard/market` calls `GET /api/v1/veridiq/market` (overview + connector status) and `GET /api/v1/veridiq/market/history/{coin_id}?days=N` for a specific coin's price history + simple indicators (SMA/momentum).
2. **Empty/degraded state:** if Binance/CoinMarketCap are unreachable or unconfigured, their sub-objects report `status: "unavailable"`/`"configuration_required"` — the page must show this per-connector, not blank out the whole page.

### 2.6 Comms / Calling — Draft → Approve (Approval Gate Pattern) **[CURRENT, pattern reused across features]**
This is the canonical **human-in-the-loop gate** used by every outbound-communication feature:

1. **Draft:** `POST /api/v1/veridiq/comms/draft` (`kind`: email/agenda/follow_up/meeting_summary/contact_notes) → returns `{ draft_id, subject, body, requires_approval_before_send: true, external_action_status: "draft_only" }`. Nothing is sent yet.
2. **Review:** UI shows the draft for the user to edit/confirm (edit-then-resubmit is a **[PLANNED]** UX affordance; today the draft is immutable once approved).
3. **Approve/Reject:** `POST /api/v1/veridiq/comms/approve` with `{ draft_id, approved, channel }`. If `approved: false` → `status: "rejected_by_user"`, terminal. If `approved: true` and the channel's integration (e.g. SMTP) is configured with a valid recipient → real send attempt, `status: "sent"` or `"send_failed"`. If not configured → `status: "approved_pending_integration"` with a clear message.
4. **AI Calling variant:** `POST /api/v1/veridiq/calling/campaigns` (create/queue) → `POST /api/v1/veridiq/calling/campaigns/{id}/approve` (`approved: true/false`). Approval only dials if Twilio is configured; otherwise `status: "approved_pending_integration"`. After a call, `POST .../summary` syncs to CRM (if configured) and `POST .../followup` drafts a follow-up email (re-entering the comms draft/approve gate).
5. **Never bypass this gate.** Any future feature that contacts a real person/system externally (new channel, new campaign type) must follow the same draft → explicit approve → (configured) send pattern — this is a product-level invariant, not just an implementation detail.

### 2.7 Investigation, News, Meeting Pages **[CURRENT]**
- Investigation: evidence/timeline/risk views sourced from completed verification jobs and the Investigation department's agents.
- News: `GET /api/v1/veridiq/pages/news-metrics` + `GET /api/v1/veridiq/connectors/news` — shows `configuration_required` state clearly when `VERIDIQ_NEWSAPI_KEY` is unset, rather than an empty-looking list with no explanation.
- Meeting: `GET /api/v1/veridiq/pages/meeting-metrics` — live meeting count, statements extracted, verification progress; `speakers_detected` is explicitly `0`/`null` when nothing is active (never fabricated).

### 2.8 Ops Center / Command Center **[CURRENT]**
- Ops (`/dashboard/ops`): worker pool state, workflow counts by status, LangGraph map, RAG/blockchain/system status, SSE endpoint info, average execution time.
- Command Center (`/dashboard/command-center`): superset combining Ops + department rollups + collaboration preview + agent health summary — the "single pane of glass" view for an ops lead.

### 2.9 Reports & Jobs **[CURRENT]**
- Jobs (`/dashboard/jobs`): `GET /api/v1/veridiq/jobs` list, each linking to detail/report.
- Reports (`/dashboard/reports`): `GET /api/v1/veridiq/pages/reports-metrics` — counts + export history; report download via `/jobs/{job_uuid}/report`.

### 2.10 Blockchain **[CURRENT readiness UI / PLANNED live attest]**
- `GET /api/v1/blockchain/status`, `GET /api/v1/blockchain/contracts/{name}`, `GET /api/v1/contracts`, `/contracts/status` for read views.
- Attestation: `POST /api/v1/blockchain/attest` (`job_id`, optional `report_path`) — works in dry-run/simulated mode without chain config; **[PLANNED]** real on-chain write path once network/wallet/contract env vars are set.
- Contract deploy/verify (`/api/v1/contracts/deploy`, `/verify`) default to `dry_run: true` — the frontend should never expose a one-click *live* deploy without a very explicit, separately-gated admin action **[PLANNED — needs product decision + role enforcement first]**.

### 2.11 Live Agent Runtime **[PHASE 5]**
- `GET /api/v1/veridiq/runtime/jobs` — merged view of persisted jobs + any in-flight worker-pool assignment not yet in the DB (e.g. a market/comms run mid-flight).
- `GET /api/v1/veridiq/runtime/status` + optional `POST /api/v1/veridiq/runtime/browser-session` (single URL screenshot, flag-gated by `VERIDIQ_BROWSER_RUNTIME=1` + Playwright installed) for a visual "what is the agent looking at" demo — **never used to scrape data for any metric or decision**.

### 2.12 Account / Settings **[CURRENT, partial]**
- Account: register/login, `GET /api/v1/auth/me` for the current user.
- Settings: local UI preferences today; **[PLANNED]** admin-only sections (rate limits, CORS, integration keys management UI) once RBAC exists — do not add credential-editing UI without server-side role enforcement in place first.

## 3. Cross-Cutting States

| State | Rule |
|---|---|
| **Idle/empty** | Always label as "Waiting for Assignment" (agents) or "Waiting for Tasks" (pool-level) or `configuration_required` (integrations) — never a spinner, never fabricated data. |
| **Loading** | Standard skeleton/spinner while awaiting the first response; do not show placeholder numbers. |
| **Error** | Surface the backend's `detail` message verbatim where safe (validation errors); use a generic fallback only for unexpected 5xx. |
| **Success** | Show the real returned data; where a value is legitimately `null` (e.g. `average_confidence` with zero completed jobs), render "—" or "No data yet," not `0`. |
| **Approval-pending** | Any draft/campaign in `draft_only`/`queued_for_approval`/`approved_pending_integration` must visually read as "not yet sent/dialed" — distinct styling from `sent`/`dialed`/`completed`. |

## 4. Assumptions

- Media upload (`/verify/upload`) is documented above as effectively synchronous server-side (the endpoint calls `global_pipeline.run(...)` directly, not `run_async`); if a future change makes it async, the App Flow step "3." above should be updated to reflect an immediate `202`-style response.
- `AgentDetailPage` is reachable only via agent cards (no sidebar entry) — this is assumed intentional (keeps the sidebar from listing 30 agents) rather than a missing nav item.
