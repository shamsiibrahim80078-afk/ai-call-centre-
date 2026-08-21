"""
Sovereign Swarm Core — Production Database Layer
Persistent SQLite engine for the Autonomous Digital Workforce Platform.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator, Iterable, Optional

DB_FILENAME = "sovereign_swarm_core.db"
DB_PATH = Path(__file__).resolve().parent / DB_FILENAME


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Open a SQLite connection with foreign keys and row factory enabled."""
    path = Path(db_path) if db_path is not None else DB_PATH
    conn = sqlite3.connect(str(path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA busy_timeout = 30000;")
    return conn


@contextmanager
def db_session(db_path: Path | str | None = None) -> Generator[sqlite3.Connection, None, None]:
    """Context-managed connection that commits on success and rolls back on error."""
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_name TEXT NOT NULL,
    website TEXT,
    pain_points TEXT,
    phone TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    scouted_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agents_registry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'idle',
    current_task TEXT,
    total_cycles INTEGER NOT NULL DEFAULT 0,
    last_ping_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS deployed_contracts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_name TEXT NOT NULL,
    token_symbol TEXT NOT NULL,
    contract_address TEXT NOT NULL,
    network TEXT NOT NULL,
    tx_hash TEXT NOT NULL,
    deployed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS financial_bills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bill_type TEXT NOT NULL,
    amount REAL NOT NULL,
    due_date TEXT NOT NULL,
    payment_status TEXT NOT NULL DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS agent_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_uuid TEXT NOT NULL,
    memory_key TEXT NOT NULL,
    memory_value TEXT NOT NULL,
    tags TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(agent_uuid, memory_key)
);

CREATE TABLE IF NOT EXISTS agent_state (
    agent_uuid TEXT PRIMARY KEY,
    agent_name TEXT NOT NULL,
    agent_type TEXT NOT NULL,
    status TEXT NOT NULL,
    registry_id INTEGER,
    current_task TEXT,
    state_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_uuid TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    payload TEXT,
    priority INTEGER NOT NULL DEFAULT 100,
    status TEXT NOT NULL DEFAULT 'queued',
    required_agent_type TEXT,
    assigned_agent_id INTEGER,
    assigned_agent_uuid TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_retries INTEGER NOT NULL DEFAULT 3,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS orchestration_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_uuid TEXT NOT NULL UNIQUE,
    topic TEXT NOT NULL,
    payload TEXT NOT NULL,
    source TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workflow_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_uuid TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    steps_json TEXT NOT NULL,
    current_step INTEGER NOT NULL DEFAULT 0,
    context_json TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS system_health_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS veridiq_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    full_name TEXT,
    role TEXT NOT NULL DEFAULT 'analyst',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS veridiq_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_uuid TEXT NOT NULL UNIQUE,
    user_id INTEGER,
    title TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    input_json TEXT,
    result_json TEXT,
    truth_score REAL,
    risk_level TEXT,
    report_path TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS veridiq_agent_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_uuid TEXT NOT NULL UNIQUE,
    job_id TEXT,
    agent_type TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    ok INTEGER NOT NULL,
    confidence REAL,
    request_json TEXT,
    response_json TEXT,
    error TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS veridiq_traces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_uuid TEXT NOT NULL UNIQUE,
    job_id TEXT,
    graph_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- Phase 5.1 persistence — replaces in-memory dict/deque state so calling
-- campaigns, comms drafts, and integration activity survive a backend
-- restart (see docs/veridiq/05-Backend-Schema.md §4).
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

-- Phase 6 — Agent control/runtime layer: explicit start/stop/pause/resume
-- state per agent_type, a command audit log, campaign/task assignment log,
-- and "Run Agent Test" execution history. Mirrors the Phase 5.1 persistence
-- pattern (SQLite-backed, never in-memory-only) so admin actions survive a
-- backend restart (see docs/veridiq/05-Backend-Schema.md).
CREATE TABLE IF NOT EXISTS veridiq_agent_control (
    agent_type TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'running',
    updated_at TEXT NOT NULL,
    updated_by TEXT
);

CREATE TABLE IF NOT EXISTS veridiq_agent_commands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    command_uuid TEXT NOT NULL UNIQUE,
    agent_type TEXT NOT NULL,
    command TEXT NOT NULL,
    payload_json TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    result_json TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS veridiq_agent_assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    assignment_uuid TEXT NOT NULL UNIQUE,
    agent_type TEXT NOT NULL,
    campaign_type TEXT NOT NULL,
    payload_json TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    result_json TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS veridiq_agent_test_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_uuid TEXT NOT NULL UNIQUE,
    agent_type TEXT NOT NULL,
    platform TEXT,
    overall_status TEXT NOT NULL,
    steps_json TEXT NOT NULL,
    metrics_json TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    duration_ms REAL
);

-- Marketing Agency — campaign briefs the daily content-pack generator and
-- comms-draft queue key off of. Posts are always queued as
-- `veridiq_comms_drafts` rows (campaign_id-tagged) so the same draft ->
-- approve -> send gate used everywhere else in the platform applies here —
-- no separate "queue" table or bypass path.
CREATE TABLE IF NOT EXISTS veridiq_marketing_campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    product_brief TEXT,
    channels_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    last_generated_date TEXT,
    created_by_user_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Agent SDK task inbox / progress (inter-agent communication)
CREATE TABLE IF NOT EXISTS veridiq_sdk_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL UNIQUE,
    from_agent TEXT NOT NULL,
    to_agent TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    priority INTEGER NOT NULL DEFAULT 100,
    job_id TEXT,
    progress REAL NOT NULL DEFAULT 0,
    confidence REAL,
    result_json TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS veridiq_sdk_streams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stream_id TEXT NOT NULL,
    agent_type TEXT NOT NULL,
    task_id TEXT,
    chunk_json TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS veridiq_webrtc_rooms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id TEXT NOT NULL UNIQUE,
    label TEXT,
    agent_type TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    meta_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS veridiq_webrtc_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id TEXT NOT NULL UNIQUE,
    room_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    from_peer TEXT NOT NULL,
    sdp TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- LiveKit meetings hub (AI Calling rebuild) — agenda chat, scheduled PKT
-- meetings, join-gate, and Telegram go-live announce. Never fabricate LiveKit
-- video; tokens are minted only when credentials are configured.
CREATE TABLE IF NOT EXISTS veridiq_meetings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id TEXT NOT NULL UNIQUE,
    topic TEXT NOT NULL,
    agenda_json TEXT,
    status TEXT NOT NULL DEFAULT 'draft',
    scheduled_at_pkt TEXT,
    scheduled_at_utc TEXT,
    livekit_room TEXT,
    join_gate_status TEXT NOT NULL DEFAULT 'closed',
    join_requested_at TEXT,
    telegram_announce_json TEXT,
    participants_json TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    ended_at TEXT
);

