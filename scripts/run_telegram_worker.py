#!/usr/bin/env python3
"""Production entrypoint: Telegram long-poll worker (Fly.io / Render / local).

Usage:
  python scripts/run_telegram_worker.py
  # or: python -m veridiq.integrations.telegram_listener

Requires VERIDIQ_TELEGRAM_BOT_TOKEN. Do not run alongside another getUpdates poller.
Deploy: docs/DEPLOY_TELEGRAM_FLY.md (preferred) or docs/DEPLOY_TELEGRAM_RENDER.md
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)


def main() -> None:
    from veridiq.integrations.base import ensure_dotenv_loaded

    ensure_dotenv_loaded()
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except ImportError:
        pass

    from veridiq.integrations.telegram_listener import run_telegram_listener_forever

    run_telegram_listener_forever()


if __name__ == "__main__":
    main()
