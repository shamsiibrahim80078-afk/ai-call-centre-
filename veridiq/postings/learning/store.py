"""SQLite persistence for Mira feedback ratings and brand reference assets."""

from __future__ import annotations

import json
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from database import db_session, initialize_database  # noqa: E402

REF_DIR = _ROOT / "marketing_out" / "references"
PUBLIC_REF_PREFIX = "/api/v1/veridiq/marketing/reference/file"


def _utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _new_id(prefix: str = "fb") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def ensure_ref_dir() -> Path:
    REF_DIR.mkdir(parents=True, exist_ok=True)
    return REF_DIR


def ensure_learning_tables(conn: Optional[sqlite3.Connection] = None) -> None:
    """Idempotent CREATE for feedback + reference tables (also in SCHEMA_SQL)."""
    ddl = """
    CREATE TABLE IF NOT EXISTS veridiq_postings_feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        feedback_id TEXT NOT NULL UNIQUE,
        prompt TEXT NOT NULL DEFAULT '',
        style TEXT NOT NULL DEFAULT '',
        media_url TEXT NOT NULL DEFAULT '',
        media_type TEXT NOT NULL DEFAULT 'image',
        rating INTEGER NOT NULL,
        chat_id TEXT,
        topic TEXT NOT NULL DEFAULT '',
        notes TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_postings_feedback_rating
        ON veridiq_postings_feedback(rating, created_at);
    CREATE INDEX IF NOT EXISTS idx_postings_feedback_chat
        ON veridiq_postings_feedback(chat_id);

    CREATE TABLE IF NOT EXISTS veridiq_postings_references (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ref_id TEXT NOT NULL UNIQUE,
        source TEXT NOT NULL DEFAULT 'upload',
        filename TEXT,
        path TEXT,
        url TEXT,
        topic TEXT NOT NULL DEFAULT '',
        tags_json TEXT,
        license TEXT NOT NULL DEFAULT 'user_upload',
        attribution TEXT,
        description TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_postings_refs_topic
        ON veridiq_postings_references(topic, created_at);
    """
    if conn is not None:
        conn.executescript(ddl)
        return
    initialize_database()
    with db_session() as c:
        c.executescript(ddl)


def _clamp_rating(rating: int) -> int:
    try:
        r = int(rating)
    except (TypeError, ValueError):
        r = 0
    return max(1, min(5, r))


def record_feedback(
    *,
    prompt: str = "",
    style: str = "",
    media_url: str = "",
    rating: int,
    chat_id: Optional[str] = None,
    media_type: str = "image",
    topic: str = "",
    notes: Optional[str] = None,
    thumbs: Optional[str] = None,
) -> dict[str, Any]:
    """Store a rating. ``thumbs`` may be 'up'/'down' (maps to 5/1). Rating is 1–5."""
    ensure_learning_tables()
    if thumbs is not None:
        t = str(thumbs).strip().lower()
        if t in ("up", "like", "👍", "+1", "good"):
            rating = 5
        elif t in ("down", "dislike", "👎", "-1", "bad"):
            rating = 1
    rating = _clamp_rating(rating)
    fid = _new_id("fb")
    now = _utc_iso()
    prompt_s = (prompt or "")[:2000]
    topic_s = (topic or prompt_s)[:400]
    style_s = (style or "")[:120]
    media = (media_url or "")[:800]
    mtype = (media_type or "image").strip().lower()[:32] or "image"
    chat = (chat_id or "").strip()[:64] or None
    note = (notes or "")[:500] if notes else None

    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO veridiq_postings_feedback
                (feedback_id, prompt, style, media_url, media_type, rating,
                 chat_id, topic, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (fid, prompt_s, style_s, media, mtype, rating, chat, topic_s, note, now),
        )
    # Refresh lightweight adapter config after each rating
    try:
        from veridiq.postings.learning.quality import rebuild_learning_config

        rebuild_learning_config()
    except Exception:
        pass
    return {
        "ok": True,
        "feedback_id": fid,
        "rating": rating,
        "created_at": now,
        "message": "Thanks — Mira will bias future prompts toward what you like.",
    }


