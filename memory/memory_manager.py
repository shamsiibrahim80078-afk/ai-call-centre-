"""
Memory Manager — SQLite-backed persistent agent memory store.
CRUD + tag/key search against the agent_memory table in sovereign_swarm_core.db.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from database import db_session, initialize_database  # noqa: E402


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _serialize_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, default=str)


def _deserialize_value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw


class MemoryManager:
    """Production memory store scoped by agent UUID (or shared namespace)."""

    def __init__(self, default_agent_uuid: str = "system") -> None:
        if not default_agent_uuid or not default_agent_uuid.strip():
            raise ValueError("default_agent_uuid is required.")
        self.default_agent_uuid = default_agent_uuid.strip()
        initialize_database()

    def save_memory(
        self,
        key: str,
        value: Any,
        *,
        agent_uuid: Optional[str] = None,
        tags: Optional[list[str] | str] = None,
    ) -> dict[str, Any]:
        """Insert or update a memory entry. Returns the persisted row."""
        if not key or not str(key).strip():
            raise ValueError("memory key is required.")

        owner = (agent_uuid or self.default_agent_uuid).strip()
        memory_key = str(key).strip()
        memory_value = _serialize_value(value)
        if isinstance(tags, list):
            tag_str = ",".join(t.strip() for t in tags if t and str(t).strip())
        elif isinstance(tags, str):
            tag_str = tags.strip()
        else:
            tag_str = None

        stamped = _utc_now_iso()
        with db_session() as conn:
            existing = conn.execute(
                """
                SELECT id, created_at FROM agent_memory
                WHERE agent_uuid = ? AND memory_key = ?
                """,
                (owner, memory_key),
            ).fetchone()

            if existing:
                conn.execute(
                    """
                    UPDATE agent_memory
                    SET memory_value = ?, tags = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (memory_value, tag_str, stamped, int(existing["id"])),
                )
                row_id = int(existing["id"])
                created_at = existing["created_at"]
            else:
                cur = conn.execute(
                    """
                    INSERT INTO agent_memory
                        (agent_uuid, memory_key, memory_value, tags, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (owner, memory_key, memory_value, tag_str, stamped, stamped),
                )
                row_id = int(cur.lastrowid)
                created_at = stamped

            row = conn.execute(
                "SELECT * FROM agent_memory WHERE id = ?",
                (row_id,),
            ).fetchone()

        result = dict(row)
        result["value"] = _deserialize_value(result.pop("memory_value"))
        result["key"] = result.pop("memory_key")
        result["created_at"] = created_at
        return result

    def load_memory(
        self,
        key: str,
        *,
        agent_uuid: Optional[str] = None,
        default: Any = None,
    ) -> Any:
        """Load a memory value by key. Returns default if missing."""
        if not key or not str(key).strip():
            raise ValueError("memory key is required.")
        owner = (agent_uuid or self.default_agent_uuid).strip()
        with db_session() as conn:
            row = conn.execute(
                """
                SELECT memory_value FROM agent_memory
                WHERE agent_uuid = ? AND memory_key = ?
                """,
                (owner, str(key).strip()),
            ).fetchone()
        if row is None:
            return default
        return _deserialize_value(row["memory_value"])

    def delete_memory(
        self,
        key: str,
        *,
        agent_uuid: Optional[str] = None,
    ) -> bool:
        """Delete a memory entry. Returns True if a row was removed."""
        if not key or not str(key).strip():
            raise ValueError("memory key is required.")
        owner = (agent_uuid or self.default_agent_uuid).strip()
        with db_session() as conn:
            cur = conn.execute(
                """
                DELETE FROM agent_memory
                WHERE agent_uuid = ? AND memory_key = ?
                """,
                (owner, str(key).strip()),
            )
            return cur.rowcount > 0

    def search_memory(
        self,
        *,
        agent_uuid: Optional[str] = None,
        query: Optional[str] = None,
        tag: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        Search memories by optional agent scope, key/value substring, and/or tag.
        """
        if limit < 1:
            raise ValueError("limit must be >= 1.")

        clauses: list[str] = []
        params: list[Any] = []

        if agent_uuid:
            clauses.append("agent_uuid = ?")
            params.append(agent_uuid.strip())

        if query:
            clauses.append("(memory_key LIKE ? OR memory_value LIKE ?)")
            pattern = f"%{query.strip()}%"
            params.extend([pattern, pattern])

        if tag:
            clauses.append("(tags = ? OR tags LIKE ? OR tags LIKE ? OR tags LIKE ?)")
            t = tag.strip()
            params.extend([t, f"{t},%", f"%,{t}", f"%,{t},%"])

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"""
            SELECT id, agent_uuid, memory_key, memory_value, tags, created_at, updated_at
            FROM agent_memory
            {where}
            ORDER BY updated_at DESC
            LIMIT ?
        """
        params.append(int(limit))

        with db_session() as conn:
            rows = conn.execute(sql, params).fetchall()

        results: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["key"] = item.pop("memory_key")
            item["value"] = _deserialize_value(item.pop("memory_value"))
            results.append(item)
        return results


def _self_test() -> None:
    print("=" * 60)
    print("MEMORY MANAGER — SELF-TEST")
    print("=" * 60)

    initialize_database()
    mm = MemoryManager(default_agent_uuid="memory-test-agent")
    print("[OK] MemoryManager initialized + DB connected")

    saved = mm.save_memory(
        "lead_profile",
        {"business": "Acme", "score": 92},
        tags=["leads", "priority"],
    )
    assert saved["key"] == "lead_profile"
    assert saved["value"]["score"] == 92
    print(f"[OK] save_memory id={saved['id']}")

    loaded = mm.load_memory("lead_profile")
    assert loaded["business"] == "Acme"
    print("[OK] load_memory")

    updated = mm.save_memory(
        "lead_profile",
        {"business": "Acme", "score": 97},
        tags=["leads", "priority", "hot"],
    )
    assert updated["value"]["score"] == 97
    print("[OK] save_memory upsert")

    mm.save_memory("market_note", "Base network expansion", tags=["market"])
    hits = mm.search_memory(query="Acme")
    assert any(h["key"] == "lead_profile" for h in hits)
    print(f"[OK] search_memory query hits={len(hits)}")

    tag_hits = mm.search_memory(tag="market")
    assert any(h["key"] == "market_note" for h in tag_hits)
    print(f"[OK] search_memory tag hits={len(tag_hits)}")

    deleted = mm.delete_memory("market_note")
    assert deleted is True
    assert mm.load_memory("market_note", default=None) is None
    print("[OK] delete_memory")

    print("=" * 60)
    print("MEMORY MANAGER SELF-TEST: PASSED")
    print("=" * 60)


if __name__ == "__main__":
    _self_test()