CREATE TABLE IF NOT EXISTS veridiq_meeting_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT NOT NULL UNIQUE,
    meeting_id TEXT,
    hub_id TEXT NOT NULL DEFAULT 'default',
    sender_type TEXT NOT NULL,
    sender_agent TEXT,
    sender_name TEXT,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS veridiq_meeting_hub (
    hub_id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'open',
    ceo_entered_at TEXT,
    active_meeting_id TEXT,
    meta_json TEXT,
    updated_at TEXT NOT NULL
);

-- Live Collaboration Hub: agent↔agent working threads (observer feed)
CREATE TABLE IF NOT EXISTS veridiq_live_threads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    topic TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'live',
    participants_json TEXT,
    meeting_id TEXT,
    turn_index INTEGER NOT NULL DEFAULT 0,
    last_tick_at TEXT,
    meta_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS veridiq_live_thread_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT NOT NULL UNIQUE,
    thread_id TEXT NOT NULL,
    agent_id TEXT,
    sender_name TEXT,
    body TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'chat',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS veridiq_hub_invites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invite_id TEXT NOT NULL UNIQUE,
    thread_id TEXT,
    meeting_id TEXT,
    user_id TEXT NOT NULL DEFAULT 'default',
    invited_by_agent TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    message TEXT,
    created_at TEXT NOT NULL,
    responded_at TEXT
);

