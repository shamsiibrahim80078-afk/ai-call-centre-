"""Persistent Mira Postings chats — SQLite threads + messages with media URLs.

Does not alter mira_engine generation; wraps conversation state around studio
commands so navigating away from Postings keeps history and artifacts.
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

DEFAULT_TITLE = "New chat"
TITLE_MAX = 72


def _utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex[:16]


def _title_from_prompt(text: str) -> str:
    raw = " ".join((text or "").strip().split())
    if not raw:
        return DEFAULT_TITLE
    if len(raw) <= TITLE_MAX:
        return raw
    return raw[: TITLE_MAX - 1].rstrip() + "…"


def media_urls_from_action(action: Any) -> dict[str, Optional[str]]:
    """Pull image/video/audio URLs from a studio action dict."""
    if not isinstance(action, dict):
        return {"image_url": None, "video_url": None, "audio_url": None}
    image = action.get("image") if isinstance(action.get("image"), dict) else {}
    render = action.get("render") if isinstance(action.get("render"), dict) else {}
    song = action.get("song") if isinstance(action.get("song"), dict) else {}
    image_url = action.get("image_url") or image.get("image_url") or None
    video_url = (
        render.get("video_url")
        or action.get("video_url")
        or action.get("url")
        or None
    )
    # Absolute path fallback → public file URL
    if not video_url:
        abs_path = render.get("absolute_path") or action.get("absolute_path")
        if abs_path:
            try:
                from pathlib import Path

                name = Path(str(abs_path)).name
                if name:
                    video_url = f"/api/v1/veridiq/marketing/video/file/{name}"
            except Exception:
                pass
    audio_url = action.get("audio_url") or song.get("audio_url") or render.get("audio_url") or None
    return {
        "image_url": str(image_url) if image_url else None,
        "video_url": str(video_url) if video_url else None,
        "audio_url": str(audio_url) if audio_url else None,
    }


def _row_chat(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "chat_id": row["chat_id"],
        "title": row["title"] or DEFAULT_TITLE,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _row_message(row: sqlite3.Row) -> dict[str, Any]:
    meta_raw = row["meta_json"]
    meta: Any = None
    if meta_raw:
        try:
            meta = json.loads(meta_raw)
        except Exception:
            meta = None
    return {
        "message_id": row["message_id"],
        "chat_id": row["chat_id"],
        "role": row["role"],
        "text": row["text"] or "",
        "image_url": row["image_url"],
        "video_url": row["video_url"],
        "audio_url": row["audio_url"],
        "meta": meta,
        "created_at": row["created_at"],
    }


def create_chat(*, title: str = "", user_id: str = "default") -> dict[str, Any]:
    """Create an empty Mira chat thread."""
    initialize_database()
    chat_id = _new_id()
    now = _utc_iso()
    clean_title = _title_from_prompt(title) if (title or "").strip() else DEFAULT_TITLE
    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO veridiq_postings_chats
                (chat_id, title, user_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (chat_id, clean_title, user_id or "default", now, now),
        )
    return {
        "ok": True,
        "chat_id": chat_id,
        "title": clean_title,
        "created_at": now,
        "updated_at": now,
        "messages": [],
    }


def list_chats(*, limit: int = 80, user_id: str = "default") -> dict[str, Any]:
    """List chats newest-first (title + timestamps, no message bodies)."""
    initialize_database()
    lim = max(1, min(int(limit or 80), 200))
    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT chat_id, title, created_at, updated_at
            FROM veridiq_postings_chats
            WHERE user_id = ?
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (user_id or "default", lim),
        ).fetchall()
    chats = [_row_chat(r) for r in rows]
    return {"ok": True, "chats": chats, "count": len(chats)}


def get_chat(chat_id: str) -> dict[str, Any]:
    """Full chat with messages (including media URLs)."""
    initialize_database()
    cid = (chat_id or "").strip()
    if not cid:
        return {"ok": False, "error": "chat_id required"}
    with db_session() as conn:
        row = conn.execute(
            "SELECT * FROM veridiq_postings_chats WHERE chat_id = ?",
            (cid,),
        ).fetchone()
        if not row:
            return {"ok": False, "error": "not_found", "chat_id": cid}
        msgs = conn.execute(
            """
            SELECT * FROM veridiq_postings_chat_messages
            WHERE chat_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (cid,),
        ).fetchall()
    chat = _row_chat(row)
    messages = [_row_message(m) for m in msgs]
    return {"ok": True, **chat, "messages": messages, "count": len(messages)}


def delete_chat(chat_id: str) -> dict[str, Any]:
    """Delete a chat and its messages."""
    initialize_database()
    cid = (chat_id or "").strip()
    if not cid:
        return {"ok": False, "error": "chat_id required"}
    with db_session() as conn:
        exists = conn.execute(
            "SELECT 1 FROM veridiq_postings_chats WHERE chat_id = ?",
            (cid,),
        ).fetchone()
        if not exists:
            return {"ok": False, "error": "not_found", "chat_id": cid}
        conn.execute(
            "DELETE FROM veridiq_postings_chat_messages WHERE chat_id = ?",
            (cid,),
        )
        conn.execute(
            "DELETE FROM veridiq_postings_chats WHERE chat_id = ?",
            (cid,),
        )
    return {"ok": True, "deleted": True, "chat_id": cid}


