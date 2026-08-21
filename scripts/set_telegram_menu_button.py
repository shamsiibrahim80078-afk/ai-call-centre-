#!/usr/bin/env python3
"""Set the Telegram bot Menu Button to open the VERIDIQ Mini App (HTTPS frontend).

Usage:
  python scripts/set_telegram_menu_button.py
  python scripts/set_telegram_menu_button.py --url https://your-frontend.example.com/mini
  python scripts/set_telegram_menu_button.py --text "Open VERIDIQ" --check

Requires:
  VERIDIQ_TELEGRAM_BOT_TOKEN
  VERIDIQ_TELEGRAM_MINIAPP_URL   (unless --url is passed)

This does NOT deploy the long-poll worker. Mini App = public HTTPS website only.
Docs: docs/TELEGRAM_MINI_APP.md
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_env = ROOT / ".env"
if _env.exists():
    for line in _env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))

from veridiq.integrations import telegram  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Set Telegram Menu Button → Mini App URL")
    parser.add_argument(
        "--url",
        default="",
        help=f"HTTPS Mini App URL (default: env {telegram.MINIAPP_URL})",
    )
    parser.add_argument("--text", default="Open VERIDIQ", help="Menu button label")
    parser.add_argument(
        "--chat-id",
        default="",
        help="Optional: set button for one chat only (default = all private chats)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only read current menu button via getChatMenuButton",
    )
    args = parser.parse_args()

    if not telegram.bot_token():
        print(f"ERROR: Set {telegram.BOT_TOKEN}", file=sys.stderr)
        return 1

    chat_id = args.chat_id.strip() or None

    if args.check:
        info = telegram.get_chat_menu_button(chat_id=chat_id)
        print(json.dumps(info, indent=2))
        return 0 if info.get("status") == "ok" else 1

    result = telegram.set_chat_menu_button(
        url=args.url.strip() or None,
        text=args.text,
        chat_id=chat_id,
    )
    print(json.dumps(result, indent=2))
    if result.get("status") != "ok":
        return 1

    verify = telegram.get_chat_menu_button(chat_id=chat_id)
    print("--- getChatMenuButton ---")
    print(json.dumps(verify, indent=2))
    print(
        "\nNext: open your bot in Telegram → tap the Menu / web_app button → Mini App loads."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
