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

CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);
CREATE INDEX IF NOT EXISTS idx_agents_type ON agents_registry(agent_type);
CREATE INDEX IF NOT EXISTS idx_contracts_network ON deployed_contracts(network);
CREATE INDEX IF NOT EXISTS idx_bills_status ON financial_bills(payment_status);
CREATE INDEX IF NOT EXISTS idx_memory_agent ON agent_memory(agent_uuid);
CREATE INDEX IF NOT EXISTS idx_memory_tags ON agent_memory(tags);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON scheduled_tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_priority ON scheduled_tasks(priority);
"""

PHASE2_AGENT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("agent_uuid", "TEXT"),
    ("agent_name", "TEXT"),
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
