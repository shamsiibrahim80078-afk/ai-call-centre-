"""VERIDIQ LiveKit meetings hub — conversations, schedule (PKT), go-live, join gate.

Persists to SQLite (`veridiq_meetings`, `veridiq_meeting_messages`,
`veridiq_meeting_hub`). Telegram announce on go-live only (no Meta/Threads).
"""

from __future__ import annotations

import json
import sqlite3
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from database import db_session, initialize_database  # noqa: E402
from veridiq.calling.agora import agora_meeting_sidecar, agora_status  # noqa: E402
from veridiq.calling.livekit_tokens import livekit_configured, livekit_status, mint_access_token  # noqa: E402
from veridiq.workforce.identities import identity_for  # noqa: E402

HUB_ID = "default"
try:
    from zoneinfo import ZoneInfo

    PKT = ZoneInfo("Asia/Karachi")
except Exception:
    # Windows without tzdata: Pakistan Standard Time is UTC+5 year-round.
    PKT = timezone(timedelta(hours=5), name="Asia/Karachi")
JOIN_WAIT_SEC = 4
JOIN_READY_SEC = 8
# Join / Call / Live controls appear within ± this window of scheduled_at (or when live).
CALL_WINDOW_SEC = 5 * 60
DEFAULT_AGENT_TYPES = ("ceo", "director_operations", "director_growth", "ai_calling")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _utc_iso(dt: Optional[datetime] = None) -> str:
    d = dt or _utc_now()
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _pkt_now() -> datetime:
    return datetime.now(PKT).replace(microsecond=0)


def _parse_pkt(when: str) -> datetime:
    """Parse a user-supplied Asia/Karachi datetime string."""
    raw = (when or "").strip()
    if not raw:
        raise ValueError("scheduled_at_pkt is required")
    # Accept "YYYY-MM-DDTHH:MM", "YYYY-MM-DD HH:MM", or with seconds / offset
    cleaned = raw.replace(" ", "T", 1)
    if cleaned.endswith("Z"):
        dt = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
        return dt.astimezone(PKT)
    try:
        dt = datetime.fromisoformat(cleaned)
    except ValueError as exc:
        raise ValueError(
            "scheduled_at_pkt must look like 2026-08-07T18:30 (Asia/Karachi)"
        ) from exc
    if dt.tzinfo is None:
        return dt.replace(tzinfo=PKT)
    return dt.astimezone(PKT)


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