def append_message(
    chat_id: str,
    *,
    role: str,
    text: str = "",
    image_url: Optional[str] = None,
    video_url: Optional[str] = None,
    audio_url: Optional[str] = None,
    meta: Any = None,
    set_title_from_text: bool = False,
) -> dict[str, Any]:
    """Append one message to a chat; bump updated_at; optionally set title."""
    initialize_database()
    cid = (chat_id or "").strip()
    if not cid:
        return {"ok": False, "error": "chat_id required"}
    role_clean = (role or "").strip().lower()
    if role_clean in ("agent", "mira", "bot"):
        role_clean = "assistant"
    if role_clean not in ("user", "assistant", "system"):
        return {"ok": False, "error": f"invalid role: {role}"}

    message_id = _new_id()
    now = _utc_iso()
    meta_json = None
    if meta is not None:
        try:
            meta_json = json.dumps(meta, default=str)
        except Exception:
            meta_json = json.dumps({"raw": str(meta)[:2000]})

    with db_session() as conn:
        row = conn.execute(
            "SELECT chat_id, title FROM veridiq_postings_chats WHERE chat_id = ?",
            (cid,),
        ).fetchone()
        if not row:
            return {"ok": False, "error": "not_found", "chat_id": cid}

        conn.execute(
            """
            INSERT INTO veridiq_postings_chat_messages
                (message_id, chat_id, role, text, image_url, video_url, audio_url, meta_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message_id,
                cid,
                role_clean,
                text or "",
                image_url,
                video_url,
                audio_url,
                meta_json,
                now,
            ),
        )
        new_title = None
        if (
            set_title_from_text
            and role_clean == "user"
            and (text or "").strip()
            and (row["title"] or DEFAULT_TITLE) == DEFAULT_TITLE
        ):
            new_title = _title_from_prompt(text)
            conn.execute(
                """
                UPDATE veridiq_postings_chats
                SET title = ?, updated_at = ?
                WHERE chat_id = ?
                """,
                (new_title, now, cid),
            )
        else:
            conn.execute(
                "UPDATE veridiq_postings_chats SET updated_at = ? WHERE chat_id = ?",
                (now, cid),
            )

    out: dict[str, Any] = {
        "ok": True,
        "message": {
            "message_id": message_id,
            "chat_id": cid,
            "role": role_clean,
            "text": text or "",
            "image_url": image_url,
            "video_url": video_url,
            "audio_url": audio_url,
            "meta": meta,
            "created_at": now,
        },
        "updated_at": now,
    }
    if new_title:
        out["title"] = new_title
    return out


def append_turn_from_agent_result(
    chat_id: str,
    *,
    user_text: str,
    result: dict[str, Any],
    skip_user: bool = False,
) -> dict[str, Any]:
    """Persist user + assistant messages from a studio handle_command result.

    For async video (status started), stores an interim assistant note;
    final media is appended later via ``append_assistant_from_action``.
    """
    cid = (chat_id or "").strip()
    if not cid:
        return {"ok": False, "error": "chat_id required"}

    saved: list[dict[str, Any]] = []
    if not skip_user:
        u = append_message(
            cid,
            role="user",
            text=user_text or "",
            set_title_from_text=True,
        )
        if not u.get("ok"):
            return u
        saved.append(u["message"])

    action = result.get("action") if isinstance(result, dict) else None
    action = action if isinstance(action, dict) else {}
    reply = ""
    if isinstance(result, dict):
        reply = str(result.get("reply") or action.get("message") or "").strip()
    if not reply:
        reply = "Done."

    media = media_urls_from_action(action)
    # Async kickoff — no final media yet
    started = (
        result.get("status") == "started"
        or action.get("status") == "started"
        or bool(result.get("job_id") or action.get("job_id"))
    ) and not (media.get("video_url") or media.get("image_url"))

    a = append_message(
        cid,
        role="assistant",
        text=reply,
        image_url=None if started else media.get("image_url"),
        video_url=None if started else media.get("video_url"),
        audio_url=None if started else media.get("audio_url"),
        meta=action or result,
    )
    if not a.get("ok"):
        return {**a, "saved": saved}
    saved.append(a["message"])
    get = get_chat(cid)
    title_out = get.get("title") if get.get("ok") else None
    return {
        "ok": True,
        "chat_id": cid,
        "title": title_out,
        "saved": saved,
        "async_started": bool(started),
    }


def append_assistant_from_action(
    chat_id: str,
    *,
    reply: str = "",
    action: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Append a final assistant message (e.g. after video job completes)."""
    act = action if isinstance(action, dict) else {}
    media = media_urls_from_action(act)
    text = (reply or act.get("message") or "Ready.").strip()
    return append_message(
        chat_id,
        role="assistant",
        text=text,
        image_url=media.get("image_url"),
        video_url=media.get("video_url"),
        audio_url=media.get("audio_url"),
        meta=act or None,
    )


def history_for_agent(chat_id: str, *, limit: int = 8) -> list[dict[str, Any]]:
    """Last N user/assistant turns shaped for studio.handle_command history."""
    data = get_chat(chat_id)
    if not data.get("ok"):
        return []
    out: list[dict[str, Any]] = []
    for m in data.get("messages") or []:
        role = m.get("role")
        if role not in ("user", "assistant"):
            continue
        item: dict[str, Any] = {
            "role": role,
            "text": m.get("text") or "",
        }
        if m.get("audio_url"):
            item["audio_url"] = m["audio_url"]
        out.append(item)
    return out[-max(1, min(int(limit or 8), 40)) :]
