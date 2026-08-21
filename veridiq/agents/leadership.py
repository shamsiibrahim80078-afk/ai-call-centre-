"""Executive leadership agents — CEO and Directors coordinate via Agent SDK."""

from __future__ import annotations

from typing import Any

from veridiq.agents.base import VeridiqAgent


def _cascade_flag(payload: dict[str, Any], *keys: str) -> bool:
    """True when any cascade/execute key is set; default False for lightweight runs."""
    for k in keys:
        if k in payload:
            return bool(payload.get(k))
    return bool(payload.get("cascade"))


class CEOAgent(VeridiqAgent):
    """Company-wide coordinator: assigns work to Directors via the Agent SDK."""

    agent_type = "ceo"

    def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        from veridiq.sdk import get_sdk
        from veridiq.os.monitoring import live_agent_monitor

        sdk = get_sdk(self.agent_type)
        sdk.reportProgress(progress=0.15, stage="assessing_workforce", message="CEO reviewing live workforce")
        monitor = live_agent_monitor(limit=30)
        instruction = str(payload.get("instruction") or payload.get("text") or "Coordinate company priorities").strip()
        cascade = _cascade_flag(payload, "execute_directors", "cascade")

        directors = ["director_operations", "director_growth", "director_intelligence"]
        assignments = []
        for director in directors:
            sent = sdk.sendTask(
                director,
                {
                    "instruction": instruction,
                    "priority_brief": f"CEO directive: {instruction[:400]}",
                    "from": "ceo",
                    "execute_team": cascade,
                    "cascade": cascade,
                },
                priority=20,
                execute=cascade,
            )
            assignments.append(sent)

        shared = sdk.shareMemory(
            "ceo_last_brief",
            {
                "instruction": instruction,
                "working_agents": monitor.get("working"),
                "idle_agents": monitor.get("idle"),
                "assignments": [a.get("task_id") for a in assignments],
                "cascade": cascade,
            },
            scope="shared",
            tags=["ceo", "brief"],
        )
        sdk.reportProgress(progress=0.9, stage="directors_notified", confidence=0.82)
        sdk.streamOutput({"brief": instruction, "directors": directors, "cascade": cascade}, done=True)

        return {
            "summary": (
                f"CEO issued directive to {len(directors)} directors "
                f"(cascade={'on' if cascade else 'queued'}). "
                f"Workforce working={monitor.get('working')} idle={monitor.get('idle')}."
            ),
            "directive": instruction,
            "cascade": cascade,
            "director_assignments": assignments,
            "workforce": {"working": monitor.get("working"), "idle": monitor.get("idle")},
            "shared_memory": shared,
            "confidence": 0.82,
        }


class DirectorOperationsAgent(VeridiqAgent):
    agent_type = "director_operations"

    def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        from veridiq.sdk import get_sdk

        sdk = get_sdk(self.agent_type)
        sdk.reportProgress(progress=0.2, stage="ops_routing", message="Operations Director routing work")
        instruction = str(payload.get("instruction") or payload.get("priority_brief") or payload.get("text") or "").strip()
        execute_team = _cascade_flag(payload, "execute_team", "cascade")
        # Full roster queued; only the first worker executes synchronously when cascading
        # to keep CEO→Directors→Workers verifiable without multi-minute runs.
        targets = ["orchestrator", "decision", "confidence_scoring", "report_generator"]
        if payload.get("targets"):
            targets = list(payload["targets"])
        tasks = []
        for i, t in enumerate(targets):
            tasks.append(
                sdk.sendTask(
                    t,
                    {
                        "instruction": instruction or "Run operations health check",
                        "text": instruction or "operations health check",
                        "from": self.agent_type,
                    },
                    priority=40,
                    execute=execute_team and i == 0,
                )
            )
        inbox = sdk.receiveTask(limit=5, claim_only=False)
        sdk.shareMemory("ops_last_plan", {"targets": targets, "instruction": instruction}, scope="shared", tags=["ops"])
        sdk.executeTool("platforms.list")
        return {
            "summary": f"Operations Director queued {len(tasks)} team tasks (executed first={execute_team}).",
            "team_tasks": tasks,
            "inbox": inbox,
            "execute_team": execute_team,
            "confidence": 0.78,
        }


class DirectorGrowthAgent(VeridiqAgent):
    agent_type = "director_growth"

    def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        from veridiq.sdk import get_sdk

        sdk = get_sdk(self.agent_type)
        instruction = str(payload.get("instruction") or payload.get("priority_brief") or payload.get("text") or "").strip()
        execute_team = _cascade_flag(payload, "execute_team", "cascade")
        targets = ["marketing_manager", "ai_calling", "linkedin_outreach", "sales_intelligence"]
        if payload.get("targets"):
            targets = list(payload["targets"])
        tasks = []
        for i, t in enumerate(targets):
            tasks.append(
                sdk.sendTask(
                    t,
                    {
                        "instruction": instruction or "Prepare growth readiness report",
                        "text": instruction or "growth readiness",
                        "from": self.agent_type,
                    },
                    priority=50,
                    execute=execute_team and i == 0,
                )
            )
        tools = [
            sdk.executeTool("linkedin.status"),
            sdk.executeTool("ai_calling.status"),
            sdk.executeTool("slack.status"),
            sdk.executeTool("gmail.status"),
            sdk.executeTool("github.status"),
            sdk.executeTool("discord.status"),
        ]
        sdk.shareMemory("growth_connector_status", tools, scope="shared", tags=["growth"])
        return {
            "summary": f"Growth Director queued {len(tasks)} specialists and probed {len(tools)} connectors.",
            "team_tasks": tasks,
            "connector_probes": tools,
            "execute_team": execute_team,
            "confidence": 0.75,
        }


class DirectorIntelligenceAgent(VeridiqAgent):
    agent_type = "director_intelligence"

    def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        from veridiq.sdk import get_sdk
        from veridiq.agents import AGENT_REGISTRY

        sdk = get_sdk(self.agent_type)
        instruction = str(payload.get("instruction") or payload.get("priority_brief") or payload.get("text") or "").strip()
        execute_team = _cascade_flag(payload, "execute_team", "cascade")
        targets = ["market_research", "web_search", "news_verification", "sentiment_analysis"]
        if payload.get("targets"):
            targets = list(payload["targets"])
        targets = [t for t in targets if t in AGENT_REGISTRY]
        tasks = []
        for i, t in enumerate(targets):
            tasks.append(
                sdk.sendTask(
                    t,
                    {
                        "instruction": instruction or "Gather intelligence snapshot",
                        "text": instruction or "intelligence snapshot",
                        "from": self.agent_type,
                    },
                    priority=45,
                    execute=execute_team and i == 0,
                )
            )
        return {
            "summary": f"Intelligence Director queued {len(tasks)} research tasks (executed first={execute_team}).",
            "team_tasks": tasks,
            "execute_team": execute_team,
            "confidence": 0.76,
        }


LEADERSHIP_AGENT_CLASSES: dict[str, type[VeridiqAgent]] = {
    "ceo": CEOAgent,
    "director_operations": DirectorOperationsAgent,
    "director_growth": DirectorGrowthAgent,
    "director_intelligence": DirectorIntelligenceAgent,
}