def _row_meeting(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d.pop("id", None)
    agenda_json = d.pop("agenda_json", None)
    participants_json = d.pop("participants_json", None)
    telegram_json = d.pop("telegram_announce_json", None)
    d["agenda"] = json.loads(agenda_json) if agenda_json else []
    d["participants"] = json.loads(participants_json) if participants_json else []
    d["telegram_announce"] = json.loads(telegram_json) if telegram_json else None
    return d


def _row_message(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d.pop("id", None)
    return d


def _insert_message(
    conn: sqlite3.Connection,
    *,
    hub_id: str,
    sender_type: str,
    body: str,
    meeting_id: Optional[str] = None,
    sender_agent: Optional[str] = None,
    sender_name: Optional[str] = None,
) -> dict[str, Any]:
    message_id = str(uuid.uuid4())
    created_at = _utc_iso()
    name = sender_name
    if not name and sender_agent:
        name = identity_for(sender_agent)["name"]
    if not name:
        name = sender_type.title()
    conn.execute(
        """
        INSERT INTO veridiq_meeting_messages
            (message_id, meeting_id, hub_id, sender_type, sender_agent, sender_name, body, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (message_id, meeting_id, hub_id, sender_type, sender_agent, name, body.strip(), created_at),
    )
    return {
        "message_id": message_id,
        "meeting_id": meeting_id,
        "hub_id": hub_id,
        "sender_type": sender_type,
        "sender_agent": sender_agent,
        "sender_name": name,
        "body": body.strip(),
        "created_at": created_at,
    }


def _ensure_hub(conn: sqlite3.Connection, hub_id: str = HUB_ID) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM veridiq_meeting_hub WHERE hub_id = ?", (hub_id,)
    ).fetchone()
    if row:
        d = dict(row)
        meta = d.pop("meta_json", None)
        d["meta"] = json.loads(meta) if meta else {}
        return d
    now = _utc_iso()
    conn.execute(
        """
        INSERT INTO veridiq_meeting_hub (hub_id, status, ceo_entered_at, active_meeting_id, meta_json, updated_at)
        VALUES (?, 'open', NULL, NULL, ?, ?)
        """,
        (hub_id, "{}", now),
    )
    return {
        "hub_id": hub_id,
        "status": "open",
        "ceo_entered_at": None,
        "active_meeting_id": None,
        "meta": {},
        "updated_at": now,
    }


def _get_meeting(conn: sqlite3.Connection, meeting_id: str) -> Optional[dict[str, Any]]:
    row = conn.execute(
        "SELECT * FROM veridiq_meetings WHERE meeting_id = ?", (meeting_id,)
    ).fetchone()
    return _row_meeting(row) if row else None


def _advance_join_gate(meeting: dict[str, Any]) -> dict[str, Any]:
    """Time-based join gate: wait → ready_prompt after agents 'discuss' briefly."""
    status = meeting.get("join_gate_status") or "closed"
    requested = meeting.get("join_requested_at")
    if status not in ("user_waiting", "ready_prompt") or not requested:
        return meeting
    try:
        req_dt = datetime.fromisoformat(requested)
        if req_dt.tzinfo is None:
            req_dt = req_dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return meeting
    elapsed = (_utc_now() - req_dt.astimezone(timezone.utc)).total_seconds()
    if status == "user_waiting" and elapsed >= JOIN_WAIT_SEC:
        meeting = dict(meeting)
        meeting["join_gate_status"] = "ready_prompt"
        with db_session() as conn:
            conn.execute(
                "UPDATE veridiq_meetings SET join_gate_status = 'ready_prompt' WHERE meeting_id = ?",
                (meeting["meeting_id"],),
            )
            if elapsed < JOIN_READY_SEC + 2:
                _insert_message(
                    conn,
                    hub_id=HUB_ID,
                    meeting_id=meeting["meeting_id"],
                    sender_type="agent",
                    sender_agent="ceo",
                    body="Ready to join? Reply Yes and we'll admit you to the LiveKit room.",
                )
    return meeting


def get_hub(*, hub_id: str = HUB_ID, message_limit: int = 80) -> dict[str, Any]:
    """Hub snapshot — never raises to callers; empty live threads on failure."""
    empty = {
        "hub_id": hub_id,
        "hub": {"hub_id": hub_id, "status": "open", "ceo_entered_at": None, "active_meeting_id": None, "meta": {}},
        "ceo": _agent_card("ceo"),
        "ceo_present": False,
        "messages": [],
        "active_meeting": None,
        "live_threads": [],
        "invites": [],
        "observer_mode": True,
        "user_can_chat": False,
        "timezone": "Asia/Karachi",
        "timezone_label": "PKT",
        "call_window_sec": CALL_WINDOW_SEC,
    }
    try:
        initialize_database()
        with db_session() as conn:
            hub = _ensure_hub(conn, hub_id)
            rows = conn.execute(
                """
                SELECT * FROM veridiq_meeting_messages
                WHERE hub_id = ?
                ORDER BY created_at ASC, id ASC
                LIMIT ?
                """,
                (hub_id, max(1, min(message_limit, 500))),
            ).fetchall()
            messages = [_row_message(r) for r in rows]
            active = None
            if hub.get("active_meeting_id"):
                active = _get_meeting(conn, hub["active_meeting_id"])
        if active:
            active = _advance_join_gate(active)
            active["call_window_open"] = meeting_in_call_window(active)
            active["call_window_sec"] = CALL_WINDOW_SEC
        live: dict[str, Any] = {"threads": [], "invites": []}
        try:
            from veridiq.calling.live_threads import list_live_threads

            # Light list (previews only) + batch tick — keeps hub GET fast
            live = list_live_threads(include_messages=False, tick=True)
        except Exception as live_exc:
            live = {"threads": [], "invites": [], "error": str(live_exc)[:200]}
        ceo = _agent_card("ceo")
        return {
            "hub_id": hub_id,
            "hub": hub,
            "ceo": ceo,
            "ceo_present": bool(hub.get("ceo_entered_at")),
            "messages": messages[-40:],
            "active_meeting": active,
            "live_threads": live.get("threads") or [],
            "invites": live.get("invites") or [],
            "observer_mode": True,
            "user_can_chat": False,
            "user_name": live.get("user_name") or "Ibrahim",
            "swarm": live.get("swarm") or {},
            "poll_hint_ms": live.get("poll_hint_ms") or 1000,
            "livekit": livekit_status(),
            "agora": agora_status(),
            "timezone": "Asia/Karachi",
            "timezone_label": "PKT",
            "now_pkt": _pkt_now().isoformat(),
            "call_window_sec": CALL_WINDOW_SEC,
            "ok": True,
        }
    except Exception as exc:
        empty["ok"] = True
        empty["error"] = str(exc)[:240]
        try:
            empty["livekit"] = livekit_status()
            empty["agora"] = agora_status()
            empty["now_pkt"] = _pkt_now().isoformat()
        except Exception:
            empty["livekit"] = {"configured": False}
            empty["agora"] = {"configured": False}
        return empty


def _seed_agent_agenda_thread(conn: sqlite3.Connection, *, hub_id: str, restart: bool = False) -> None:
    """CEO Aurelia opens first; Marcus + Selene discuss agenda / PKT schedule."""
    ceo = identity_for("ceo")
    ops = identity_for("director_operations")
    growth = identity_for("director_growth")
    if restart:
        _insert_message(
            conn,
            hub_id=hub_id,
            sender_type="system",
            body="Agents restarted the Collaboration Hub conversation.",
        )
    else:
        _insert_message(
            conn,
            hub_id=hub_id,
            sender_type="system",
            body=f"{ceo['name']} (CEO) entered the Collaboration Hub.",
        )
    _insert_message(
        conn,
        hub_id=hub_id,
        sender_type="ceo",
        sender_agent="ceo",
        body=(
            f"Good day — {ceo['name']} here. Let's align on today's agent-to-agent agenda "
            "before we go live. What should we prioritize, and when should we meet in Asia/Karachi (PKT)?"
        ),
    )
    _insert_message(
        conn,
        hub_id=hub_id,
        sender_type="agent",
        sender_agent="director_operations",
        body=(
            f"{ops['name']}: Ops is ready. Suggest we lock a topic, pick a PKT start time, "
            "then open the LiveKit room from AI Calling when that window arrives."
        ),
    )
    _insert_message(
        conn,
        hub_id=hub_id,
        sender_type="agent",
        sender_agent="director_growth",
        body=(
            f"{growth['name']}: Agreed. Schedule here, then join from Calling near the PKT time. "
            "Telegram announce on go-live only."
        ),
    )


def enter_ceo(*, hub_id: str = HUB_ID) -> dict[str, Any]:
    """CEO agent enters the Conversations Hub first and opens the agenda thread."""
    initialize_database()
    with db_session() as conn:
        hub = _ensure_hub(conn, hub_id)
        now = _utc_iso()
        if not hub.get("ceo_entered_at"):
            conn.execute(
                """
                UPDATE veridiq_meeting_hub
                SET ceo_entered_at = ?, status = 'discussing', updated_at = ?
                WHERE hub_id = ?
                """,
                (now, now, hub_id),
            )
            _seed_agent_agenda_thread(conn, hub_id=hub_id, restart=False)
        else:
            conn.execute(
                "UPDATE veridiq_meeting_hub SET updated_at = ? WHERE hub_id = ?",
                (now, hub_id),
            )
    return get_hub(hub_id=hub_id)


def start_agent_conversation(*, hub_id: str = HUB_ID, force: bool = False) -> dict[str, Any]:
    """Ensure CEO is present and (re)seed Aurelia → Marcus → Selene agenda chat.

    Used by Collaboration Hub on open / “Start agent conversation”.
    """
    initialize_database()
    with db_session() as conn:
        hub = _ensure_hub(conn, hub_id)
        now = _utc_iso()
        first = not hub.get("ceo_entered_at")
        if first:
            conn.execute(
                """
                UPDATE veridiq_meeting_hub
                SET ceo_entered_at = ?, status = 'discussing', updated_at = ?
                WHERE hub_id = ?
                """,
                (now, now, hub_id),
            )
            _seed_agent_agenda_thread(conn, hub_id=hub_id, restart=False)
        elif force:
            conn.execute(
                """
                UPDATE veridiq_meeting_hub
                SET status = 'discussing', updated_at = ?
                WHERE hub_id = ?
                """,
                (now, hub_id),
            )
            _seed_agent_agenda_thread(conn, hub_id=hub_id, restart=True)
        else:
            conn.execute(
                "UPDATE veridiq_meeting_hub SET updated_at = ? WHERE hub_id = ?",
                (now, hub_id),
            )
    hub_out = get_hub(hub_id=hub_id)
    hub_out["started"] = True
    hub_out["seeded"] = first or force
    return hub_out


def meeting_in_call_window(meeting: dict[str, Any], *, now: Optional[datetime] = None) -> bool:
    """True when status is live, or scheduled_at is within ±CALL_WINDOW_SEC of now (PKT clock)."""
    status = (meeting.get("status") or "").strip().lower()
    if status == "live":
        return True
    if status != "scheduled":
        return False
    ref = now or _utc_now()
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    raw = meeting.get("scheduled_at_utc") or meeting.get("scheduled_at_pkt")
    if not raw:
        return False
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=PKT).astimezone(timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    delta = abs((ref.astimezone(timezone.utc) - dt).total_seconds())
    return delta <= CALL_WINDOW_SEC


def post_hub_message(
    *,
    body: str,
    hub_id: str = HUB_ID,
    as_user: bool = True,
    meeting_id: Optional[str] = None,
) -> dict[str, Any]:
    """User (or system) posts into the pre-meeting text hub; agents may reply."""
    text = (body or "").strip()
    if not text:
        return {"ok": False, "error": "empty_message"}
    initialize_database()
    with db_session() as conn:
        hub = _ensure_hub(conn, hub_id)
        if not hub.get("ceo_entered_at"):
            # Auto-enter CEO if user speaks first
            pass
    if not get_hub(hub_id=hub_id).get("ceo_present"):
        enter_ceo(hub_id=hub_id)

    with db_session() as conn:
        user_msg = _insert_message(
            conn,
            hub_id=hub_id,
            meeting_id=meeting_id,
            sender_type="user" if as_user else "system",
            sender_name="You",
            body=text,
        )
        lower = text.lower()
        replies: list[dict[str, Any]] = []
        if any(k in lower for k in ("schedule", "pkt", "meeting", "agenda", "topic", "live")):
            replies.append(
                _insert_message(
                    conn,
                    hub_id=hub_id,
                    meeting_id=meeting_id,
                    sender_type="ceo",
                    sender_agent="ceo",
                    body=(
                        "Noted. Use Schedule meeting with a clear topic and Asia/Karachi (PKT) time. "
                        "I'll bring directors into the LiveKit room when we start."
                    ),
                )
            )
        elif any(k in lower for k in ("yes", "admit", "ready", "join")):
            replies.append(
                _insert_message(
                    conn,
                    hub_id=hub_id,
                    meeting_id=meeting_id,
                    sender_type="agent",
                    sender_agent="director_operations",
                    body="If a live meeting is waiting on you, confirm join from the Live room panel.",
                )
            )
        else:
            replies.append(
                _insert_message(
                    conn,
                    hub_id=hub_id,
                    meeting_id=meeting_id,
                    sender_type="agent",
                    sender_agent="ai_calling",
                    body=(
                        f"{identity_for('ai_calling')['name']}: Captured. Propose a topic + PKT time "
                        "when you're ready to schedule the agent-to-agent call."
                    ),
                )
            )
    return {"ok": True, "message": user_msg, "replies": replies, "hub": get_hub(hub_id=hub_id)}


def schedule_meeting(
    *,
    topic: str,
    scheduled_at_pkt: str,
    agenda: Optional[list[str]] = None,
    agent_types: Optional[list[str]] = None,
    hub_id: str = HUB_ID,
) -> dict[str, Any]:
    topic_clean = (topic or "").strip()
    if not topic_clean:
        return {"ok": False, "error": "topic_required"}
    try:
        pkt_dt = _parse_pkt(scheduled_at_pkt)
    except ValueError as exc:
        return {"ok": False, "error": "invalid_schedule", "message": str(exc)}

    initialize_database()
    with db_session() as conn:
        hub_row = _ensure_hub(conn, hub_id)
        if not hub_row.get("ceo_entered_at"):
            now_ceo = _utc_iso()
            conn.execute(
                """
                UPDATE veridiq_meeting_hub
                SET ceo_entered_at = ?, status = 'discussing', updated_at = ?
                WHERE hub_id = ?
                """,
                (now_ceo, now_ceo, hub_id),
            )

    agents = list(agent_types) if agent_types else list(DEFAULT_AGENT_TYPES)
    if "ceo" not in agents:
        agents = ["ceo", *agents]
    participants = [_agent_card(a) for a in agents]
    agenda_items = [str(a).strip() for a in (agenda or []) if str(a).strip()]
    if not agenda_items:
        agenda_items = [
            "Align on objectives",
            "Assign follow-ups",
            "Confirm Telegram go-live announce",
        ]

    meeting_id = str(uuid.uuid4())
    room = f"veridiq-{meeting_id[:8]}"
    created_at = _utc_iso()
    pkt_iso = pkt_dt.isoformat()
    utc_iso = pkt_dt.astimezone(timezone.utc).isoformat()

    initialize_database()
    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO veridiq_meetings
                (meeting_id, topic, agenda_json, status, scheduled_at_pkt, scheduled_at_utc,
                 livekit_room, join_gate_status, participants_json, created_at)
            VALUES (?, ?, ?, 'scheduled', ?, ?, ?, 'closed', ?, ?)
            """,
            (
                meeting_id,
                topic_clean,
                json.dumps(agenda_items),
                pkt_iso,
                utc_iso,
                room,
                json.dumps(participants),
                created_at,
            ),
        )
        conn.execute(
            """
            UPDATE veridiq_meeting_hub
            SET active_meeting_id = ?, status = 'scheduled', updated_at = ?
            WHERE hub_id = ?
            """,
            (meeting_id, created_at, hub_id),
        )
        _insert_message(
            conn,
            hub_id=hub_id,
            meeting_id=meeting_id,
            sender_type="ceo",
            sender_agent="ceo",
            body=(
                f"Meeting scheduled: “{topic_clean}” at {pkt_dt.strftime('%Y-%m-%d %H:%M')} PKT "
                f"(Asia/Karachi). Room `{room}`. Start when ready — I'll enter LiveKit first."
            ),
        )
        meeting = _get_meeting(conn, meeting_id)
    return {"ok": True, "meeting": meeting}


def list_meetings(*, limit: int = 40) -> list[dict[str, Any]]:
    initialize_database()
    with db_session() as conn:
        rows = conn.execute(
            "SELECT * FROM veridiq_meetings ORDER BY created_at DESC LIMIT ?",
            (max(1, min(limit, 200)),),
        ).fetchall()
    meetings = [_row_meeting(r) for r in rows]
    out: list[dict[str, Any]] = []
    for m in meetings:
        if m.get("status") == "live":
            m = _advance_join_gate(m)
        m["call_window_open"] = meeting_in_call_window(m)
        m["call_window_sec"] = CALL_WINDOW_SEC
        out.append(m)
    return out


def get_meeting(meeting_id: str) -> Optional[dict[str, Any]]:
    initialize_database()
    with db_session() as conn:
        meeting = _get_meeting(conn, meeting_id)
    if not meeting:
        return None
    if meeting.get("status") == "live":
        meeting = _advance_join_gate(meeting)
    meeting["call_window_open"] = meeting_in_call_window(meeting)
    meeting["call_window_sec"] = CALL_WINDOW_SEC
    return meeting


def _frontend_join_url(meeting_id: str) -> str:
    import os

    base = (
        os.getenv("VERIDIQ_PUBLIC_FRONTEND_URL")
        or os.getenv("VERIDIQ_TELEGRAM_MINIAPP_URL")
        or "http://localhost:5173"
    ).strip().rstrip("/")
    return f"{base}/dashboard/calling?meeting={meeting_id}"


def _announce_telegram(meeting: dict[str, Any]) -> dict[str, Any]:
    """Post go-live notice to the default Telegram group (no other socials)."""
    from veridiq.integrations import telegram as telegram_mod

    chat_id = telegram_mod.default_chat_id()
    if not telegram_mod.bot_token() or not chat_id:
        return {
            "status": "configuration_required",
            "message": "Telegram bot token / default chat id not set — meeting is live without announce.",
        }
    join_url = _frontend_join_url(meeting["meeting_id"])
    pkt = meeting.get("scheduled_at_pkt") or "now"
    text = (
        "🔴 VERIDIQ agent-to-agent meeting is LIVE\n\n"
        f"Topic: {meeting.get('topic')}\n"
        f"Scheduled (PKT): {pkt}\n"
        f"LiveKit room: {meeting.get('livekit_room')}\n\n"
        f"Join from the dashboard: {join_url}\n"
        "(Telegram-only announce for this milestone — no Meta/Threads/X.)"
    )
    result = telegram_mod.send_message(chat_id=chat_id, text=text)
    result["join_url"] = join_url
    result["chat_id"] = chat_id
    return result


def start_meeting(*, meeting_id: str, hub_id: str = HUB_ID, announce_telegram: bool = True) -> dict[str, Any]:
    """Mark meeting live, ensure LiveKit creds, optionally announce on Telegram."""
    if not livekit_configured():
        return {
            "ok": False,
            "error": "livekit_not_configured",
            "livekit": livekit_status(),
            "message": "Cannot start a real LiveKit meeting without credentials.",
        }
    meeting = get_meeting(meeting_id)
    if not meeting:
        return {"ok": False, "error": "unknown_meeting"}
    if meeting["status"] == "ended":
        return {"ok": False, "error": "meeting_ended"}
    if meeting["status"] == "live":
        return {"ok": True, "meeting": meeting, "already_live": True, "livekit": livekit_status()}

    started_at = _utc_iso()
    initialize_database()
    with db_session() as conn:
        conn.execute(
            """
            UPDATE veridiq_meetings
            SET status = 'live', started_at = ?, join_gate_status = 'closed'
            WHERE meeting_id = ?
            """,
            (started_at, meeting_id),
        )
        conn.execute(
            """
            UPDATE veridiq_meeting_hub
            SET active_meeting_id = ?, status = 'live', updated_at = ?
            WHERE hub_id = ?
            """,
            (meeting_id, started_at, hub_id),
        )
        ceo = identity_for("ceo")
        _insert_message(
            conn,
            hub_id=hub_id,
            meeting_id=meeting_id,
            sender_type="ceo",
            sender_agent="ceo",
            body=(
                f"{ceo['name']} entered the LiveKit room first. Directors are joining. "
                "Humans: request to join — we'll ask you to wait, then confirm when ready."
            ),
        )
        meeting = _get_meeting(conn, meeting_id)

    announce: dict[str, Any]
    if announce_telegram:
        announce = _announce_telegram(meeting)  # type: ignore[arg-type]
        with db_session() as conn:
            conn.execute(
                "UPDATE veridiq_meetings SET telegram_announce_json = ? WHERE meeting_id = ?",
                (json.dumps(announce), meeting_id),
            )
            meeting = _get_meeting(conn, meeting_id)
    else:
        announce = {"status": "skipped", "message": "Telegram announce skipped for personal invite meeting."}

    agora = agora_meeting_sidecar(
        meeting_id=meeting_id,
        livekit_room=str((meeting or {}).get("livekit_room") or ""),
    )
    return {
        "ok": True,
        "meeting": meeting,
        "telegram": announce,
        "livekit": livekit_status(),
        "agora": agora,
    }


def request_join(*, meeting_id: str, hub_id: str = HUB_ID) -> dict[str, Any]:
    meeting = get_meeting(meeting_id)
    if not meeting:
        return {"ok": False, "error": "unknown_meeting"}
    if meeting["status"] != "live":
        return {"ok": False, "error": "meeting_not_live"}
    if meeting.get("join_gate_status") == "admitted":
        return {"ok": True, "meeting": meeting, "already_admitted": True}

    now = _utc_iso()
    initialize_database()
    with db_session() as conn:
        conn.execute(
            """
            UPDATE veridiq_meetings
            SET join_gate_status = 'user_waiting', join_requested_at = ?
            WHERE meeting_id = ?
            """,
            (now, meeting_id),
        )
        _insert_message(
            conn,
            hub_id=hub_id,
            meeting_id=meeting_id,
            sender_type="user",
            sender_name="You",
            body="Requesting to join the live meeting.",
        )
        _insert_message(
            conn,
            hub_id=hub_id,
            meeting_id=meeting_id,
            sender_type="agent",
            sender_agent="ceo",
            body="Please wait — finishing agent discussion, then we'll ask if you're ready to join.",
        )
        meeting = _get_meeting(conn, meeting_id)
    return {"ok": True, "meeting": meeting, "message": "Agents asked you to wait."}


def confirm_join(*, meeting_id: str, yes: bool = True, hub_id: str = HUB_ID) -> dict[str, Any]:
    meeting = get_meeting(meeting_id)
    if not meeting:
        return {"ok": False, "error": "unknown_meeting"}
    if meeting["status"] != "live":
        return {"ok": False, "error": "meeting_not_live"}
    meeting = _advance_join_gate(meeting)

    if not yes:
        initialize_database()
        with db_session() as conn:
            conn.execute(
                "UPDATE veridiq_meetings SET join_gate_status = 'closed', join_requested_at = NULL WHERE meeting_id = ?",
                (meeting_id,),
            )
            _insert_message(
                conn,
                hub_id=hub_id,
                meeting_id=meeting_id,
                sender_type="system",
                body="Join declined — you can request again anytime.",
            )
            meeting = _get_meeting(conn, meeting_id)
        return {"ok": True, "meeting": meeting, "admitted": False}

    gate = meeting.get("join_gate_status")
    if gate not in ("ready_prompt", "admitted", "user_waiting"):
        return {"ok": False, "error": "join_not_ready", "meeting": meeting}
    # Allow confirm once ready_prompt; if still waiting but enough time, advance first
    if gate == "user_waiting":
        meeting = _advance_join_gate(meeting)
        if meeting.get("join_gate_status") != "ready_prompt":
            return {
                "ok": False,
                "error": "still_waiting",
                "message": "Agents said wait — try again in a few seconds.",
                "meeting": meeting,
            }

    initialize_database()
    with db_session() as conn:
        conn.execute(
            "UPDATE veridiq_meetings SET join_gate_status = 'admitted' WHERE meeting_id = ?",
            (meeting_id,),
        )
        _insert_message(
            conn,
            hub_id=hub_id,
            meeting_id=meeting_id,
            sender_type="ceo",
            sender_agent="ceo",
            body="Admitted. Connecting you to the LiveKit room now.",
        )
        meeting = _get_meeting(conn, meeting_id)
    return {"ok": True, "meeting": meeting, "admitted": True}


def end_meeting(*, meeting_id: str, hub_id: str = HUB_ID) -> dict[str, Any]:
    meeting = get_meeting(meeting_id)
    if not meeting:
        return {"ok": False, "error": "unknown_meeting"}
    ended_at = _utc_iso()
    initialize_database()
    with db_session() as conn:
        conn.execute(
            "UPDATE veridiq_meetings SET status = 'ended', ended_at = ?, join_gate_status = 'closed' WHERE meeting_id = ?",
            (ended_at, meeting_id),
        )
        conn.execute(
            "UPDATE veridiq_meeting_hub SET status = 'open', updated_at = ? WHERE hub_id = ?",
            (ended_at, hub_id),
        )
        _insert_message(
            conn,
            hub_id=hub_id,
            meeting_id=meeting_id,
            sender_type="system",
            body="Meeting ended.",
        )
        meeting = _get_meeting(conn, meeting_id)
    return {"ok": True, "meeting": meeting}


def mint_meeting_token(
    *,
    meeting_id: str,
    identity: str = "veridiq-user",
    name: str = "You",
    role: str = "user",
) -> dict[str, Any]:
    """Mint LiveKit JWT. Users must be admitted; agent identities may join when live."""
    meeting = get_meeting(meeting_id)
    if not meeting:
        return {"ok": False, "error": "unknown_meeting"}
    if meeting["status"] != "live":
        return {"ok": False, "error": "meeting_not_live", "meeting": meeting}
    if not livekit_configured():
        return {"ok": False, "error": "livekit_not_configured", "livekit": livekit_status()}

    role = (role or "user").strip().lower()
    if role == "user" and meeting.get("join_gate_status") != "admitted":
        return {
            "ok": False,
            "error": "not_admitted",
            "message": "Request to join and confirm when agents ask Ready to join?",
            "meeting": meeting,
        }

    room = meeting.get("livekit_room") or f"veridiq-{meeting_id[:8]}"
    safe_identity = (identity or "veridiq-user").strip()[:64] or "veridiq-user"
    display = (name or safe_identity).strip()[:64]
    token = mint_access_token(
        identity=safe_identity,
        room_name=room,
        name=display,
        can_publish=True,
        can_subscribe=True,
        can_publish_data=True,
    )
    if not token.get("ok"):
        return token
    return {
        **token,
        "meeting_id": meeting_id,
        "meeting": meeting,
        "participants": meeting.get("participants") or [],
        "role": role,
    }


def agent_tokens_for_meeting(meeting_id: str) -> dict[str, Any]:
    """Mint LiveKit tokens for agent participants (avatar-side presence / data)."""
    meeting = get_meeting(meeting_id)
    if not meeting:
        return {"ok": False, "error": "unknown_meeting"}
    if meeting["status"] != "live":
        return {"ok": False, "error": "meeting_not_live"}
    if not livekit_configured():
        return {"ok": False, "error": "livekit_not_configured", "livekit": livekit_status()}

    room = meeting.get("livekit_room") or f"veridiq-{meeting_id[:8]}"
    tokens = []
    for p in meeting.get("participants") or []:
        at = p.get("agent_type") or "agent"
        # Publish enabled so agent presence (TTS audio / avatar video) can join.
        tok = mint_access_token(
            identity=f"agent-{at}",
            room_name=room,
            name=p.get("name") or at,
            can_publish=True,
            can_subscribe=True,
            can_publish_data=True,
        )
        if tok.get("ok"):
            tokens.append({**tok, "agent_type": at, "avatar_hue": p.get("avatar_hue"), "role": p.get("role")})
    return {"ok": True, "room": room, "url": livekit_status().get("url"), "tokens": tokens, "meeting": meeting}
