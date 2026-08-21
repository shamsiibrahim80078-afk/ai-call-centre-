"""Marketing Agency campaign store + daily content-pack generator.

Persisted to `veridiq_marketing_campaigns` (SQLite), mirroring the Phase 5.1
persistence pattern used by `veridiq/calling/campaigns.py` and
`veridiq/comms/assistant.py`. Every piece of content this module generates is
queued as a `veridiq_comms_drafts` row via `veridiq.comms.draft_marketing_content`
— nothing is ever sent directly; the existing draft -> approve -> send gate
always applies.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import uuid
from datetime import date as _date
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from database import db_session, initialize_database  # noqa: E402

from veridiq.marketing.content import CORE_FEATURES, DEFAULT_CAMPAIGN_CHANNELS, feature_of_the_day  # noqa: E402
from veridiq.marketing.human_voice import is_influencer_voice, persona_for, render_for_agent  # noqa: E402

VALID_STATUSES = ("active", "paused", "archived")

# The always-on default campaign "Run now" targets when the caller (an agent
# Run/Start click, or the "Run marketing team now" button) doesn't supply a
# campaign_id — so the operator never has to fill out a campaign-create form
# before the marketing team can do real work. Identity-first, not form-first.
DEFAULT_CAMPAIGN_NAME = "Market VeriDiQ"
DEFAULT_CAMPAIGN_BRIEF = (
    "VeriDiQ is an AI-native truth verification and workforce platform — verify claims, run a live AI team, "
    "and optionally attest findings on-chain."
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _today() -> _date:
    return datetime.now(timezone.utc).date()


def _row_to_campaign(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d.pop("id", None)
    channels_json = d.pop("channels_json", None)
    d["channels"] = json.loads(channels_json) if channels_json else []
    return d


def create_campaign(
    *,
    name: str,
    product_brief: str = "",
    channels: Optional[list[str]] = None,
    created_by_user_id: Optional[int] = None,
) -> dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise ValueError("name is required to create a marketing campaign")
    resolved_channels = [c for c in (channels or DEFAULT_CAMPAIGN_CHANNELS) if c]
    if not resolved_channels:
        resolved_channels = list(DEFAULT_CAMPAIGN_CHANNELS)
    initialize_database()
    campaign_id = str(uuid.uuid4())
    created_at = _utc_now()
    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO veridiq_marketing_campaigns
                (campaign_id, name, product_brief, channels_json, status,
                 created_by_user_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'active', ?, ?, ?)
            """,
            (campaign_id, name, product_brief.strip(), json.dumps(resolved_channels), created_by_user_id, created_at, created_at),
        )
    return get_campaign(campaign_id)  # type: ignore[return-value]


def list_campaigns(status: Optional[str] = None) -> list[dict[str, Any]]:
    initialize_database()
    query = "SELECT * FROM veridiq_marketing_campaigns"
    params: list[Any] = []
    if status:
        query += " WHERE status = ?"
        params.append(status)
    query += " ORDER BY created_at DESC"
    with db_session() as conn:
        rows = conn.execute(query, tuple(params)).fetchall()
    return [_row_to_campaign(r) for r in rows]


