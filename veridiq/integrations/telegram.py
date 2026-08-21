"""Telegram integration — official Bot API only. No scraping."""

from __future__ import annotations

import os
import re
import time
from typing import Any, Callable, Optional, TypeVar

import requests

from veridiq.integrations.base import status_shape

BOT_TOKEN = "VERIDIQ_TELEGRAM_BOT_TOKEN"
DEFAULT_CHAT_ID = "VERIDIQ_TELEGRAM_DEFAULT_CHAT_ID"
AUTO_REPLY = "VERIDIQ_TELEGRAM_AUTO_REPLY"
WELCOME = "VERIDIQ_TELEGRAM_WELCOME"
REPLY_ONLY_MENTIONS = "VERIDIQ_TELEGRAM_REPLY_ONLY_MENTIONS"
TELEGRAM_PROXY = "VERIDIQ_TELEGRAM_PROXY"
# Delivery mode for dedicated Render services: longpoll (default) | webhook
TELEGRAM_MODE = "VERIDIQ_TELEGRAM_MODE"
WEBHOOK_URL = "VERIDIQ_TELEGRAM_WEBHOOK_URL"
WEBHOOK_SECRET = "VERIDIQ_TELEGRAM_WEBHOOK_SECRET"
WEBHOOK_PATH = "VERIDIQ_TELEGRAM_WEBHOOK_PATH"
# When 0, FastAPI lifespan will not start the embedded long-poller (use dedicated worker/webhook).
LISTENER_IN_API = "VERIDIQ_TELEGRAM_LISTENER_IN_API"
ENV_VARS = [
    BOT_TOKEN,
    DEFAULT_CHAT_ID,
    AUTO_REPLY,
    WELCOME,
    REPLY_ONLY_MENTIONS,
    TELEGRAM_PROXY,
    TELEGRAM_MODE,
    WEBHOOK_URL,
    WEBHOOK_SECRET,
    WEBHOOK_PATH,
    LISTENER_IN_API,
]
# Optional aliases (same meaning; VERIDIQ_* preferred)
_BOT_TOKEN_ALIASES = ("TELEGRAM_BOT_TOKEN", "BOT_TOKEN")
_CHAT_ID_ALIASES = ("TELEGRAM_DEFAULT_CHAT_ID", "TELEGRAM_CHAT_ID")
API_TIMEOUT_SEC = 30
AUTO_REPLY_TIMEOUT_SEC = 20
LISTENER_CONNECT_TIMEOUT_SEC = 12
API_RETRIES = 5
LISTENER_CONNECT_RETRIES = 2
API_RETRY_DELAY_SEC = 3
LISTENER_RETRY_DELAY_SEC = 2
CAPABILITIES = [
    "send_message (after explicit comms approval)",
    "reply/comment in a group via reply_to_message_id (after explicit comms approval)",
    "get_updates (long-polling inbound auto-reply when VERIDIQ_TELEGRAM_AUTO_REPLY=1)",
    "welcome new_chat_members (when VERIDIQ_TELEGRAM_WELCOME=1; bot must see join events)",
    "webhook (setWebhook + HTTPS push — preferred on Render free/sleeping web)",
]
DOCS = "https://core.telegram.org/bots/api"


def bot_token() -> str:
    """Resolve bot token from VERIDIQ_TELEGRAM_BOT_TOKEN (preferred) or aliases."""
    from veridiq.integrations.base import first_env

    return (first_env(BOT_TOKEN, *_BOT_TOKEN_ALIASES) or "").strip()


def default_chat_id() -> str:
    from veridiq.integrations.base import first_env

    return (first_env(DEFAULT_CHAT_ID, *_CHAT_ID_ALIASES) or "").strip()


def delivery_mode() -> str:
    """Return ``longpoll`` (default) or ``webhook``."""
    raw = (os.getenv(TELEGRAM_MODE) or "longpoll").strip().lower()
    if raw in ("webhook", "hook", "push"):
        return "webhook"
    return "longpoll"


