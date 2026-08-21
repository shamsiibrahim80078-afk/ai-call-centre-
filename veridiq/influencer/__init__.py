"""Thin influencer research helpers — extends marketing agency, not a parallel app.

Uses ``research.multi_search`` + ``ai_gateway`` when configured.
Never fabricates follower counts, engagement, or outreach success.
"""

from veridiq.influencer.research import research_creators

__all__ = ["research_creators"]
