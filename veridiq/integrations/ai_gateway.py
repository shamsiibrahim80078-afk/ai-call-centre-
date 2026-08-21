"""AI Gateway — wraps existing LLM providers with task-typed fallback chains.

Does not replace individual provider connectors. Agents should prefer
``ai_gateway.generate`` for multi-provider resilience.
"""

from __future__ import annotations

from typing import Any, Optional

from veridiq.integrations.base import status_shape

PLATFORM = "ai_gateway"
DISPLAY = "AI Gateway"
CATEGORY = "ai"
ENV_VARS: tuple[str, ...] = ()  # inherits from underlying providers
CAPABILITIES = ["generate", "status", "fallback_chain"]
DOCS = None

# task_type -> ordered provider module names under veridiq.integrations.llm
TASK_CHAINS: dict[str, tuple[str, ...]] = {
    "fast": ("groq", "fireworks", "together", "mistral", "openrouter", "google_ai", "cohere", "huggingface"),
    "reason": ("openrouter", "mistral", "together", "google_ai", "groq", "fireworks", "cohere"),
    "research": ("openrouter", "google_ai", "mistral", "together", "groq", "fireworks"),
    "vision": ("google_ai", "openrouter", "huggingface", "together", "fireworks"),
    "voice": ("assemblyai", "deepgram"),  # speech — generate falls back to note
}


def _load_provider(name: str):
    import importlib

    return importlib.import_module(f"veridiq.integrations.llm.{name}")


def _configured_providers() -> list[str]:
    configured: list[str] = []
    seen: set[str] = set()
    for chain in TASK_CHAINS.values():
        for name in chain:
            if name in seen:
                continue
            seen.add(name)
            try:
                mod = _load_provider(name)
                st = mod.status()
                if st.get("configured"):
                    configured.append(name)
            except Exception:
                continue
    return configured


def status() -> dict[str, Any]:
    configured = _configured_providers()
    if not configured:
        return status_shape(
            PLATFORM,
            DISPLAY,
            CATEGORY,
            status="configuration_required",
            configured=False,
            message="No underlying LLM/speech providers configured. Set provider API keys (e.g. VERIDIQ_GROQ_API_KEY).",
            env_vars=ENV_VARS,
            capabilities=CAPABILITIES,
            docs_url=DOCS,
            extra={"configured_providers": [], "task_types": sorted(TASK_CHAINS.keys())},
        )
    return status_shape(
        PLATFORM,
        DISPLAY,
        CATEGORY,
        status="configured",
        configured=True,
        message=f"AI Gateway ready with {len(configured)} provider(s): {', '.join(configured[:8])}.",
        env_vars=ENV_VARS,
        capabilities=CAPABILITIES,
        docs_url=DOCS,
        extra={"configured_providers": configured, "task_types": sorted(TASK_CHAINS.keys())},
    )


def test_connection() -> dict[str, Any]:
    st = status()
    if not st.get("configured"):
        return {
            "platform": PLATFORM,
            "status": "configuration_required",
            "ok": False,
            "message": st.get("message"),
            "configured_providers": [],
        }
    # Probe first configured text provider with a tiny generate
    providers = st.get("configured_providers") or []
    text_providers = [p for p in providers if p not in {"assemblyai", "deepgram"}]
    if not text_providers:
        return {
            "platform": PLATFORM,
            "status": "configuration_required",
            "ok": False,
            "message": "Only speech providers configured; set a text LLM key for generate.",
            "configured_providers": providers,
        }
    result = generate(prompt="ping", task_type="fast", max_providers=1)
    return {
        "platform": PLATFORM,
        "status": result.get("status"),
        "ok": result.get("ok", False),
        "message": result.get("message") or "AI Gateway probe complete.",
        "provider_used": result.get("provider_used"),
        "attempts": result.get("attempts"),
        "configured_providers": providers,
    }


def generate(
    *,
    prompt: str,
    task_type: str = "fast",
    stream: bool = False,
    max_providers: int = 4,
    model: Optional[str] = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Generate text via fallback chain. Streaming not implemented — non-stream first."""
    q = (prompt or "").strip()
    if not q:
        return {
            "platform": PLATFORM,
            "status": "invalid_args",
            "ok": False,
            "message": "prompt is required.",
        }
    if stream:
        # Honest: stream path not wired yet
        pass

    task = (task_type or "fast").strip().lower()
    chain = TASK_CHAINS.get(task) or TASK_CHAINS["fast"]
    if task == "voice":
        return {
            "platform": PLATFORM,
            "status": "invalid_args",
            "ok": False,
            "message": "task_type=voice uses speech providers (transcribe). Use assemblyai.transcribe / deepgram.transcribe, or task_type=fast|reason|research|vision.",
            "task_type": task,
        }

    attempts: list[dict[str, Any]] = []
    tried = 0
    for name in chain:
        if tried >= max(1, int(max_providers)):
            break
        try:
            mod = _load_provider(name)
            st = mod.status()
            if not st.get("configured"):
                continue
            tried += 1
            gen_kwargs: dict[str, Any] = {"prompt": q[:12000]}
            if model:
                gen_kwargs["model"] = model
            # pass through harmless extras
            for k in ("temperature", "max_tokens"):
                if k in kwargs:
                    gen_kwargs[k] = kwargs[k]
            if not hasattr(mod, "generate_text"):
                attempts.append({"provider": name, "status": "skipped", "message": "no generate_text"})
                continue
            result = mod.generate_text(**gen_kwargs)
            attempts.append(
                {
                    "provider": name,
                    "status": result.get("status"),
                    "message": (result.get("message") or "")[:120],
                }
            )
            if result.get("status") == "ok" and result.get("ok", True):
                out = {
                    "platform": PLATFORM,
                    "status": "ok",
                    "ok": True,
                    "task_type": task,
                    "provider_used": name,
                    "text": result.get("text"),
                    "model": result.get("model"),
                    "streamed": False,
                    "message": f"Generated via {name} (task_type={task}).",
                    "attempts": attempts,
                    "api_response_status": result.get("api_response_status"),
                }
                return out
        except Exception as exc:
            attempts.append({"provider": name, "status": "error", "message": str(exc)[:120]})

    if not attempts:
        return {
            "platform": PLATFORM,
            "status": "configuration_required",
            "ok": False,
            "task_type": task,
            "message": f"No configured providers in chain for task_type={task}.",
            "attempts": attempts,
            "streamed": False,
        }
    return {
        "platform": PLATFORM,
        "status": "error",
        "ok": False,
        "task_type": task,
        "message": f"All {len(attempts)} provider attempt(s) failed for task_type={task}.",
        "attempts": attempts,
        "streamed": False,
    }
