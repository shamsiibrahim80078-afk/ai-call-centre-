"""AI Calling campaigns — draft/approve gate mirrors the comms assistant.

No number is ever dialed automatically. `create_campaign` only queues a
campaign for review; `approve_campaign` is the single explicit-approval
choke point that may place a real Twilio call (only when Twilio is
configured). CRM sync and follow-up drafting reuse the same honesty rules
as the rest of the platform integrations.

Phase 5.1: persisted to `veridiq_calling_campaigns` (SQLite) instead of an
in-memory dict, so campaigns survive a backend restart. Function signatures
and returned dict shapes are unchanged from the in-memory implementation —
callers (`app.py`, tests, frontend) need zero changes.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from database import db_session, initialize_database  # noqa: E402


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _row_to_campaign(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d.pop("id", None)
    call_result_json = d.pop("call_result_json", None)
    crm_sync_json = d.pop("crm_sync_json", None)
    d["call_result"] = json.loads(call_result_json) if call_result_json else None
    d["crm_sync"] = json.loads(crm_sync_json) if crm_sync_json else None
    return d


def create_campaign(
    *,
    to_number: str,
    purpose: str,
    script: str,
    contact_name: str = "",
    created_by_user_id: Optional[int] = None,
) -> dict[str, Any]:
    initialize_database()
    campaign_id = str(uuid.uuid4())
    created_at = _utc_now()
    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO veridiq_calling_campaigns
                (campaign_id, to_number, contact_name, purpose, script, status,
                 created_by_user_id, created_at)
            VALUES (?, ?, ?, ?, ?, 'queued_for_approval', ?, ?)
            """,
            (campaign_id, to_number, contact_name, purpose, script, created_by_user_id, created_at),
        )
    return get_campaign(campaign_id)  # type: ignore[return-value]


def list_campaigns() -> list[dict[str, Any]]:
    initialize_database()
    with db_session() as conn:
        rows = conn.execute(
            "SELECT * FROM veridiq_calling_campaigns ORDER BY created_at DESC"
        ).fetchall()
    return [_row_to_campaign(r) for r in rows]


def get_campaign(campaign_id: str) -> Optional[dict[str, Any]]:
    initialize_database()
    with db_session() as conn:
        row = conn.execute(
            "SELECT * FROM veridiq_calling_campaigns WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()
    return _row_to_campaign(row) if row else None


def approve_campaign(campaign_id: str, *, approved: bool) -> dict[str, Any]:
    campaign = get_campaign(campaign_id)
    if not campaign:
        return {"ok": False, "error": "unknown campaign_id"}
    if not approved:
        with db_session() as conn:
            conn.execute(
                "UPDATE veridiq_calling_campaigns SET status = 'rejected_by_user' WHERE campaign_id = ?",
                (campaign_id,),
            )
        return {"ok": True, "campaign": get_campaign(campaign_id)}

    from veridiq.integrations import twilio_calling
    from veridiq.integrations.activity import global_platform_activity

    approved_at = _utc_now()
    twilio_status = twilio_calling.status()
    if not twilio_status["configured"]:
        with db_session() as conn:
            conn.execute(
                "UPDATE veridiq_calling_campaigns SET status = 'approved_pending_integration', approved_at = ? "
                "WHERE campaign_id = ?",
                (approved_at, campaign_id),
            )
        return {
            "ok": True,
            "campaign": get_campaign(campaign_id),
            "message": f"Approved, but Twilio is not configured yet: {twilio_status['message']}",
        }

    result = twilio_calling.place_call(to=campaign["to_number"], message=campaign["script"])
    new_status = "dialed" if result.get("status") == "ok" else "call_failed"
    with db_session() as conn:
        conn.execute(
            "UPDATE veridiq_calling_campaigns SET status = ?, call_result_json = ?, approved_at = ? "
            "WHERE campaign_id = ?",
            (new_status, json.dumps(result, default=str), approved_at, campaign_id),
        )
    global_platform_activity.record(
        platform="ai_calling",
        agent_type="ai_calling",
        task=f"Place call to {campaign['to_number']}",
        workflow_stage="calling_dial",
        completion_status="completed" if result.get("status") == "ok" else "failed",
        api_response_status=result.get("status"),
        recent_activity=result.get("message"),
        errors=result.get("message") if result.get("status") == "error" else None,
    )
    return {"ok": True, "campaign": get_campaign(campaign_id)}


def sync_summary_to_crm(campaign_id: str, *, summary: str) -> dict[str, Any]:
    """CRM sync only ever runs a real API call when a CRM is configured."""
    campaign = get_campaign(campaign_id)
    if not campaign:
        return {"ok": False, "error": "unknown campaign_id"}

    from veridiq.integrations import crm
    from veridiq.integrations.activity import global_platform_activity

    crm_status = crm.status()
    if not crm_status["configured"]:
        result = {"status": "configuration_required", "message": crm_status["message"]}
        with db_session() as conn:
            conn.execute(
                "UPDATE veridiq_calling_campaigns SET summary = ?, crm_sync_json = ? WHERE campaign_id = ?",
                (summary, json.dumps(result), campaign_id),
            )
        return {"ok": True, "status": "configuration_required", "message": crm_status["message"]}

    who = campaign.get("contact_name") or campaign["to_number"]
    note_body = f"VERIDIQ AI Calling summary for {who} — {campaign.get('purpose')}: {summary}"
    result = crm.sync_note(note_body)
    with db_session() as conn:
        conn.execute(
            "UPDATE veridiq_calling_campaigns SET summary = ?, crm_sync_json = ? WHERE campaign_id = ?",
            (summary, json.dumps(result, default=str), campaign_id),
        )
    global_platform_activity.record(
        platform="crm",
        agent_type="ai_calling",
        task=f"Sync call summary for {who} to CRM",
        workflow_stage="crm_sync",
        completion_status="completed" if result.get("status") == "ok" else "failed",
        api_response_status=result.get("status"),
        recent_activity=result.get("message"),
        errors=result.get("message") if result.get("status") == "error" else None,
    )
    return {"ok": True, **result}


def draft_followup(campaign_id: str, *, recipient_email: str) -> dict[str, Any]:
    campaign = get_campaign(campaign_id)
    if not campaign:
        return {"ok": False, "error": "unknown campaign_id"}

    from veridiq.comms import draft_communication

    who = campaign.get("contact_name") or campaign["to_number"]
    draft = draft_communication(
        kind="follow_up",
        context=f"Follow-up after AI calling campaign with {who}: {campaign.get('purpose')}",
        recipient_hint=recipient_email,
    )
    with db_session() as conn:
        conn.execute(
            "UPDATE veridiq_calling_campaigns SET followup_draft_id = ? WHERE campaign_id = ?",
            (draft["draft_id"], campaign_id),
        )
    return {
        "ok": True,
        "draft": draft,
        "message": "Follow-up drafted — approve via /api/v1/veridiq/comms/approve to send.",
    }
