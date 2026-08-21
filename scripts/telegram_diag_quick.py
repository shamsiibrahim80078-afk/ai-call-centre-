"""Quick Telegram connectivity diagnostic (loads .env, no secrets printed)."""
from __future__ import annotations

import json
import os
import sys
import time
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
from veridiq.integrations.telegram_listener import listener_status  # noqa: E402


def main() -> None:
    probe = telegram.connectivity_probe(listener_fast=True)
    listener = listener_status(include_webhook=True, probe_api=False)

    if probe.get("api_reachable"):
        summary = f"OK — api.telegram.org reachable (@{probe.get('bot_username') or '?'})."
    elif probe.get("token_configured"):
        summary = (
            "BLOCKED — api.telegram.org unreachable from this PC. "
            "Use VPN or set VERIDIQ_TELEGRAM_PROXY / HTTPS_PROXY."
        )
    else:
        summary = f"NOT CONFIGURED — set {telegram.BOT_TOKEN}."
    print(f"SUMMARY: {summary}")
    print(
        f"proxy: {'set (' + str(probe.get('proxy_source') or 'env') + ')' if probe.get('proxy_configured') else 'none'}"
    )
    print(
        f"listener: enabled={listener.get('enabled')} running={listener.get('running')} "
        f"failures={listener.get('consecutive_failures', 0)}"
    )
    print(f"getMe: status={probe.get('get_me_status')} elapsed={probe.get('elapsed_sec', '?')}s")
    if probe.get("message") and not probe.get("api_reachable"):
        print(f"  detail: {probe['message']}")

    t1 = time.time()
    wh = telegram.get_webhook_info(listener_fast=True)
    print(f"webhook: status={wh.get('status')} url={wh.get('url')!r} elapsed={time.time()-t1:.1f}s")
    if wh.get("pending_update_count") is not None:
        print(f"  pending_update_count={wh.get('pending_update_count')}")

    t2 = time.time()
    upd = telegram.get_updates(timeout_sec=0, listener_fast=True)
    print(
        f"getUpdates: status={upd.get('status')} count={len(upd.get('result') or [])} "
        f"elapsed={time.time()-t2:.1f}s"
    )
    if upd.get("status") != "ok" and upd.get("message"):
        print(f"  error: {upd['message']}")
    for u in upd.get("result") or []:
        m = u.get("message") or u.get("edited_message") or {}
        chat = m.get("chat") or {}
        print(
            f"  update_id={u.get('update_id')} chat_id={chat.get('id')} "
            f"title={chat.get('title')!r} thread={m.get('message_thread_id')} "
            f"text={json.dumps((m.get('text') or '')[:80])}"
        )

    print(f"\nAPI status endpoint: GET /api/v1/veridiq/integrations/telegram/listener")


if __name__ == "__main__":
    main()