def webhook_path() -> str:
    path = (os.getenv(WEBHOOK_PATH) or "/telegram/webhook").strip() or "/telegram/webhook"
    if not path.startswith("/"):
        path = "/" + path
    return path


def resolve_webhook_url() -> str:
    """Public HTTPS URL for setWebhook — VERIDIQ_TELEGRAM_WEBHOOK_URL or RENDER_EXTERNAL_URL + path."""
    explicit = (os.getenv(WEBHOOK_URL) or "").strip()
    if explicit:
        return explicit.rstrip("/")
    base = (os.getenv("RENDER_EXTERNAL_URL") or "").strip().rstrip("/")
    if base:
        return f"{base}{webhook_path()}"
    return ""

T = TypeVar("T")

_BOT_TOKEN_IN_URL = re.compile(r"/bot[^/\s]+/", re.IGNORECASE)


def redact_telegram_secrets(text: str) -> str:
    """Redact bot tokens from URLs and exception text before logging or API responses."""
    if not text:
        return text
    return _BOT_TOKEN_IN_URL.sub("/bot***/", str(text))


def _safe_exc_message(exc: BaseException, *, limit: int = 200) -> str:
    return redact_telegram_secrets(str(exc)[:limit])


def http_proxies() -> Optional[dict[str, str]]:
    """Optional proxy for regions where api.telegram.org is blocked.

    Precedence: VERIDIQ_TELEGRAM_PROXY, then HTTPS_PROXY, then HTTP_PROXY.
    """
    proxy = (
        (os.getenv(TELEGRAM_PROXY) or "").strip()
        or (os.getenv("HTTPS_PROXY") or "").strip()
        or (os.getenv("HTTP_PROXY") or "").strip()
    )
    if not proxy:
        return None
    return {"http": proxy, "https": proxy}


def _request_timeout(
    *,
    listener_fast: bool = False,
    poll_timeout_sec: Optional[int] = None,
) -> tuple[float, float]:
    """(connect_timeout, read_timeout) — short connect avoids long hangs when blocked."""
    if poll_timeout_sec is not None:
        connect = float(LISTENER_CONNECT_TIMEOUT_SEC if listener_fast else 10)
        return connect, float(max(poll_timeout_sec + 5, connect + 1))
    if listener_fast:
        return float(LISTENER_CONNECT_TIMEOUT_SEC), float(AUTO_REPLY_TIMEOUT_SEC)
    return 10.0, float(API_TIMEOUT_SEC)


def _api_get(
    url: str,
    *,
    params: Optional[dict[str, Any]] = None,
    listener_fast: bool = False,
    poll_timeout_sec: Optional[int] = None,
    retries: Optional[int] = None,
    delay_sec: Optional[float] = None,
) -> requests.Response:
    timeout = _request_timeout(listener_fast=listener_fast, poll_timeout_sec=poll_timeout_sec)
    use_retries = retries if retries is not None else (_listener_retries() if listener_fast else API_RETRIES)
    use_delay = delay_sec if delay_sec is not None else (
        _listener_retry_delay_sec() if listener_fast else API_RETRY_DELAY_SEC
    )
    proxies = http_proxies()

    def _get() -> requests.Response:
        return requests.get(url, params=params, timeout=timeout, proxies=proxies)

    return _with_retries(_get, retries=use_retries, delay_sec=use_delay)


