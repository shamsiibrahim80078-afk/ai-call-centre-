"""AI Calling — in-app command agent (Marcus) + legacy Twilio campaign routes."""

from veridiq.calling.agent import agent_persona, handle_command
from veridiq.calling.campaigns import (
    approve_campaign,
    create_campaign,
    draft_followup,
    get_campaign,
    list_campaigns,
    sync_summary_to_crm,
)

__all__ = [
    "agent_persona",
    "handle_command",
    "create_campaign",
    "list_campaigns",
    "get_campaign",
    "approve_campaign",
    "sync_summary_to_crm",
    "draft_followup",
]
