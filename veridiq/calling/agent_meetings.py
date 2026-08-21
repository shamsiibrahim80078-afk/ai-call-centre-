"""Agent-to-agent meetings — propose, approve, countdown, LiveKit auto-join, dialogue.

User is optional (spectator). Default duration 120s; extends to 300s when an extra
agent joins mid-call.

Env:
  VERIDIQ_AGENT_MEET_COUNTDOWN_SECONDS=120
  VERIDIQ_AGENT_MEET_DURATION_SECONDS=120
  VERIDIQ_AGENT_MEET_EXTENDED_SECONDS=300
  VERIDIQ_AGENT_MEET_DAILY_STANDUP=1
  VERIDIQ_AGENT_MEET_DAILY_STANDUP_PKT=09:00
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from database import db_session, initialize_database
from veridiq.workforce.identities import identity_for

logger = logging.getLogger("veridiq.calling.agent_meetings")

_lock = threading.RLock()

# Status machine: proposed → approved → live → ended | declined | cancelled
STATUSES = frozenset({"proposed", "approved", "live", "ended", "declined", "cancelled"})


def countdown_seconds() -> int:
    return max(1, int(os.getenv("VERIDIQ_AGENT_MEET_COUNTDOWN_SECONDS", "120") or "120"))


def duration_seconds() -> int:
    return max(30, int(os.getenv("VERIDIQ_AGENT_MEET_DURATION_SECONDS", "120") or "120"))


def extended_seconds() -> int:
    return max(duration_seconds(), int(os.getenv("VERIDIQ_AGENT_MEET_EXTENDED_SECONDS", "300") or "300"))


def daily_standup_enabled() -> bool:
    raw = (os.getenv("VERIDIQ_AGENT_MEET_DAILY_STANDUP", "1") or "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def daily_standup_pkt() -> str:
    return (os.getenv("VERIDIQ_AGENT_MEET_DAILY_STANDUP_PKT", "09:00") or "09:00").strip()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _utc_iso(dt: Optional[datetime] = None) -> str:
    d = dt or _utc_now()
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _parse_iso(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _agent_card(agent_type: str) -> dict[str, Any]:
    ident = identity_for(agent_type)
    return {
        "agent_type": agent_type,
        "name": ident["name"],
        "role": ident["role"],
        "avatar_hue": ident.get("avatar_hue", 200),
        "avatar_presentation": ident.get("avatar_presentation", "androgynous"),
        "avatar_hair": ident.get("avatar_hair", "short"),
        "avatar_skin": ident.get("avatar_skin", "#c4a484"),
        "avatar_hair_color": ident.get("avatar_hair_color", "#2a1f14"),
        "kind": "agent",
    }


def _ensure_tables() -> None:
    initialize_database()
    with db_session() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS veridiq_agent_meetings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                proposal_id TEXT NOT NULL UNIQUE,
                thread_id TEXT,
                meeting_id TEXT,
                proposer_agent TEXT NOT NULL,
                invitee_agent TEXT NOT NULL,
                topic TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'proposed',
                participants_json TEXT,
                start_at TEXT,
                approved_at TEXT,
                started_at TEXT,
                ended_at TEXT,
                countdown_seconds INTEGER NOT NULL DEFAULT 120,
                duration_seconds INTEGER NOT NULL DEFAULT 120,
                max_duration_seconds INTEGER NOT NULL DEFAULT 120,
                extended INTEGER NOT NULL DEFAULT 0,
                timed_session_id TEXT,
                dialogue_json TEXT,
                meta_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_meetings_status "
            "ON veridiq_agent_meetings(status, start_at)"
        )


def _row_to_proposal(row: Any) -> dict[str, Any]:
    d = dict(row)
    d.pop("id", None)
    for key, default in (
        ("participants_json", []),
        ("dialogue_json", []),
        ("meta_json", {}),
    ):
        raw = d.pop(key, None)
        out_key = key.replace("_json", "")
        try:
            d[out_key] = json.loads(raw) if raw else default
        except json.JSONDecodeError:
            d[out_key] = default
    # Enrich countdown remaining for UI
    status = d.get("status")
    start_at = _parse_iso(d.get("start_at"))
    now = _utc_now()
    if status == "approved" and start_at:
        d["countdown_remaining_seconds"] = max(0, int((start_at - now).total_seconds()))
        d["ready_to_start"] = start_at <= now
    else:
        d["countdown_remaining_seconds"] = None
        d["ready_to_start"] = status == "live"
    if d.get("proposer_agent"):
        d["proposer"] = _agent_card(d["proposer_agent"])
    if d.get("invitee_agent"):
        d["invitee"] = _agent_card(d["invitee_agent"])
    return d


def get_proposal(proposal_id: str) -> Optional[dict[str, Any]]:
    _ensure_tables()
    with db_session() as conn:
        row = conn.execute(
            "SELECT * FROM veridiq_agent_meetings WHERE proposal_id = ?",
            (proposal_id,),
        ).fetchone()
    return _row_to_proposal(row) if row else None


def list_proposals(
    *,
    status: Optional[str] = None,
    thread_id: Optional[str] = None,
    limit: int = 40,
) -> list[dict[str, Any]]:
    _ensure_tables()
    query = "SELECT * FROM veridiq_agent_meetings WHERE 1=1"
    params: list[Any] = []
    if status:
        query += " AND status = ?"
        params.append(status)
    if thread_id:
        query += " AND thread_id = ?"
        params.append(thread_id)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(max(1, min(int(limit), 100)))
    with db_session() as conn:
        rows = conn.execute(query, params).fetchall()
    return [_row_to_proposal(r) for r in rows]


def _hub_post(thread_id: Optional[str], agent_id: Optional[str], body: str, *, kind: str = "chat") -> None:
    if not thread_id:
        return
    try:
        from veridiq.calling.live_threads import _insert_thread_message

        with db_session() as conn:
            _insert_thread_message(
                conn,
                thread_id=thread_id,
                agent_id=agent_id,
                body=body,
                kind=kind,
            )
    except Exception:  # noqa: BLE001
        logger.exception("hub post failed for agent meeting")


def propose_meeting(
    *,
    proposer_agent: str,
    invitee_agent: str,
    topic: str = "",
    thread_id: Optional[str] = None,
    countdown: Optional[int] = None,
) -> dict[str, Any]:
    """Agent A proposes a meeting with agent B (user not required)."""
    _ensure_tables()
    proposer = (proposer_agent or "").strip() or "x_twitter_voice"
    invitee = (invitee_agent or "").strip() or "influencer_relations"
    if proposer == invitee:
        return {"ok": False, "error": "same_agent", "message": "Proposer and invitee must differ."}

    topic_clean = (topic or f"Working sync: {identity_for(proposer)['name']} × {identity_for(invitee)['name']}").strip()[:400]
    proposal_id = f"ameet-{uuid.uuid4().hex[:12]}"
    now = _utc_iso()
    cd = int(countdown) if countdown is not None else countdown_seconds()
    dur = duration_seconds()
    participants = [_agent_card(proposer), _agent_card(invitee), _agent_card("ai_calling")]
    tid = thread_id

    if not tid:
        try:
            from veridiq.calling.live_threads import create_live_thread

            created = create_live_thread(
                topic=topic_clean,
                agent_types=[proposer, invitee, "ai_calling", "ceo"],
                auto_start=False,
            )
            tid = (created.get("thread") or {}).get("thread_id")
        except Exception as exc:  # noqa: BLE001
            logger.warning("could not create hub thread for proposal: %s", exc)

    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO veridiq_agent_meetings
                (proposal_id, thread_id, meeting_id, proposer_agent, invitee_agent, topic, status,
                 participants_json, start_at, approved_at, started_at, ended_at,
                 countdown_seconds, duration_seconds, max_duration_seconds, extended,
                 timed_session_id, dialogue_json, meta_json, created_at, updated_at)
            VALUES (?, ?, NULL, ?, ?, ?, 'proposed', ?, NULL, NULL, NULL, NULL,
                    ?, ?, ?, 0, NULL, ?, ?, ?, ?)
            """,
            (
                proposal_id,
                tid,
                proposer,
                invitee,
                topic_clean,
                json.dumps(participants),
                cd,
                dur,
                dur,
                json.dumps([]),
                json.dumps({"source": "propose"}),
                now,
                now,
            ),
        )

    prop_name = identity_for(proposer)["name"]
    inv_name = identity_for(invitee)["name"]
    _hub_post(
        tid,
        proposer,
        f"{prop_name}: I need to schedule a meeting with you, {inv_name} — topic “{topic_clean}”.",
        kind="chat",
    )
    _hub_post(
        tid,
        "ai_calling",
        f"{identity_for('ai_calling')['name']}: Meeting proposal logged. {inv_name} can approve when ready.",
        kind="system",
    )

    proposal = get_proposal(proposal_id)
    return {
        "ok": True,
        "status": "proposed",
        "proposal": proposal,
        "message": f"{prop_name} proposed a meeting with {inv_name}. Awaiting approval.",
    }


