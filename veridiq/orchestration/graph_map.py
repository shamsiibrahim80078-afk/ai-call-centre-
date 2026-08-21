"""Central map of LangGraph orchestration nodes to specialist agent types.

Single source of truth shared by app.py (API responses) and the workforce
roster/detail builders, so agent profiles and connectivity reports never
drift out of sync.
"""

from __future__ import annotations

from veridiq.orchestration.market_graph import MARKET_AGENT_MAP

LANGGRAPH_AGENT_MAP: dict[str, list[str]] = {
    "route": ["orchestrator"],
    "perception": [
        "emotion_detection",
        "lie_detection",
        "meeting_analysis",
        "timeline_builder",
        "voice_analysis",
        "face_analysis",
    ],
    "evidence_rag": [
        "evidence_collection",
        "web_search",
        "news_verification",
        "citation",
        "source_credibility",
    ],
    "verification": ["statement_verification", "fact_checking"],
    "reasoning": [
        "risk_analysis",
        "confidence_scoring",
        "decision",
        "report_generator",
        "conversation_memory",
    ],
}

ALL_GRAPH_NODES: dict[str, list[str]] = {**LANGGRAPH_AGENT_MAP, **MARKET_AGENT_MAP}


def nodes_for_agent(agent_type: str) -> list[str]:
    return [node for node, agents in ALL_GRAPH_NODES.items() if agent_type in agents]
