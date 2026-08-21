# VERIDIQ — Backend Schema Document

> Status labels: **[CURRENT]**, **[PHASE 5]**, **[PLANNED]**, **[OUT OF V1]**.
> Database: **SQLite**, file `sovereign_swarm_core.db` (repo root), WAL journal mode, `PRAGMA foreign_keys = ON` (note: most tables do not declare explicit `FOREIGN KEY` constraints — relationships are convention-based via matching string IDs; see TRD §5). Schema is defined in `database.py` (`SCHEMA_SQL`) plus additive columns applied via `_ensure_column` for backward-compatible migrations, and a couple of VERIDIQ-specific tables also created by `database.py`.

## 1. Entity-Relationship Summary

```
veridiq_users (1) ──< (many) veridiq_jobs
veridiq_jobs (1) ──< (many) veridiq_agent_runs      [joined by job_uuid ↔ job_id, string, no FK constraint]
veridiq_jobs (1) ──< (many) veridiq_traces          [joined by job_uuid ↔ job_id, string, no FK constraint]

agents_registry (1) ──< (many) agent_memory          [joined by agent_uuid, no FK constraint]
agents_registry (1) ──< (1) agent_state              [joined by agent_uuid, no FK constraint]

scheduled_tasks ──> agents_registry (assigned_agent_id / assigned_agent_uuid, no FK constraint)

leads: standalone (scout/lead-gen subsystem, unrelated to veridiq_* tables)
deployed_contracts, financial_bills: standalone (legacy/demo tables)
orchestration_events, workflow_runs, system_health_snapshots: standalone operational logs
```

## 2. Tables — **[CURRENT]** (all created by `database.py`)

### 2.1 `veridiq_users`
| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | |
| `email` | TEXT UNIQUE NOT NULL | Normalized lowercase before insert. |
| `password_hash` | TEXT NOT NULL | bcrypt. |
| `full_name` | TEXT | |
| `role` | TEXT NOT NULL DEFAULT `'analyst'` | Observed values: `admin` (bootstrap account), `analyst` (self-registered default). **No `CHECK` constraint** — any string is technically insertable. `operator`/`viewer` are **[PLANNED]** values with no enforcement yet. |
| `created_at` | TEXT NOT NULL | ISO-8601 UTC. |

**Ownership:** self-contained; referenced by `veridiq_jobs.user_id` (loosely — no FK).

### 2.2 `veridiq_jobs`
| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | |
| `job_uuid` | TEXT UNIQUE NOT NULL | External/API identifier. |
| `user_id` | INTEGER | Nullable — anonymous verification is allowed (`get_optional_user`). |
| `title` | TEXT | |
| `status` | TEXT NOT NULL DEFAULT `'queued'` | `queued` \| `processing` \| `completed` \| `failed`. |
| `input_json` | TEXT | JSON blob of original input (`text`, `video_path`, `audio_path`, `image_path`, `async_mode`). |
| `result_json` | TEXT | JSON blob of full pipeline result (or `{error, pipeline_stages}` on failure). |
| `truth_score` | REAL | Set on completion. |
| `risk_level` | TEXT | `low` \| `medium` \| `high` \| `critical` \| `unknown`. |
| `report_path` | TEXT | Filesystem path to generated PDF (`reports_out/{job_uuid}.pdf`). |
| `created_at` / `updated_at` / `completed_at` | TEXT | ISO-8601 UTC; `completed_at` null until finished. |

**Ownership:** owned by `user_id` (nullable). Read/written exclusively via `veridiq/pipeline/truth_pipeline.py`.

### 2.3 `veridiq_agent_runs`
| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | |
| `run_uuid` | TEXT UNIQUE NOT NULL | |
| `job_id` | TEXT | Loosely references `veridiq_jobs.job_uuid`. |
| `agent_type` | TEXT NOT NULL | Matches an `AGENT_REGISTRY` key. |
| `agent_name` | TEXT NOT NULL | Persona name at time of run (e.g. "Noah"). |
| `ok` | INTEGER NOT NULL | Boolean (0/1). |
| `confidence` | REAL | |
| `request_json` / `response_json` | TEXT | Full agent I/O for traceability/audit. |
| `error` | TEXT | Nullable. |
| `created_at` | TEXT NOT NULL | |

**Write path confirmed:** every `VeridiqAgent` subclass logs a row here via `_log_run()` (`veridiq/agents/base.py`) each time it runs — this is a real, active per-agent audit trail, not a dormant table.

### 2.4 `veridiq_traces`
| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | |
| `trace_uuid` | TEXT UNIQUE NOT NULL | |
| `job_id` | TEXT | Loosely references `veridiq_jobs.job_uuid`. |
| `graph_json` | TEXT NOT NULL | Intended for full LangGraph execution trace. |
| `created_at` | TEXT NOT NULL | |

