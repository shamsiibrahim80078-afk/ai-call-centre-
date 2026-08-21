"""Live Collaboration Hub — DM-first agent chats + optional swarm rooms.

Primary UX: 1:1 DMs (user ↔ each workforce agent). Creative compose routes to
Mira (Postings) over HTTP. Swarm / working rooms remain available as optional
Rooms. LiveKit meetings are never auto-started from the hub — only after an
explicit Request interact → Accept invite → Join on AI Calling / Meet Marcus.
"""

from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from database import db_session, initialize_database
from veridiq.workforce.identities import identity_for

DEFAULT_USER_ID = "default"
DEFAULT_USER_NAME = "Ibrahim"

from veridiq.calling.hub_swarm import (  # noqa: E402
    TARGET_LIVE_THREADS,
    TICK_BATCH,
    TICK_INTERVAL_SEC,
    THREAD_BLUEPRINTS,
    estimated_agent_presence,
    opening_line,
    pick_tick_indices,
    work_line_for,
)

MAX_SCRIPT_TURNS = 14

# Pinned at top of DM contact list (WhatsApp-style)
DM_PINNED_AGENTS: tuple[str, ...] = (
    "ceo",  # Aurelia
    "ai_calling",  # Marcus
    "posting_studio",  # Mira
    "director_operations",
    "director_growth",
    "director_intelligence",
    "content_creator",
    "social_poster",
    "marketing_manager",
    "influencer_relations",
    "sales_intelligence",
    "web_search",
)

# Keyword → specialist agent for personal meeting requests
SPECIALIST_ALIASES: dict[str, tuple[str, ...]] = {
    "content_creator": ("canva", "logo", "design", "graphic", "daily post", "daily posts", "content", "copy", "jasper"),
    "social_poster": ("social", "instagram", "linkedin post", "x post", "tweet", "lena", "poster"),
    "marketing_manager": ("campaign", "marketing manager", "renata"),
    "influencer_relations": ("influencer", "adrian", "creator outreach", "influencers"),
    "telegram_community": ("telegram", "community", "theo"),
    "x_twitter_voice": ("twitter", "nova", "x voice"),
    "linkedin_outreach": ("linkedin", "talia", "outreach"),
    "sales_intelligence": ("sales", "diego", "crm"),
    "market_research": ("market research", "research desk"),
    "face_analysis": ("face", "emma"),
    "lie_detection": ("lie", "deception", "maya"),
}

_lock = threading.RLock()
_bg_started = False
_tick_salt = 0


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _utc_iso(dt: Optional[datetime] = None) -> str:
    d = dt or _utc_now()
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _agent_card(agent_type: str) -> dict[str, Any]:
    ident = identity_for(agent_type)
    return {
        "agent_type": agent_type,
        "agent_id": agent_type,
        "name": ident["name"],
        "role": ident["role"],
        "avatar_hue": ident.get("avatar_hue", 200),
        "avatar_presentation": ident.get("avatar_presentation", "androgynous"),
        "avatar_hair": ident.get("avatar_hair", "short"),
        "avatar_skin": ident.get("avatar_skin", "#c4a484"),
        "avatar_hair_color": ident.get("avatar_hair_color", "#2a1f14"),
        "kind": "agent",
    }


def resolve_specialist(query: str) -> str:
    q = (query or "").strip().lower()
    if not q:
        return "content_creator"
    for agent_type, keys in SPECIALIST_ALIASES.items():
        if any(k in q for k in keys):
            return agent_type
    # Match any workforce identity by type or display name
    from veridiq.workforce.identities import AGENT_IDENTITIES

    for agent_type, meta in AGENT_IDENTITIES.items():
        name = str(meta.get("name") or "").lower()
        role = str(meta.get("role") or "").lower()
        if agent_type.replace("_", " ") in q or agent_type in q or (name and name in q) or (role and role in q):
            return agent_type
    return "content_creator"


def _row_thread(row: Any) -> dict[str, Any]:
    d = dict(row)
    d.pop("id", None)
    parts = d.pop("participants_json", None)
    meta = d.pop("meta_json", None)
    d["participants"] = json.loads(parts) if parts else []
    d["meta"] = json.loads(meta) if meta else {}
    return d