def list_feedback(
    *,
    min_rating: int = 1,
    limit: int = 100,
    chat_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    ensure_learning_tables()
    limit = max(1, min(500, int(limit)))
    min_rating = max(1, min(5, int(min_rating)))
    with db_session() as conn:
        if chat_id:
            rows = conn.execute(
                """
                SELECT * FROM veridiq_postings_feedback
                WHERE rating >= ? AND chat_id = ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (min_rating, chat_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM veridiq_postings_feedback
                WHERE rating >= ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (min_rating, limit),
            ).fetchall()
    return [_row_feedback(r) for r in rows]


def top_rated_feedback(*, limit: int = 50) -> list[dict[str, Any]]:
    """High-rated examples for similarity retrieval (rating >= 4)."""
    ensure_learning_tables()
    limit = max(1, min(200, int(limit)))
    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT * FROM veridiq_postings_feedback
            WHERE rating >= 4
            ORDER BY rating DESC, created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [_row_feedback(r) for r in rows]


def downvoted_feedback(*, limit: int = 40) -> list[dict[str, Any]]:
    ensure_learning_tables()
    limit = max(1, min(200, int(limit)))
    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT * FROM veridiq_postings_feedback
            WHERE rating <= 2
            ORDER BY rating ASC, created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [_row_feedback(r) for r in rows]


def feedback_count() -> int:
    ensure_learning_tables()
    with db_session() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM veridiq_postings_feedback"
        ).fetchone()
    return int(row["n"] if row else 0)


def _row_feedback(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "feedback_id": row["feedback_id"],
        "prompt": row["prompt"] or "",
        "style": row["style"] or "",
        "media_url": row["media_url"] or "",
        "media_type": row["media_type"] or "image",
        "rating": int(row["rating"]),
        "chat_id": row["chat_id"],
        "topic": row["topic"] or "",
        "notes": row["notes"],
        "created_at": row["created_at"],
    }


def register_brand_reference(
    *,
    path: Optional[str] = None,
    url: Optional[str] = None,
    filename: Optional[str] = None,
    topic: str = "",
    tags: Optional[list[str]] = None,
    source: str = "upload",
    license: str = "user_upload",
    attribution: Optional[str] = None,
    description: Optional[str] = None,
    copy_into_references: bool = True,
) -> dict[str, Any]:
    """Index a lasting brand/reference asset (user upload or free-licensed fetch)."""
    ensure_learning_tables()
    ensure_ref_dir()
    rid = _new_id("ref")
    now = _utc_iso()
    src = (source or "upload").strip().lower()[:40]
    lic = (license or "user_upload").strip()[:80]
    topic_s = (topic or "")[:400]
    tags_json = json.dumps(list(tags or [])[:20])
    dest_path: Optional[str] = None
    dest_name: Optional[str] = filename
    dest_url = url

    if path and copy_into_references:
        src_path = Path(path)
        if src_path.is_file():
            ext = src_path.suffix.lower() or ".png"
            dest_name = dest_name or f"ref_{uuid.uuid4().hex[:10]}{ext}"
            dest = REF_DIR / dest_name
            try:
                dest.write_bytes(src_path.read_bytes())
                dest_path = str(dest)
                dest_url = f"{PUBLIC_REF_PREFIX}/{dest_name}"
            except OSError:
                dest_path = str(src_path)
                dest_name = src_path.name
    elif path:
        dest_path = path
        dest_name = dest_name or Path(path).name

    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO veridiq_postings_references
                (ref_id, source, filename, path, url, topic, tags_json,
                 license, attribution, description, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rid,
                src,
                dest_name,
                dest_path,
                dest_url,
                topic_s,
                tags_json,
                lic,
                (attribution or "")[:300] or None,
                (description or "")[:800] or None,
                now,
            ),
        )
    return {
        "ok": True,
        "ref_id": rid,
        "filename": dest_name,
        "path": dest_path,
        "url": dest_url,
        "topic": topic_s,
        "source": src,
        "license": lic,
        "created_at": now,
    }


def list_references(
    *,
    topic: Optional[str] = None,
    limit: int = 40,
) -> list[dict[str, Any]]:
    ensure_learning_tables()
    limit = max(1, min(200, int(limit)))
    with db_session() as conn:
        if topic and topic.strip():
            like = f"%{topic.strip()[:80]}%"
            rows = conn.execute(
                """
                SELECT * FROM veridiq_postings_references
                WHERE topic LIKE ? OR description LIKE ? OR tags_json LIKE ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (like, like, like, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM veridiq_postings_references
                ORDER BY created_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
    return [_row_ref(r) for r in rows]


def reference_count() -> int:
    ensure_learning_tables()
    with db_session() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM veridiq_postings_references"
        ).fetchone()
    return int(row["n"] if row else 0)


def _row_ref(row: sqlite3.Row) -> dict[str, Any]:
    tags: list[str] = []
    raw = row["tags_json"]
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                tags = [str(t) for t in parsed]
        except json.JSONDecodeError:
            pass
    return {
        "ref_id": row["ref_id"],
        "source": row["source"] or "upload",
        "filename": row["filename"],
        "path": row["path"],
        "url": row["url"],
        "topic": row["topic"] or "",
        "tags": tags,
        "license": row["license"] or "",
        "attribution": row["attribution"],
        "description": row["description"],
        "created_at": row["created_at"],
    }
