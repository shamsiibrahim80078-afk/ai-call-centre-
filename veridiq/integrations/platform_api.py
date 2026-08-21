"""Unified VERIDIQ platform API — agents and HTTP callers use this only.

Every external platform is reached through this dispatch layer, which wraps
official connector modules under ``veridiq.integrations.*``. No scraping.
Missing credentials return ``configuration_required`` honestly.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from veridiq.integrations.activity import global_platform_activity

# platform -> action -> callable factory (lazy import)
ActionFn = Callable[..., dict[str, Any]]


def _mod(name: str):
    import importlib

    return importlib.import_module(f"veridiq.integrations.{name}")


PLATFORM_ACTIONS: dict[str, dict[str, str]] = {
    # module_attr names resolved at call time
    "linkedin": {"status": "status", "test": "test_connection", "share_post": "share_post", "comment": "comment_on_post"},
    "x_twitter": {"status": "status", "test": "test_connection", "post_tweet": "post_tweet", "reply": "reply_tweet"},
    "telegram": {"status": "status", "test": "test_connection", "send_message": "send_message"},
    "instagram": {"status": "status", "test": "test_connection", "publish_media": "publish_media", "reply_comment": "reply_to_comment"},
    "threads": {
        "status": "status",
        "test": "test_connection",
        "publish_text": "publish_text",
        "reply": "reply_to_post",
    },
    "whatsapp": {"status": "status", "test": "test_connection", "send_message": "send_message"},
    "email": {"status": "status", "test": "test_connection", "send_email": "send_email"},
    "crm": {"status": "status", "test": "test_connection", "sync_note": "sync_note"},
    "ai_calling": {"status": "status", "test": "test_connection", "place_call": "place_call", "call_status": "call_status"},
    "gmail": {"status": "status", "test": "test_connection", "list_messages": "list_messages"},
    "google_calendar": {"status": "status", "test": "test_connection", "list_events": "list_events"},
    "google_drive": {"status": "status", "test": "test_connection", "list_files": "list_files"},
    "github": {"status": "status", "test": "test_connection", "list_repos": "list_repos"},
    "notion": {"status": "status", "test": "test_connection", "search_pages": "search_pages"},
    "slack": {"status": "status", "test": "test_connection", "post_message": "post_message"},
    "discord": {"status": "status", "test": "test_connection", "send_message": "send_message"},
    "browser_playwright": {"status": "status", "test": "test_connection", "screenshot": "screenshot"},
    "webrtc_signaling": {
        "status": "status",
        "test": "test_connection",
        "create_room": "create_room",
        "create_offer": "create_offer",
        "create_answer": "create_answer",
        "list_signals": "list_signals",
    },
    "canva": {"status": "status", "test": "test_connection", "create_design": "create_design"},
    "video_render": {"status": "status", "test": "test_connection", "render_storyboard": "render_storyboard"},
    "marketing": {"status": "status", "test": "test_connection", "send_campaign": "send_campaign"},
    # Research / search
    "tavily": {"status": "status", "test": "test_connection", "search": "search"},
    "serpapi": {"status": "status", "test": "test_connection", "search": "search"},
    "exa": {"status": "status", "test": "test_connection", "search": "search"},
    # Data / auth bridges / payments / infra
    "supabase": {"status": "status", "test": "test_connection", "rest_health": "rest_health"},
    "clerk": {"status": "status", "test": "test_connection", "optional_jwt_verify_stub": "optional_jwt_verify_stub"},
    "stripe": {"status": "status", "test": "test_connection"},
    "firebase": {"status": "status", "test": "test_connection", "project_status": "project_status"},
    # AI Gateway (multi-provider fallback)
    "ai_gateway": {"status": "status", "test": "test_connection", "generate": "generate"},
    # AI / LLM providers
    "google_ai": {"status": "status", "test": "test_connection", "generate_text": "generate_text"},
    "groq": {"status": "status", "test": "test_connection", "generate_text": "generate_text"},
    "openrouter": {"status": "status", "test": "test_connection", "generate_text": "generate_text"},
    "huggingface": {"status": "status", "test": "test_connection", "generate_text": "generate_text"},
    "cohere": {"status": "status", "test": "test_connection", "generate_text": "generate_text"},
    "mistral": {"status": "status", "test": "test_connection", "generate_text": "generate_text"},
    "together": {"status": "status", "test": "test_connection", "generate_text": "generate_text"},
    "fireworks": {"status": "status", "test": "test_connection", "generate_text": "generate_text"},
    # Speech providers
    "assemblyai": {"status": "status", "test": "test_connection", "transcribe": "transcribe"},
    "deepgram": {"status": "status", "test": "test_connection", "transcribe": "transcribe"},
}

# Map public platform ids used in registry to module names
MODULE_ALIASES: dict[str, str] = {
    "email": "email_smtp",
    "ai_calling": "twilio_calling",
    "browser": "browser_playwright",
    "browser_playwright": "browser_playwright",
    "webrtc": "webrtc_signaling",
    "webrtc_signaling": "webrtc_signaling",
    "supabase": "supabase_conn",
    "clerk": "clerk_conn",
    "stripe": "stripe_conn",
    "firebase": "firebase_conn",
    "google_ai": "llm.google_ai",
    "groq": "llm.groq",
    "openrouter": "llm.openrouter",
    "huggingface": "llm.huggingface",
    "cohere": "llm.cohere",
    "mistral": "llm.mistral",
    "together": "llm.together",
    "fireworks": "llm.fireworks",
    "assemblyai": "llm.assemblyai",
    "deepgram": "llm.deepgram",
}


def list_platforms() -> dict[str, Any]:
    platforms = []
    for platform, actions in sorted(PLATFORM_ACTIONS.items()):
        platforms.append(
            {
                "platform": platform,
                "module": MODULE_ALIASES.get(platform, platform),
                "actions": sorted(actions.keys()),
            }
        )
    return {"count": len(platforms), "platforms": platforms}


def platform_status(platform: str) -> dict[str, Any]:
    return dispatch(platform, "status")


def dispatch(
    platform: str,
    action: str,
    *,
    args: Optional[dict[str, Any]] = None,
    agent_type: Optional[str] = None,
    record_activity: bool = True,
) -> dict[str, Any]:
    """Execute a platform action through the unified VERIDIQ API layer."""
    key = (platform or "").strip().lower()
    act = (action or "").strip().lower()
    if key in {"browser"}:
        key = "browser_playwright"
    if key in {"webrtc"}:
        key = "webrtc_signaling"
    if key in {"email_smtp"}:
        key = "email"
    if key in {"twilio_calling"}:
        key = "ai_calling"

    catalog = PLATFORM_ACTIONS.get(key)
    if not catalog:
        return {
            "ok": False,
            "platform": key,
            "action": act,
            "status": "unknown_platform",
            "message": f"Unknown platform '{key}'. See /api/v1/veridiq/platforms",
        }
    attr = catalog.get(act)
    if not attr:
        return {
            "ok": False,
            "platform": key,
            "action": act,
            "status": "unknown_action",
            "message": f"Action '{act}' not available. Actions: {', '.join(sorted(catalog))}",
        }

    module_name = MODULE_ALIASES.get(key, key)
    try:
        mod = _mod(module_name)
        fn = getattr(mod, attr)
    except Exception as exc:
        return {
            "ok": False,
            "platform": key,
            "action": act,
            "status": "error",
            "message": f"Failed to load connector: {exc}"[:300],
        }

    kwargs = dict(args or {})
    try:
        # status/test take no kwargs; others may be positional-heavy — prefer kwargs
        if act in {"status", "test"}:
            result = fn()
        else:
            result = fn(**kwargs)
    except TypeError as exc:
        return {
            "ok": False,
            "platform": key,
            "action": act,
            "status": "invalid_args",
            "message": str(exc)[:300],
        }
    except Exception as exc:
        if record_activity:
            global_platform_activity.record(
                platform=key,
                task=f"{key}.{act}",
                agent_type=agent_type,
                workflow_stage="platform_api",
                completion_status="failed",
                api_response_status="error",
                recent_activity=f"{key}.{act} failed",
                errors=str(exc)[:200],
            )
        return {
            "ok": False,
            "platform": key,
            "action": act,
            "status": "error",
            "message": str(exc)[:300],
        }

    if not isinstance(result, dict):
        result = {"result": result}
    out = dict(result)
    out.setdefault("platform", key)
    out.setdefault("action", act)
    status = out.get("status")
    if "ok" not in out:
        out["ok"] = status in {"ok", "configured", "public"} or out.get("configured") is True

    if record_activity and act not in {"status"}:
        completion = (
            "completed"
            if out.get("ok") or status in {"ok", "configured"}
            else "configuration_required"
            if status == "configuration_required"
            else "failed"
        )
        global_platform_activity.record(
            platform=key,
            task=f"{key}.{act}",
            agent_type=agent_type,
            workflow_stage="platform_api",
            completion_status=completion,
            api_response_status=str(out.get("api_response_status") or status),
            recent_activity=out.get("message") or f"{key}.{act}",
            errors=out.get("message") if completion == "failed" else None,
        )
    return out
