"""Platform integrations package — modular connectors for outbound platforms.

Official APIs only. No scraping. Missing credentials always yield
``configuration_required`` and never fabricated activity.
"""

from veridiq.integrations.activity import global_platform_activity
from veridiq.integrations.registry import all_integrations, integration_detail, test_integration

__all__ = [
    "all_integrations",
    "integration_detail",
    "test_integration",
    "global_platform_activity",
]