def _insert_thread_message(
    conn: Any,
    *,
    thread_id: str,
    agent_id: Optional[str],
    body: str,
    kind: str = "chat",
    sender_name: Optional[str] = None,
) -> dict[str, Any]:
    message_id = str(uuid.uuid4())
    created_at = _utc_iso()
    name = sender_name
    if not name and agent_id:
        name = identity_for(agent_id)["name"]
    if not name:
        name = "System"
    conn.execute(
        """
        INSERT INTO veridiq_live_thread_messages
            (message_id, thread_id, agent_id, sender_name, body, kind, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (message_id, thread_id, agent_id, name, body.strip(), kind, created_at),
    )
    conn.execute(
        "UPDATE veridiq_live_threads SET updated_at = ? WHERE thread_id = ?",
        (created_at, thread_id),
    )
    return {
        "message_id": message_id,
        "thread_id": thread_id,
        "agent_id": agent_id,
        "sender_name": name,
        "body": body.strip(),
        "kind": kind,
        "created_at": created_at,
        "avatar": _agent_card(agent_id) if agent_id else None,
    }


def _get_thread(conn: Any, thread_id: str) -> Optional[dict[str, Any]]:
    row = conn.execute(
        "SELECT * FROM veridiq_live_threads WHERE thread_id = ?", (thread_id,)
    ).fetchone()
    return _row_thread(row) if row else None


def _is_dm_thread(thread: Optional[dict[str, Any]]) -> bool:
    if not thread:
        return False
    meta = thread.get("meta") or {}
    return str(meta.get("kind") or "") == "dm"


def _dm_agent_type(thread: Optional[dict[str, Any]]) -> Optional[str]:
    if not _is_dm_thread(thread):
        return None
    meta = thread.get("meta") or {}
    agent = str(meta.get("dm_agent") or "").strip()
    return agent or None


def _dm_roster() -> list[str]:
    """Unique agent types for the DM contact list (pinned first, then rest)."""
    from veridiq.workforce.identities import AGENT_IDENTITIES

    seen_names: set[str] = set()
    out: list[str] = []
    for agent_type in DM_PINNED_AGENTS:
        if agent_type not in AGENT_IDENTITIES:
            continue
        name = str(identity_for(agent_type).get("name") or agent_type).lower()
        if name in seen_names:
            continue
        seen_names.add(name)
        out.append(agent_type)
    for agent_type in AGENT_IDENTITIES:
        if agent_type in out:
            continue
        name = str(identity_for(agent_type).get("name") or agent_type).lower()
        if name in seen_names:
            continue
        seen_names.add(name)
        out.append(agent_type)
    return out


def _thread_messages(conn: Any, thread_id: str, *, limit: int = 120) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT * FROM veridiq_live_thread_messages
        WHERE thread_id = ?
        ORDER BY created_at ASC, id ASC
        LIMIT ?
        """,
        (thread_id, max(1, min(limit, 500))),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        d.pop("id", None)
        if d.get("agent_id"):
            d["avatar"] = _agent_card(d["agent_id"])
        out.append(d)
    return out


def _llm_turn(agent_type: str, topic: str, history: list[dict[str, str]]) -> Optional[str]:
    """Best-effort LLM turn; returns None when gateway unavailable."""
    try:
        from veridiq.integrations import ai_gateway

        if not ai_gateway.status().get("configured"):
            return None
        ident = identity_for(agent_type)
        hist = "\n".join(f"{h['name']}: {h['text']}" for h in history[-6:])
        prompt = (
            f"You are {ident['name']}, VERIDIQ {ident['role']}. "
            f"You are collaborating with other AI agents on: {topic}. "
            "Reply in 1-2 short professional sentences as a working chat message. "
            "Do not address the human unless inviting them. No markdown.\n\n"
            f"Recent thread:\n{hist}\n\nYour message:"
        )
        gen = ai_gateway.generate(prompt=prompt, task_type="fast", max_providers=2, max_tokens=180)
        if gen.get("ok") and gen.get("text"):
            text = str(gen["text"]).strip().split("\n")[0].strip()[:420]
            return text or None
    except Exception:
        return None
    return None


def _scripted_turns(topic: str, agents: list[str], user_name: str = DEFAULT_USER_NAME) -> list[tuple[str, str, str]]:
    """Structured agent↔agent work turns.

    Does **not** auto-create meeting invites — invites only after an explicit
    user request (Request interact / Marcus personal meeting).
    """
    del user_name  # reserved for invite path; swarm chatter stays agent-only
    turns: list[tuple[str, str, str]] = []
    if not agents:
        agents = ["ceo", "content_creator"]
    lead = agents[0]
    turns.append((lead, opening_line(lead, topic), "chat"))
    for i, a in enumerate(agents):
        turns.append((a, work_line_for(a, topic, i + 1), "chat"))
    for i, a in enumerate(agents):
        turns.append((a, work_line_for(a, topic, i + 10), "chat"))
    # Extra cadence lines (no invite kinds — avoid unwanted LiveKit meetings)
    for n in range(8):
        a = agents[n % len(agents)]
        turns.append((a, work_line_for(a, topic, n + 20), "chat"))
    return turns


def create_live_thread(
    *,
    topic: str = "Daily content & Canva ops",
    agent_types: Optional[list[str]] = None,
    auto_start: bool = True,
    blueprint_key: Optional[str] = None,
) -> dict[str, Any]:
    initialize_database()
    agents = list(agent_types) if agent_types else [
        "ceo",
        "director_operations",
        "content_creator",
        "ai_calling",
    ]
    participants = [_agent_card(a) for a in agents]
    thread_id = str(uuid.uuid4())
    now = _utc_iso()
    title = f"Live · {topic.strip()[:80]}"
    meta = {"script": "swarm", "llm_preferred": False, "blueprint_key": blueprint_key}
    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO veridiq_live_threads
                (thread_id, title, topic, status, participants_json, meeting_id,
                 turn_index, last_tick_at, meta_json, created_at, updated_at)
            VALUES (?, ?, ?, 'live', ?, NULL, 0, ?, ?, ?, ?)
            """,
            (
                thread_id,
                title,
                topic.strip() or "Agent collaboration",
                json.dumps(participants),
                now if auto_start else None,
                json.dumps(meta),
                now,
                now,
            ),
        )
        _insert_thread_message(
            conn,
            thread_id=thread_id,
            agent_id=None,
            body="Live agent↔agent room. Observer only until an agent invites you.",
            kind="system",
            sender_name="System",
        )
        if auto_start:
            script = _scripted_turns(topic, agents)
            agent_id, body, kind = script[0]
            _insert_thread_message(conn, thread_id=thread_id, agent_id=agent_id, body=body, kind=kind)
            # Seed a few more lines so the room doesn't look empty
            for extra in script[1:4]:
                aid, b, k = extra
                _insert_thread_message(conn, thread_id=thread_id, agent_id=aid, body=b, kind=k)
                if k == "invite":
                    _create_invite_from_message(conn, thread_id=thread_id, agent_id=aid, body=b)
            conn.execute(
                "UPDATE veridiq_live_threads SET turn_index = 4, last_tick_at = ? WHERE thread_id = ?",
                (now, thread_id),
            )
        thread = _get_thread(conn, thread_id)
        messages = _thread_messages(conn, thread_id, limit=40)
    return {"ok": True, "thread": thread, "messages": messages}


def _create_invite_from_message(
    conn: Any,
    *,
    thread_id: str,
    agent_id: str,
    body: str,
    user_id: str = DEFAULT_USER_ID,
) -> dict[str, Any]:
    # Avoid duplicate pending invites for same thread
    existing = conn.execute(
        """
        SELECT * FROM veridiq_hub_invites
        WHERE thread_id = ? AND user_id = ? AND status = 'pending'
        ORDER BY created_at DESC LIMIT 1
        """,
        (thread_id, user_id),
    ).fetchone()
    if existing:
        d = dict(existing)
        d.pop("id", None)
        return d
    invite_id = str(uuid.uuid4())
    now = _utc_iso()
    conn.execute(
        """
        INSERT INTO veridiq_hub_invites
            (invite_id, thread_id, meeting_id, user_id, invited_by_agent, status, message, created_at, responded_at)
        VALUES (?, ?, NULL, ?, ?, 'pending', ?, ?, NULL)
        """,
        (invite_id, thread_id, user_id, agent_id, body.strip()[:500], now),
    )
    return {
        "invite_id": invite_id,
        "thread_id": thread_id,
        "meeting_id": None,
        "user_id": user_id,
        "invited_by_agent": agent_id,
        "status": "pending",
        "message": body.strip()[:500],
        "created_at": now,
        "responded_at": None,
    }


def ensure_live_threads(*, force_new: bool = False) -> list[dict[str, Any]]:
    """Ensure the full swarm of live working rooms exists (~24 threads)."""
    initialize_database()
    with _lock:
        with db_session() as conn:
            rows = conn.execute(
                "SELECT * FROM veridiq_live_threads WHERE status = 'live' ORDER BY created_at ASC LIMIT 120"
            ).fetchall()
            all_threads = [_row_thread(r) for r in rows]
            existing = [t for t in all_threads if not _is_dm_thread(t)]
            existing_keys = {
                (t.get("meta") or {}).get("blueprint_key")
                for t in existing
                if (t.get("meta") or {}).get("blueprint_key")
            }

        if force_new:
            created = create_live_thread(
                topic=THREAD_BLUEPRINTS[0]["topic"],
                agent_types=list(THREAD_BLUEPRINTS[0]["agents"]),
                blueprint_key=THREAD_BLUEPRINTS[0]["key"],
            )
            return [created["thread"]] if created.get("thread") else existing

        if len(existing) >= TARGET_LIVE_THREADS:
            return existing

        # Bootstrap missing blueprints
        for bp in THREAD_BLUEPRINTS:
            if bp["key"] in existing_keys:
                continue
            create_live_thread(
                topic=bp["topic"],
                agent_types=list(bp["agents"]),
                blueprint_key=bp["key"],
            )
            existing_keys.add(bp["key"])

        with db_session() as conn:
            rows = conn.execute(
                "SELECT * FROM veridiq_live_threads WHERE status = 'live' ORDER BY updated_at DESC LIMIT 120"
            ).fetchall()
            return [t for t in (_row_thread(r) for r in rows) if not _is_dm_thread(t)]


def tick_thread(thread_id: str, *, force: bool = False, use_llm: bool = False) -> dict[str, Any]:
    """Advance one agent turn if enough time elapsed."""
    initialize_database()
    acquired = _lock.acquire(blocking=False) if not force else _lock.acquire(blocking=True, timeout=1.5)
    if not acquired:
        return {"ok": True, "ticked": False, "skipped": "busy"}
    try:
        with db_session() as conn:
            thread = _get_thread(conn, thread_id)
            if not thread or thread.get("status") != "live":
                return {"ok": False, "error": "thread_not_live"}
            if _is_dm_thread(thread):
                return {"ok": True, "ticked": False, "skipped": "dm", "thread": thread}
            turn_index = int(thread.get("turn_index") or 0)
            last = thread.get("last_tick_at")
            if last and not force:
                try:
                    last_dt = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
                    if last_dt.tzinfo is None:
                        last_dt = last_dt.replace(tzinfo=timezone.utc)
                    if (_utc_now() - last_dt.astimezone(timezone.utc)).total_seconds() < TICK_INTERVAL_SEC:
                        return {"ok": True, "ticked": False, "thread": thread}
                except ValueError:
                    pass

            agents = [p.get("agent_type") for p in (thread.get("participants") or []) if p.get("agent_type")]
            if not agents:
                agents = ["ceo", "content_creator"]
            topic = thread.get("topic") or "collaboration"
            script = _scripted_turns(topic, agents)

            if turn_index < len(script):
                agent_id, body, kind = script[turn_index]
            else:
                agent_id = agents[turn_index % len(agents)]
                kind = "chat"
                body = work_line_for(agent_id, topic, turn_index)
                if use_llm:
                    llm_text = _llm_turn(agent_id, topic, [{"name": identity_for(agent_id)["name"], "text": body}])
                    if llm_text:
                        body = llm_text

            # Never auto-mint LiveKit invites from swarm ticks — only request_personal_meeting
            if kind == "invite":
                kind = "chat"
                body = work_line_for(agent_id, topic, turn_index)
            msg = _insert_thread_message(conn, thread_id=thread_id, agent_id=agent_id, body=body, kind=kind)

            now = _utc_iso()
            conn.execute(
                "UPDATE veridiq_live_threads SET turn_index = ?, last_tick_at = ?, updated_at = ? WHERE thread_id = ?",
                (turn_index + 1, now, now, thread_id),
            )
            thread = _get_thread(conn, thread_id)
        return {"ok": True, "ticked": True, "message": msg, "thread": thread}
    finally:
        _lock.release()


def tick_all_live(*, force: bool = False, use_llm: bool = False, batch: int = TICK_BATCH) -> dict[str, Any]:
    """Advance a batch of threads (not all) for high-cadence feel without melting DB."""
    global _tick_salt
    threads = ensure_live_threads()
    _tick_salt += 1
    idxs = pick_tick_indices(len(threads), batch=batch, salt=_tick_salt)
    results = []
    for i in idxs:
        tid = threads[i].get("thread_id")
        if tid:
            results.append(tick_thread(tid, force=force, use_llm=use_llm))
    return {"ok": True, "count": len(results), "results": results, "batch": batch}


def list_live_threads(
    *,
    include_messages: bool = False,
    tick: bool = True,
    message_limit: int = 60,
    thread_limit: int = 40,
) -> dict[str, Any]:
    """List live threads; tick a batch; preload only previews unless include_messages."""
    try:
        initialize_database()
        ensure_live_threads()
        if tick:
            tick_all_live(force=False, use_llm=False, batch=TICK_BATCH)
        presence = estimated_agent_presence()
        with db_session() as conn:
            rows = conn.execute(
                """
                SELECT * FROM veridiq_live_threads
                WHERE status IN ('live', 'paused')
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (max(1, min(thread_limit, 80)),),
            ).fetchall()
            threads = []
            agent_ids: set[str] = set()
            for r in rows:
                t = _row_thread(r)
                if _is_dm_thread(t):
                    continue
                for p in t.get("participants") or []:
                    if p.get("agent_type"):
                        agent_ids.add(p["agent_type"])
                if include_messages:
                    msgs = _thread_messages(conn, t["thread_id"], limit=message_limit)
                    t["messages"] = msgs
                    t["message_count"] = len(msgs)
                    t["preview"] = (msgs[-1]["body"] if msgs else "")[:160]
                else:
                    # Light preview: last message only
                    row_m = conn.execute(
                        """
                        SELECT body, sender_name, agent_id, created_at FROM veridiq_live_thread_messages
                        WHERE thread_id = ?
                        ORDER BY id DESC LIMIT 1
                        """,
                        (t["thread_id"],),
                    ).fetchone()
                    if row_m:
                        t["preview"] = str(row_m["body"])[:160]
                        t["preview_sender"] = row_m["sender_name"]
                        t["updated_at"] = t.get("updated_at") or row_m["created_at"]
                    else:
                        t["preview"] = t.get("topic") or ""
                    cnt = conn.execute(
                        "SELECT COUNT(*) AS c FROM veridiq_live_thread_messages WHERE thread_id = ?",
                        (t["thread_id"],),
                    ).fetchone()
                    t["message_count"] = int(cnt["c"] if cnt else 0)
                    t["messages"] = []
                threads.append(t)
            invites = _list_invites_conn(conn, status="pending")
        return {
            "ok": True,
            "count": len(threads),
            "threads": threads,
            "invites": invites,
            "observer_mode": True,
            "user_can_chat": False,
            "user_name": DEFAULT_USER_NAME,
            "swarm": {
                **presence,
                "unique_agents_online": len(agent_ids),
                "live_threads": len(threads),
            },
            "poll_hint_ms": 1000,
        }
    except Exception as exc:
        return {
            "ok": True,
            "count": 0,
            "threads": [],
            "invites": [],
            "observer_mode": True,
            "user_can_chat": False,
            "user_name": DEFAULT_USER_NAME,
            "error": str(exc)[:240],
        }


