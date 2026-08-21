"""Workforce package."""

from veridiq.workforce.identities import identity_for, list_identities
from veridiq.workforce.pool import global_worker_pool

__all__ = ["global_worker_pool", "identity_for", "list_identities"]