def approve_proposal(
    *,
    proposal_id: str,
    approved_by: Optional[str] = None,
) -> dict[str, Any]:
    """Invitee (or organizer) approves → Marcus posts fixed join time + countdown starts."""
    _ensure_tables()
    proposal = get_proposal(proposal_id)
    if not proposal:
        return {"ok": False, "error": "unknown_proposal"}
    if proposal["status"] == "approved":
        return {"ok": True, "already_approved": True, "proposal": proposal}
    if proposal["status"] == "live":
        return {"ok": True, "already_live": True, "proposal": proposal}
    if proposal["status"] not in ("proposed",):
        return {"ok": False, "error": "not_approvable", "status": proposal["status"]}

    cd = int(proposal.get("countdown_seconds") or countdown_seconds())
    now = _utc_now()
    start_at = now + timedelta(seconds=cd)
    start_iso = _utc_iso(start_at)
    approved_iso = _utc_iso(now)
    marcus = identity_for("ai_calling")
    invitee = proposal["invitee_agent"]
    proposer = proposal["proposer_agent"]

    # Schedule underlying LiveKit meeting row (scheduled until go-live)
    meeting_id: Optional[str] = None
    try:
        from veridiq.calling.meetings import PKT, schedule_meeting

        pkt_when = start_at.astimezone(PKT).strftime("%Y-%m-%dT%H:%M")
        agents = []
        for p in proposal.get("participants") or []:
            at = p.get("agent_type")
            if at and at not in agents:
                agents.append(at)
        for extra in (proposer, invitee, "ai_calling"):
            if extra not in agents:
                agents.append(extra)
        sched = schedule_meeting(
            topic=proposal.get("topic") or "Agent meeting",
            scheduled_at_pkt=pkt_when,
            agenda=["Agent sync", "Marcus facilitates", "Action items"],
            agent_types=agents,
        )
        if sched.get("ok"):
            meeting_id = (sched.get("meeting") or {}).get("meeting_id")
    except Exception as exc:  # noqa: BLE001
        logger.exception("schedule_meeting for agent meet failed")
        return {"ok": False, "error": "schedule_failed", "message": str(exc)[:200]}

    with db_session() as conn:
        conn.execute(
            """
            UPDATE veridiq_agent_meetings
            SET status = 'approved', approved_at = ?, start_at = ?, meeting_id = ?,
                updated_at = ?, meta_json = ?
            WHERE proposal_id = ?
            """,
            (
                approved_iso,
                start_iso,
                meeting_id,
                approved_iso,
                json.dumps(
                    {
                        **(proposal.get("meta") or {}),
                        "approved_by": approved_by or invitee,
                    }
                ),
                proposal_id,
            ),
        )
        if proposal.get("thread_id") and meeting_id:
            conn.execute(
                "UPDATE veridiq_live_threads SET meeting_id = ?, updated_at = ? WHERE thread_id = ?",
                (meeting_id, approved_iso, proposal["thread_id"]),
            )

    try:
        from veridiq.calling.meetings import PKT as _PKT

        start_pkt = start_at.astimezone(_PKT).strftime("%H:%M:%S %Z")
    except Exception:
        start_pkt = start_at.astimezone(timezone(timedelta(hours=5))).strftime("%H:%M:%S PKT")

    _hub_post(
        proposal.get("thread_id"),
        invitee,
        f"{identity_for(invitee)['name']}: Approved — let's meet.",
        kind="chat",
    )
    _hub_post(
        proposal.get("thread_id"),
        "ai_calling",
        (
            f"{marcus['name']} (Call Organizer): Confirmed. Agents join at {start_pkt} "
            f"(in {cd}s). Humans can Watch live as spectators — you are not required."
        ),
        kind="system",
    )

    proposal = get_proposal(proposal_id)
    return {
        "ok": True,
        "status": "approved",
        "proposal": proposal,
        "meeting_id": meeting_id,
        "start_at": start_iso,
        "countdown_seconds": cd,
        "message": (
            f"Approved. Marcus posted join time — countdown {cd}s, then agents auto-join LiveKit."
        ),
        "watch_path": f"/dashboard/calling?agentMeet={proposal_id}&spectator=1",
    }


