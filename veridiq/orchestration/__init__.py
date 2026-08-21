"""VERIDIQ orchestration package."""

from veridiq.orchestration.events import global_job_events

__all__ = ["VeridiqOrchestrator", "global_orchestrator", "global_job_events"]


def __getattr__(name: str):
    if name in {"VeridiqOrchestrator", "global_orchestrator"}:
        from veridiq.orchestration.graph import VeridiqOrchestrator, global_orchestrator

        return VeridiqOrchestrator if name == "VeridiqOrchestrator" else global_orchestrator
    raise AttributeError(name)
