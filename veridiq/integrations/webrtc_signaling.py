"""WebRTC signaling — internal VERIDIQ rooms for voice/agent WebRTC sessions.

Does not place PSTN calls. Twilio Voice remains the approval-gated dialer.
This module stores SDP offers/answers so calling agents and browser clients
can negotiate peer connections through VERIDIQ APIs.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from database import db_session, initialize_database
from veridiq.integrations.base import status_shape

ENV_VARS: list[str] = []
CAPABILITIES = ["create_room", "create_offer", "create_answer", "list_signals"]
DOCS = "/api/v1/veridiq/webrtc"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def status() -> dict[str, Any]:
    return status_shape(
        "webrtc_signaling",
        "WebRTC Signaling (VERIDIQ)",
        "calling",
        status="ok",
        configured=True,
        message="Internal WebRTC signaling rooms available — no third-party key required.",
        env_vars=ENV_VARS,
        capabilities=CAPABILITIES,
        docs_url=DOCS,
    )


def test_connection() -> dict[str, Any]:
    room = create_room(label="connectivity-test")
    return {
        "platform": "webrtc_signaling",
        "status": "ok",
        "message": f"WebRTC signaling ready — test room {room['room_id']}.",
        "room_id": room["room_id"],
    }


def create_room(*, label: Optional[str] = None, agent_type: Optional[str] = None) -> dict[str, Any]:
    initialize_database()
    room_id = str(uuid.uuid4())
    stamped = _utc_now()
    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO veridiq_webrtc_rooms
                (room_id, label, agent_type, status, meta_json, created_at, updated_at)
            VALUES (?, ?, ?, 'open', ?, ?, ?)
            """,
            (
                room_id,
                (label or "agent-voice")[:120],
                agent_type,
                json.dumps({"created_by": agent_type}),
                stamped,
                stamped,
            ),
        )
    return {"ok": True, "room_id": room_id, "label": label, "status": "open", "created_at": stamped}


def create_offer(*, room_id: str, sdp: str, from_peer: str = "agent", **_kwargs: Any) -> dict[str, Any]:
    return _add_signal(room_id=room_id, kind="offer", sdp=sdp, from_peer=from_peer)


def create_answer(*, room_id: str, sdp: str, from_peer: str = "client", **_kwargs: Any) -> dict[str, Any]:
    return _add_signal(room_id=room_id, kind="answer", sdp=sdp, from_peer=from_peer)


def _add_signal(*, room_id: str, kind: str, sdp: str, from_peer: str) -> dict[str, Any]:
    initialize_database()
    if not room_id or not sdp:
        return {"ok": False, "status": "invalid_args", "message": "room_id and sdp are required."}
    signal_id = str(uuid.uuid4())
    stamped = _utc_now()
    with db_session() as conn:
        room = conn.execute("SELECT room_id FROM veridiq_webrtc_rooms WHERE room_id = ?", (room_id,)).fetchone()
        if not room:
            return {"ok": False, "status": "not_found", "message": f"Unknown room_id {room_id}."}
        conn.execute(
            """
            INSERT INTO veridiq_webrtc_signals
                (signal_id, room_id, kind, from_peer, sdp, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (signal_id, room_id, kind, from_peer[:64], sdp[:200000], stamped),
        )
        conn.execute(
            "UPDATE veridiq_webrtc_rooms SET updated_at = ? WHERE room_id = ?",
            (stamped, room_id),
        )
    return {"ok": True, "signal_id": signal_id, "room_id": room_id, "kind": kind, "created_at": stamped}


def list_signals(*, room_id: str, limit: int = 50) -> dict[str, Any]:
    initialize_database()
    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT signal_id, room_id, kind, from_peer, sdp, created_at
            FROM veridiq_webrtc_signals
            WHERE room_id = ?
            ORDER BY id ASC
            LIMIT ?
            """,
            (room_id, max(1, min(200, int(limit)))),
        ).fetchall()
    return {"ok": True, "room_id": room_id, "count": len(rows), "signals": [dict(r) for r in rows]}
