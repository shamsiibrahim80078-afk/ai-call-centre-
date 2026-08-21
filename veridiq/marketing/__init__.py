"""VERIDIQ Marketing Agency — campaign briefs, daily content packs, and
comment/engagement drafting for VeriDiQ's own social channels.

Every post/comment this package produces is queued through the existing
`veridiq.comms` draft -> approve -> send gate (see `veridiq/comms/assistant.py`)
and every real send goes through the existing platform integrations
(`veridiq/integrations/*`). This package never sends anything directly and
never fabricates a delivered post.
"""

from veridiq.marketing.campaigns import (
    clear_pending_drafts,
    create_campaign,
    daily_status,
    generate_daily_pack,
    get_campaign,
    get_or_create_default_campaign,
    list_campaigns,
    list_queue,
    set_campaign_status,
)
from veridiq.marketing.cadence import approve_batch_with_cadence, cadence_enabled, compute_delay_sec
from veridiq.marketing.human_voice import persona_for, render_for_agent
from veridiq.marketing.team_run import build_run_payload, go_live_checklist, prepare_queue_for_run
from veridiq.marketing.postings_handoff import handoff_draft_to_postings, handoff_pack_drafts

from veridiq.marketing.storyboard import (
    generate_product_tour_storyboard,
    generate_storyboard,
    get_storyboard,
    render_storyboard,
)

__all__ = [
    "create_campaign",
    "list_campaigns",
    "get_campaign",
    "get_or_create_default_campaign",
    "set_campaign_status",
    "generate_daily_pack",
    "daily_status",
    "list_queue",
    "clear_pending_drafts",
    "build_run_payload",
    "go_live_checklist",
    "prepare_queue_for_run",
    "handoff_draft_to_postings",
    "handoff_pack_drafts",
    "approve_batch_with_cadence",
    "cadence_enabled",
    "compute_delay_sec",
    "persona_for",
    "render_for_agent",
    "generate_storyboard",
    "generate_product_tour_storyboard",
    "get_storyboard",
    "render_storyboard",
]