**Write path confirmed:** `VeridiqOrchestrator._persist_trace()` (`veridiq/orchestration/graph.py`) writes one row per completed job with `{framework: "LangGraph", trace, rag_hits}` — this is the durable LangGraph execution trace for audit/debugging.

## 3. Tables — **[CURRENT, legacy subsystem]** (pre-dates `veridiq/` package, still actively used by `app.py`)

### 3.1 `leads`
Scout/lead-generation records. Columns: `id`, `business_name`, `website`, `pain_points`, `phone`, `status` (default `new`), `scouted_at`, plus Phase-3 additive columns: `industry`, `email`, `city`, `country`, `opportunity_score`, `automation_score`, `website_summary`, `last_analyzed`. Indexed on `status`, `website`, `opportunity_score`. Used by `/api/v1/leads`, `/api/v1/scout/*`, `brain/lead_prioritizer.py`.

### 3.2 `agents_registry`
Generic agent registry (older, parallel to `veridiq/agents/AGENT_REGISTRY`). Columns: `id`, `agent_type`, `status` (default `idle`), `current_task`, `total_cycles`, `last_ping_at`, plus Phase-2 additive columns `agent_uuid`, `agent_name` (unique index on `agent_uuid` where not null). Used by `/api/v1/agents*`, `agents/registry.py`, `scheduler/*`.

### 3.3 `deployed_contracts`
Columns: `id`, `token_name`, `token_symbol`, `contract_address`, `network`, `tx_hash`, `deployed_at`. Indexed on `network`. Written by `save_deployed_contract` (used by legacy contract-deploy flows and self-test); the newer `blockchain/` package tracks its own deployment JSON (`deployments/*.json`) and `blockchain/deploy_service.py` may write here too — **confirm before assuming a single source of truth for deployed contracts; reconcile in a future task rather than duplicating silently.**

### 3.4 `financial_bills`
Columns: `id`, `bill_type`, `amount`, `due_date`, `payment_status` (default `pending`). Indexed on `payment_status`. Appears to be a legacy/demo table from an earlier "autonomous digital workforce" iteration of this codebase — **no route in `app.py` currently reads/writes it**. Treat as **[OUT OF V1]** unless a future billing feature explicitly revives it.

### 3.5 `agent_memory`
Columns: `id`, `agent_uuid`, `memory_key`, `memory_value`, `tags`, `created_at`, `updated_at`; `UNIQUE(agent_uuid, memory_key)`. Indexed on `agent_uuid`, `tags`. Backs `memory/memory_manager.py`, used by `ConversationMemoryAgent` (`veridiq/agents/__init__.py`) for session continuity.

### 3.6 `agent_state`
Columns: `agent_uuid` (PK), `agent_name`, `agent_type`, `status`, `registry_id`, `current_task`, `state_json`, `updated_at`. General-purpose agent state snapshot store.

### 3.7 `scheduled_tasks`
Columns: `id`, `task_uuid` (unique), `title`, `payload`, `priority` (default 100), `status` (default `queued`), `required_agent_type`, `assigned_agent_id`, `assigned_agent_uuid`, `attempts`, `max_retries` (default 3), `last_error`, `created_at`, `updated_at`, `completed_at`. Indexed on `status`, `priority`. Backs `scheduler/task_scheduler.py`, `scheduler/task_queue.py`, `brain/decision_engine.py`, `/api/v1/agents/task`, `/api/v1/orchestration/enqueue`.

### 3.8 `orchestration_events`
Columns: `id`, `event_uuid` (unique), `topic`, `payload`, `source`, `created_at`. Indexed on `topic`. Generic event bus log (`scheduler/event_bus.py`), used by `/api/v1/orchestration/events`.

### 3.9 `workflow_runs`
Columns: `id`, `workflow_uuid` (unique), `name`, `status` (default `pending`), `steps_json`, `current_step` (default 0), `context_json`, `last_error`, `created_at`, `updated_at`, `completed_at`. Indexed on `status`. Backs `scheduler/workflow_engine.py`, `/api/v1/orchestration/workflow`.

### 3.10 `system_health_snapshots`
Columns: `id`, `snapshot_json`, `created_at`. Backs `utils/system_health.py` (`logs/system_health.json` is the file-based counterpart used by `/api/v1/orchestration/status`).

## 4. In-Memory State (NOT Persisted Today) — **[PHASE 5 — persistence needed]**

These subsystems currently hold state only in Python process memory and are **lost on every backend restart**. This is acceptable for a demo but is a real gap for any production/compliance use case (calling campaigns, comms drafts, and integration activity are exactly the kind of thing an enterprise would need to audit later).

