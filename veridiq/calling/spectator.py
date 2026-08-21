"""Spectator LiveKit tokens — subscribe-only for agent-agent meetings.

User observes/joins to watch; mic/cam publish disabled by default on the token.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from veridiq.calling.livekit_tokens import livekit_configured, livekit_status, mint_access_token
from veridiq.calling.meetings import get_meeting


def mint_spectator_token(
    *,
    meeting_id: str,
    identity: Optional[str] = None,
    name: str = "Spectator",
) -> dict[str, Any]:
    """Mint a subscribe-only LiveKit JWT for watching an agent meeting."""
    if not livekit_configured():
        return {"ok": False, "error": "livekit_not_configured", "livekit": livekit_status()}
    meeting = get_meeting(meeting_id)
    if not meeting:
        return {"ok": False, "error": "unknown_meeting"}
    if meeting.get("status") != "live":
        return {
            "ok": False,
            "error": "meeting_not_live",
            "meeting": meeting,
            "message": "Meeting is not live yet — wait for countdown or Watch when agents join.",
        }

    room = meeting.get("livekit_room") or f"veridiq-{meeting_id[:8]}"
    safe_id = (identity or f"spectator-{uuid.uuid4().hex[:10]}").strip()[:64]
    display = (name or "Spectator").strip()[:64] or "Spectator"
    tok = mint_access_token(
        identity=safe_id,
        room_name=room,
        name=display,
        can_publish=False,
        can_subscribe=True,
        can_publish_data=False,
    )
    if not tok.get("ok"):
        return tok
    return {
        **tok,
        "ok": True,
        "role": "spectator",
        "meeting_id": meeting_id,
        "meeting": meeting,
        "mute_defaults": {"microphone": True, "camera": True},
        "message": "Spectator token ready — subscribe to audio/video; mic/cam stay off.",
    }


def spectator_for_proposal(*, proposal_id: str, name: str = "Spectator") -> dict[str, Any]:
    """Resolve agent-meeting proposal → spectator token (ticks countdown first)."""
    from veridiq.calling.agent_meetings import get_live_bundle, get_proposal, tick_agent_meetings

    tick_agent_meetings()
    proposal = get_proposal(proposal_id)
    if not proposal:
        return {"ok": False, "error": "unknown_proposal"}
    if proposal["status"] == "approved":
        rem = proposal.get("countdown_remaining_seconds")
        return {
            "ok": False,
            "error": "countdown_active",
            "proposal": proposal,
            "countdown_remaining_seconds": rem,
            "message": f"Agents join in {rem}s — token available when live.",
        }
    if proposal["status"] != "live":
        return {
            "ok": False,
            "error": "not_watchable",
            "status": proposal.get("status"),
            "proposal": proposal,
            "message": f"Proposal status is {proposal.get('status')} — approve and wait for go-live.",
        }
    mid = proposal.get("meeting_id")
    if not mid:
        return {"ok": False, "error": "missing_meeting", "proposal": proposal}
    tok = mint_spectator_token(meeting_id=mid, name=name)
    bundle = get_live_bundle(proposal_id=proposal_id)
    return {
        **tok,
        "proposal": proposal,
        "dialogue": bundle.get("dialogue") or [],
        "agent_tokens": bundle.get("agent_tokens") or [],
        "mode": "spectator",
    }
