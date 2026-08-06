#!/usr/bin/env python3
"""Production entrypoint: Telegram webhook Web Service (Render).

Usage:
  python scripts/run_telegram_webhook.py

Sets Telegram setWebhook on boot using VERIDIQ_TELEGRAM_WEBHOOK_URL or
RENDER_EXTERNAL_URL + VERIDIQ_TELEGRAM_WEBHOOK_PATH.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    from veridiq.integrations.base import ensure_dotenv_loaded

    ensure_dotenv_loaded()
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except ImportError:
        pass

    # Force webhook mode semantics for this process.
    os.environ.setdefault("VERIDIQ_TELEGRAM_MODE", "webhook")

    import uvicorn

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "10000"))
    uvicorn.run(
        "veridiq.integrations.telegram_webhook_app:app",
        host=host,
        port=port,
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )


if __name__ == "__main__":
    main()
