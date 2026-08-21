"""Communication assistant package."""

from veridiq.comms.assistant import (
    approve_external_action,
    draft_communication,
    draft_marketing_content,
    list_drafts,
)

__all__ = ["draft_communication", "approve_external_action", "draft_marketing_content", "list_drafts"]