def _api_post(
    url: str,
    *,
    json: Optional[dict[str, Any]] = None,
    params: Optional[dict[str, Any]] = None,
    listener_fast: bool = False,
    retries: Optional[int] = None,
    delay_sec: Optional[float] = None,
    read_timeout_sec: Optional[float] = None,
) -> requests.Response:
    connect = float(LISTENER_CONNECT_TIMEOUT_SEC if listener_fast else 10)
    read = float(read_timeout_sec or (AUTO_REPLY_TIMEOUT_SEC if listener_fast else API_TIMEOUT_SEC))
    use_retries = retries if retries is not None else (_listener_retries() if listener_fast else API_RETRIES)
    use_delay = delay_sec if delay_sec is not None else (
        _listener_retry_delay_sec() if listener_fast else API_RETRY_DELAY_SEC
    )
    proxies = http_proxies()

    def _post() -> requests.Response:
        return requests.post(url, json=json, params=params, timeout=(connect, read), proxies=proxies)

    return _with_retries(_post, retries=use_retries, delay_sec=use_delay)


def _with_retries(
    fn: Callable[[], T],
    *,
    retries: int = API_RETRIES,
    delay_sec: float = API_RETRY_DELAY_SEC,
) -> T:
    last_exc: Optional[Exception] = None
    for attempt in range(1, max(1, retries) + 1):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(delay_sec)
    assert last_exc is not None
    raise last_exc


def status() -> dict[str, Any]:
    """Telegram's getMe call is free/lightweight, so status performs a real live check."""
    token = bot_token()
    if not token:
        return status_shape(
            "telegram",
            "Telegram",
            "messaging",
            status="configuration_required",
            configured=False,
            message=f"Set {BOT_TOKEN} (from @BotFather) to enable the official Telegram Bot API.",
            env_vars=ENV_VARS,
            capabilities=CAPABILITIES,
            docs_url=DOCS,
        )
    try:
        resp = _api_get(f"https://api.telegram.org/bot{token}/getMe", listener_fast=True)
        data = resp.json() if resp.content else {}
        if resp.ok and data.get("ok"):
            bot = data.get("result") or {}
            return status_shape(
                "telegram",
                "Telegram",
                "messaging",
                status="ok",
                configured=True,
                message=f"Bot @{bot.get('username', '?')} verified and reachable.",
                env_vars=ENV_VARS,
                capabilities=CAPABILITIES,
                docs_url=DOCS,
            )
        return status_shape(
            "telegram",
            "Telegram",
            "messaging",
            status="error",
            configured=True,
            message=f"Telegram API returned HTTP {resp.status_code}.",
            env_vars=ENV_VARS,
            capabilities=CAPABILITIES,
            docs_url=DOCS,
        )
    except Exception as exc:
        return status_shape(
            "telegram",
            "Telegram",
            "messaging",
            status="error",
            configured=True,
            message=(
                f"Telegram API unreachable: {_safe_exc_message(exc, limit=160)}. "
                f"If blocked, set {TELEGRAM_PROXY} or HTTPS_PROXY/HTTP_PROXY."
            ),
            env_vars=ENV_VARS,
            capabilities=CAPABILITIES,
            docs_url=DOCS,
        )


def test_connection() -> dict[str, Any]:
    result = status()
    return {
        "platform": "telegram",
        "status": result["status"],
        "message": result["message"],
        "api_response_status": result["status"],
    }


def send_message(
    *,
    chat_id: str,
    text: str,
    reply_to_message_id: Optional[int] = None,
    message_thread_id: Optional[int] = None,
) -> dict[str, Any]:
    """Send a real message via the official Telegram Bot API (`sendMessage`).

    Only ever invoked after explicit approval of a comms draft
    (`veridiq.comms.assistant.approve_external_action`, channel="telegram" or
    "telegram_comment"). `chat_id` may be a numeric chat id or a public
    `@channelusername`. When `reply_to_message_id` is set, the message is
    posted as a threaded reply — Telegram's group-chat equivalent of a
    comment on the original message (official Bot API parameter).
    """
    token = bot_token()
    if not token:
        return {"status": "configuration_required", "message": f"Set {BOT_TOKEN} to send Telegram messages."}
    if not (chat_id or "").strip():
        return {"status": "error", "message": "chat_id is required to send a Telegram message."}
    content = (text or "").strip()
    if not content:
        return {"status": "error", "message": "Message text is empty — nothing to send."}
    payload: dict[str, Any] = {"chat_id": chat_id, "text": content[:4096]}
    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id
    if message_thread_id is not None:
        payload["message_thread_id"] = message_thread_id
    try:
        resp = _api_post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json=payload,
        )
        data = resp.json() if resp.content else {}
        if resp.ok and data.get("ok"):
            message_id = (data.get("result") or {}).get("message_id")
            verb = "replied in" if reply_to_message_id else "sent to"
            return {"status": "ok", "message_id": message_id, "message": f"Telegram message {verb} {chat_id}."}
        return {
            "status": "error",
            "api_response_status": resp.status_code,
            "message": f"Telegram send failed: {data.get('description') or f'HTTP {resp.status_code}'}",
        }
    except Exception as exc:
        return {"status": "error", "message": f"Telegram send failed: {_safe_exc_message(exc)}"}


