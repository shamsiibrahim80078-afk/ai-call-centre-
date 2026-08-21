"""Tool registry — agents call platforms only through the VERIDIQ platform API."""

from __future__ import annotations

from typing import Any, Callable, Optional

from veridiq.integrations.platform_api import PLATFORM_ACTIONS, dispatch, list_platforms

ToolFn = Callable[..., dict[str, Any]]

_TOOLS: dict[str, ToolFn] = {}
_BUILT = False


def register_tool(name: str, fn: ToolFn) -> None:
    key = name.strip().lower()
    if not key:
        raise ValueError("tool name is required")
    _TOOLS[key] = fn


def list_tools() -> list[str]:
    _ensure_builtins()
    return sorted(_TOOLS.keys())


def execute_tool(name: str, **kwargs: Any) -> dict[str, Any]:
    _ensure_builtins()
    key = (name or "").strip().lower()
    agent_type = kwargs.pop("_agent_type", None)
    if key in _TOOLS:
        fn = _TOOLS[key]
        try:
            if agent_type is not None:
                kwargs = {**kwargs, "_agent_type": agent_type}
            result = fn(**kwargs)
            if isinstance(result, dict):
                out = dict(result)
                if "ok" not in out:
                    status = out.get("status")
                    out["ok"] = status in {"ok", "configured", "public"} or out.get("configured") is True
                out.setdefault("tool", key)
                return out
            return {"ok": True, "tool": key, "result": result}
        except TypeError as exc:
            return {"ok": False, "tool": key, "status": "invalid_args", "message": str(exc)[:300]}
        except Exception as exc:
            return {"ok": False, "tool": key, "status": "error", "message": str(exc)[:300]}

    if "." in key:
        platform, action = key.split(".", 1)
        return dispatch(platform, action, args=kwargs, agent_type=agent_type)
    return {
        "ok": False,
        "tool": key,
        "status": "unknown_tool",
        "message": f"Tool '{key}' is not registered. Use platform.action form. Sample: {', '.join(sorted(_TOOLS)[:24])}",
    }


def _ensure_builtins() -> None:
    global _BUILT
    if _BUILT and _TOOLS:
        return
    _TOOLS.clear()
    for platform, actions in PLATFORM_ACTIONS.items():
        for action in actions:
            tool_name = f"{platform}.{action}"

            def _make(p: str = platform, a: str = action) -> ToolFn:
                def _fn(**kwargs: Any) -> dict[str, Any]:
                    agent_type = kwargs.pop("_agent_type", None)
                    return dispatch(p, a, args=kwargs, agent_type=agent_type)

                return _fn

            register_tool(tool_name, _make())

    # Convenience aliases used by leadership / docs
    register_tool("browser.status", lambda **kw: dispatch("browser_playwright", "status", args=kw))
    register_tool("browser.screenshot", lambda **kw: dispatch("browser_playwright", "screenshot", args=kw))
    register_tool("webrtc.status", lambda **kw: dispatch("webrtc_signaling", "status", args=kw))
    register_tool("webrtc.create_offer", lambda **kw: dispatch("webrtc_signaling", "create_offer", args=kw))
    register_tool("platforms.list", lambda **_kw: list_platforms())
    register_tool("ai_gateway.generate", lambda **kw: dispatch("ai_gateway", "generate", args=kw))
    register_tool("ai_gateway.status", lambda **kw: dispatch("ai_gateway", "status", args=kw))

    def _multi_search(**kwargs: Any) -> dict[str, Any]:
        from veridiq.research.multi_search import multi_search

        kwargs.pop("_agent_type", None)
        return multi_search(**kwargs)

    register_tool("research.multi_search", _multi_search)

    def _deep_research(**kwargs: Any) -> dict[str, Any]:
        from veridiq.research.deep_research import deep_research

        kwargs.pop("_agent_type", None)
        return deep_research(**kwargs)

    register_tool("research.deep_research", _deep_research)

    def _influencer_research(**kwargs: Any) -> dict[str, Any]:
        from veridiq.influencer.research import research_creators

        kwargs.pop("_agent_type", None)
        return research_creators(**kwargs)

    register_tool("influencer.research", _influencer_research)

    def _marketing_handoff(**kwargs: Any) -> dict[str, Any]:
        from veridiq.marketing.postings_handoff import handoff_draft_to_postings

        kwargs.pop("_agent_type", None)
        return handoff_draft_to_postings(**kwargs)

    register_tool("marketing.handoff_postings", _marketing_handoff)

    def _calling_budget(**kwargs: Any) -> dict[str, Any]:
        from veridiq.calling.budget import budget_status

        kwargs.pop("_agent_type", None)
        return budget_status(**kwargs)

    register_tool("ai_calling.budget", _calling_budget)

    def _calling_schedule(**kwargs: Any) -> dict[str, Any]:
        from veridiq.calling.timed_calls import schedule_timed_call

        kwargs.pop("_agent_type", None)
        return schedule_timed_call(**kwargs)

    register_tool("ai_calling.schedule_timed", _calling_schedule)
    _BUILT = True