-- Mira Postings Studio: persistent ChatGPT-style conversations + media URLs
CREATE TABLE IF NOT EXISTS veridiq_postings_chats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL DEFAULT 'New chat',
    user_id TEXT NOT NULL DEFAULT 'default',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS veridiq_postings_chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT NOT NULL UNIQUE,
    chat_id TEXT NOT NULL,
    role TEXT NOT NULL,
    text TEXT NOT NULL DEFAULT '',
    image_url TEXT,
    video_url TEXT,
    audio_url TEXT,
    meta_json TEXT,
    created_at TEXT NOT NULL
);

-- Mira learning loop: ratings + legal brand/reference index (not scraped web)
CREATE TABLE IF NOT EXISTS veridiq_postings_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    feedback_id TEXT NOT NULL UNIQUE,
    prompt TEXT NOT NULL DEFAULT '',
    style TEXT NOT NULL DEFAULT '',
    media_url TEXT NOT NULL DEFAULT '',
    media_type TEXT NOT NULL DEFAULT 'image',
    rating INTEGER NOT NULL,
    chat_id TEXT,
    topic TEXT NOT NULL DEFAULT '',
    notes TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS veridiq_postings_references (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ref_id TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL DEFAULT 'upload',
    filename TEXT,
    path TEXT,
    url TEXT,
    topic TEXT NOT NULL DEFAULT '',
    tags_json TEXT,
    license TEXT NOT NULL DEFAULT 'user_upload',
    attribution TEXT,
    description TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);