def auto_reply_enabled() -> bool:
    """Inbound chat auto-reply defaults on when a bot token is configured."""
    if not bot_token():
        return False
    val = (os.getenv(AUTO_REPLY, "1") or "1").strip().lower()
    return val in ("1", "true", "yes", "on")


def welcome_enabled() -> bool:
    """Welcome new group members. Defaults on when bot token is set; set VERIDIQ_TELEGRAM_WELCOME=0 to disable."""
    if not bot_token():
        return False
    val = (os.getenv(WELCOME, "1") or "1").strip().lower()
    return val in ("1", "true", "yes", "on")


def listener_enabled() -> bool:
    """Long-poll listener runs when auto-reply and/or welcome is enabled."""
    return auto_reply_enabled() or welcome_enabled()


def listener_in_api_enabled() -> bool:
    """Whether the FastAPI process should embed the long-poll thread (local default: on).

    Set ``VERIDIQ_TELEGRAM_LISTENER_IN_API=0`` on a Render web API when a dedicated
    Background Worker or webhook service owns inbound updates (only one getUpdates
    consumer / one webhook target allowed).
    """
    if not listener_enabled():
        return False
    if delivery_mode() == "webhook":
        return False
    val = (os.getenv(LISTENER_IN_API, "1") or "1").strip().lower()
    return val in ("1", "true", "yes", "on")


def reply_only_mentions_enabled() -> bool:
    val = (os.getenv(REPLY_ONLY_MENTIONS, "0") or "0").strip().lower()
    return val in ("1", "true", "yes", "on")


def _listener_retries() -> int:
    return LISTENER_CONNECT_RETRIES


def _listener_timeout_sec() -> int:
    return LISTENER_CONNECT_TIMEOUT_SEC


def _listener_retry_delay_sec() -> float:
    return float(LISTENER_RETRY_DELAY_SEC)


def get_webhook_info(*, listener_fast: bool = False) -> dict[str, Any]:
    """Return webhook configuration — a set webhook blocks getUpdates long-polling."""
    token = bot_token()
    if not token:
        return {"status": "configuration_required", "message": f"Set {BOT_TOKEN}."}
    try:
        resp = _api_get(
            f"https://api.telegram.org/bot{token}/getWebhookInfo",
            listener_fast=listener_fast,
        )
        data = resp.json() if resp.content else {}
        if resp.ok and data.get("ok"):
            info = data.get("result") or {}
            return {
                "status": "ok",
                "url": (info.get("url") or "").strip(),
                "pending_update_count": info.get("pending_update_count"),
                "last_error_message": info.get("last_error_message"),
            }
        return {
            "status": "error",
            "message": f"Telegram getWebhookInfo failed: {data.get('description') or f'HTTP {resp.status_code}'}",
        }
    except Exception as exc:
        return {"status": "error", "message": f"Telegram getWebhookInfo failed: {_safe_exc_message(exc)}"}


