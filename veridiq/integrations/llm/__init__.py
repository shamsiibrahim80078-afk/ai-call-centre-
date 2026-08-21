"""AI / LLM / speech provider connectors — official HTTP APIs only.

Each submodule exposes ``status``, ``test_connection``, and a minimal usable
action (``generate_text`` or ``transcribe``). Missing credentials always yield
``configuration_required``. Secrets live in env vars only.
"""

from __future__ import annotations

from typing import Any

from veridiq.integrations.llm import (
    assemblyai,
    cohere,
    deepgram,
    fireworks,
    google_ai,
    groq,
    huggingface,
    mistral,
    openrouter,
    together,
)

PROVIDERS = (
    google_ai,
    groq,
    openrouter,
    huggingface,
    cohere,
    mistral,
    together,
    fireworks,
    assemblyai,
    deepgram,
)


def all_ai_provider_statuses() -> list[dict[str, Any]]:
    return [mod.status() for mod in PROVIDERS]


__all__ = [
    "PROVIDERS",
    "all_ai_provider_statuses",
    "google_ai",
    "groq",
    "openrouter",
    "huggingface",
    "cohere",
    "mistral",
    "together",
    "fireworks",
    "assemblyai",
    "deepgram",
]
