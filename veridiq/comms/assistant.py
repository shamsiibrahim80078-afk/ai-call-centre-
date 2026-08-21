"""Communication assistant — drafts only; external contact requires explicit approval.

Phase 5.1: persisted to `veridiq_comms_drafts` (SQLite) instead of an
in-memory dict, so drafts survive a backend restart. Function signatures and
returned dict shapes are unchanged from the in-memory implementation —
callers (`app.py`, `veridiq/calling/campaigns.py`, tests, frontend) need
zero changes.
"""

from __future__ import annotations

import json
import os
import re
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

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_DRAFT_READY_MESSAGE = "Draft ready. Explicit user approval is required before any email/phone/messaging action."

# Non-email channels wired to real send/publish APIs. Each sender receives the
# draft row (dict) and returns a dict with at least a "status" key
# ("ok" | "configuration_required" | "error") — never a fabricated success.
# `recipient_hint` is repurposed per channel: LinkedIn/X post to the
# configured account and ignore it; Telegram/WhatsApp treat it as the
# chat id/phone number; Instagram treats it as the required image URL.


def _send_linkedin(draft: dict[str, Any]) -> dict[str, Any]:
    from veridiq.integrations import linkedin

    return linkedin.share_post(draft.get("body") or draft.get("subject") or "")


def _send_x_twitter(draft: dict[str, Any]) -> dict[str, Any]:
    from veridiq.integrations import x_twitter

    return x_twitter.post_tweet(draft.get("body") or draft.get("subject") or "")


def _send_instagram(draft: dict[str, Any]) -> dict[str, Any]:
    from veridiq.integrations import instagram

    image_url = (draft.get("recipient_hint") or "").strip()
    return instagram.publish_media(caption=draft.get("body") or "", image_url=image_url)


def _send_threads(draft: dict[str, Any]) -> dict[str, Any]:
    from veridiq.integrations import threads

    # Optional public image URL for IMAGE media_type; text-only posts leave this empty.
    # (Comment/reply drafts use channel=threads_comment with recipient_hint = parent media id.)
    image_url = (draft.get("recipient_hint") or "").strip() or None
    return threads.publish_text(text=draft.get("body") or "", image_url=image_url)


def _send_threads_comment(draft: dict[str, Any]) -> dict[str, Any]:
    from veridiq.integrations import threads

    # recipient_hint = parent Threads media id to reply to (reply_to_id).
    return threads.reply_to_post(
        text=draft.get("body") or "",
        reply_to_id=(draft.get("recipient_hint") or "").strip(),
    )


def _send_telegram(draft: dict[str, Any]) -> dict[str, Any]:
    from veridiq.integrations import telegram

    # Marketing daily posts don't have a per-post recipient (they broadcast
    # to the community), so fall back to an operator-configured default
    # channel/group id when the draft itself doesn't specify one.
    chat_id = (draft.get("recipient_hint") or "").strip() or os.getenv("VERIDIQ_TELEGRAM_DEFAULT_CHAT_ID", "").strip()
    if not chat_id:
        return {
            "status": "configuration_required",
            "message": (
                "No Telegram target chat — set VERIDIQ_TELEGRAM_DEFAULT_CHAT_ID (your channel/group id) or "
                "provide a recipient_hint chat id on the draft."
            ),
        }
    return telegram.send_message(chat_id=chat_id, text=draft.get("body") or "")


def _send_whatsapp(draft: dict[str, Any]) -> dict[str, Any]:
    from veridiq.integrations import whatsapp

    to = (draft.get("recipient_hint") or "").strip()
    return whatsapp.send_message(to=to, text=draft.get("body") or "")


def _send_marketing(draft: dict[str, Any]) -> dict[str, Any]:
    from veridiq.integrations import marketing

    return marketing.send_campaign(
        subject=draft.get("subject") or "",
        body=draft.get("body") or "",
        audience_hint=draft.get("recipient_hint") or "",
    )


# Comment/reply channels — same draft -> approve -> send gate as regular
# posts. `recipient_hint` is repurposed as the *target reference* being
# commented on: an X tweet id, a LinkedIn post URN, an Instagram comment id
# to reply to, or a Telegram "chat_id" / "chat_id:message_id" pair.


def _send_x_twitter_comment(draft: dict[str, Any]) -> dict[str, Any]:
    from veridiq.integrations import x_twitter

    return x_twitter.reply_tweet(text=draft.get("body") or "", in_reply_to_tweet_id=(draft.get("recipient_hint") or "").strip())


def _send_linkedin_comment(draft: dict[str, Any]) -> dict[str, Any]:
    from veridiq.integrations import linkedin

    return linkedin.comment_on_post(post_urn=(draft.get("recipient_hint") or "").strip(), text=draft.get("body") or "")