def decline_proposal(*, proposal_id: str) -> dict[str, Any]:
    _ensure_tables()
    proposal = get_proposal(proposal_id)
    if not proposal:
        return {"ok": False, "error": "unknown_proposal"}
    if proposal["status"] not in ("proposed", "approved"):
        return {"ok": False, "error": "not_declinable", "status": proposal["status"]}
    now = _utc_iso()
    with db_session() as conn:
        conn.execute(
            """
            UPDATE veridiq_agent_meetings
            SET status = 'declined', updated_at = ?, ended_at = ?
            WHERE proposal_id = ?
            """,
            (now, now, proposal_id),
        )
    _hub_post(
        proposal.get("thread_id"),
        proposal.get("invitee_agent"),
        f"{identity_for(proposal['invitee_agent'])['name']}: Declining this meeting for now.",
        kind="chat",
    )
    return {"ok": True, "status": "declined", "proposal": get_proposal(proposal_id)}


def _build_dialogue_script(proposal: dict[str, Any]) -> list[dict[str, str]]:
    """Short turn-taking script: Marcus facilitates, others respond."""
    topic = proposal.get("topic") or "our sync"
    agents = []
    for p in proposal.get("participants") or []:
        at = p.get("agent_type")
        if at and at not in agents:
            agents.append(at)
    if "ai_calling" not in agents:
        agents.insert(0, "ai_calling")
    # Ensure marcus first
    agents = ["ai_calling"] + [a for a in agents if a != "ai_calling"]
    others = [a for a in agents if a != "ai_calling"][:3]
    turns: list[dict[str, str]] = []
    marcus = identity_for("ai_calling")["name"]
    turns.append(
        {
            "agent_type": "ai_calling",
            "text": (
                f"Hi team — {marcus} facilitating. We're live on “{topic[:80]}”. "
                "Quick round: status and one ask."
            ),
        }
    )
    for a in others:
        name = identity_for(a)["name"]
        turns.append(
            {
                "agent_type": a,
                "text": (
                    f"{name} here. Progress is on track for {topic[:60]}. "
                    "I need a clear next step and owner after this call."
                ),
            }
        )
    if others:
        turns.append(
            {
                "agent_type": "ai_calling",
                "text": (
                    f"Thanks {identity_for(others[0])['name']}. "
                    "I'll capture action items and keep us inside the timed budget. "
                    "Anyone else — brief add-on?"
                ),
            }
        )
        if len(others) > 1:
            turns.append(
                {
                    "agent_type": others[1],
                    "text": (
                        f"{identity_for(others[1])['name']}: Aligned. "
                        "I'll sync the deliverable and ping the hub when done."
                    ),
                }
            )
    turns.append(
        {
            "agent_type": "ai_calling",
            "text": (
                f"{marcus}: Solid. Wrapping this segment — spectators can stay muted. "
                "Invite another agent from the sidebar if we need more time."
            ),
        }
    )
    return turns


