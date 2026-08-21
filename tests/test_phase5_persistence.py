"""VERIDIQ Phase 5.1 — persistence of calling campaigns, comms drafts, and
platform activity across a fresh SQLite session (Implementation Plan §5.1).

These tests intentionally bypass the app-level TestClient for the assertion
step and instead open a brand-new `db_session()` (simulating a backend
restart, since the module functions hold no process-lifetime state) to prove
data was actually written to SQLite and not just an in-memory dict/deque.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database import db_session, initialize_database  # noqa: E402
from veridiq.calling.campaigns import approve_campaign, create_campaign  # noqa: E402
from veridiq.comms.assistant import draft_communication  # noqa: E402
from veridiq.integrations.activity import global_platform_activity  # noqa: E402

initialize_database()


def test_calling_campaign_survives_a_fresh_db_session() -> None:
    campaign = create_campaign(
        to_number="+15559990000", purpose="persistence test", script="Hello.", contact_name="Persist Co"
    )
    campaign_id = campaign["campaign_id"]

    # Simulate a restart: read back via a brand-new connection, not the module's
    # own get_campaign() (which would pass even if state were still in-memory).
    with db_session() as conn:
        row = conn.execute(
            "SELECT * FROM veridiq_calling_campaigns WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()
    assert row is not None
    assert row["to_number"] == "+15559990000"
    assert row["status"] == "queued_for_approval"

    approve_campaign(campaign_id, approved=False)
    with db_session() as conn:
        row = conn.execute(
            "SELECT status FROM veridiq_calling_campaigns WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()
    assert row["status"] == "rejected_by_user"


def test_comms_draft_survives_a_fresh_db_session() -> None:
    draft = draft_communication(kind="follow_up", context="Persistence check", recipient_hint="a@b.com")
    draft_id = draft["draft_id"]

    with db_session() as conn:
        row = conn.execute("SELECT * FROM veridiq_comms_drafts WHERE draft_id = ?", (draft_id,)).fetchone()
    assert row is not None
    assert row["kind"] == "follow_up"
    assert row["external_action_status"] == "draft_only"
    assert row["recipient_hint"] == "a@b.com"


def test_platform_activity_survives_a_fresh_db_session() -> None:
    entry = global_platform_activity.record(
        platform="_persistence_test_platform",
        task="Persistence smoke test",
        agent_type="ai_calling",
        completion_status="completed",
    )
    assert entry["platform"] == "_persistence_test_platform"

    with db_session() as conn:
        rows = conn.execute(
            "SELECT * FROM veridiq_integration_activity WHERE platform = ?",
            ("_persistence_test_platform",),
        ).fetchall()
    assert len(rows) >= 1
    assert rows[-1]["task"] == "Persistence smoke test"

    # recent() must reflect the same durable row, not a resettable in-memory buffer.
    recent = global_platform_activity.recent(limit=5, platform="_persistence_test_platform")
    assert any(item["task"] == "Persistence smoke test" for item in recent)


def test_calling_campaign_field_names_match_backend_schema_doc() -> None:
    """Guards the drop-in-replacement contract called out in
    docs/veridiq/05-Backend-Schema.md §4.1 — column names must match the
    dict keys create_campaign()/approve_campaign() already return."""
    with db_session() as conn:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(veridiq_calling_campaigns);").fetchall()}
    for expected in (
        "campaign_id",
        "to_number",
        "contact_name",
        "purpose",
        "script",
        "status",
        "call_result_json",
        "summary",
        "crm_sync_json",
        "followup_draft_id",
        "created_by_user_id",
        "created_at",
        "approved_at",
    ):
        assert expected in cols


def test_comms_drafts_and_integration_activity_table_shapes() -> None:
    with db_session() as conn:
        draft_cols = {r["name"] for r in conn.execute("PRAGMA table_info(veridiq_comms_drafts);").fetchall()}
        activity_cols = {r["name"] for r in conn.execute("PRAGMA table_info(veridiq_integration_activity);").fetchall()}
    for expected in ("draft_id", "kind", "subject", "body", "recipient_hint", "external_action_status"):
        assert expected in draft_cols
    for expected in ("platform", "agent_type", "job_id", "task", "completion_status", "recent_activity"):
        assert expected in activity_cols