def _send_instagram_comment(draft: dict[str, Any]) -> dict[str, Any]:
    from veridiq.integrations import instagram

    return instagram.reply_to_comment(comment_id=(draft.get("recipient_hint") or "").strip(), message=draft.get("body") or "")


def _send_telegram_comment(draft: dict[str, Any]) -> dict[str, Any]:
    from veridiq.integrations import telegram

    hint = (draft.get("recipient_hint") or "").strip()
    parts = hint.split(":")
    chat_id = parts[0] if parts else ""
    reply_id: Optional[int] = None
    thread_id: Optional[int] = None
    if len(parts) > 1 and parts[1].strip().isdigit():
        reply_id = int(parts[1].strip())
    if len(parts) > 2 and parts[2].strip().isdigit():
        thread_id = int(parts[2].strip())
    return telegram.send_message(
        chat_id=chat_id,
        text=draft.get("body") or "",
        reply_to_message_id=reply_id,
        message_thread_id=thread_id,
    )


_SOCIAL_SENDERS: dict[str, Any] = {
    "linkedin": _send_linkedin,
    "x_twitter": _send_x_twitter,
    "instagram": _send_instagram,
    "threads": _send_threads,
    "telegram": _send_telegram,
    "whatsapp": _send_whatsapp,
    "marketing": _send_marketing,
    "x_twitter_comment": _send_x_twitter_comment,
    "linkedin_comment": _send_linkedin_comment,
    "instagram_comment": _send_instagram_comment,
    "telegram_comment": _send_telegram_comment,
    "threads_comment": _send_threads_comment,
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _row_to_draft(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d.pop("id", None)
    send_attempt_json = d.pop("send_attempt_json", None)
    d["send_attempt"] = json.loads(send_attempt_json) if send_attempt_json else None
    d["requires_approval_before_send"] = True
    d["message"] = _DRAFT_READY_MESSAGE
    return d


def _get_draft(draft_id: str) -> Optional[dict[str, Any]]:
    initialize_database()
    with db_session() as conn:
        row = conn.execute("SELECT * FROM veridiq_comms_drafts WHERE draft_id = ?", (draft_id,)).fetchone()
    return _row_to_draft(row) if row else None


def draft_communication(
    *,
    kind: str,
    context: str,
    recipient_hint: str = "",
    created_by_user_id: Optional[int] = None,
) -> dict[str, Any]:
    kind = (kind or "email").lower()
    ctx = (context or "").strip()
    if kind == "agenda":
        subject = "Call agenda"
        body = (
            f"Agenda draft based on: {ctx}\n\n"
            "1) Objectives\n2) Key discussion points\n3) Decisions needed\n4) Next steps / owners\n"
        )
    elif kind == "follow_up":
        subject = "Follow-up"
        body = (
            f"Hi{(' ' + recipient_hint) if recipient_hint else ''},\n\n"
            f"Following up on: {ctx}\n\n"
            "Please let me know if you need anything else.\n\nBest regards"
        )
    elif kind == "meeting_summary":
        subject = "Meeting summary"
        body = f"Summary draft:\n\n{ctx}\n\nActions:\n- [ ] Confirm owners\n- [ ] Schedule follow-up\n"
    elif kind == "contact_notes":
        subject = "Contact notes"
        body = f"Contact notes:\n\n{ctx}\n\nDisposition: pending review\n"
    else:
        subject = "Outreach"
        body = (
            f"Hi{(' ' + recipient_hint) if recipient_hint else ''},\n\n"
            f"{ctx}\n\nLooking forward to your thoughts.\n\nBest regards"
        )

    initialize_database()
    draft_id = str(uuid.uuid4())
    created_at = _utc_now()
    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO veridiq_comms_drafts
                (draft_id, kind, subject, body, recipient_hint, external_action_status,
                 created_by_user_id, created_at)
            VALUES (?, ?, ?, ?, ?, 'draft_only', ?, ?)
            """,
            (draft_id, kind, subject, body, recipient_hint, created_by_user_id, created_at),
        )
    return _get_draft(draft_id)  # type: ignore[return-value]


def draft_marketing_content(
    *,
    channel: str,
    subject: str = "",
    body: str,
    recipient_hint: str = "",
    campaign_id: Optional[str] = None,
    created_by_user_id: Optional[int] = None,
    created_by_agent: Optional[str] = None,
) -> dict[str, Any]:
    """Queue an already-composed marketing post/comment as a comms draft.

    Used by the Marketing Agency (`veridiq/marketing/campaigns.py`) instead
    of `draft_communication` because campaign content (tweet variants,
    Telegram education blurbs, engagement comments...) is fully composed by
    channel-specific templates and must not be re-wrapped in the generic
    "Hi ... Looking forward to your thoughts" outreach template. Goes
    through the exact same draft -> approve -> send gate as every other
    comms draft — `channel` here is only a label (`kind`) until
    `approve_external_action(channel=...)` is explicitly called.
    """
    content = (body or "").strip()
    if not content:
        raise ValueError("body is required to queue marketing content")
    initialize_database()
    draft_id = str(uuid.uuid4())
    created_at = _utc_now()
    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO veridiq_comms_drafts
                (draft_id, kind, subject, body, recipient_hint, external_action_status,
                 created_by_user_id, created_at, campaign_id)
            VALUES (?, ?, ?, ?, ?, 'draft_only', ?, ?, ?)
            """,
            (draft_id, f"marketing_{channel}", subject or None, content, recipient_hint, created_by_user_id, created_at, campaign_id),
        )
    try:
        from veridiq.integrations.activity import global_platform_activity
        from veridiq.workforce.identities import identity_for
        from veridiq.workforce.stage_labels import channel_noun, friendly_channel

        agent_name = identity_for(created_by_agent).get("name") if created_by_agent else "Marketing agent"
        snippet = content[:90] + ("…" if len(content) > 90 else "")
        is_comment = channel.endswith("_comment")
        platform = channel.removesuffix("_comment")
        label = friendly_channel(platform)
        noun = "comment/reply" if is_comment else channel_noun(platform)
        action_text = f"{agent_name} drafted {label} {noun} — awaiting approval"
        global_platform_activity.record(
            platform=platform,
            agent_type=created_by_agent,
            task=action_text,
            workflow_stage="draft_queued",
            completion_status="completed",
            api_response_status="draft_only",
            recent_activity=f"{action_text}: {snippet}",
        )
    except Exception:
        pass  # draft queue must never fail because of activity logging
    return _get_draft(draft_id)  # type: ignore[return-value]


def list_drafts(
    *,
    campaign_id: Optional[str] = None,
    kind_prefix: Optional[str] = None,
    status: Optional[str] = None,
    created_after: Optional[str] = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """List comms drafts, optionally filtered by campaign/kind/status/date —
    powers the Marketing Agency's queue + daily-status views."""
    initialize_database()
    query = "SELECT * FROM veridiq_comms_drafts"
    clauses: list[str] = []
    params: list[Any] = []
    if campaign_id:
        clauses.append("campaign_id = ?")
        params.append(campaign_id)
    if kind_prefix:
        clauses.append("kind LIKE ?")
        params.append(f"{kind_prefix}%")
    if status:
        clauses.append("external_action_status = ?")
        params.append(status)
    if created_after:
        clauses.append("created_at >= ?")
        params.append(created_after)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(max(1, limit))
    with db_session() as conn:
        rows = conn.execute(query, tuple(params)).fetchall()
    return [_row_to_draft(r) for r in rows]


def approve_external_action(draft_id: str, *, approved: bool, channel: str = "email") -> dict[str, Any]:
    draft = _get_draft(draft_id)
    if not draft:
        return {"ok": False, "error": "unknown draft_id"}
    if not approved:
        with db_session() as conn:
            conn.execute(
                "UPDATE veridiq_comms_drafts SET external_action_status = 'rejected_by_user' WHERE draft_id = ?",
                (draft_id,),
            )
        return {"ok": True, "status": "rejected_by_user", "draft": _get_draft(draft_id)}

    approved_at = _utc_now()
    with db_session() as conn:
        conn.execute(
            "UPDATE veridiq_comms_drafts SET external_action_status = 'approved_pending_integration', "
            "approved_channel = ?, approved_at = ? WHERE draft_id = ?",
            (channel, approved_at, draft_id),
        )

    if channel == "email":
        try:
            from veridiq.integrations import email_smtp
            from veridiq.integrations.activity import global_platform_activity

            smtp_status = email_smtp.status()
            recipient = (draft.get("recipient_hint") or "").strip()
            if smtp_status.get("configured") and _EMAIL_RE.match(recipient):
                sent = email_smtp.send_email(to=recipient, subject=draft["subject"], body=draft["body"])
                final_status = "sent" if sent.get("status") == "ok" else "send_failed"
                with db_session() as conn:
                    conn.execute(
                        "UPDATE veridiq_comms_drafts SET external_action_status = ?, send_attempt_json = ? "
                        "WHERE draft_id = ?",
                        (final_status, json.dumps(sent, default=str), draft_id),
                    )
                global_platform_activity.record(
                    platform="email",
                    task=f"Send {draft['kind']} email to {recipient}",
                    workflow_stage="comms_send",
                    completion_status="completed" if sent.get("status") == "ok" else "failed",
                    api_response_status=sent.get("status"),
                    recent_activity=sent.get("message") or "Attempted SMTP send.",
                    errors=sent.get("message") if sent.get("status") == "error" else None,
                )
                updated = _get_draft(draft_id)
                if sent.get("status") == "ok":
                    return {"ok": True, "status": "sent", "message": sent.get("message"), "draft": updated}
                return {
                    "ok": True,
                    "status": "send_failed",
                    "message": sent.get("message") or "SMTP send failed.",
                    "draft": updated,
                }
            if smtp_status.get("configured") and not _EMAIL_RE.match(recipient):
                global_platform_activity.record(
                    platform="email",
                    task="Send email — no valid recipient",
                    workflow_stage="comms_send",
                    completion_status="skipped",
                    api_response_status="skipped_no_recipient",
                    recent_activity="SMTP is configured but recipient_hint was not a valid email address.",
                )
        except Exception as exc:
            err_payload = {"status": "error", "message": f"{type(exc).__name__}: {exc}"}
            with db_session() as conn:
                conn.execute(
                    "UPDATE veridiq_comms_drafts SET external_action_status = ?, send_attempt_json = ? "
                    "WHERE draft_id = ?",
                    ("send_failed", json.dumps(err_payload, default=str), draft_id),
                )
            try:
                from veridiq.integrations.activity import global_platform_activity

                global_platform_activity.record(
                    platform="email",
                    task="Send email — exception",
                    workflow_stage="comms_send",
                    completion_status="failed",
                    api_response_status="error",
                    recent_activity=err_payload["message"],
                    errors=err_payload["message"],
                )
            except Exception:
                pass
            return {
                "ok": True,
                "status": "send_failed",
                "message": err_payload["message"],
                "draft": _get_draft(draft_id),
            }

    sender = _SOCIAL_SENDERS.get(channel)
    if sender:
        try:
            from veridiq.integrations.activity import global_platform_activity

            result = sender(draft) or {}
            result_status = result.get("status")
            from veridiq.workforce.stage_labels import friendly_channel

            channel_label = friendly_channel(channel)
            # Activity board keys are base platforms (threads), not *_comment variants.
            activity_platform = channel.removesuffix("_comment")
            if result_status == "configuration_required":
                global_platform_activity.record(
                    platform=activity_platform,
                    task=f"Approved {channel_label} send — connector not configured",
                    workflow_stage="comms_send",
                    completion_status="configuration_required",
                    api_response_status="configuration_required",
                    recent_activity=result.get("message") or f"{channel_label} is not configured — nothing was posted.",
                )
                return {
                    "ok": True,
                    "status": "approved_pending_integration",
                    "message": result.get("message") or f"Approved, but {channel} is not configured yet.",
                    "draft": _get_draft(draft_id),
                }

            final_status = "sent" if result_status == "ok" else "send_failed"
            with db_session() as conn:
                conn.execute(
                    "UPDATE veridiq_comms_drafts SET external_action_status = ?, send_attempt_json = ? "
                    "WHERE draft_id = ?",
                    (final_status, json.dumps(result, default=str), draft_id),
                )
            send_ok = result_status == "ok"
            global_platform_activity.record(
                platform=activity_platform,
                task=(
                    f"Sent live {channel_label} post"
                    if send_ok
                    else f"Failed live {channel_label} send"
                ),
                workflow_stage="comms_send",
                completion_status="completed" if send_ok else "failed",
                api_response_status=result_status,
                recent_activity=result.get("message")
                or (f"Posted to {channel_label}." if send_ok else f"Attempted {channel_label} send."),
                errors=result.get("message") if not send_ok else None,
            )
            updated = _get_draft(draft_id)
            return {"ok": True, "status": final_status, "message": result.get("message"), "draft": updated}
        except Exception as exc:
            # Do not mask real send crashes as "pending integration".
            err_payload = {"status": "error", "message": f"{type(exc).__name__}: {exc}"}
            with db_session() as conn:
                conn.execute(
                    "UPDATE veridiq_comms_drafts SET external_action_status = ?, send_attempt_json = ? "
                    "WHERE draft_id = ?",
                    ("send_failed", json.dumps(err_payload, default=str), draft_id),
                )
            try:
                from veridiq.integrations.activity import global_platform_activity

                global_platform_activity.record(
                    platform=channel.removesuffix("_comment"),
                    task=f"Failed live {channel} send (exception)",
                    workflow_stage="comms_send",
                    completion_status="failed",
                    api_response_status="error",
                    recent_activity=err_payload["message"],
                    errors=err_payload["message"],
                )
            except Exception:
                pass
            return {
                "ok": True,
                "status": "send_failed",
                "message": err_payload["message"],
                "draft": _get_draft(draft_id),
            }

    return {
        "ok": True,
        "status": "approved_pending_integration",
        "message": (
            "Approval recorded. Outbound connectors are not auto-fired in this build; "
            "wire SMTP/CRM credentials to enable real sends."
        ),
        "draft": _get_draft(draft_id),
    }