def _synthesize_dialogue(proposal: dict[str, Any]) -> list[dict[str, Any]]:
    from veridiq.calling.agent_presence import synthesize_greeting

    voices = {
        "ai_calling": "en-US-GuyNeural",
        "ceo": "en-US-JennyNeural",
        "influencer_relations": "en-US-DavisNeural",
        "x_twitter_voice": "en-US-JasonNeural",
        "marketing_manager": "en-US-AriaNeural",
        "content_creator": "en-US-JennyNeural",
    }
    # edge-tts voice is fixed inside synthesize for GuyNeural — we still pass scripts
    dialogue = []
    meeting_id = proposal.get("meeting_id") or proposal.get("proposal_id") or "ameet"
    for i, turn in enumerate(_build_dialogue_script(proposal)):
        at = turn["agent_type"]
        script = turn["text"]
        clip = synthesize_greeting(script, meeting_id=str(meeting_id), agent_type=at)
        dialogue.append(
            {
                "turn": i,
                "agent_type": at,
                "name": identity_for(at)["name"],
                "text": script,
                "clip_id": clip.get("clip_id"),
                "audio_url": clip.get("audio_url"),
                "tts_ok": bool((clip.get("tts") or {}).get("ok")),
                "voice": voices.get(at, "en-US-GuyNeural"),
            }
        )
    return dialogue


def _prepare_agent_tokens(proposal: dict[str, Any]) -> list[dict[str, Any]]:
    from veridiq.calling.livekit_tokens import livekit_configured, mint_access_token
    from veridiq.calling.meetings import get_meeting

    if not livekit_configured():
        return []
    mid = proposal.get("meeting_id")
    if not mid:
        return []
    meeting = get_meeting(mid)
    if not meeting or meeting.get("status") != "live":
        return []
    room = meeting.get("livekit_room") or f"veridiq-{mid[:8]}"
    out = []
    for p in proposal.get("participants") or []:
        at = p.get("agent_type")
        if not at:
            continue
        tok = mint_access_token(
            identity=f"agent-{at}",
            room_name=room,
            name=p.get("name") or identity_for(at)["name"],
            can_publish=True,
            can_subscribe=True,
            can_publish_data=True,
        )
        if tok.get("ok"):
            out.append({**tok, "agent_type": at, "agent": _agent_card(at)})
    return out


