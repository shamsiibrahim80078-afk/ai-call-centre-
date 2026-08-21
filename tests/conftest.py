"""Shared pytest configuration.

Sets `VERIDIQ_MIN_VISIBLE_SEC=0` *before* `app`/`veridiq` are imported by any
test module, so the worker-pool visibility floor (see
`veridiq/workforce/pool.py`) — which intentionally holds a worker "busy" for a
few seconds after a real run finishes, so the Agent Workspace / Live pages can
actually observe it — doesn't make the shared, in-process `global_worker_pool`
singleton bleed "busy" state across unrelated tests that run within that
window. Tests that specifically want to exercise the visibility floor pass an
explicit `min_visible_sec` to `run_agent_task` / `start_agent_task` instead of
relying on this env default.
"""

from __future__ import annotations

import os

os.environ.setdefault("VERIDIQ_MIN_VISIBLE_SEC", "0")
os.environ.setdefault("VERIDIQ_MARKETING_MIN_VISIBLE_SEC", "0")
# Keep pytest from starting the real Telegram long-poll listener when TestClient
# opens the FastAPI lifespan (token may be present in local .env).
os.environ.setdefault("VERIDIQ_TELEGRAM_AUTO_REPLY", "0")