def _list_invites_conn(
    conn: Any,
    *,
    thread_id: Optional[str] = None,
    user_id: str = DEFAULT_USER_ID,
    status: Optional[str] = None,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM veridiq_hub_invites WHERE user_id = ?"
    params: list[Any] = [user_id]
    if thread_id:
        sql += " AND thread_id = ?"
        params.append(thread_id)
    if status:
        sql += " AND status = ?"
        params.append(status)
    sql += " ORDER BY created_at DESC LIMIT 40"
    rows = conn.execute(sql, params).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d.pop("id", None)
        if d.get("invited_by_agent"):
            d["invited_by"] = _agent_card(d["invited_by_agent"])
        out.append(d)
    return out


def list_invites(*, user_id: str = DEFAULT_USER_ID, status: Optional[str] = None) -> list[dict[str, Any]]:
    initialize_database()
    with db_session() as conn:
        return _list_invites_conn(conn, user_id=user_id, status=status)


def get_live_thread(thread_id: str, *, tick: bool = True) -> Optional[dict[str, Any]]:
    initialize_database()
    with db_session() as conn:
        peek = _get_thread(conn, thread_id)
    is_dm = _is_dm_thread(peek)
    if tick and not is_dm:
        tick_thread(thread_id, force=True, use_llm=False)
    with db_session() as conn:
        thread = _get_thread(conn, thread_id)
        if not thread:
            return None
        if is_dm:
            # Mark read on open
            meta = dict(thread.get("meta") or {})
            meta["last_read_at"] = _utc_iso()
            conn.execute(
                "UPDATE veridiq_live_threads SET meta_json = ?, updated_at = updated_at WHERE thread_id = ?",
                (json.dumps(meta), thread_id),
            )
            thread["meta"] = meta
        messages = _thread_messages(conn, thread_id, limit=200)
        invites = _list_invites_conn(conn, thread_id=thread_id)
        # Marcus DM also surfaces global pending invites for Accept/Decline inline
        if is_dm and _dm_agent_type(thread) == "ai_calling":
            invites = _list_invites_conn(conn, status="pending")
    return {
        "thread": thread,
        "messages": messages,
        "invites": invites,
        "observer_mode": not is_dm,
        "user_can_chat": True if is_dm else False,
        "is_dm": is_dm,
        "dm_agent": _dm_agent_type(thread),
        "user_name": DEFAULT_USER_NAME,
    }


def request_personal_meeting(
    *,
    specialist_query: str,
    topic: Optional[str] = None,
    user_name: str = DEFAULT_USER_NAME,
    user_id: str = DEFAULT_USER_ID,
) -> dict[str, Any]:
    """Calling agent posts a personal-meeting request into the collab hub; specialists approve → invite."""
    initialize_database()
    specialist = resolve_specialist(specialist_query)
    spec = identity_for(specialist)
    caller = identity_for("ai_calling")
    topic_clean = (topic or f"Personal session with {spec['name']}").strip()[:200]

    # Ensure a dedicated request thread
    created = create_live_thread(
        topic=topic_clean,
        agent_types=["ai_calling", "ceo", "director_operations", specialist],
        auto_start=False,
    )
    thread_id = created["thread"]["thread_id"]
    now = _utc_iso()

    with db_session() as conn:
        _insert_thread_message(
            conn,
            thread_id=thread_id,
            agent_id="ai_calling",
            body=(
                f"{caller['name']}: {user_name} asked me to arrange a personal LiveKit meeting "
                f"with {spec['name']} ({spec['role']}) — topic “{topic_clean}”."
            ),
            kind="chat",
        )
        _insert_thread_message(
            conn,
            thread_id=thread_id,
            agent_id="director_operations",
            body=f"{identity_for('director_operations')['name']}: Request received. {spec['name']} — please approve.",
            kind="chat",
        )
        _insert_thread_message(
            conn,
            thread_id=thread_id,
            agent_id=specialist,
            body=(
                f"{spec['name']}: Approved. {user_name}, we want you to join and interact with us — "
                "accept the invite for our personal meeting."
            ),
            kind="invite",
        )
        invite = _create_invite_from_message(
            conn,
            thread_id=thread_id,
            agent_id=specialist,
            body=(
                f"{spec['name']}: {user_name}, we want you to join and interact with us — "
                "accept the invite for our personal meeting."
            ),
            user_id=user_id,
        )
        _insert_thread_message(
            conn,
            thread_id=thread_id,
            agent_id="ceo",
            body=f"{identity_for('ceo')['name']}: Specialist approved. Invite is live for {user_name}.",
            kind="chat",
        )
        conn.execute(
            "UPDATE veridiq_live_threads SET turn_index = 5, last_tick_at = ?, status = 'live', updated_at = ? WHERE thread_id = ?",
            (now, now, thread_id),
        )
        thread = _get_thread(conn, thread_id)
        messages = _thread_messages(conn, thread_id)

    return {
        "ok": True,
        "specialist": _agent_card(specialist),
        "thread": thread,
        "messages": messages,
        "invite": invite,
        "message": (
            f"Posted request in Collaboration Hub. {spec['name']} approved — "
            f"accept the invite to open a personal LiveKit meeting."
        ),
        "links": [
            {"label": "Collaboration Hub", "href": "/dashboard/collaboration"},
            {"label": "AI Calling", "href": "/dashboard/calling"},
        ],
    }


def accept_invite(
    *,
    invite_id: str,
    user_id: str = DEFAULT_USER_ID,
    user_name: str = DEFAULT_USER_NAME,
) -> dict[str, Any]:
    """Accept invite → create/start personal LiveKit meeting with specialist; admit user."""
    from veridiq.calling.livekit_tokens import livekit_configured, livekit_status
    from veridiq.calling.meetings import get_meeting, schedule_meeting

    initialize_database()
    with db_session() as conn:
        row = conn.execute(
            "SELECT * FROM veridiq_hub_invites WHERE invite_id = ? AND user_id = ?",
            (invite_id, user_id),
        ).fetchone()
        if not row:
            return {"ok": False, "error": "unknown_invite"}
        invite = dict(row)
        if invite.get("status") == "accepted" and invite.get("meeting_id"):
            meeting = get_meeting(invite["meeting_id"])
            return {"ok": True, "already_accepted": True, "invite": _invite_public(invite), "meeting": meeting}
        if invite.get("status") not in ("pending", "accepted"):
            return {"ok": False, "error": "invite_not_pending", "status": invite.get("status")}

        thread = _get_thread(conn, invite["thread_id"]) if invite.get("thread_id") else None
        specialist = invite.get("invited_by_agent") or "content_creator"
        agents = ["ai_calling", specialist, "ceo"]
        topic = (thread or {}).get("topic") or f"Personal meeting with {identity_for(specialist)['name']}"

    try:
        from veridiq.calling.meetings import _pkt_now

        pkt_when = (_pkt_now() + timedelta(seconds=30)).strftime("%Y-%m-%dT%H:%M")
    except Exception:
        pkt_when = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M")

    # Avoid nested get_hub / enter_ceo side effects from schedule_meeting where possible:
    # schedule still ensures CEO hub row; keep it for meeting row creation.
    sched = schedule_meeting(
        topic=topic,
        scheduled_at_pkt=pkt_when,
        agenda=["Personal working session", "Iterate content / logo / posts live"],
        agent_types=agents,
    )
    if not sched.get("ok"):
        return {"ok": False, "error": "schedule_failed", "detail": sched}

    meeting = sched["meeting"]
    mid = meeting["meeting_id"]
    now = _utc_iso()
    # Fast path: mark live + admitted without Telegram announce (was causing multi‑minute hangs)
    with db_session() as conn:
        conn.execute(
            """
            UPDATE veridiq_meetings
            SET status = 'live', started_at = ?, join_gate_status = 'admitted', join_requested_at = ?
            WHERE meeting_id = ?
            """,
            (now, now, mid),
        )
        conn.execute(
            """
            UPDATE veridiq_hub_invites
            SET status = 'accepted', meeting_id = ?, responded_at = ?
            WHERE invite_id = ?
            """,
            (mid, now, invite_id),
        )
        if invite.get("thread_id"):
            _insert_thread_message(
                conn,
                thread_id=invite["thread_id"],
                agent_id="ai_calling",
                body=(
                    f"{identity_for('ai_calling')['name']}: {user_name} accepted the invite. "
                    f"Personal meeting ready — open AI Calling to join LiveKit."
                ),
                kind="system",
            )
            conn.execute(
                "UPDATE veridiq_live_threads SET meeting_id = ?, updated_at = ? WHERE thread_id = ?",
                (mid, now, invite["thread_id"]),
            )
        invite_row = conn.execute(
            "SELECT * FROM veridiq_hub_invites WHERE invite_id = ?", (invite_id,)
        ).fetchone()
        invite_out = _invite_public(dict(invite_row)) if invite_row else None

    meeting = get_meeting(mid)
    lk = livekit_status()
    return {
        "ok": True,
        "invite": invite_out,
        "meeting": meeting,
        "start": {
            "ok": livekit_configured(),
            "livekit": lk,
            "message": (
                "Personal meeting live — joining LiveKit video call."
                if livekit_configured()
                else "Meeting reserved — set LiveKit credentials to connect video."
            ),
        },
        # Lobby deep-link only — user must click Join / Meet Marcus (no auto LiveKit connect)
        "join_path": f"/dashboard/calling?meeting={mid}",
        "message": (
            "Invite accepted. Meeting is ready in AI Calling — click Join with Marcus when you want to connect."
        ),
        "livekit": lk,
        "auto_connect": False,
    }


def _invite_public(invite: dict[str, Any]) -> dict[str, Any]:
    d = {k: v for k, v in invite.items() if k != "id"}
    if d.get("invited_by_agent"):
        d["invited_by"] = _agent_card(d["invited_by_agent"])
    return d


def decline_invite(*, invite_id: str, user_id: str = DEFAULT_USER_ID) -> dict[str, Any]:
    initialize_database()
    now = _utc_iso()
    with db_session() as conn:
        row = conn.execute(
            "SELECT * FROM veridiq_hub_invites WHERE invite_id = ? AND user_id = ?",
            (invite_id, user_id),
        ).fetchone()
        if not row:
            return {"ok": False, "error": "unknown_invite"}
        conn.execute(
            "UPDATE veridiq_hub_invites SET status = 'declined', responded_at = ? WHERE invite_id = ?",
            (now, invite_id),
        )
        invite = dict(row)
        if invite.get("thread_id"):
            _insert_thread_message(
                conn,
                thread_id=invite["thread_id"],
                agent_id=None,
                body="User declined the invite. Observer mode continues.",
                kind="system",
            )
    return {"ok": True, "status": "declined"}


def post_meeting_work_chat(
    *,
    meeting_id: str,
    body: str,
    hub_id: str = "default",
) -> dict[str, Any]:
    """User work chat inside an admitted personal meeting (logo/copy changes etc.)."""
    from veridiq.calling.meetings import _insert_message, get_meeting

    text = (body or "").strip()
    if not text:
        return {"ok": False, "error": "empty_message"}
    meeting = get_meeting(meeting_id)
    if not meeting:
        return {"ok": False, "error": "unknown_meeting"}
    if meeting.get("join_gate_status") != "admitted" and meeting.get("status") != "live":
        return {"ok": False, "error": "not_admitted", "message": "Accept an invite and join before chatting with agents."}

    participants = meeting.get("participants") or []
    specialist = None
    for p in participants:
        at = p.get("agent_type")
        if at and at not in ("ceo", "ai_calling", "director_operations", "director_growth"):
            specialist = at
            break
    if not specialist:
        specialist = "content_creator"

    initialize_database()
    with db_session() as conn:
        user_msg = _insert_message(
            conn,
            hub_id=hub_id,
            meeting_id=meeting_id,
            sender_type="user",
            sender_name="You",
            body=text,
        )
        lower = text.lower()
        ident = identity_for(specialist)
        if any(k in lower for k in ("logo", "brand mark", "icon")):
            reply = (
                f"{ident['name']}: Got it — I'll revise the logo placement / mark for this Canva draft. "
                "Confirm colors or aspect ratio if you have a preference."
            )
        elif any(k in lower for k in ("post", "caption", "copy", "text", "headline")):
            reply = (
                f"{ident['name']}: Updating post copy now. I'll keep brand voice and swap the lines you flagged."
            )
        elif any(k in lower for k in ("color", "palette", "font")):
            reply = f"{ident['name']}: Noted design tokens — applying to the daily post layout."
        else:
            llm = _llm_turn(
                specialist,
                f"Personal meeting work chat about {meeting.get('topic')}",
                [{"name": "You", "text": text}],
            )
            reply = llm or (
                f"{ident['name']}: Captured. I'll adjust the working draft and confirm in this meeting."
            )
        agent_msg = _insert_message(
            conn,
            hub_id=hub_id,
            meeting_id=meeting_id,
            sender_type="agent",
            sender_agent=specialist,
            body=reply,
        )
    return {
        "ok": True,
        "message": user_msg,
        "reply": agent_msg,
        "meeting_id": meeting_id,
        "specialist": _agent_card(specialist),
    }


_POST_INTENT_RE = re.compile(
    r"\b("
    r"create\s+(a\s+)?(post|image|video|reel|carousel)|"
    r"draft\s+(a\s+)?(post|caption)|"
    r"make\s+(a\s+|an\s+)?(post|image|video|graphic)|"
    r"post\s+(for|about)|"
    r"generate\s+(a\s+)?(post|image|video)|"
    r"mira\b|"
    r"postings?\b"
    r")\b",
    re.I,
)


def looks_like_postings_command(text: str) -> bool:
    q = (text or "").strip()
    if not q:
        return False
    if _POST_INTENT_RE.search(q):
        return True
    lower = q.lower()
    return any(
        k in lower
        for k in (
            "for my verdiq",
            "for verdiq",
            "for veridiq",
            "create content",
            "social post",
        )
    )


def _find_dm_thread_conn(
    conn: Any,
    agent_type: str,
    *,
    user_id: str = DEFAULT_USER_ID,
) -> Optional[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT * FROM veridiq_live_threads
        WHERE status IN ('live', 'paused')
        ORDER BY updated_at DESC
        LIMIT 200
        """
    ).fetchall()
    for r in rows:
        t = _row_thread(r)
        meta = t.get("meta") or {}
        if meta.get("kind") != "dm":
            continue
        if str(meta.get("dm_agent") or "") != agent_type:
            continue
        if str(meta.get("user_id") or DEFAULT_USER_ID) != user_id:
            continue
        return t
    return None


def ensure_dm_thread(
    agent_type: str,
    *,
    user_id: str = DEFAULT_USER_ID,
    user_name: str = DEFAULT_USER_NAME,
) -> dict[str, Any]:
    """Get or create a dedicated 1:1 DM thread between the user and one agent."""
    initialize_database()
    from veridiq.workforce.identities import AGENT_IDENTITIES

    key = (agent_type or "").strip()
    if key not in AGENT_IDENTITIES:
        # Allow resolve by display name / alias
        key = resolve_specialist(key)
        if key not in AGENT_IDENTITIES and key not in ("ceo", "ai_calling", "posting_studio"):
            # Still try exact identity lookup after resolve
            if key not in AGENT_IDENTITIES:
                key = "ai_calling"

    ident = identity_for(key)
    with _lock:
        with db_session() as conn:
            existing = _find_dm_thread_conn(conn, key, user_id=user_id)
            if existing:
                return {"ok": True, "created": False, "thread": existing, "agent": _agent_card(key)}

            thread_id = str(uuid.uuid4())
            now = _utc_iso()
            title = ident["name"]
            topic = f"DM · {ident['name']}"
            participants = [_agent_card(key)]
            meta = {
                "kind": "dm",
                "dm_agent": key,
                "user_id": user_id,
                "user_name": user_name,
                "last_read_at": now,
            }
            conn.execute(
                """
                INSERT INTO veridiq_live_threads
                    (thread_id, title, topic, status, participants_json, meeting_id,
                     turn_index, last_tick_at, meta_json, created_at, updated_at)
                VALUES (?, ?, ?, 'live', ?, NULL, 0, NULL, ?, ?, ?)
                """,
                (
                    thread_id,
                    title,
                    topic,
                    json.dumps(participants),
                    json.dumps(meta),
                    now,
                    now,
                ),
            )
            greet = {
                "ceo": (
                    f"{ident['name']}: Hi {user_name} — this is your private line to me. "
                    "Ask for workforce direction, director routing, or strategy."
                ),
                "ai_calling": (
                    f"{ident['name']}: Hi {user_name}. Schedule meetings, request specialist calls, "
                    "or say “create a post…” and I’ll route creative work to Mira."
                ),
                "posting_studio": (
                    f"{ident['name']}: Ready when you are — say “create a post for Verdiq …” "
                    "and I’ll draft in Postings from this chat."
                ),
            }.get(
                key,
                f"{ident['name']}: Hi {user_name} — this is our private chat. "
                f"Tell me what you need from your {ident['role']}.",
            )
            _insert_thread_message(
                conn,
                thread_id=thread_id,
                agent_id=key,
                body=greet,
                kind="chat",
                sender_name=ident["name"],
            )
            thread = _get_thread(conn, thread_id)
    return {"ok": True, "created": True, "thread": thread, "agent": _agent_card(key)}


def open_dm(
    agent_type: str,
    *,
    user_id: str = DEFAULT_USER_ID,
    user_name: str = DEFAULT_USER_NAME,
) -> dict[str, Any]:
    """Ensure DM exists and return thread + messages (marks read)."""
    ensured = ensure_dm_thread(agent_type, user_id=user_id, user_name=user_name)
    thread = ensured.get("thread") or {}
    tid = thread.get("thread_id")
    if not tid:
        return {"ok": False, "error": "dm_create_failed"}
    detail = get_live_thread(tid, tick=False)
    if not detail:
        return {"ok": False, "error": "unknown_thread"}
    return {
        "ok": True,
        "created": bool(ensured.get("created")),
        "agent": ensured.get("agent") or _agent_card(agent_type),
        **detail,
    }


def list_agent_dms(
    *,
    user_id: str = DEFAULT_USER_ID,
    user_name: str = DEFAULT_USER_NAME,
    ensure_pinned: bool = True,
) -> dict[str, Any]:
    """List workforce agents as DM contacts (WhatsApp-style). Creates pinned DMs lightly."""
    initialize_database()
    if ensure_pinned:
        for pinned in DM_PINNED_AGENTS[:3]:  # Aurelia, Marcus, Mira — ready on first load
            try:
                ensure_dm_thread(pinned, user_id=user_id, user_name=user_name)
            except Exception:
                pass

    roster = _dm_roster()
    presence = estimated_agent_presence()
    invites = list_invites(user_id=user_id, status="pending")
    contacts: list[dict[str, Any]] = []

    with db_session() as conn:
        for agent_type in roster:
            card = _agent_card(agent_type)
            thread = _find_dm_thread_conn(conn, agent_type, user_id=user_id)
            preview = ""
            preview_sender = ""
            updated_at = ""
            message_count = 0
            unread = 0
            thread_id = None
            status = "online"
            if thread:
                thread_id = thread["thread_id"]
                updated_at = str(thread.get("updated_at") or "")
                meta = thread.get("meta") or {}
                last_read = str(meta.get("last_read_at") or "")
                row_m = conn.execute(
                    """
                    SELECT body, sender_name, agent_id, created_at FROM veridiq_live_thread_messages
                    WHERE thread_id = ?
                    ORDER BY id DESC LIMIT 1
                    """,
                    (thread_id,),
                ).fetchone()
                if row_m:
                    preview = str(row_m["body"])[:160]
                    preview_sender = str(row_m["sender_name"] or "")
                    updated_at = str(row_m["created_at"] or updated_at)
                cnt = conn.execute(
                    "SELECT COUNT(*) AS c FROM veridiq_live_thread_messages WHERE thread_id = ?",
                    (thread_id,),
                ).fetchone()
                message_count = int(cnt["c"] if cnt else 0)
                if last_read:
                    unread_row = conn.execute(
                        """
                        SELECT COUNT(*) AS c FROM veridiq_live_thread_messages
                        WHERE thread_id = ? AND created_at > ?
                          AND (agent_id IS NOT NULL AND agent_id != '')
                          AND COALESCE(sender_name, '') NOT IN (?, 'You')
                        """,
                        (thread_id, last_read, user_name),
                    ).fetchone()
                    unread = int(unread_row["c"] if unread_row else 0)
                # Light "working" cue when agent has recent swarm activity
                if message_count > 1 and preview_sender == card["name"]:
                    status = "working"
            contacts.append(
                {
                    **card,
                    "dm_thread_id": thread_id,
                    "preview": preview,
                    "preview_sender": preview_sender,
                    "updated_at": updated_at,
                    "message_count": message_count,
                    "unread": unread,
                    "status": status,
                }
            )

    # Sort: unread + recent activity first; idle contacts keep pinned order
    pin_rank = {a: i for i, a in enumerate(DM_PINNED_AGENTS)}
    with_activity = [c for c in contacts if c.get("updated_at")]
    without = [c for c in contacts if not c.get("updated_at")]
    with_activity.sort(
        key=lambda c: (-(int(c.get("unread") or 0)), str(c.get("updated_at") or "")),
        reverse=False,
    )
    with_activity.sort(key=lambda c: str(c.get("updated_at") or ""), reverse=True)
    with_activity.sort(key=lambda c: -(int(c.get("unread") or 0)))
    without.sort(key=lambda c: (pin_rank.get(str(c.get("agent_type") or ""), 999), str(c.get("name") or "")))
    contacts = with_activity + without

    return {
        "ok": True,
        "count": len(contacts),
        "agents": contacts,
        "invites": invites,
        "user_name": user_name,
        "user_can_chat": True,
        "observer_mode": False,
        "dm_first": True,
        "swarm": presence,
        "poll_hint_ms": 2500,
    }


def _dm_reply_body(agent_type: str, user_text: str, *, user_name: str = DEFAULT_USER_NAME) -> str:
    ident = identity_for(agent_type)
    llm = _llm_turn(
        agent_type,
        f"1:1 private DM with {user_name}",
        [{"name": user_name or "You", "text": user_text}],
    )
    if llm:
        name = ident["name"]
        return llm if llm.lower().startswith(name.lower()) else f"{name}: {llm}"
    if agent_type == "ai_calling":
        return (
            f"{ident['name']}: Got it. I can schedule a meeting, request a specialist call, "
            "or route creative work — try “schedule a meeting with you” or “create a post…”."
        )
    if agent_type == "posting_studio":
        return (
            f"{ident['name']}: Tell me what to make — e.g. “create a post for Verdiq about …” "
            "and I’ll draft it from this chat."
        )
    if agent_type == "ceo":
        return (
            f"{ident['name']}: Noted, {user_name}. I’ll coordinate directors if you need a "
            "workforce decision — keep messaging me here."
        )
    return (
        f"{ident['name']}: Received. I’ll handle that as your {ident['role']} "
        "and update you in this chat."
    )


def post_collab_user_message(
    *,
    body: str,
    thread_id: Optional[str] = None,
    user_name: str = DEFAULT_USER_NAME,
) -> dict[str, Any]:
    """User compose on Collaboration Hub — DM replies + Mira/postings + meeting intents.

    DM threads reply as the selected agent. Creative intents still bridge to Mira.
    """
    from veridiq.calling.collab_postings_bridge import handoff_collab_to_postings

    text = (body or "").strip()
    if not text:
        return {"ok": False, "error": "empty_message", "message": "Message required."}

    initialize_database()

    tid = (thread_id or "").strip()
    thread: Optional[dict[str, Any]] = None
    if tid:
        with db_session() as conn:
            thread = _get_thread(conn, tid)
    if not tid or not thread:
        ensured = ensure_dm_thread("ai_calling", user_name=user_name)
        tid = ensured["thread"]["thread_id"]
        thread = ensured["thread"]

    is_dm = _is_dm_thread(thread)
    dm_agent = _dm_agent_type(thread) or "ai_calling"

    with db_session() as conn:
        user_msg = _insert_thread_message(
            conn,
            thread_id=tid,
            agent_id=None,
            body=text,
            kind="chat",
            sender_name=user_name or "You",
        )

    # Agent-to-agent schedule / approve / external Meet proxy (before Mira routing)
    try:
        from veridiq.calling.agent_meetings import handle_hub_meeting_intents

        meet_hit = handle_hub_meeting_intents(text=text, thread_id=tid)
    except Exception:
        meet_hit = None
    if meet_hit and meet_hit.get("ok") is not False and meet_hit.get("routed"):
        routed = meet_hit.get("routed")
        reply_body = meet_hit.get("message") or "Agent meeting update posted."
        reply_agent = dm_agent if is_dm else "ai_calling"
        with db_session() as conn:
            agent_msg = _insert_thread_message(
                conn,
                thread_id=tid,
                agent_id=reply_agent,
                body=f"{identity_for(reply_agent)['name']}: {reply_body}",
                kind="system",
                sender_name=identity_for(reply_agent)["name"],
            )
            conn.execute(
                "UPDATE veridiq_live_threads SET updated_at = ? WHERE thread_id = ?",
                (_utc_iso(), tid),
            )
        return {
            "ok": True,
            "routed": routed,
            "thread_id": tid,
            "message": user_msg,
            "reply": agent_msg,
            "agent_meeting": meet_hit,
            "is_dm": is_dm,
            "links": [
                {"label": "Watch live", "href": meet_hit.get("watch_path") or "/dashboard/calling"},
                {"label": "AI Calling", "href": "/dashboard/calling"},
            ],
        }

    postings_result: Optional[dict[str, Any]] = None
    # Creative intents work in Mira's DM or any agent DM / room
    if looks_like_postings_command(text) or (is_dm and dm_agent == "posting_studio"):
        if looks_like_postings_command(text) or dm_agent == "posting_studio":
            # Only hand off when it looks creative OR we're already in Mira DM with work-ish text
            should_handoff = looks_like_postings_command(text) or (
                dm_agent == "posting_studio"
                and any(
                    k in text.lower()
                    for k in ("post", "image", "video", "design", "caption", "create", "draft", "make")
                )
            )
            if should_handoff and looks_like_postings_command(text):
                postings_result = handoff_collab_to_postings(message=text, thread_id=tid)
                mira_body = (postings_result.get("reply_text") or postings_result.get("message") or "").strip()
                if not mira_body:
                    mira_body = (
                        "Mira (Postings): Got your request — open Postings Studio if media is still rendering."
                    )
                with db_session() as conn:
                    agent_msg = _insert_thread_message(
                        conn,
                        thread_id=tid,
                        agent_id="posting_studio" if is_dm and dm_agent == "posting_studio" else "content_creator",
                        body=mira_body,
                        kind="chat",
                        sender_name="Mira",
                    )
                    conn.execute(
                        "UPDATE veridiq_live_threads SET updated_at = ? WHERE thread_id = ?",
                        (_utc_iso(), tid),
                    )
                return {
                    "ok": True,
                    "routed": "postings",
                    "thread_id": tid,
                    "message": user_msg,
                    "reply": agent_msg,
                    "postings": postings_result,
                    "is_dm": is_dm,
                    "links": [
                        {"label": "Open in Postings", "href": "/dashboard/postings"},
                        {"label": "AI Calling", "href": "/dashboard/calling"},
                    ],
                }

    if is_dm:
        reply_text = _dm_reply_body(dm_agent, text, user_name=user_name)
        with db_session() as conn:
            agent_msg = _insert_thread_message(
                conn,
                thread_id=tid,
                agent_id=dm_agent,
                body=reply_text,
                kind="chat",
                sender_name=identity_for(dm_agent)["name"],
            )
            conn.execute(
                "UPDATE veridiq_live_threads SET updated_at = ? WHERE thread_id = ?",
                (_utc_iso(), tid),
            )
        return {
            "ok": True,
            "routed": "dm",
            "thread_id": tid,
            "message": user_msg,
            "reply": agent_msg,
            "is_dm": True,
            "dm_agent": dm_agent,
            "links": [
                {"label": "AI Calling", "href": "/dashboard/calling"},
                {"label": "Postings Studio", "href": "/dashboard/postings"},
            ],
        }

    # Legacy swarm room compose — short guide (rooms are observe-oriented)
    guide = (
        f"{identity_for('ai_calling')['name']}: Working rooms are observe-first. "
        "Open an agent’s personal chat from the left (Aurelia, Marcus, Mira, …) to talk 1:1. "
        "For creative work, say e.g. “create a post for my Verdiq …”."
    )
    with db_session() as conn:
        agent_msg = _insert_thread_message(
            conn,
            thread_id=tid,
            agent_id="ai_calling",
            body=guide,
            kind="system",
            sender_name=identity_for("ai_calling")["name"],
        )
        conn.execute(
            "UPDATE veridiq_live_threads SET updated_at = ? WHERE thread_id = ?",
            (_utc_iso(), tid),
        )
    return {
        "ok": True,
        "routed": "guide",
        "thread_id": tid,
        "message": user_msg,
        "reply": agent_msg,
        "is_dm": False,
        "links": [
            {"label": "AI Calling", "href": "/dashboard/calling"},
            {"label": "Postings Studio", "href": "/dashboard/postings"},
        ],
    }


def start_background_ticker() -> None:
    """Optional daemon: tick live threads periodically."""
    global _bg_started
    with _lock:
        if _bg_started:
            return
        _bg_started = True

    def _loop() -> None:
        import os
        import time

        while True:
            try:
                ensure_live_threads()
                # Occasional LLM enrichment off the request path (won't block hub GET)
                use_llm = os.getenv("VERIDIQ_LIVE_HUB_LLM", "1").strip() not in ("0", "false", "no")
                tick_all_live(force=False, use_llm=use_llm)
            except Exception:
                pass
            time.sleep(TICK_INTERVAL_SEC)

    t = threading.Thread(target=_loop, name="veridiq-live-hub", daemon=True)
    t.start()


def extract_meeting_request(message: str) -> Optional[dict[str, str]]:
    """Detect calling-agent phrases that request a personal specialist meeting."""
    q = (message or "").strip()
    if not q:
        return None
    lower = q.lower()
    markers = (
        "arrange",
        "schedule",
        "set up",
        "setup",
        "book",
        "personal meeting",
        "meet with",
        "meeting with",
        "talk to",
        "speak with",
        "connect me",
        "introduce me",
    )
    if not any(m in lower for m in markers):
        # also: "canva agent" + meeting-ish
        if not re.search(r"\b(canva|daily posts?|social poster|content creator|lena|jasper)\b", lower):
            return None
        if not any(w in lower for w in ("meet", "call", "session", "join", "talk", "discuss")):
            return None
    specialist_query = q
    return {"specialist_query": specialist_query, "topic": q[:200]}