def start_agent_meeting(*, proposal_id: str, force: bool = False) -> dict[str, Any]:
    """Go live: mark LiveKit meeting live, admit spectators, synthesize dialogue, open budget."""
    _ensure_tables()
    proposal = get_proposal(proposal_id)
    if not proposal:
        return {"ok": False, "error": "unknown_proposal"}
    if proposal["status"] == "live":
        return {
            "ok": True,
            "already_live": True,
            "proposal": proposal,
            "dialogue": proposal.get("dialogue") or [],
            "agent_tokens": _prepare_agent_tokens(proposal),
        }
    if proposal["status"] != "approved" and not force:
        return {"ok": False, "error": "not_approved", "status": proposal["status"]}

    start_at = _parse_iso(proposal.get("start_at"))
    if not force and start_at and start_at > _utc_now():
        rem = int((start_at - _utc_now()).total_seconds())
        return {
            "ok": False,
            "error": "countdown_active",
            "countdown_remaining_seconds": rem,
            "proposal": proposal,
            "message": f"Countdown still running ({rem}s).",
        }

    mid = proposal.get("meeting_id")
    if not mid:
        return {"ok": False, "error": "missing_meeting"}

    from veridiq.calling.livekit_tokens import livekit_configured, livekit_status
    from veridiq.calling.meetings import get_meeting
    from veridiq.calling.timed_calls import schedule_timed_call

    if not livekit_configured():
        return {
            "ok": False,
            "error": "livekit_not_configured",
            "livekit": livekit_status(),
            "message": "LiveKit credentials required for agent-agent rooms.",
        }

    now = _utc_iso()
    # Force live + admitted (spectators can join without user as publisher)
    with db_session() as conn:
        conn.execute(
            """
            UPDATE veridiq_meetings
            SET status = 'live', started_at = ?, join_gate_status = 'admitted', join_requested_at = ?
            WHERE meeting_id = ?
            """,
            (now, now, mid),
        )

    meeting = get_meeting(mid)
    # Dialogue TTS (best-effort — still go live if TTS fails)
    dialogue: list[dict[str, Any]] = []
    try:
        dialogue = _synthesize_dialogue(proposal)
    except Exception as exc:  # noqa: BLE001
        logger.exception("dialogue TTS failed")
        dialogue = [{"turn": 0, "agent_type": "ai_calling", "text": str(exc)[:120], "tts_ok": False}]

    dur = int(proposal.get("max_duration_seconds") or proposal.get("duration_seconds") or duration_seconds())
    timed = schedule_timed_call(
        purpose=f"Agent meeting {proposal_id[:12]} — {proposal.get('topic') or 'sync'}",
        script=" | ".join(t.get("text", "")[:80] for t in dialogue[:4]),
        requested_seconds=dur,
        agent_type="ai_calling",
        user_key="agent-meet",
        record_chain=True,
    )
    timed_id = ((timed or {}).get("session") or {}).get("session_id")

    with db_session() as conn:
        conn.execute(
            """
            UPDATE veridiq_agent_meetings
            SET status = 'live', started_at = ?, dialogue_json = ?, timed_session_id = ?,
                updated_at = ?
            WHERE proposal_id = ?
            """,
            (now, json.dumps(dialogue), timed_id, now, proposal_id),
        )

    # Auto-start budget clock (agents are the primary participants)
    if timed_id and timed.get("ok"):
        try:
            from veridiq.calling.timed_calls import start_session

            start_session(timed_id)
        except Exception:  # noqa: BLE001
            logger.exception("failed to start timed session for agent meet")

    proposal = get_proposal(proposal_id)
    tokens = _prepare_agent_tokens(proposal)
    _hub_post(
        proposal.get("thread_id"),
        "ai_calling",
        (
            f"{identity_for('ai_calling')['name']}: Agents are live in the room now. "
            "Open Watch live on Collaboration Hub or AI Calling to observe."
        ),
        kind="system",
    )
    return {
        "ok": True,
        "status": "live",
        "proposal": proposal,
        "meeting": meeting,
        "dialogue": dialogue,
        "agent_tokens": tokens,
        "timed": timed,
        "duration_seconds": dur,
        "watch_path": f"/dashboard/calling?agentMeet={proposal_id}&spectator=1",
        "message": "Agents auto-joined LiveKit — dialogue TTS ready.",
    }