CREATE INDEX IF NOT EXISTS idx_agents_type ON agents_registry(agent_type);
CREATE INDEX IF NOT EXISTS idx_contracts_network ON deployed_contracts(network);
CREATE INDEX IF NOT EXISTS idx_bills_status ON financial_bills(payment_status);
CREATE INDEX IF NOT EXISTS idx_memory_agent ON agent_memory(agent_uuid);
CREATE INDEX IF NOT EXISTS idx_memory_tags ON agent_memory(tags);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON scheduled_tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_priority ON scheduled_tasks(priority);
CREATE INDEX IF NOT EXISTS idx_events_topic ON orchestration_events(topic);
CREATE INDEX IF NOT EXISTS idx_workflows_status ON workflow_runs(status);
CREATE INDEX IF NOT EXISTS idx_calling_campaigns_status ON veridiq_calling_campaigns(status);
CREATE INDEX IF NOT EXISTS idx_comms_drafts_status ON veridiq_comms_drafts(external_action_status);
CREATE INDEX IF NOT EXISTS idx_integration_activity_platform ON veridiq_integration_activity(platform);
CREATE INDEX IF NOT EXISTS idx_integration_activity_agent ON veridiq_integration_activity(agent_type);
CREATE INDEX IF NOT EXISTS idx_agent_commands_type ON veridiq_agent_commands(agent_type);
CREATE INDEX IF NOT EXISTS idx_agent_assignments_type ON veridiq_agent_assignments(agent_type);
CREATE INDEX IF NOT EXISTS idx_agent_test_runs_type ON veridiq_agent_test_runs(agent_type);
CREATE INDEX IF NOT EXISTS idx_sdk_tasks_to ON veridiq_sdk_tasks(to_agent, status);
CREATE INDEX IF NOT EXISTS idx_sdk_tasks_from ON veridiq_sdk_tasks(from_agent);
CREATE INDEX IF NOT EXISTS idx_sdk_streams_agent ON veridiq_sdk_streams(agent_type);
CREATE INDEX IF NOT EXISTS idx_webrtc_signals_room ON veridiq_webrtc_signals(room_id);
CREATE INDEX IF NOT EXISTS idx_marketing_campaigns_status ON veridiq_marketing_campaigns(status);
CREATE INDEX IF NOT EXISTS idx_meetings_status ON veridiq_meetings(status);
CREATE INDEX IF NOT EXISTS idx_meeting_messages_hub ON veridiq_meeting_messages(hub_id, created_at);
CREATE INDEX IF NOT EXISTS idx_meeting_messages_meeting ON veridiq_meeting_messages(meeting_id);
CREATE INDEX IF NOT EXISTS idx_live_threads_status ON veridiq_live_threads(status, updated_at);
CREATE INDEX IF NOT EXISTS idx_live_thread_messages_thread ON veridiq_live_thread_messages(thread_id, created_at);
CREATE INDEX IF NOT EXISTS idx_hub_invites_user ON veridiq_hub_invites(user_id, status);
CREATE INDEX IF NOT EXISTS idx_postings_chats_user ON veridiq_postings_chats(user_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_postings_chat_messages_chat ON veridiq_postings_chat_messages(chat_id, created_at);
CREATE INDEX IF NOT EXISTS idx_postings_feedback_rating ON veridiq_postings_feedback(rating, created_at);
CREATE INDEX IF NOT EXISTS idx_postings_feedback_chat ON veridiq_postings_feedback(chat_id);
CREATE INDEX IF NOT EXISTS idx_postings_refs_topic ON veridiq_postings_references(topic, created_at);
"""

PHASE2_AGENT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("agent_uuid", "TEXT"),
    ("agent_name", "TEXT"),
)

PHASE6_COMMS_DRAFT_COLUMNS: tuple[tuple[str, str], ...] = (
    # Marketing Agency — links a comms draft back to the campaign that queued
    # it so /marketing/daily/status and /marketing/queue can filter without a
    # separate queue table (see docs/veridiq/05-Backend-Schema.md).
    ("campaign_id", "TEXT"),
)

PHASE3_LEAD_COLUMNS: tuple[tuple[str, str], ...] = (
    ("industry", "TEXT"),
    ("email", "TEXT"),
    ("city", "TEXT"),
    ("country", "TEXT"),
    ("opportunity_score", "REAL"),
    ("automation_score", "REAL"),
    ("website_summary", "TEXT"),
    ("last_analyzed", "TEXT"),
)


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, col_type: str) -> None:
    """Add a column to an existing table if it is missing (backward-compatible migration)."""
    existing = {
        str(row["name"])
        for row in conn.execute(f"PRAGMA table_info({table});").fetchall()
    }
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type};")


def initialize_database(db_path: Path | str | None = None) -> Path:
    """Create all relational tables and indexes if they do not already exist."""
    path = Path(db_path) if db_path is not None else DB_PATH
    with db_session(path) as conn:
        conn.executescript(SCHEMA_SQL)
        for column, col_type in PHASE2_AGENT_COLUMNS:
            _ensure_column(conn, "agents_registry", column, col_type)
        for column, col_type in PHASE3_LEAD_COLUMNS:
            _ensure_column(conn, "leads", column, col_type)
        for column, col_type in PHASE6_COMMS_DRAFT_COLUMNS:
            _ensure_column(conn, "veridiq_comms_drafts", column, col_type)
        _ensure_column(conn, "veridiq_users", "clerk_user_id", "TEXT")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_veridiq_users_clerk "
            "ON veridiq_users(clerk_user_id) WHERE clerk_user_id IS NOT NULL;"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_comms_drafts_campaign ON veridiq_comms_drafts(campaign_id);"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_agents_uuid "
            "ON agents_registry(agent_uuid) WHERE agent_uuid IS NOT NULL;"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_leads_website "
            "ON leads(website);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_leads_opportunity "
            "ON leads(opportunity_score);"
        )
    return path


def verify_schema(db_path: Path | str | None = None) -> dict[str, list[str]]:
    """Return column names for each core table to confirm structure."""
    required = (
        "leads",
        "agents_registry",
        "deployed_contracts",
        "financial_bills",
        "agent_memory",
        "agent_state",
        "scheduled_tasks",
        "orchestration_events",
        "workflow_runs",
        "system_health_snapshots",
    )
    result: dict[str, list[str]] = {}
    with db_session(db_path) as conn:
        for table in required:
            rows = conn.execute(f"PRAGMA table_info({table});").fetchall()
            if not rows:
                raise RuntimeError(f"Table '{table}' is missing after initialization.")
            result[table] = [str(row["name"]) for row in rows]
    return result


def execute_select_one(db_path: Path | str | None = None) -> int:
    """Health-check helper: run SELECT 1 and return the scalar result."""
    with db_session(db_path) as conn:
        row = conn.execute("SELECT 1;").fetchone()
        if row is None:
            raise RuntimeError("SELECT 1 returned no rows.")
        return int(row[0])


# ---------------------------------------------------------------------------
# Safe record writers
# ---------------------------------------------------------------------------

def save_lead(
    business_name: str,
    website: Optional[str] = None,
    pain_points: Optional[str] = None,
    phone: Optional[str] = None,
    status: str = "new",
    scouted_at: Optional[str] = None,
    industry: Optional[str] = None,
    email: Optional[str] = None,
    city: Optional[str] = None,
    country: Optional[str] = None,
    opportunity_score: Optional[float] = None,
    automation_score: Optional[float] = None,
    website_summary: Optional[str] = None,
    last_analyzed: Optional[str] = None,
    db_path: Path | str | None = None,
) -> int:
    """Insert a lead and return its primary key."""
    if not business_name or not business_name.strip():
        raise ValueError("business_name is required.")
    stamped = scouted_at or _utc_now_iso()
    with db_session(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO leads (
                business_name, website, pain_points, phone, status, scouted_at,
                industry, email, city, country, opportunity_score, automation_score,
                website_summary, last_analyzed
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                business_name.strip(),
                website,
                pain_points,
                phone,
                status,
                stamped,
                industry,
                email,
                city,
                country,
                opportunity_score,
                automation_score,
                website_summary,
                last_analyzed,
            ),
        )
        return int(cur.lastrowid)


def find_lead(
    *,
    business_name: Optional[str] = None,
    website: Optional[str] = None,
    db_path: Path | str | None = None,
) -> Optional[dict[str, Any]]:
    """Find an existing lead by website and/or normalized business name."""
    if not business_name and not website:
        raise ValueError("Provide business_name or website.")

    def _norm_site(value: str) -> str:
        cleaned = value.strip().lower()
        for prefix in ("https://", "http://"):
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix):]
        if cleaned.startswith("www."):
            cleaned = cleaned[4:]
        return cleaned.rstrip("/")

    with db_session(db_path) as conn:
        if website and website.strip():
            target = _norm_site(website)
            rows = conn.execute(
                "SELECT * FROM leads WHERE website IS NOT NULL AND trim(website) != ''"
            ).fetchall()
            for candidate in rows:
                if _norm_site(str(candidate["website"])) == target:
                    return dict(candidate)
        if business_name and business_name.strip():
            name = business_name.strip().lower()
            row = conn.execute(
                """
                SELECT * FROM leads
                WHERE lower(business_name) = ?
                ORDER BY id ASC LIMIT 1
                """,
                (name,),
            ).fetchone()
            return dict(row) if row else None
    return None


def update_lead(
    lead_id: int,
    *,
    business_name: Optional[str] = None,
    website: Optional[str] = None,
    pain_points: Optional[str] = None,
    phone: Optional[str] = None,
    status: Optional[str] = None,
    industry: Optional[str] = None,
    email: Optional[str] = None,
    city: Optional[str] = None,
    country: Optional[str] = None,
    opportunity_score: Optional[float] = None,
    automation_score: Optional[float] = None,
    website_summary: Optional[str] = None,
    last_analyzed: Optional[str] = None,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """Partially update a lead row and return the refreshed record."""
    with db_session(db_path) as conn:
        existing = conn.execute(
            "SELECT * FROM leads WHERE id = ?",
            (lead_id,),
        ).fetchone()
        if existing is None:
            raise LookupError(f"Lead id={lead_id} not found.")

        values = {
            "business_name": business_name if business_name is not None else existing["business_name"],
            "website": website if website is not None else existing["website"],
            "pain_points": pain_points if pain_points is not None else existing["pain_points"],
            "phone": phone if phone is not None else existing["phone"],
            "status": status if status is not None else existing["status"],
            "industry": industry if industry is not None else existing["industry"],
            "email": email if email is not None else existing["email"],
            "city": city if city is not None else existing["city"],
            "country": country if country is not None else existing["country"],
            "opportunity_score": (
                opportunity_score if opportunity_score is not None else existing["opportunity_score"]
            ),
            "automation_score": (
                automation_score if automation_score is not None else existing["automation_score"]
            ),
            "website_summary": (
                website_summary if website_summary is not None else existing["website_summary"]
            ),
            "last_analyzed": (
                last_analyzed if last_analyzed is not None else existing["last_analyzed"]
            ),
        }
        conn.execute(
            """
            UPDATE leads SET
                business_name = ?, website = ?, pain_points = ?, phone = ?, status = ?,
                industry = ?, email = ?, city = ?, country = ?,
                opportunity_score = ?, automation_score = ?, website_summary = ?,
                last_analyzed = ?
            WHERE id = ?
            """,
            (
                values["business_name"],
                values["website"],
                values["pain_points"],
                values["phone"],
                values["status"],
                values["industry"],
                values["email"],
                values["city"],
                values["country"],
                values["opportunity_score"],
                values["automation_score"],
                values["website_summary"],
                values["last_analyzed"],
                lead_id,
            ),
        )
        row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
        return dict(row) if row else {}


def list_leads(
    *,
    status: Optional[str] = None,
    limit: int = 200,
    db_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Return leads ordered by opportunity_score DESC then id DESC."""
    with db_session(db_path) as conn:
        if status:
            rows = conn.execute(
                """
                SELECT * FROM leads
                WHERE status = ?
                ORDER BY coalesce(opportunity_score, -1) DESC, id DESC
                LIMIT ?
                """,
                (status, int(limit)),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM leads
                ORDER BY coalesce(opportunity_score, -1) DESC, id DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        return [dict(row) for row in rows]


def get_lead(lead_id: int, db_path: Path | str | None = None) -> Optional[dict[str, Any]]:
    """Fetch a single lead by id."""
    with db_session(db_path) as conn:
        row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
        return dict(row) if row else None


def save_agent(
    agent_type: str,
    status: str = "idle",
    current_task: Optional[str] = None,
    total_cycles: int = 0,
    last_ping_at: Optional[str] = None,
    agent_uuid: Optional[str] = None,
    agent_name: Optional[str] = None,
    db_path: Path | str | None = None,
) -> int:
    """Register an agent and return its primary key."""
    if not agent_type or not agent_type.strip():
        raise ValueError("agent_type is required.")
    stamped = last_ping_at or _utc_now_iso()
    with db_session(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO agents_registry
                (agent_type, status, current_task, total_cycles, last_ping_at,
                 agent_uuid, agent_name)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                agent_type.strip(),
                status,
                current_task,
                int(total_cycles),
                stamped,
                agent_uuid,
                agent_name,
            ),
        )
        return int(cur.lastrowid)


def get_agent_record(
    agent_id: Optional[int] = None,
    agent_uuid: Optional[str] = None,
    db_path: Path | str | None = None,
) -> Optional[dict[str, Any]]:
    """Fetch a single agents_registry row by id or uuid."""
    if agent_id is None and not agent_uuid:
        raise ValueError("Provide agent_id or agent_uuid.")
    with db_session(db_path) as conn:
        if agent_uuid:
            row = conn.execute(
                "SELECT * FROM agents_registry WHERE agent_uuid = ?",
                (agent_uuid,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM agents_registry WHERE id = ?",
                (agent_id,),
            ).fetchone()
        return dict(row) if row else None


def update_agent_record(
    agent_id: int,
    *,
    status: Optional[str] = None,
    current_task: Optional[str] = None,
    agent_name: Optional[str] = None,
    agent_uuid: Optional[str] = None,
    total_cycles: Optional[int] = None,
    last_ping_at: Optional[str] = None,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """Partially update an agents_registry row and return the fresh record."""
    with db_session(db_path) as conn:
        existing = conn.execute(
            "SELECT * FROM agents_registry WHERE id = ?",
            (agent_id,),
        ).fetchone()
        if existing is None:
            raise LookupError(f"Agent id={agent_id} not found.")

        fields = {
            "status": status if status is not None else existing["status"],
            "current_task": current_task if current_task is not None else existing["current_task"],
            "agent_name": agent_name if agent_name is not None else existing["agent_name"],
            "agent_uuid": agent_uuid if agent_uuid is not None else existing["agent_uuid"],
            "total_cycles": (
                int(total_cycles) if total_cycles is not None else int(existing["total_cycles"])
            ),
            "last_ping_at": last_ping_at if last_ping_at is not None else existing["last_ping_at"],
        }
        conn.execute(
            """
            UPDATE agents_registry
            SET status = ?, current_task = ?, agent_name = ?, agent_uuid = ?,
                total_cycles = ?, last_ping_at = ?
            WHERE id = ?
            """,
            (
                fields["status"],
                fields["current_task"],
                fields["agent_name"],
                fields["agent_uuid"],
                fields["total_cycles"],
                fields["last_ping_at"],
                agent_id,
            ),
        )
        row = conn.execute(
            "SELECT * FROM agents_registry WHERE id = ?",
            (agent_id,),
        ).fetchone()
        return dict(row) if row else {}


def delete_agent_record(
    agent_id: Optional[int] = None,
    agent_uuid: Optional[str] = None,
    db_path: Path | str | None = None,
) -> bool:
    """Delete an agents_registry row. Returns True if a row was removed."""
    if agent_id is None and not agent_uuid:
        raise ValueError("Provide agent_id or agent_uuid.")
    with db_session(db_path) as conn:
        if agent_uuid:
            cur = conn.execute(
                "DELETE FROM agents_registry WHERE agent_uuid = ?",
                (agent_uuid,),
            )
        else:
            cur = conn.execute(
                "DELETE FROM agents_registry WHERE id = ?",
                (agent_id,),
            )
        return cur.rowcount > 0


def list_agent_records(db_path: Path | str | None = None) -> list[dict[str, Any]]:
    """Return all agents_registry rows ordered by id."""
    with db_session(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, agent_type, status, current_task, total_cycles, last_ping_at,
                   agent_uuid, agent_name
            FROM agents_registry
            ORDER BY id ASC
            """
        ).fetchall()
        return [dict(row) for row in rows]


def save_deployed_contract(
    token_name: str,
    token_symbol: str,
    contract_address: str,
    network: str,
    tx_hash: str,
    deployed_at: Optional[str] = None,
    db_path: Path | str | None = None,
) -> int:
    """Persist a simulated (or live) contract deployment record."""
    for field_name, value in (
        ("token_name", token_name),
        ("token_symbol", token_symbol),
        ("contract_address", contract_address),
        ("network", network),
        ("tx_hash", tx_hash),
    ):
        if not value or not str(value).strip():
            raise ValueError(f"{field_name} is required.")
    stamped = deployed_at or _utc_now_iso()
    with db_session(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO deployed_contracts
                (token_name, token_symbol, contract_address, network, tx_hash, deployed_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                token_name.strip(),
                token_symbol.strip().upper(),
                contract_address.strip(),
                network.strip(),
                tx_hash.strip(),
                stamped,
            ),
        )
        return int(cur.lastrowid)


def save_financial_bill(
    bill_type: str,
    amount: float,
    due_date: str,
    payment_status: str = "pending",
    db_path: Path | str | None = None,
) -> int:
    """Insert a financial bill and return its primary key."""
    if not bill_type or not bill_type.strip():
        raise ValueError("bill_type is required.")
    if amount < 0:
        raise ValueError("amount must be non-negative.")
    if not due_date or not due_date.strip():
        raise ValueError("due_date is required.")
    with db_session(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO financial_bills (bill_type, amount, due_date, payment_status)
            VALUES (?, ?, ?, ?)
            """,
            (bill_type.strip(), float(amount), due_date.strip(), payment_status),
        )
        return int(cur.lastrowid)


# ---------------------------------------------------------------------------
# Heartbeat helpers
# ---------------------------------------------------------------------------

def ping_agent(
    agent_id: int,
    status: Optional[str] = None,
    current_task: Optional[str] = None,
    increment_cycle: bool = True,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """Update an agent's last_ping_at (and optional status/task), return the row."""
    stamped = _utc_now_iso()
    with db_session(db_path) as conn:
        existing = conn.execute(
            "SELECT * FROM agents_registry WHERE id = ?",
            (agent_id,),
        ).fetchone()
        if existing is None:
            raise LookupError(f"Agent id={agent_id} not found.")

        new_status = status if status is not None else existing["status"]
        new_task = current_task if current_task is not None else existing["current_task"]
        new_cycles = int(existing["total_cycles"]) + (1 if increment_cycle else 0)

        conn.execute(
            """
            UPDATE agents_registry
            SET status = ?, current_task = ?, total_cycles = ?, last_ping_at = ?
            WHERE id = ?
            """,
            (new_status, new_task, new_cycles, stamped, agent_id),
        )
        row = conn.execute(
            "SELECT * FROM agents_registry WHERE id = ?",
            (agent_id,),
        ).fetchone()
        return dict(row) if row else {}


def read_heartbeats(
    agent_type: Optional[str] = None,
    db_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Read agent heartbeat rows, optionally filtered by agent_type."""
    with db_session(db_path) as conn:
        if agent_type:
            rows: Iterable[sqlite3.Row] = conn.execute(
                """
                SELECT id, agent_type, status, current_task, total_cycles, last_ping_at
                FROM agents_registry
                WHERE agent_type = ?
                ORDER BY last_ping_at DESC
                """,
                (agent_type,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, agent_type, status, current_task, total_cycles, last_ping_at
                FROM agents_registry
                ORDER BY last_ping_at DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]


def list_deployed_contracts(db_path: Path | str | None = None) -> list[dict[str, Any]]:
    """Return all deployed contract records ordered by newest first."""
    with db_session(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, token_name, token_symbol, contract_address, network, tx_hash, deployed_at
            FROM deployed_contracts
            ORDER BY id DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]


# Auto-initialization on import
initialize_database()


def _self_test() -> None:
    """Exercise schema creation, writers, and heartbeat readers."""
    print("=" * 60)
    print("SOVEREIGN SWARM CORE — DATABASE SELF-TEST")
    print("=" * 60)

    path = initialize_database()
    print(f"[OK] Database path: {path}")
    print(f"[OK] File exists:   {path.exists()}")

    schema = verify_schema()
    for table, columns in schema.items():
        print(f"[OK] Table `{table}` columns: {', '.join(columns)}")

    assert execute_select_one() == 1
    print("[OK] SELECT 1 connectivity probe passed")

    lead_id = save_lead(
        business_name="Acme Robotics LLC",
        website="https://acme-robotics.example",
        pain_points="Manual lead qualification",
        phone="+1-555-0100",
        status="scouted",
    )
    print(f"[OK] Saved lead id={lead_id}")

    agent_id = save_agent(
        agent_type="scout",
        status="active",
        current_task="market_scan",
        total_cycles=0,
    )
    print(f"[OK] Saved agent id={agent_id}")

    heartbeat = ping_agent(agent_id, status="active", current_task="deep_crawl")
    print(
        f"[OK] Heartbeat agent id={heartbeat['id']} "
        f"cycles={heartbeat['total_cycles']} ping={heartbeat['last_ping_at']}"
    )

    beats = read_heartbeats(agent_type="scout")
    assert len(beats) >= 1
    print(f"[OK] read_heartbeats returned {len(beats)} scout agent(s)")

    bill_id = save_financial_bill(
        bill_type="infra_compute",
        amount=249.99,
        due_date="2026-08-15",
        payment_status="pending",
    )
    print(f"[OK] Saved financial bill id={bill_id}")

    contract_id = save_deployed_contract(
        token_name="Sovereign Test Token",
        token_symbol="SVT",
        contract_address="0xTEST_INIT_PLACEHOLDER_00000001",
        network="Base",
        tx_hash="0xTEST_TX_INIT_00000001",
    )
    print(f"[OK] Saved deployed contract id={contract_id}")

    print("=" * 60)
    print("DATABASE SELF-TEST: PASSED")
    print("=" * 60)


if __name__ == "__main__":
    _self_test()
