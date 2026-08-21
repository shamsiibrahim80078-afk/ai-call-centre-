"""VERIDIQ Postings Studio — draft posts, Canva designs, video storyboards.

Chat agent for the Postings page. Never fabricates live social posts or MP4s.
Default brain: Mira Creative Model (Free).

Zero-cost media for posting agents::

    from veridiq.postings.free_media_pipeline import run_pipeline
    # or: from veridiq.postings import run_pipeline
"""

from veridiq.postings.studio import agent_persona, handle_command, studio_status

try:
    from veridiq.postings.free_media_pipeline import run_pipeline
except Exception:  # pragma: no cover — optional soft import for agents
    run_pipeline = None  # type: ignore[misc, assignment]

__all__ = ["agent_persona", "handle_command", "studio_status", "run_pipeline"]