def tick_agent_meetings() -> dict[str, Any]:
    """Advance approved→live when countdown elapses; end live sessions past max duration."""
    _ensure_tables()
    started: list[str] = []
    ended: list[str] = []
    now = _utc_now()
    with db_session() as conn:
        due = conn.execute(
            """
            SELECT proposal_id, start_at FROM veridiq_agent_meetings
            WHERE status = 'approved' AND start_at IS NOT NULL
            """
        ).fetchall()
        live_rows = conn.execute(
            """
            SELECT proposal_id, started_at, max_duration_seconds, meeting_id
            FROM veridiq_agent_meetings WHERE status = 'live'
            """
        ).fetchall()

    for row in due:
        pid = row["proposal_id"]
        start_at = _parse_iso(row["start_at"])
        if start_at and start_at <= now:
            try:
                res = start_agent_meeting(proposal_id=pid)
                if res.get("ok"):
                    started.append(pid)
            except Exception:  # noqa: BLE001
                logger.exception("tick start failed for %s", pid)

    for row in live_rows:
        started_at = _parse_iso(row["started_at"])
        max_dur = int(row["max_duration_seconds"] or duration_seconds())
        if started_at and (now - started_at).total_seconds() >= max_dur:
            try:
                end_agent_meeting(proposal_id=row["proposal_id"], reason="budget")
                ended.append(row["proposal_id"])
            except Exception:  # noqa: BLE001
                logger.exception("tick end failed for %s", row["proposal_id"])

    return {"ok": True, "started": started, "ended": ended, "started_count": len(started), "ended_count": len(ended)}


def end_agent_meeting(*, proposal_id: str, reason: str = "completed") -> dict[str, Any]:
    _ensure_tables()
    proposal = get_proposal(proposal_id)
    if not proposal:
        return {"ok": False, "error": "unknown_proposal"}
    if proposal["status"] in ("ended", "cancelled", "declined"):
        return {"ok": True, "already_ended": True, "proposal": proposal}
    now = _utc_iso()
    with db_session() as conn:
        conn.execute(
            """
            UPDATE veridiq_agent_meetings
            SET status = 'ended', ended_at = ?, updated_at = ?
            WHERE proposal_id = ?
            """,
            (now, now, proposal_id),
        )
    mid = proposal.get("meeting_id")
    if mid:
        try:
            from veridiq.calling.meetings import end_meeting

            end_meeting(meeting_id=mid)
        except Exception:  # noqa: BLE001
            logger.exception("end underlying meeting failed")
    sid = proposal.get("timed_session_id")
    if sid:
        try:
            from veridiq.calling.timed_calls import end_session

            end_session(sid, reason=reason if reason in ("completed", "expired", "failed", "cancelled") else "completed")
        except Exception:  # noqa: BLE001
            pass
    return {"ok": True, "status": "ended", "proposal": get_proposal(proposal_id), "reason": reason}


def invite_agent(*, proposal_id: str, agent_type: str) -> dict[str, Any]:
    """Mid-call: invite another agent; on accept path we auto-accept and extend to 5 min."""
    _ensure_tables()
    proposal = get_proposal(proposal_id)
    if not proposal:
        return {"ok": False, "error": "unknown_proposal"}
    if proposal["status"] != "live":
        return {"ok": False, "error": "not_live", "message": "Can only invite during a live agent meeting."}
    at = (agent_type or "").strip()
    if not at:
        return {"ok": False, "error": "agent_type_required"}

    participants = list(proposal.get("participants") or [])
    if any(p.get("agent_type") == at for p in participants):
        # Still extend if not yet extended
        return extend_meeting(proposal_id=proposal_id, reason="duplicate_invite")

    participants.append(_agent_card(at))
    # Auto-accept live invite (agents accept immediately in this system)
    ext = extended_seconds()
    now = _utc_iso()
    with db_session() as conn:
        conn.execute(
            """
            UPDATE veridiq_agent_meetings
            SET participants_json = ?, max_duration_seconds = ?, extended = 1, updated_at = ?
            WHERE proposal_id = ?
            """,
            (json.dumps(participants), ext, now, proposal_id),
        )
        mid = proposal.get("meeting_id")
        if mid:
            conn.execute(
                "UPDATE veridiq_meetings SET participants_json = ? WHERE meeting_id = ?",
                (json.dumps(participants), mid),
            )

    # Extend timed session allowed_seconds if possible
    sid = proposal.get("timed_session_id")
    if sid:
        try:
            with db_session() as conn:
                conn.execute(
                    """
                    UPDATE veridiq_calling_timed_sessions
                    SET allowed_seconds = ?, updated_at = ?
                    WHERE session_id = ? AND status IN ('scheduled', 'active')
                    """,
                    (ext, now, sid),
                )
        except Exception:  # noqa: BLE001
            logger.exception("extend timed session failed")

    # Fresh greeting turn for the newcomer
    extra_turn = None
    try:
        from veridiq.calling.agent_presence import synthesize_greeting

        name = identity_for(at)["name"]
        script = f"{name} joining mid-call. Thanks for the invite — I'm up to speed and ready."
        clip = synthesize_greeting(script, meeting_id=str(proposal.get("meeting_id") or proposal_id), agent_type=at)
        extra_turn = {
            "agent_type": at,
            "name": name,
            "text": script,
            "clip_id": clip.get("clip_id"),
            "audio_url": clip.get("audio_url"),
            "tts_ok": bool((clip.get("tts") or {}).get("ok")),
        }
        dialogue = list(proposal.get("dialogue") or [])
        dialogue.append({**extra_turn, "turn": len(dialogue)})
        with db_session() as conn:
            conn.execute(
                "UPDATE veridiq_agent_meetings SET dialogue_json = ?, updated_at = ? WHERE proposal_id = ?",
                (json.dumps(dialogue), now, proposal_id),
            )
    except Exception:  # noqa: BLE001
        logger.exception("newcomer TTS failed")

    proposal = get_proposal(proposal_id)
    tokens = _prepare_agent_tokens(proposal)
    _hub_post(
        proposal.get("thread_id"),
        "ai_calling",
        (
            f"{identity_for('ai_calling')['name']}: {identity_for(at)['name']} accepted and joined. "
            f"Call budget extended to {ext}s."
        ),
        kind="system",
    )
    return {
        "ok": True,
        "status": "extended",
        "proposal": proposal,
        "invited": _agent_card(at),
        "max_duration_seconds": ext,
        "extra_turn": extra_turn,
        "agent_tokens": tokens,
        "message": f"{identity_for(at)['name']} joined — duration now {ext}s.",
    }


