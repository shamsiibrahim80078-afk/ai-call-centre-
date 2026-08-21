"""Human-readable workflow stage labels for live visibility (marketing-focused)."""

from __future__ import annotations

from typing import Optional

# Raw pool stages → operator-facing labels (especially marketing agency runs).
STAGE_LABELS: dict[str, str] = {
    "initializing": "Starting",
    "task_execution": "Executing task",
    "content_generation": "Generating content",
    "draft_queue": "Queuing drafts for approval",
    "result_collection": "Drafts ready for approval",
    "error_reporting": "Reporting error",
    "connector_call": "Calling platform API",
    "daily_pack_generation": "Building daily content pack",
    "draft_queued": "Draft queued for approval",
    "comms_send": "Platform send",
    "integration_test": "Testing integration",
    "Waiting for Assignment": "Waiting for Assignment",
}

CHANNEL_LABELS: dict[str, str] = {
    "telegram": "Telegram",
    "x_twitter": "X",
    "twitter": "X",
    "linkedin": "LinkedIn",
    "instagram": "Instagram",
    "threads": "Threads",
    "email": "Email",
    "marketing_agency": "Marketing",
    "canva": "Canva",
}

# Noun used in honest draft/send copy ("drafted Telegram message").
CHANNEL_NOUNS: dict[str, str] = {
    "telegram": "message",
    "x_twitter": "tweet",
    "twitter": "tweet",
    "linkedin": "post",
    "instagram": "caption",
    "threads": "caption",
    "email": "email",
}


def friendly_stage(stage: Optional[str]) -> Optional[str]:
    if stage is None:
        return None
    raw = str(stage).strip()
    if not raw:
        return None
    if raw in STAGE_LABELS:
        return STAGE_LABELS[raw]
    return raw.replace("_", " ").title()


def friendly_channel(channel: Optional[str]) -> str:
    if not channel:
        return "platform"
    key = str(channel).strip().lower().removesuffix("_comment")
    return CHANNEL_LABELS.get(key, key.replace("_", " ").title())


def channel_noun(channel: Optional[str]) -> str:
    if not channel:
        return "post"
    key = str(channel).strip().lower().removesuffix("_comment")
    return CHANNEL_NOUNS.get(key, "post")
