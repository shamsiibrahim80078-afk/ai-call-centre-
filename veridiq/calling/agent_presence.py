"""Agent LiveKit presence — Marcus joins the room with voice (TTS).

Does not require the heavy LiveKit Agents SDK. Flow:
  1. Mint a publish-capable agent JWT for the meeting room.
  2. Synthesize a short greeting (+ agenda) via edge-tts.
  3. Frontend (or optional server worker) connects as the agent and
     publishes the audio track so the human hears a remote participant.

Also opens a timed calling budget session (max 120s by default) for the call.
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("veridiq.calling.agent_presence")

_ROOT = Path(__file__).resolve().parent.parent.parent
TTS_DIR = _ROOT / "marketing_out" / "calling_tts"
_lock = threading.Lock()
_clips: dict[str, dict[str, Any]] = {}


def _utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def build_greeting_script(meeting: dict[str, Any], *, agent_name: str = "Marcus") -> str:
    """Short spoken greeting for join — respects timed-call brevity."""
    topic = (meeting.get("topic") or "our working session").strip()
    agenda = meeting.get("agenda") or []
    agenda_bits = [str(a).strip() for a in agenda if str(a).strip()][:3]
    if agenda_bits:
        agenda_line = " Today's agenda: " + "; ".join(agenda_bits) + "."
    else:
        agenda_line = " I'll keep this focused and within our timed call budget."
    return (
        f"Hi — {agent_name} here, joining you live. "
        f"We're on the call about {topic}.{agenda_line} "
        "Go ahead whenever you're ready."
    )


def _run_edge_tts(text: str, out_path: Path, *, voice: str = "en-US-GuyNeural") -> dict[str, Any]:
    """Write mp3 via edge-tts. Synchronous wrapper for request threads."""
    cleaned = re.sub(r"\s+", " ", (text or "").strip())[:900]
    if not cleaned:
        return {"ok": False, "status": "empty_script", "message": "No greeting text."}
    try:
        import edge_tts
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "status": "edge_tts_missing", "message": str(exc)[:160]}

    async def _save() -> None:
        communicate = edge_tts.Communicate(cleaned, voice, rate="-4%", pitch="+0Hz")
        await communicate.save(str(out_path))

    try:
        asyncio.run(_save())
    except RuntimeError:
        # Nested event loop (rare) — spin a dedicated thread.
        err: list[BaseException] = []

        def _thread_run() -> None:
            try:
                asyncio.run(_save())
            except BaseException as e:  # noqa: BLE001
                err.append(e)

        t = threading.Thread(target=_thread_run, daemon=True, name="calling-edge-tts")
        t.start()
        t.join(timeout=45)
        if err:
            return {"ok": False, "status": "tts_failed", "message": str(err[0])[:200]}
        if t.is_alive():
            return {"ok": False, "status": "tts_timeout", "message": "edge-tts timed out"}
    except Exception as exc:  # noqa: BLE001
        logger.exception("edge-tts greeting failed")
        return {"ok": False, "status": "tts_failed", "message": str(exc)[:200]}

    if not out_path.exists() or out_path.stat().st_size < 200:
        return {"ok": False, "status": "tts_empty", "message": "TTS produced no audio"}
    return {
        "ok": True,
        "status": "ready",
        "path": str(out_path),
        "bytes": out_path.stat().st_size,
        "voice": voice,
    }


def synthesize_greeting(
    script: str,
    *,
    meeting_id: str,
    agent_type: str = "ai_calling",
) -> dict[str, Any]:
    """Generate and register a greeting clip; returns clip_id + public URL path."""
    TTS_DIR.mkdir(parents=True, exist_ok=True)
    clip_id = f"greet-{uuid.uuid4().hex[:12]}"
    out = TTS_DIR / f"{clip_id}.mp3"
    result = _run_edge_tts(script, out)
    meta = {
        "clip_id": clip_id,
        "meeting_id": meeting_id,
        "agent_type": agent_type,
        "script": script,
        "created_at": _utc_iso(),
        "path": str(out) if result.get("ok") else None,
        "audio_url": f"/api/v1/veridiq/calling/agent-tts/{clip_id}" if result.get("ok") else None,
        "tts": result,
    }
    with _lock:
        _clips[clip_id] = meta
    return meta


def get_tts_clip(clip_id: str) -> Optional[dict[str, Any]]:
    with _lock:
        hit = _clips.get(clip_id)
    if hit:
        return hit
    # Disk fallback after process restart
    path = TTS_DIR / f"{clip_id}.mp3"
    if path.exists() and path.stat().st_size > 200:
        return {
            "clip_id": clip_id,
            "path": str(path),
            "audio_url": f"/api/v1/veridiq/calling/agent-tts/{clip_id}",
            "tts": {"ok": True, "status": "disk"},
        }
    return None


def mint_publishable_agent_token(
    *,
    meeting_id: str,
    agent_type: str = "ai_calling",
    name: Optional[str] = None,
) -> dict[str, Any]:
    """Mint LiveKit JWT with publish rights so the agent can speak."""
    from veridiq.calling.livekit_tokens import livekit_configured, livekit_status, mint_access_token
    from veridiq.calling.meetings import get_meeting
    from veridiq.workforce.identities import identity_for

    if not livekit_configured():
        return {"ok": False, "error": "livekit_not_configured", "livekit": livekit_status()}
    meeting = get_meeting(meeting_id)
    if not meeting:
        return {"ok": False, "error": "unknown_meeting"}
    if meeting.get("status") != "live":
        return {"ok": False, "error": "meeting_not_live", "meeting": meeting}

    ident = identity_for(agent_type)
    display = (name or ident.get("name") or agent_type).strip()[:64]
    room = meeting.get("livekit_room") or f"veridiq-{meeting_id[:8]}"
    tok = mint_access_token(
        identity=f"agent-{agent_type}",
        room_name=room,
        name=display,
        can_publish=True,
        can_subscribe=True,
        can_publish_data=True,
    )
    if not tok.get("ok"):
        return tok
    return {
        **tok,
        "ok": True,
        "agent_type": agent_type,
        "avatar_hue": ident.get("avatar_hue"),
        "role": ident.get("role"),
        "meeting_id": meeting_id,
        "meeting": meeting,
    }


def prepare_agent_presence(
    *,
    meeting_id: str,
    agent_type: str = "ai_calling",
    open_budget: bool = True,
    user_key: str = "default",
    speak: bool = True,
) -> dict[str, Any]:
    """Bundle token + greeting TTS + optional timed budget for a live meeting.

    Presence (token + TTS) is always attempted even when daily budget is exhausted,
    so Marcus can still join. Timed budget is only *scheduled* here — ``start_session``
    runs after the client confirms the agent connected (avoids charging failed joins).
    """
    from veridiq.calling.budget import budget_status, max_call_seconds
    from veridiq.calling.livekit_tokens import livekit_status
    from veridiq.calling.meetings import get_meeting
    from veridiq.calling.timed_calls import schedule_timed_call
    from veridiq.workforce.identities import identity_for

    meeting = get_meeting(meeting_id)
    if not meeting:
        return {"ok": False, "error": "unknown_meeting"}
    if meeting.get("status") != "live":
        return {"ok": False, "error": "meeting_not_live", "meeting": meeting}

    ident = identity_for(agent_type)
    agent_name = ident.get("name") or "Marcus"
    script = build_greeting_script(meeting, agent_name=agent_name)

    token = mint_publishable_agent_token(meeting_id=meeting_id, agent_type=agent_type, name=agent_name)
    greeting: Optional[dict[str, Any]] = None
    if speak:
        try:
            greeting = synthesize_greeting(script, meeting_id=meeting_id, agent_type=agent_type)
        except Exception as exc:  # noqa: BLE001
            logger.exception("greeting synthesize failed")
            greeting = {"ok": False, "tts": {"ok": False, "message": str(exc)[:200]}, "script": script}

    budget = budget_status(agent_type="ai_calling", user_key=user_key)
    timed: Optional[dict[str, Any]] = None
    if open_budget:
        try:
            # Schedule only — do not start until agent LiveKit join succeeds.
            timed = schedule_timed_call(
                purpose=f"LiveKit meeting {meeting_id[:8]} — {meeting.get('topic') or 'call'}",
                script=script,
                requested_seconds=max_call_seconds(),
                agent_type="ai_calling",
                user_key=user_key,
                record_chain=True,
            )
            if timed.get("ok") and timed.get("session"):
                timed["pending_start"] = True
                timed["message"] = (
                    (timed.get("message") or "")
                    + " Timer starts when Marcus connects to the room."
                ).strip()
            elif not timed.get("ok"):
                # Presence still proceeds; UI can show exhausted banner.
                timed = {
                    **(timed or {}),
                    "ok": False,
                    "pending_start": False,
                    "presence_allowed": True,
                    "message": (
                        timed.get("message")
                        if timed
                        else "Budget exhausted — join still allowed; timed cap disabled."
                    ),
                }
        except Exception as exc:  # noqa: BLE001
            logger.exception("timed budget open failed for meeting %s", meeting_id)
            timed = {
                "ok": False,
                "status": "error",
                "message": str(exc)[:200],
                "presence_allowed": True,
            }

    livekit_ok = bool(token.get("ok"))
    tts_ok = bool((greeting or {}).get("tts", {}).get("ok")) if greeting else False
    return {
        "ok": livekit_ok,
        "mode": "agent_presence",
        "message": (
            f"{agent_name} is ready to join the LiveKit room with voice."
            if livekit_ok
            else (token.get("message") or token.get("error") or "Agent token unavailable")
        ),
        "agent": {
            "agent_type": agent_type,
            "name": agent_name,
            "role": ident.get("role"),
            "avatar_hue": ident.get("avatar_hue"),
            "avatar_presentation": ident.get("avatar_presentation"),
            "avatar_hair": ident.get("avatar_hair"),
            "avatar_skin": ident.get("avatar_skin"),
            "avatar_hair_color": ident.get("avatar_hair_color"),
        },
        "token": token if livekit_ok else None,
        "greeting": {
            "script": script,
            "clip_id": (greeting or {}).get("clip_id"),
            "audio_url": (greeting or {}).get("audio_url"),
            "tts_ok": tts_ok,
            "tts": (greeting or {}).get("tts"),
        },
        "budget": budget,
        "timed": timed,
        "timed_session_id": ((timed or {}).get("session") or {}).get("session_id"),
        "livekit": livekit_status(),
        "meeting": meeting,
        "max_call_seconds": max_call_seconds(),
        "budget_blocks_presence": False,
    }


def activate_presence_budget(*, session_id: str) -> dict[str, Any]:
    """Start the timed budget clock after Marcus has joined LiveKit."""
    from veridiq.calling.timed_calls import start_session

    if not session_id:
        return {"ok": False, "status": "missing_session", "message": "session_id required"}
    return start_session(session_id)


def cancel_presence_budget(*, session_id: str, reason: str = "agent_join_failed") -> dict[str, Any]:
    """Cancel a scheduled/active timed session without charging (failed / abandoned join)."""
    from veridiq.calling.timed_calls import end_session, get_session

    if not session_id:
        return {"ok": False, "status": "missing_session"}
    session = get_session(session_id)
    if not session:
        return {"ok": False, "status": "unknown_session"}
    if session.get("status") in {"completed", "expired", "cancelled", "failed"}:
        return {"ok": True, "status": session["status"], "session": session}
    # Never started → cancel with zero charge; started but failed early → charge 0
    return end_session(session_id, reason="cancelled" if reason != "failed" else "failed", consumed_override=0.0)


def enter_meeting_with_agent(
    *,
    meeting_id: str,
    identity: str = "veridiq-user",
    name: str = "You",
    user_key: str = "default",
    announce_telegram: bool = False,
) -> dict[str, Any]:
    """E2E helper: start (if needed) → admit → mint user token → prepare agent presence."""
    from veridiq.calling.meetings import confirm_join, get_meeting, mint_meeting_token, start_meeting

    meeting = get_meeting(meeting_id)
    if not meeting:
        return {"ok": False, "error": "unknown_meeting"}

    if meeting.get("status") == "scheduled":
        started = start_meeting(meeting_id=meeting_id, announce_telegram=announce_telegram)
        if not started.get("ok"):
            return started
        meeting = started.get("meeting") or get_meeting(meeting_id)
    elif meeting.get("status") != "live":
        return {"ok": False, "error": "meeting_not_joinable", "meeting": meeting}

    # Fast-path admit for human-like calling UX (skip wait/ready gate)
    if (meeting or {}).get("join_gate_status") != "admitted":
        admitted = confirm_join(meeting_id=meeting_id, yes=True)
        # confirm_join may refuse if still_waiting — force admit for enter path
        if not admitted.get("admitted"):
            from database import db_session, initialize_database

            initialize_database()
            with db_session() as conn:
                conn.execute(
                    "UPDATE veridiq_meetings SET join_gate_status = 'admitted' WHERE meeting_id = ?",
                    (meeting_id,),
                )
            meeting = get_meeting(meeting_id)
        else:
            meeting = admitted.get("meeting") or get_meeting(meeting_id)

    user_tok = mint_meeting_token(
        meeting_id=meeting_id,
        identity=identity,
        name=name,
        role="user",
    )
    if not user_tok.get("ok"):
        return user_tok

    presence = prepare_agent_presence(
        meeting_id=meeting_id,
        agent_type="ai_calling",
        open_budget=True,
        user_key=user_key,
        speak=True,
    )
    return {
        "ok": True,
        "meeting": meeting,
        "user_token": user_tok,
        "agent_presence": presence,
        "message": "Admitted — connect LiveKit; Marcus will join and speak a greeting.",
    }


def schedule_and_enter(
    *,
    topic: str,
    scheduled_at_pkt: Optional[str] = None,
    agenda: Optional[list[str]] = None,
    identity: str = "veridiq-user",
    name: str = "You",
    user_key: str = "default",
) -> dict[str, Any]:
    """Schedule a meeting (default: now PKT) and enter with Marcus voice."""
    from veridiq.calling.meetings import PKT, schedule_meeting
    from veridiq.calling.livekit_tokens import livekit_configured, livekit_status

    if not livekit_configured():
        # Still allow schedule so lobby shows upcoming; enter will fail clearly
        when = scheduled_at_pkt
        if not when:
            when = datetime.now(PKT).replace(second=0, microsecond=0).isoformat()
        scheduled = schedule_meeting(
            topic=topic or "Timed call with Marcus",
            scheduled_at_pkt=when,
            agenda=agenda or ["Greeting", "Agenda check-in", "Next steps"],
            agent_types=["ai_calling", "ceo"],
        )
        return {
            "ok": False,
            "error": "livekit_not_configured",
            "livekit": livekit_status(),
            "scheduled": scheduled,
            "message": livekit_status().get("message")
            or "LiveKit credentials missing — meeting scheduled but cannot go live yet.",
        }

    when = scheduled_at_pkt
    if not when:
        when = datetime.now(PKT).replace(second=0, microsecond=0).isoformat()
    scheduled = schedule_meeting(
        topic=topic or "Timed call with Marcus",
        scheduled_at_pkt=when,
        agenda=agenda or ["Greeting", "Agenda check-in", "Next steps"],
        agent_types=["ai_calling", "ceo"],
    )
    if not scheduled.get("ok"):
        return scheduled
    mid = (scheduled.get("meeting") or {}).get("meeting_id")
    if not mid:
        return {"ok": False, "error": "schedule_failed", "scheduled": scheduled}
    entered = enter_meeting_with_agent(
        meeting_id=mid,
        identity=identity,
        name=name,
        user_key=user_key,
        announce_telegram=False,
    )
    return {**entered, "scheduled": scheduled}
