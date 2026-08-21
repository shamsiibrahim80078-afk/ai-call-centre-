"""Coordinated marketing team runs — one pack + per-agent single drafts, not 6× floods."""

from __future__ import annotations

import os
from typing import Any, Optional

# Skip generating new drafts when the queue is already backed up.
MAX_PENDING_BEFORE_SKIP = int(os.getenv("VERIDIQ_MARKETING_MAX_PENDING", "50"))
# Hard cap on new drafts created by a single "Run marketing team now" click.
MAX_DRAFTS_TEAM_RUN = int(os.getenv("VERIDIQ_MARKETING_MAX_DRAFTS_TEAM", "24"))
# Individual agent "Run now" (non-team) still caps per click.
MAX_DRAFTS_AGENT_RUN = int(os.getenv("VERIDIQ_MARKETING_MAX_DRAFTS_AGENT", "8"))

MARKETING_AGENT_TYPES = (
    "marketing_manager",
    "content_creator",
    "social_poster",
    "telegram_community",
    "x_twitter_voice",
    "influencer_relations",
)

# Per-agent channel focus for team runs — manager gets a capped daily pack;
# everyone else queues exactly one draft on their specialty channel.
TEAM_RUN_CHANNELS: dict[str, list[str]] = {
    "marketing_manager": ["telegram", "x_twitter", "linkedin", "instagram", "threads"],
    "content_creator": ["linkedin"],
    "social_poster": ["threads"],
    "telegram_community": ["telegram"],
    "x_twitter_voice": ["x_twitter"],
    "influencer_relations": ["instagram", "threads"],
}

AGENT_RUN_CHANNELS: dict[str, list[str]] = {
    "marketing_manager": ["telegram", "x_twitter", "linkedin", "instagram", "threads"],
    "content_creator": ["linkedin", "x_twitter"],
    "social_poster": ["linkedin", "instagram", "x_twitter", "threads"],
    "telegram_community": ["telegram"],
    "x_twitter_voice": ["x_twitter"],
    "influencer_relations": ["instagram", "x_twitter", "threads"],
}


def pending_count(*, campaign_id: Optional[str] = None) -> int:
    from veridiq.marketing.campaigns import daily_status

    return int(daily_status(campaign_id=campaign_id).get("pending_approval") or 0)


def should_skip_draft_generation(*, campaign_id: Optional[str] = None) -> tuple[bool, str]:
    pending = pending_count(campaign_id=campaign_id)
    if pending >= MAX_PENDING_BEFORE_SKIP:
        return True, (
            f"Queue has {pending} pending draft(s) (limit {MAX_PENDING_BEFORE_SKIP}). "
            "Approve or clear old drafts before generating more."
        )
    return False, ""


def prepare_queue_for_run(
    *,
    campaign_id: Optional[str] = None,
    auto_clear: bool = True,
    keep_recent: int = 20,
) -> dict[str, Any]:
    """If the draft queue is flooded, optionally clear old drafts so agents can run.

    Flooded queues previously made influencer/marketing runs look "broken"
    (every click returned skip_draft_generation with zero new drafts).
    """
    skip, reason = should_skip_draft_generation(campaign_id=campaign_id)
    if not skip:
        return {"skipped": False, "cleared": 0, "reason": None}
    if not auto_clear:
        return {"skipped": True, "cleared": 0, "reason": reason}
    from veridiq.marketing.campaigns import clear_pending_drafts

    cleared = clear_pending_drafts(campaign_id=campaign_id, keep_recent=keep_recent)
    still_skip, still_reason = should_skip_draft_generation(campaign_id=campaign_id)
    return {
        "skipped": still_skip,
        "cleared": int(cleared.get("removed") or 0),
        "reason": still_reason if still_skip else (
            f"Cleared {cleared.get('removed', 0)} old pending draft(s) so new content can queue. "
            f"Previously: {reason}"
        ),
        "clear_result": cleared,
    }