def extend_meeting(*, proposal_id: str, reason: str = "manual") -> dict[str, Any]:
    _ensure_tables()
    proposal = get_proposal(proposal_id)
    if not proposal:
        return {"ok": False, "error": "unknown_proposal"}
    if proposal["status"] != "live":
        return {"ok": False, "error": "not_live"}
    ext = extended_seconds()
    now = _utc_iso()
    with db_session() as conn:
        conn.execute(
            """
            UPDATE veridiq_agent_meetings
            SET max_duration_seconds = ?, extended = 1, updated_at = ?,
                meta_json = ?
            WHERE proposal_id = ?
            """,
            (
                ext,
                now,
                json.dumps({**(proposal.get("meta") or {}), "extend_reason": reason}),
                proposal_id,
            ),
        )
        sid = proposal.get("timed_session_id")
        if sid:
            conn.execute(
                """
                UPDATE veridiq_calling_timed_sessions
                SET allowed_seconds = ?, updated_at = ?
                WHERE session_id = ? AND status IN ('scheduled', 'active')
                """,
                (ext, now, sid),
            )
    return {
        "ok": True,
        "max_duration_seconds": ext,
        "proposal": get_proposal(proposal_id),
        "message": f"Extended call budget to {ext}s.",
    }


def get_live_bundle(*, proposal_id: str) -> dict[str, Any]:
    """Snapshot for Watch live / AI Calling: proposal + tokens + dialogue + spectator hint."""
    tick_agent_meetings()
    proposal = get_proposal(proposal_id)
    if not proposal:
        return {"ok": False, "error": "unknown_proposal"}
    tokens = _prepare_agent_tokens(proposal) if proposal["status"] == "live" else []
    return {
        "ok": True,
        "proposal": proposal,
        "dialogue": proposal.get("dialogue") or [],
        "agent_tokens": tokens,
        "countdown_seconds": countdown_seconds(),
        "duration_seconds": duration_seconds(),
        "extended_seconds": extended_seconds(),
        "spectator_hint": True,
        "watch_path": f"/dashboard/calling?agentMeet={proposal_id}&spectator=1",
    }


# --- Intent detection for hub compose / swarm ---------------------------------

_SCHEDULE_RE = re.compile(
    r"\b("
    r"schedule\s+(a\s+)?meeting|"
    r"need\s+to\s+schedule|"
    r"meet(ing)?\s+with\s+you|"
    r"can\s+we\s+meet|"
    r"book\s+(a\s+)?(call|meeting|sync)|"
    r"set\s+up\s+(a\s+)?(call|meeting)"
    r")\b",
    re.I,
)

_APPROVE_RE = re.compile(
    r"\b(approve[d]?|i\s+accept|sounds\s+good|let'?s\s+meet|i'?m\s+in|confirmed)\b",
    re.I,
)

_EXTERNAL_MEET_RE = re.compile(
    r"(?:go\s+join\s+this\s+meeting|this\s+is\s+the\s+meeting\s+go\s+join\s+it|"
    r"join\s+(?:this\s+)?(?:google\s+)?meet(?:ing)?)\s*:?\s*(?P<url>https?://\S+)",
    re.I,
)


def detect_schedule_intent(text: str) -> bool:
    return bool(_SCHEDULE_RE.search(text or ""))


