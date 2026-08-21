"""Shared helpers for platform integration modules — consistent status shape, env lookup."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

_ENV_LOADED = False


def ensure_dotenv_loaded() -> None:
    """Load repo-root ``.env`` into ``os.environ`` (setdefault) if not already done.

    Mirrors ``app.py`` so research / connectors see keys even when imported
    without going through the FastAPI entrypoint.
    """
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if env_path.exists():
        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if not key:
                    continue
                # Fill missing or blank values so empty placeholders don't block real keys.
                if not (os.environ.get(key) or "").strip():
                    os.environ[key] = val
        except OSError:
            pass
    _ENV_LOADED = True


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def first_env(*names: str) -> Optional[str]:
    for name in names:
        val = os.environ.get(name)
        if val is None:
            continue
        cleaned = val.strip().strip('"').strip("'")
        if cleaned:
            return cleaned
    return None


def status_shape(
    platform: str,
    display_name: str,
    category: str,
    *,
    status: str,
    configured: bool,
    message: Optional[str] = None,
    env_vars: Iterable[str] = (),
    capabilities: Iterable[str] = (),
    docs_url: Optional[str] = None,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "platform": platform,
        "display_name": display_name,
        "category": category,
        "status": status,
        "configured": configured,
        "message": message,
        "env_vars": list(env_vars),
        "capabilities": list(capabilities),
        "docs_url": docs_url,
        "timestamp": _utc_now(),
    }
    if extra:
        out.update(extra)
    return out


# Eager load so first_env never re-reads .env after tests (or operators) clear vars.
ensure_dotenv_loaded()