def build_run_payload(
    agent_type: str,
    campaign_id: str,
    *,
    team_run: bool = False,
    team_run_id: Optional[str] = None,
    auto_clear_queue: bool = True,
) -> dict[str, Any]:
    """Payload injected into marketing agent runs so each click does bounded work."""
    prep = prepare_queue_for_run(campaign_id=campaign_id, auto_clear=auto_clear_queue)
    skip = bool(prep.get("skipped"))
    reason = prep.get("reason")
    channels = (TEAM_RUN_CHANNELS if team_run else AGENT_RUN_CHANNELS).get(agent_type, ["telegram"])
    max_drafts = 1 if (team_run and agent_type != "marketing_manager") else (
        min(7, MAX_DRAFTS_TEAM_RUN) if team_run else MAX_DRAFTS_AGENT_RUN
    )
    if team_run and agent_type == "marketing_manager":
        max_drafts = min(7, MAX_DRAFTS_TEAM_RUN - 5)  # leave headroom for specialist singles

    payload: dict[str, Any] = {
        "campaign_id": campaign_id,
        "channels": channels,
        "team_run": team_run,
        "team_run_id": team_run_id,
        "max_drafts": max_drafts,
        "skip_draft_generation": skip,
        "skip_reason": reason if skip else None,
        "queue_prepared": prep,
        "handoff_to_postings": True,
    }
    return payload


def _marketing_send_ready(platform_key: str) -> tuple[bool, list[str]]:
    """True when approve → send has the minimum env vars (not just a status probe)."""
    import os

    from veridiq.integrations import instagram, linkedin, telegram, threads, x_twitter

    if platform_key == "telegram":
        needed = [telegram.BOT_TOKEN, telegram.DEFAULT_CHAT_ID]
    elif platform_key == "x_twitter":
        needed = list(x_twitter.POST_ENV_VARS)
    elif platform_key == "linkedin":
        needed = [linkedin.ACCESS_TOKEN]
    elif platform_key == "instagram":
        needed = list(instagram.ENV_VARS)
    elif platform_key == "threads":
        needed = list(threads.ENV_VARS)
    else:
        return False, []
    missing = [v for v in needed if not (os.getenv(v) or "").strip()]
    return len(missing) == 0, missing


def go_live_checklist() -> dict[str, Any]:
    """Missing env vars per marketing platform — honest configuration_required list."""
    from veridiq.integrations import instagram, linkedin, telegram, threads, x_twitter

    platforms = [
        ("telegram", telegram.status()),
        ("x_twitter", x_twitter.status()),
        ("linkedin", linkedin.status()),
        ("instagram", instagram.status()),
        ("threads", threads.status()),
    ]
    items = []
    ready = 0
    for key, st in platforms:
        send_ready, missing = _marketing_send_ready(key)
        if send_ready:
            ready += 1
        send_note = st.get("message") or ""
        if key == "x_twitter" and not send_ready:
            send_note = (
                "Live posts need all four OAuth 1.0a vars below (Bearer alone is status-only). "
                "X may also require paid API credits before tweets succeed."
            )
        elif key == "linkedin" and not send_ready:
            send_note = (
                "LinkedIn Developer Portal needs an eligible LinkedIn member account "
                "(age/login gates cannot be bypassed by VERIDIQ). Skip LinkedIn for now; "
                "use Threads/Telegram/X when configured. " + send_note
            )
        elif key == "instagram" and not send_ready:
            send_note = f"Paste credentials when ready — drafts queue offline without them. {send_note}"
        elif key == "threads" and not send_ready:
            send_note = (
                "Preferred live-test path when LinkedIn is gated. Create a Meta app with the Threads "
                "use case, grant threads_basic + threads_content_publish (+ threads_manage_replies for comments), "
                "then paste token + user id. "
                + send_note
            )
        items.append(
            {
                "platform": key,
                "display_name": st.get("display_name") or key,
                "configured": send_ready,
                "send_ready": send_ready,
                "status": st.get("status"),
                "message": send_note,
                "env_vars": missing if not send_ready else (st.get("env_vars") or []),
                "docs_url": st.get("docs_url"),
                "blocked_reason": "age_or_oauth_gate" if key == "linkedin" and not send_ready else None,
            }
        )
    return {
        "ready_count": ready,
        "total": len(items),
        "all_ready": ready == len(items),
        "platforms": items,
        "note": (
            "Drafts queue offline with zero setup. Paste the env vars below into .env, restart the backend, "
            "then Approve drafts on the Marketing page to attempt real platform sends. "
            "LinkedIn cannot be auto-provisioned if your LinkedIn account is age-restricted — "
            "prefer Threads (Meta) for live testing, or Telegram/X when configured. "
            "Batch approve spaces sends 30–180s apart (VERIDIQ_MARKETING_SEND_JITTER_*). "
            "Telegram may need VERIDIQ_TELEGRAM_PROXY or VPN if api.telegram.org is blocked."
        ),
    }