def detect_approve_intent(text: str) -> bool:
    return bool(_APPROVE_RE.search(text or ""))


def extract_external_meet_url(text: str) -> Optional[str]:
    m = _EXTERNAL_MEET_RE.search(text or "")
    if m:
        return m.group("url").rstrip(").,]")
    # Fallback: explicit command + any URL
    lower = (text or "").lower()
    if any(p in lower for p in ("go join this meeting", "this is the meeting go join", "join this meet")):
        url_m = re.search(r"https?://\S+", text or "")
        if url_m:
            return url_m.group(0).rstrip(").,]")
    return None


def resolve_agent_pair_from_text(
    text: str,
    *,
    default_proposer: str = "x_twitter_voice",
    default_invitee: str = "influencer_relations",
) -> tuple[str, str]:
    """Best-effort pair from hub message (marketing/twitter → influencer)."""
    from veridiq.calling.live_threads import resolve_specialist

    lower = (text or "").lower()
    invitee = default_invitee
    proposer = default_proposer
    if any(k in lower for k in ("influencer", "adrian", "creator")):
        invitee = "influencer_relations"
    if any(k in lower for k in ("twitter", "nova", "x voice", "tweet", "marketing")):
        proposer = "x_twitter_voice" if "twitter" in lower or "nova" in lower or "tweet" in lower else "marketing_manager"
    # If user names a specialist as invitee
    try:
        resolved = resolve_specialist(text)
        if resolved and resolved not in ("content_creator",):
            if "with" in lower or "schedule" in lower:
                invitee = resolved
    except Exception:
        pass
    return proposer, invitee


def handle_hub_meeting_intents(
    *,
    text: str,
    thread_id: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Process schedule / approve / external-join from Collaboration Hub compose."""
    url = extract_external_meet_url(text)
    if url:
        from veridiq.calling.external_meet import schedule_external_join

        return {
            "routed": "external_meet",
            **schedule_external_join(url=url, instructions=text, thread_id=thread_id),
        }

    if detect_approve_intent(text) and not detect_schedule_intent(text):
        # Approve latest proposed for this thread
        props = list_proposals(status="proposed", thread_id=thread_id, limit=5)
        if not props:
            props = list_proposals(status="proposed", limit=5)
        if props:
            return {"routed": "agent_meet_approve", **approve_proposal(proposal_id=props[0]["proposal_id"])}

    if detect_schedule_intent(text):
        proposer, invitee = resolve_agent_pair_from_text(text)
        return {
            "routed": "agent_meet_propose",
            **propose_meeting(
                proposer_agent=proposer,
                invitee_agent=invitee,
                topic=text[:200],
                thread_id=thread_id,
            ),
        }
    return None


def ensure_daily_standup(*, force: bool = False) -> dict[str, Any]:
    """Create a daily standup-style proposal if configured and none pending today."""
    if not daily_standup_enabled() and not force:
        return {"ok": True, "skipped": True, "reason": "disabled"}
    _ensure_tables()
    today = _utc_now().date().isoformat()
    with db_session() as conn:
        row = conn.execute(
            """
            SELECT proposal_id FROM veridiq_agent_meetings
            WHERE json_extract(meta_json, '$.standup_day') = ?
               OR (topic LIKE '%standup%' AND created_at LIKE ?)
            LIMIT 1
            """,
            (today, f"{today}%"),
        ).fetchone()
    if row and not force:
        return {"ok": True, "already": True, "proposal_id": row["proposal_id"]}

    result = propose_meeting(
        proposer_agent="ai_calling",
        invitee_agent="ceo",
        topic=f"Daily agent standup ({daily_standup_pkt()} PKT)",
    )
    if result.get("ok") and result.get("proposal"):
        pid = result["proposal"]["proposal_id"]
        with db_session() as conn:
            conn.execute(
                "UPDATE veridiq_agent_meetings SET meta_json = ? WHERE proposal_id = ?",
                (json.dumps({"standup_day": today, "standup_pkt": daily_standup_pkt()}), pid),
            )
        # Auto-approve standup so countdown runs
        return approve_proposal(proposal_id=pid, approved_by="ceo")
    return result


def maybe_seed_demo_proposal(*, thread_id: Optional[str] = None) -> Optional[dict[str, Any]]:
    """Optional: if no open proposals, seed twitter→influencer schedule (for hub demos)."""
    open_ones = list_proposals(status="proposed", limit=3) + list_proposals(status="approved", limit=3)
    if open_ones:
        return None
    return propose_meeting(
        proposer_agent="x_twitter_voice",
        invitee_agent="influencer_relations",
        topic="Campaign sync — Twitter voice × Influencer outreach",
        thread_id=thread_id,
    )
