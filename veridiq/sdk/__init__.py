"""VERIDIQ Agent SDK — universal inter-agent communication layer.

Every agent communicates through this SDK instead of hardcoded integrations.
Methods: sendTask, receiveTask, askAgent, shareMemory, executeTool,
streamOutput, reportProgress, completeTask.
"""

from veridiq.sdk.agent_sdk import AgentSDK, get_sdk

__all__ = ["AgentSDK", "get_sdk"]