| Subsystem | Current storage | Planned table |
|---|---|---|
| AI Calling campaigns (`veridiq/calling/campaigns.py`, `_CAMPAIGNS: dict`) | In-memory dict, process lifetime only | **[PLANNED]** `veridiq_calling_campaigns` |
| Comms drafts (`veridiq/comms/assistant.py`, `_PENDING: dict`) | In-memory dict, process lifetime only | **[PLANNED]** `veridiq_comms_drafts` |
| Platform activity log (`veridiq/integrations/activity.py`, `deque(maxlen=300)`) | In-memory ring buffer, process lifetime only | **[PLANNED]** `veridiq_integration_activity` |
| Worker pool assignments (`veridiq/workforce/pool.py`) | In-memory, intentionally ephemeral (this one is fine to stay in-memory — it represents *live* state, not a durable record) | Not planned for persistence; `veridiq_agent_runs`/`veridiq_traces` are the durable audit trail once wired (see §2.3–2.4). |

### 4.1 Planned Table: `veridiq_calling_campaigns` **[PLANNED]**
```sql
CREATE TABLE IF NOT EXISTS veridiq_calling_campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id TEXT NOT NULL UNIQUE,
    to_number TEXT NOT NULL,
    contact_name TEXT,
    purpose TEXT,
    script TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued_for_approval',
    call_result_json TEXT,
    summary TEXT,
    crm_sync_json TEXT,
    followup_draft_id TEXT,
    created_by_user_id INTEGER,
    created_at TEXT NOT NULL,
    approved_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_calling_campaigns_status ON veridiq_calling_campaigns(status);
```
Field names mirror `create_campaign`/`approve_campaign`/`sync_summary_to_crm`/`draft_followup` in `veridiq/calling/campaigns.py` exactly, so the migration is a drop-in replacement for the `_CAMPAIGNS` dict (swap dict reads/writes for `db_session()` calls).

### 4.2 Planned Table: `veridiq_comms_drafts` **[PLANNED]**
```sql
CREATE TABLE IF NOT EXISTS veridiq_comms_drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    draft_id TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    subject TEXT,
    body TEXT NOT NULL,
    recipient_hint TEXT,
    external_action_status TEXT NOT NULL DEFAULT 'draft_only',
    approved_channel TEXT,
    send_attempt_json TEXT,
    created_by_user_id INTEGER,
    created_at TEXT NOT NULL,
    approved_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_comms_drafts_status ON veridiq_comms_drafts(external_action_status);
```

### 4.3 Planned Table: `veridiq_integration_activity` **[PLANNED]**
```sql
CREATE TABLE IF NOT EXISTS veridiq_integration_activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    agent_type TEXT,
    job_id TEXT,
    task TEXT NOT NULL,
    workflow_stage TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    progress REAL,
    completion_status TEXT NOT NULL,
    api_response_status TEXT,
    recent_activity TEXT,
    errors TEXT
);
CREATE INDEX IF NOT EXISTS idx_integration_activity_platform ON veridiq_integration_activity(platform);
CREATE INDEX IF NOT EXISTS idx_integration_activity_agent ON veridiq_integration_activity(agent_type);
```
Mirrors `PlatformActivityLog.record()`'s exact field set — replace the `deque` with an insert + a `LIMIT`-based `recent()` query (keep a periodic prune job if unbounded growth is a concern, or keep a rolling `DELETE ... WHERE id < (SELECT MAX(id)-N ...)`).

## 5. Planned Table: Live Runtime Sessions **[PLANNED — only if browser runtime is promoted beyond a demo]**
`veridiq/runtime/browser_recorder.py` capture sessions (screenshots) are currently file-based with no DB row (confirm exact storage path before building on this). If the Live Agent Runtime page needs to list/search past sessions, add:
```sql
CREATE TABLE IF NOT EXISTS veridiq_runtime_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL UNIQUE,
    url TEXT NOT NULL,
    job_id TEXT,
    agent_type TEXT,
    screenshot_path TEXT,
    status TEXT NOT NULL DEFAULT 'captured',
    created_at TEXT NOT NULL
);
```
This is speculative — only implement once the Live Agent Runtime feature's requirements are confirmed (it is explicitly opt-in and off by default today, `VERIDIQ_BROWSER_RUNTIME=0`).

## 6. Migration Discipline

- Follow the existing pattern: add new `CREATE TABLE IF NOT EXISTS` blocks to `SCHEMA_SQL` in `database.py`, and use `_ensure_column(conn, table, column, col_type)` for any additive column on an existing table (as done for `PHASE2_AGENT_COLUMNS` / `PHASE3_LEAD_COLUMNS`).
- Do not rename or drop existing columns in place — SQLite `ALTER TABLE` support for renames/drops is limited and every consumer (across `app.py`, `veridiq/*`, `agents/*`, `scheduler/*`, `brain/*`) reads columns by name.
- Any new table should get a UUID-style external ID column (`*_uuid` or `*_id` string) alongside the integer PK, matching the codebase-wide convention.
