"""Manual process_update + send_auto_reply smoke test (loads .env, no secrets printed)."""
from __future__ import annotations

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
from veridiq.integrations.telegram_listener import process_update  # noqa: E402


def main() -> None:
    me = telegram.get_me(listener_fast=True)
    print("getMe:", me.get("status"), me.get("message", ""))
    if me.get("status") != "ok":
        print("Cannot proceed — Telegram API unreachable.")
        return
    bot = me["result"]
    bot_id = bot.get("id")
    bot_username = bot.get("username") or ""
    print(f"  bot=@{bot_username} id={bot_id}")

    chat_id = os.getenv(telegram.DEFAULT_CHAT_ID, "@ibrahimshamsi1")
    fake_update = {
        "update_id": 999999001,
        "message": {
            "message_id": 1,
            "from": {"id": 123456789, "is_bot": False, "first_name": "TestUser"},
            "chat": {"id": chat_id, "type": "private", "username": "ibrahimshamsi1"},
            "text": "What is VeriDiQ?",
        },
    }
    print("process_update (fake inbound)...")
    result = process_update(
        fake_update,
        bot_id=bot_id,
        bot_username=bot_username,
        reply_only_mentions=False,
    )
    print("process_update result:", result)

    print("send_auto_reply direct test...")
    direct = telegram.send_auto_reply(
        chat_id=chat_id,
        text="VeriDiQ diagnostic test — if you see this, send path works.",
    )
    print("send_auto_reply:", direct.get("status"), direct.get("message", ""))


if __name__ == "__main__":
    main()
