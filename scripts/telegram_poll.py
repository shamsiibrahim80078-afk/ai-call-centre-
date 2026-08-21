"""One-shot Telegram getMe / getUpdates poll for diagnostics."""
from __future__ import annotations

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


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--send-test", action="store_true", help="Send test auto-reply to default chat")
    parser.add_argument("--thread-id", type=int, default=None, help="Forum topic message_thread_id")
    args = parser.parse_args()

    me = telegram.get_me()
    print("getMe:", me.get("status"), me.get("message", ""))
    if me.get("status") == "ok":
        bot = me["result"]
        print(f"  bot @{bot.get('username')} id={bot.get('id')}")

    wh = telegram.get_webhook_info()
    if wh.get("status") == "ok":
        print(f"webhook url={wh.get('url')!r} pending={wh.get('pending_update_count')}")

    upd = telegram.get_updates(timeout_sec=0)
    print("getUpdates:", upd.get("status"), "count=", len(upd.get("result") or []))
    if upd.get("message"):
        print("  error:", upd["message"])
    thread_from_updates = None
    chat_from_updates = None
    for u in upd.get("result") or []:
        m = u.get("message") or u.get("edited_message") or {}
        chat = m.get("chat") or {}
        if m.get("message_thread_id") is not None:
            thread_from_updates = m.get("message_thread_id")
            chat_from_updates = chat.get("id")
        print(
            f"  update_id={u.get('update_id')} chat_id={chat.get('id')} "
            f"title={chat.get('title')!r} thread={m.get('message_thread_id')} "
            f"text={json.dumps((m.get('text') or '')[:80])}"
        )

    if args.send_test:
        chat_id = chat_from_updates or os.getenv(telegram.DEFAULT_CHAT_ID, "")
        thread_id = args.thread_id if args.thread_id is not None else thread_from_updates
        print(f"send_test chat_id={chat_id!r} thread_id={thread_id}")
        result = telegram.send_auto_reply(
            chat_id=chat_id,
            text="VeriDiQ auto-reply test — forum thread support is live. Ask: What is VeriDiQ?",
            message_thread_id=thread_id,
        )
        print("send_auto_reply:", result.get("status"), result.get("message", ""))


if __name__ == "__main__":
    main()
