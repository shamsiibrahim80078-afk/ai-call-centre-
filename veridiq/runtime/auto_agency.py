"""Auto-connect & agency run — uses only configured official platforms.

Cannot create LinkedIn/Meta/Google OAuth apps for the operator (those require
their human account). Age-restricted LinkedIn is reported honestly and skipped.
Agents still run: CEO cascade, marketing drafts on ready channels, connector probes.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Optional

# Platforms we never pretend to unlock without operator credentials.
HUMAN_OAUTH_PLATFORMS = {
    "linkedin",
    "instagram",
    "gmail",
    "google_calendar",
    "google_drive",
    "x_twitter",
    "slack",
    "discord",
    "github",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def probe_all_platforms() -> dict[str, Any]:
    from veridiq.integrations.platform_api import list_platforms, dispatch

    catalog = list_platforms()
    rows = []
    ready = []
    blocked = []
    for p in catalog["platforms"]:
        key = p["platform"]
        st = dispatch(key, "status", record_activity=False)
        configured = bool(st.get("configured")) or st.get("status") in {"ok", "configured", "public"}
        # WebRTC / browser-without-flag / status-only public
        if key == "webrtc_signaling":
            configured = True
        note = None
        if key == "linkedin" and not configured:
            note = (
                "LinkedIn Developer apps require a LinkedIn member account that passes "
                "age/eligibility checks. VERIDIQ cannot create that account or bypass the gate. "
                "Skip LinkedIn until an eligible account is available; other agencies still run."
            )
            blocked.append({"platform": key, "reason": "age_or_oauth_gate", "note": note})
        elif key in HUMAN_OAUTH_PLATFORMS and not configured:
            blocked.append(
                {
                    "platform": key,
                    "reason": "configuration_required",
                    "note": st.get("message"),
                }
            )
        elif configured:
            ready.append(key)
        rows.append(
            {
                "platform": key,
                "status": st.get("status"),
                "configured": configured,
                "message": note or st.get("message"),
                "actions": p.get("actions"),
            }
        )
    return {
        "ready": ready,
        "blocked": blocked,
        "platforms": rows,
        "timestamp": _utc_now(),
    }


def configured_marketing_channels() -> list[str]:
    """Channels marketing may draft for; LinkedIn omitted when not configured."""
    from veridiq.integrations import instagram, linkedin, telegram, x_twitter

    channels: list[str] = []
    if telegram.status().get("configured"):
        channels.append("telegram")
    if x_twitter.status().get("configured"):
        channels.append("x_twitter")
    # LinkedIn: only if configured — never fake
    if linkedin.status().get("configured"):
        channels.append("linkedin")
    if instagram.status().get("configured"):
        channels.append("instagram")
    # Always allow draft generation for at least telegram path if nothing ready —
    # drafts stay pending approval and send will report configuration_required.
    if not channels:
        channels = ["telegram"]
    return channels


def run_auto_agency(
    *,
    instruction: str = "Auto agency run: probe platforms, cascade leadership, queue marketing drafts",
    run_cascade: bool = True,
    run_marketing: bool = True,
    approve_sends: bool = False,
) -> dict[str, Any]:
    """End-to-end auto run without inventing third-party credentials.

    ``approve_sends`` stays False by default — outbound still needs human approve.
    """
    probe = probe_all_platforms()
    result: dict[str, Any] = {
        "ok": True,
        "mode": "auto_agency",
        "probe": probe,
        "cascade": None,
        "marketing": None,
        "linkedin_policy": (
            "LinkedIn cannot be unlocked by VERIDIQ code when the member account is "
            "age-restricted. Use Telegram/X/email when configured; revisit LinkedIn later."
        ),
        "timestamp": _utc_now(),
    }

    if run_cascade:
        from veridiq.orchestration.leadership_cascade import run_leadership_cascade

        try:
            result["cascade"] = run_leadership_cascade(instruction)
        except Exception as exc:
            result["cascade"] = {"ok": False, "error": str(exc)[:400]}
            result["ok"] = False

    if run_marketing:
        try:
            from veridiq.marketing.campaigns import get_or_create_default_campaign
            from veridiq.marketing.team_run import MARKETING_AGENT_TYPES, build_run_payload
            from veridiq.agents import get_agent
            from veridiq.workforce.pool import global_worker_pool

            campaign = get_or_create_default_campaign()
            channels = configured_marketing_channels()
            team_run_id = f"auto-{_utc_now().replace(':', '').replace('-', '')[:18]}"
            agent_results = []
            for agent_type in MARKETING_AGENT_TYPES:
                payload = build_run_payload(
                    agent_type,
                    campaign["campaign_id"],
                    team_run=True,
                    team_run_id=team_run_id,
                )
                # Prefer ready channels only
                payload["channels"] = [c for c in (payload.get("channels") or channels) if c in channels] or channels[:1]
                payload["auto_agency"] = True
                payload["skip_linkedin"] = "linkedin" not in channels

                def _runner(at: str = agent_type, pl: dict[str, Any] = payload) -> dict[str, Any]:
                    return get_agent(at).run(pl)

                try:
                    env = global_worker_pool.run_agent_task(
                        agent_type=agent_type,
                        fn=_runner,
                        task=f"auto_agency:{agent_type}",
                        min_visible_sec=0.0,
                    )
                    agent_results.append(
                        {
                            "agent_type": agent_type,
                            "ok": bool(isinstance(env, dict) and env.get("ok")),
                            "channels": payload["channels"],
                        }
                    )
                except Exception as exc:
                    agent_results.append({"agent_type": agent_type, "ok": False, "error": str(exc)[:200]})

            result["marketing"] = {
                "ok": any(a.get("ok") for a in agent_results),
                "campaign_id": campaign["campaign_id"],
                "channels_used": channels,
                "agents": agent_results,
                "approve_sends": approve_sends,
                "note": "Drafts queued for human approve — no silent outbound sends.",
            }
        except Exception as exc:
            result["marketing"] = {"ok": False, "error": str(exc)[:400]}
            result["ok"] = False

    result["next_steps"] = [
        "Open Command Center → confirm cascade/SDK tasks",
        "Open Marketing Agency → approve drafts for configured channels only",
        "LinkedIn: needs an eligible LinkedIn developer account (not creatable by VERIDIQ)",
        "When you have keys, paste into .env and restart — probes flip to configured",
    ]
    return result