def delete_webhook(*, drop_pending_updates: bool = False) -> dict[str, Any]:
    """Remove webhook so getUpdates long-polling works."""
    token = bot_token()
    if not token:
        return {"status": "configuration_required", "message": f"Set {BOT_TOKEN}."}
    params = {"drop_pending_updates": "true" if drop_pending_updates else "false"}
    try:
        resp = _api_post(
            f"https://api.telegram.org/bot{token}/deleteWebhook",
            params=params,
            listener_fast=True,
        )
        data = resp.json() if resp.content else {}
        if resp.ok and data.get("ok"):
            return {"status": "ok", "message": "Telegram webhook removed."}
        return {
            "status": "error",
            "message": f"Telegram deleteWebhook failed: {data.get('description') or f'HTTP {resp.status_code}'}",
        }
    except Exception as exc:
        return {"status": "error", "message": f"Telegram deleteWebhook failed: {_safe_exc_message(exc)}"}


def set_webhook(
    *,
    url: Optional[str] = None,
    secret_token: Optional[str] = None,
    drop_pending_updates: bool = False,
    max_connections: int = 40,
) -> dict[str, Any]:
    """Register an HTTPS webhook URL (disables getUpdates until deleted)."""
    token = bot_token()
    if not token:
        return {"status": "configuration_required", "message": f"Set {BOT_TOKEN}."}
    target = (url or resolve_webhook_url()).strip()
    if not target:
        return {
            "status": "configuration_required",
            "message": (
                f"Set {WEBHOOK_URL} or RENDER_EXTERNAL_URL so Telegram can POST updates."
            ),
        }
    if not target.lower().startswith("https://"):
        return {"status": "error", "message": "Telegram webhook URL must be HTTPS."}
    secret = (secret_token if secret_token is not None else os.getenv(WEBHOOK_SECRET) or "").strip()
    payload: dict[str, Any] = {
        "url": target,
        "allowed_updates": ["message", "edited_message"],
        "drop_pending_updates": bool(drop_pending_updates),
        "max_connections": max(1, min(int(max_connections), 100)),
    }
    if secret:
        payload["secret_token"] = secret[:256]
    try:
        resp = _api_post(
            f"https://api.telegram.org/bot{token}/setWebhook",
            json=payload,
            listener_fast=True,
        )
        data = resp.json() if resp.content else {}
        if resp.ok and data.get("ok"):
            return {"status": "ok", "url": target, "message": f"Telegram webhook set to {target}."}
        return {
            "status": "error",
            "message": f"Telegram setWebhook failed: {data.get('description') or f'HTTP {resp.status_code}'}",
        }
    except Exception as exc:
        return {"status": "error", "message": f"Telegram setWebhook failed: {_safe_exc_message(exc)}"}


def get_me(*, listener_fast: bool = False) -> dict[str, Any]:
    """Lightweight bot identity lookup for the inbound listener."""
    token = bot_token()
    if not token:
        return {"status": "configuration_required", "message": f"Set {BOT_TOKEN}."}
    try:
        resp = _api_get(
            f"https://api.telegram.org/bot{token}/getMe",
            listener_fast=listener_fast,
        )
        data = resp.json() if resp.content else {}
        if resp.ok and data.get("ok"):
            return {"status": "ok", "result": data.get("result") or {}}
        return {
            "status": "error",
            "message": f"Telegram getMe failed: {data.get('description') or f'HTTP {resp.status_code}'}",
        }
    except Exception as exc:
        return {"status": "error", "message": f"Telegram getMe failed: {_safe_exc_message(exc)}"}


