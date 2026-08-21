"""Mira continuous improvement — free local learning, not foundation training.

This package improves Postings image/video prompts over time by:

1. Storing thumbs-up/down (or 1–5) ratings on generated media (SQLite)
2. Retrieving top-rated similar prompts as "quality anchors"
3. Using user uploads as brand/style reference guidance injected into prompts
4. Local ``mira_learning_config.json`` adapters (preferred styles, negatives, suffixes)

What this is NOT:
- Not training a Veo-scale / foundation neural model
- Not Unsplash (disabled / not used — ``UNSPLASH_ACCESS_KEY`` ignored)
- Not Meta/social posting (learning does not require posting)
- Not a mass web scraper of Google, Pinterest, or arbitrary copyrighted sites
- Not claiming we fine-tune weights on scraped internet images

``apply_learned_quality(prompt, topic)`` is the single hook called from the
creative / generate path. ``mira_learning_config.json`` stores lightweight
"adapter" weights: preferred styles, negatives from downvotes, prompt suffixes
from upvotes. Cost: free.
"""

from __future__ import annotations

from veridiq.postings.learning.quality import (
    apply_learned_quality,
    feedback_stats,
    learning_status,
    rebuild_learning_config,
)
from veridiq.postings.learning.store import (
    ensure_learning_tables,
    list_references,
    record_feedback,
    register_brand_reference,
)
from veridiq.postings.learning.references import (
    fetch_unsplash_references,
    reference_guidance_for_topic,
)

__all__ = [
    "apply_learned_quality",
    "feedback_stats",
    "learning_status",
    "rebuild_learning_config",
    "ensure_learning_tables",
    "list_references",
    "record_feedback",
    "register_brand_reference",
    "fetch_unsplash_references",
    "reference_guidance_for_topic",
]
