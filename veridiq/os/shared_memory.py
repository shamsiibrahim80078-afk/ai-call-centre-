"""Shared memory snapshot across the VERIDIQ agent OS."""

from __future__ import annotations

from typing import Any

from memory.memory_manager import MemoryManager

_SHARED_NS = "veridiq-shared-memory"


def shared_memory_snapshot(*, limit: int = 50) -> dict[str, Any]:
    mm = MemoryManager(default_agent_uuid=_SHARED_NS)
    entries = mm.search_memory(agent_uuid=_SHARED_NS, tag="sdk", limit=limit)
    if not entries:
        entries = mm.search_memory(agent_uuid=_SHARED_NS, limit=limit)
    return {
        "namespace": _SHARED_NS,
        "count": len(entries),
        "entries": entries,
    }