def get_updates(
    *,
    offset: Optional[int] = None,
    timeout_sec: int = 25,
    listener_fast: bool = False,
) -> dict[str, Any]:
    """Long-poll Telegram updates (`getUpdates`). Used by the inbound listener only."""
    token = bot_token()
    if not token:
        return {"status": "configuration_required", "message": f"Set {BOT_TOKEN}."}
    params: dict[str, Any] = {
        "timeout": max(0, min(timeout_sec, 50)),
        "allowed_updates": ["message", "edited_message"],
    }
    if offset is not None:
        params["offset"] = offset
    try:
        resp = _api_get(
            f"https://api.telegram.org/bot{token}/getUpdates",
            params=params,
            listener_fast=listener_fast,
            poll_timeout_sec=timeout_sec,
        )
        data = resp.json() if resp.content else {}
        if resp.ok and data.get("ok"):
            return {"status": "ok", "result": data.get("result") or []}
        return {
            "status": "error",
            "message": f"Telegram getUpdates failed: {data.get('description') or f'HTTP {resp.status_code}'}",
        }
    except Exception as exc:
        return {"status": "error", "message": f"Telegram getUpdates failed: {_safe_exc_message(exc)}"}


def send_auto_reply(
    *,
    chat_id: str | int,
    text: str,
    reply_to_message_id: Optional[int] = None,
    message_thread_id: Optional[int] = None,
) -> dict[str, Any]:
    """Fast outbound reply for inbound chat — not gated by comms/marketing approval."""
    token = bot_token()
    if not token:
        return {"status": "configuration_required", "message": f"Set {BOT_TOKEN} to send Telegram messages."}
    content = (text or "").strip()
    if not content:
        return {"status": "error", "message": "Message text is empty — nothing to send."}
    payload: dict[str, Any] = {"chat_id": chat_id, "text": content[:4096]}
    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id
    if message_thread_id is not None:
        payload["message_thread_id"] = message_thread_id
    try:
        resp = _api_post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json=payload,
            listener_fast=True,
        )
        data = resp.json() if resp.content else {}
        if resp.ok and data.get("ok"):
            message_id = (data.get("result") or {}).get("message_id")
            return {"status": "ok", "message_id": message_id, "message": f"Auto-replied in chat {chat_id}."}
        return {
            "status": "error",
            "api_response_status": resp.status_code,
            "message": f"Telegram auto-reply failed: {data.get('description') or f'HTTP {resp.status_code}'}",
        }
    except Exception as exc:
        return {"status": "error", "message": f"Telegram auto-reply failed: {_safe_exc_message(exc)}"}


def connectivity_probe(*, listener_fast: bool = True) -> dict[str, Any]:
    """One-shot reachability check for diagnostics and status endpoints (no secrets)."""
    proxy = http_proxies()
    out: dict[str, Any] = {
        "token_configured": bool(bot_token()),
        "proxy_configured": proxy is not None,
        "proxy_source": (
            TELEGRAM_PROXY
            if (os.getenv(TELEGRAM_PROXY) or "").strip()
            else ("HTTPS_PROXY" if (os.getenv("HTTPS_PROXY") or "").strip() else (
                "HTTP_PROXY" if (os.getenv("HTTP_PROXY") or "").strip() else None
            ))
        ),
        "api_reachable": False,
        "get_me_status": None,
        "message": "",
        "delivery_mode": delivery_mode(),
    }
    if not out["token_configured"]:
        out["message"] = f"Set {BOT_TOKEN} to test Telegram connectivity."
        return out
    if not proxy:
        out["message"] = (
            "No proxy configured — direct api.telegram.org required unless VPN is active."
        )
    else:
        out["message"] = f"Proxy configured via {out['proxy_source']}."
    t0 = time.time()
    me = get_me(listener_fast=listener_fast)
    out["elapsed_sec"] = round(time.time() - t0, 2)
    out["get_me_status"] = me.get("status")
    if me.get("status") == "ok":
        bot = me.get("result") or {}
        out["api_reachable"] = True
        out["bot_username"] = bot.get("username")
        out["message"] = f"api.telegram.org reachable — bot @{bot.get('username', '?')} verified."
    else:
        err = redact_telegram_secrets(str(me.get("message") or "unknown"))
        out["message"] = (
            f"api.telegram.org unreachable ({err}). "
            f"Use VPN or set {TELEGRAM_PROXY} / HTTPS_PROXY if Telegram is blocked."
        )
    return out