def get_campaign(campaign_id: str) -> Optional[dict[str, Any]]:
    initialize_database()
    with db_session() as conn:
        row = conn.execute(
            "SELECT * FROM veridiq_marketing_campaigns WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()
    return _row_to_campaign(row) if row else None


def set_campaign_status(campaign_id: str, status: str) -> dict[str, Any]:
    if status not in VALID_STATUSES:
        raise ValueError(f"status must be one of {VALID_STATUSES}")
    if not get_campaign(campaign_id):
        return {"ok": False, "error": "unknown campaign_id"}
    with db_session() as conn:
        conn.execute(
            "UPDATE veridiq_marketing_campaigns SET status = ?, updated_at = ? WHERE campaign_id = ?",
            (status, _utc_now(), campaign_id),
        )
    return {"ok": True, "campaign": get_campaign(campaign_id)}


def generate_daily_pack(
    campaign_id: str,
    *,
    channels: Optional[list[str]] = None,
    features: Optional[list[str]] = None,
    created_by_agent: Optional[str] = None,
    created_by_user_id: Optional[int] = None,
    max_drafts: Optional[int] = None,
    skip_draft_generation: bool = False,
    skip_reason: Optional[str] = None,
) -> dict[str, Any]:
    """Generate today's content and queue it as channel-specific comms
    drafts. Never sends anything — every item lands in `draft_only` status
    and requires the normal comms approve flow before any live platform call.

    `max_drafts` caps how many new rows are created (team runs use this to
    avoid flooding the queue). When `skip_draft_generation` is True the run
    still succeeds but queues zero new drafts and returns an honest message.
    """
    from veridiq.comms import draft_marketing_content
    from veridiq.integrations.activity import global_platform_activity
    from veridiq.workforce.pool import global_worker_pool
    from veridiq.workforce.stage_labels import friendly_channel

    if skip_draft_generation:
        campaign = get_campaign(campaign_id)
        name = campaign["name"] if campaign else campaign_id
        msg = skip_reason or "Draft generation skipped — queue threshold reached."
        global_platform_activity.record(
            platform="marketing_agency",
            agent_type=created_by_agent,
            task=f"Skipped draft generation for '{name}'",
            workflow_stage="daily_pack_skipped",
            completion_status="completed",
            recent_activity=msg,
        )
        return {"ok": True, "campaign_id": campaign_id, "count": 0, "drafts": [], "skipped": True, "message": msg}

    campaign = get_campaign(campaign_id)
    if not campaign:
        return {"ok": False, "error": "unknown campaign_id"}
    if campaign["status"] != "active":
        return {"ok": False, "error": f"campaign is {campaign['status']} — set it active before generating content"}

    supported = {"telegram", "x_twitter", "linkedin", "instagram", "threads"}
    # Explicit specialty channels (team runs) must win even if an older campaign
    # row predates threads / a channel — otherwise agents collapse onto telegram.
    if channels:
        target_channels = [c for c in channels if c in supported]
        if not target_channels:
            target_channels = [c for c in campaign["channels"] if c in supported] or list(DEFAULT_CAMPAIGN_CHANNELS)
    else:
        target_channels = [c for c in campaign["channels"] if c in supported] or list(DEFAULT_CAMPAIGN_CHANNELS)
    feature_key = feature_of_the_day(_today(), features) if not features else features[0]
    if feature_key not in CORE_FEATURES:
        feature_key = feature_of_the_day(_today())
    feature_title = CORE_FEATURES[feature_key]["title"]
    brief = campaign.get("product_brief") or None
    influencer = is_influencer_voice(created_by_agent)
    persona = persona_for(created_by_agent)
    draft_cap = max_drafts if max_drafts is not None else 999
    first_channel_label = friendly_channel(target_channels[0]) if target_channels else "platform"

    if created_by_agent:
        global_worker_pool.set_agent_stage(
            created_by_agent,
            stage="content_generation",
            progress=0.25,
            task=f"Drafting {first_channel_label} caption about {feature_title}",
            platform=target_channels[0] if target_channels else None,
            channel=target_channels[0] if target_channels else None,
        )

    created: list[dict[str, Any]] = []
    for channel in target_channels:
        if len(created) >= draft_cap:
            break
        channel_label = friendly_channel(channel)
        subject = f"{persona.name} — {feature_title}" + (" (influencer)" if influencer else "")
        if created_by_agent:
            global_worker_pool.set_agent_stage(
                created_by_agent,
                stage="draft_queue",
                progress=min(0.85, 0.3 + len(created) * 0.12),
                task=f"Queued {channel_label} draft for approval — not sent",
                platform=channel,
                channel=channel,
            )
        if channel == "x_twitter":
            n = min(2 if influencer else 3, max(1, draft_cap - len(created)))
            variants = render_for_agent(created_by_agent, channel, feature_key, brief, n=n)
            if isinstance(variants, str):
                variants = [variants]
            for variant in variants:
                if len(created) >= draft_cap:
                    break
                draft = draft_marketing_content(
                    channel="x_twitter",
                    subject=subject,
                    body=variant,
                    campaign_id=campaign_id,
                    created_by_user_id=created_by_user_id,
                    created_by_agent=created_by_agent,
                )
                created.append(draft)
        elif channel in ("telegram", "linkedin", "instagram", "threads"):
            body = render_for_agent(created_by_agent, channel, feature_key, brief)
            if isinstance(body, list):
                body = body[0]
            created.append(
                draft_marketing_content(
                    channel=channel,
                    subject=subject,
                    body=str(body),
                    campaign_id=campaign_id,
                    created_by_user_id=created_by_user_id,
                    created_by_agent=created_by_agent,
                )
            )
        else:
            continue

    with db_session() as conn:
        conn.execute(
            "UPDATE veridiq_marketing_campaigns SET last_generated_date = ?, updated_at = ? WHERE campaign_id = ?",
            (_today().isoformat(), _utc_now(), campaign_id),
        )

    channel_list = ", ".join(friendly_channel(c) for c in target_channels)
    if created_by_agent:
        global_worker_pool.set_agent_stage(
            created_by_agent,
            stage="result_collection",
            progress=0.95,
            task=f"Queued {len(created)} draft(s) for approval — not sent yet",
            platform=target_channels[0] if target_channels else "marketing_agency",
            channel=target_channels[0] if target_channels else None,
        )

    global_platform_activity.record(
        platform=target_channels[0] if len(target_channels) == 1 else "marketing_agency",
        agent_type=created_by_agent,
        task=f"Generate daily content pack for campaign '{campaign['name']}'",
        workflow_stage="daily_pack_generation",
        completion_status="completed",
        api_response_status="draft_only",
        recent_activity=(
            f"{persona.name} queued {len(created)} draft(s) across {channel_list} "
            f"— feature: {feature_title}"
            + (" (influencer voice)" if influencer else "")
            + ". Awaiting approval before any live send."
        ),
    )

    return {
        "ok": True,
        "campaign_id": campaign_id,
        "date": _today().isoformat(),
        "feature": feature_key,
        "feature_title": feature_title,
        "channels": target_channels,
        "count": len(created),
        "drafts": created,
        "message": (
            f"Queued {len(created)} draft(s) — every item requires approval via "
            "POST /api/v1/veridiq/comms/approve (or the Marketing Agency queue) before anything is sent."
        ),
    }


def clear_pending_drafts(
    *,
    campaign_id: Optional[str] = None,
    keep_recent: int = 20,
) -> dict[str, Any]:
    """Archive excess draft_only marketing rows so repeated team runs don't flood the queue."""
    from veridiq.comms import list_drafts

    pending = list_drafts(campaign_id=campaign_id, kind_prefix="marketing_", status="draft_only", limit=5000)
    if len(pending) <= keep_recent:
        return {
            "ok": True,
            "removed": 0,
            "remaining": len(pending),
            "message": f"No cleanup needed — {len(pending)} pending draft(s) (keeping up to {keep_recent}).",
        }
    to_remove = pending[keep_recent:]
    removed_ids = [d["draft_id"] for d in to_remove]
    with db_session() as conn:
        for draft_id in removed_ids:
            conn.execute(
                "UPDATE veridiq_comms_drafts SET external_action_status = 'archived_cleared' WHERE draft_id = ?",
                (draft_id,),
            )
    return {
        "ok": True,
        "removed": len(removed_ids),
        "remaining": keep_recent,
        "message": f"Cleared {len(removed_ids)} old pending draft(s); kept the {keep_recent} most recent.",
    }


def get_or_create_default_campaign() -> dict[str, Any]:
    """Return the always-on "Market VeriDiQ" campaign, creating it once if it
    doesn't exist yet, and reactivating it if a prior explicit pause left it
    inactive. This is the campaign every marketing agent's "Run now" targets
    when no campaign_id is supplied, so the identity-first roster never needs
    a campaign-create form in the primary flow."""
    initialize_database()
    with db_session() as conn:
        row = conn.execute(
            "SELECT campaign_id FROM veridiq_marketing_campaigns WHERE name = ? ORDER BY created_at ASC LIMIT 1",
            (DEFAULT_CAMPAIGN_NAME,),
        ).fetchone()
    if row:
        campaign = get_campaign(row["campaign_id"])
        if campaign and campaign["status"] != "active":
            set_campaign_status(campaign["campaign_id"], "active")
            campaign = get_campaign(campaign["campaign_id"])
        if campaign:
            return campaign
    return create_campaign(name=DEFAULT_CAMPAIGN_NAME, product_brief=DEFAULT_CAMPAIGN_BRIEF, channels=DEFAULT_CAMPAIGN_CHANNELS)


def daily_status(*, campaign_id: Optional[str] = None, day: Optional[_date] = None) -> dict[str, Any]:
    """Per-channel/status breakdown of today's (or a given day's) marketing queue."""
    from veridiq.comms import list_drafts

    day = day or _today()
    created_after = f"{day.isoformat()}T00:00:00"
    drafts = list_drafts(campaign_id=campaign_id, kind_prefix="marketing_", created_after=created_after, limit=500)

    by_channel: dict[str, dict[str, int]] = {}
    by_status: dict[str, int] = {}
    for d in drafts:
        channel = str(d.get("kind") or "").removeprefix("marketing_")
        by_channel.setdefault(channel, {})
        status = d.get("external_action_status") or "draft_only"
        by_channel[channel][status] = by_channel[channel].get(status, 0) + 1
        by_status[status] = by_status.get(status, 0) + 1

    return {
        "date": day.isoformat(),
        "campaign_id": campaign_id,
        "total": len(drafts),
        "by_channel": by_channel,
        "by_status": by_status,
        "pending_approval": by_status.get("draft_only", 0),
    }


def list_queue(
    *,
    campaign_id: Optional[str] = None,
    channel: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    from veridiq.comms import list_drafts

    kind_prefix = f"marketing_{channel}" if channel else "marketing_"
    return list_drafts(campaign_id=campaign_id, kind_prefix=kind_prefix, status=status, limit=limit)
