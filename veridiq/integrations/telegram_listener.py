"""Telegram inbound auto-reply + new-member welcome — long-polling getUpdates."""

from __future__ import annotations

import logging
import os
import signal
import threading
import time
from typing import Any, Callable, Optional

from veridiq.integrations import telegram
from veridiq.marketing.human_voice import build_community_reply

logger = logging.getLogger(__name__)

_SERVICE_MESSAGE_KEYS = frozenset(
    {
        "new_chat_members",
        "left_chat_member",
        "new_chat_title",
        "new_chat_photo",
        "delete_chat_photo",
        "group_chat_created",
        "supergroup_chat_created",
        "channel_chat_created",
        "migrate_to_chat_id",
        "migrate_from_chat_id",
        "pinned_message",
        "video_chat_started",
        "video_chat_ended",
        "video_chat_participants_invited",
        "message_auto_delete_timer_changed",
    }
)

_listener_lock = threading.Lock()
_listener: Optional["TelegramUpdateListener"] = None


def extract_message_text(message: dict[str, Any]) -> str:
    text = (message.get("text") or message.get("caption") or "").strip()
    return text


def member_display_name(user: dict[str, Any]) -> str:
    """Prefer first_name, then username, then a friendly fallback."""
    first = (user.get("first_name") or "").strip()
    if first:
        return first
    username = (user.get("username") or "").strip().lstrip("@")
    if username:
        return username
    last = (user.get("last_name") or "").strip()
    if last:
        return last
    return "friend"


def build_welcome_text(user: dict[str, Any]) -> str:
    name = member_display_name(user)
    return (
        f"Welcome, {name}! Glad you're here. "
        "Ask me anything about VeriDiQ, verification, or just say hi — happy to help."
    )


def extract_new_members_to_welcome(
    message: dict[str, Any],
    *,
    bot_id: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Return human members from new_chat_members (skip bots / self)."""
    members = message.get("new_chat_members") or []
    if not isinstance(members, list):
        return []
    out: list[dict[str, Any]] = []
    for member in members:
        if not isinstance(member, dict):
            continue
        if member.get("is_bot"):
            continue
        if bot_id is not None and member.get("id") == bot_id:
            continue
        out.append(member)
    return out


def should_skip_message(
    message: dict[str, Any],
    *,
    bot_id: Optional[int],
    bot_username: str = "",
    reply_only_mentions: bool = False,
) -> Optional[str]:
    """Return a skip reason, or None if the message should be answered."""
    sender = message.get("from") or {}
    if sender.get("is_bot"):
        return "bot_message"
    if bot_id is not None and sender.get("id") == bot_id:
        return "self_message"
    if any(message.get(k) for k in _SERVICE_MESSAGE_KEYS):
        return "service_message"
    if message.get("sticker") and not extract_message_text(message):
        return "sticker_only"
    question = extract_message_text(message)
    if not question:
        return "empty_message"
    chat = message.get("chat") or {}
    chat_type = chat.get("type")
    if reply_only_mentions and chat_type in ("group", "supergroup"):
        username = (bot_username or "").lstrip("@").lower()
        mentioned = False
        if username:
            lower_q = question.lower()
            if f"@{username}" in lower_q:
                mentioned = True
        for entity in message.get("entities") or []:
            if entity.get("type") == "mention" and username:
                start = entity.get("offset", 0)
                end = start + entity.get("length", 0)
                mention = question[start:end].lstrip("@").lower()
                if mention == username:
                    mentioned = True
        reply_to = message.get("reply_to_message") or {}
        reply_from = reply_to.get("from") or {}
        if reply_from.get("id") == bot_id:
            mentioned = True
        if not mentioned:
            return "mention_required"
    return None


def build_reply_text(question: str) -> str:
    """Conversational community reply (Theo's voice) — fast heuristics, not robotic."""
    return build_community_reply(question)


def handle_inbound_message(
    message: dict[str, Any],
    *,
    bot_id: Optional[int] = None,
    bot_username: str = "",
    reply_only_mentions: bool = False,
) -> Optional[str]:
    """Return reply text for an inbound Telegram message, or None to skip."""
    skip = should_skip_message(
        message,
        bot_id=bot_id,
        bot_username=bot_username,
        reply_only_mentions=reply_only_mentions,
    )
    if skip:
        return None
    return build_reply_text(extract_message_text(message))


def process_welcome_members(
    message: dict[str, Any],
    *,
    bot_id: Optional[int],
    send_fn: Callable[..., dict[str, Any]] = telegram.send_auto_reply,
    log_fn: Optional[Callable[..., Any]] = None,
) -> list[dict[str, Any]]:
    """Send welcome messages for new_chat_members. Returns list of send results."""
    if not telegram.welcome_enabled():
        return []
    members = extract_new_members_to_welcome(message, bot_id=bot_id)
    if not members:
        return []
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None:
        return []
    thread_id = message.get("message_thread_id")
    results: list[dict[str, Any]] = []
    for member in members:
        text = build_welcome_text(member)
        send_kwargs: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if thread_id is not None:
            send_kwargs["message_thread_id"] = thread_id
        result = send_fn(**send_kwargs)
        results.append(result)
        if log_fn:
            name = member_display_name(member)
            completion = "completed" if result.get("status") == "ok" else "failed"
            log_fn(
                platform="telegram",
                task="New member welcome",
                agent_type="telegram_listener",
                workflow_stage="new_member_welcome",
                completion_status=completion,
                api_response_status=str(result.get("status") or result.get("api_response_status") or ""),
                recent_activity=f"Welcomed {name} in chat {chat_id}",
                errors=result.get("message") if result.get("status") != "ok" else None,
            )
    return results


def process_update(
    update: dict[str, Any],
    *,
    bot_id: Optional[int],
    bot_username: str,
    reply_only_mentions: bool,
    send_fn: Callable[..., dict[str, Any]] = telegram.send_auto_reply,
    log_fn: Optional[Callable[..., Any]] = None,
) -> Optional[dict[str, Any]]:
    """Process one Telegram update; returns the send result when a reply/welcome is posted."""
    message = update.get("message") or update.get("edited_message")
    if not message:
        return None

    # New members first (service messages are otherwise skipped by auto-reply).
    if message.get("new_chat_members"):
        welcome_results = process_welcome_members(
            message,
            bot_id=bot_id,
            send_fn=send_fn,
            log_fn=log_fn,
        )
        if welcome_results:
            # Return last send result for callers/tests; all were attempted.
            return welcome_results[-1]
        return None

    reply_text = handle_inbound_message(
        message,
        bot_id=bot_id,
        bot_username=bot_username,
        reply_only_mentions=reply_only_mentions,
    )
    if not reply_text:
        return None
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None:
        return None
    question = extract_message_text(message)
    thread_id = message.get("message_thread_id")
    send_kwargs: dict[str, Any] = {
        "chat_id": chat_id,
        "text": reply_text,
        "reply_to_message_id": message.get("message_id"),
    }
    if thread_id is not None:
        send_kwargs["message_thread_id"] = thread_id
    result = send_fn(**send_kwargs)
    if log_fn:
        completion = "completed" if result.get("status") == "ok" else "failed"
        log_fn(
            platform="telegram",
            task="Inbound chat auto-reply",
            agent_type="telegram_listener",
            workflow_stage="inbound_auto_reply",
            completion_status=completion,
            api_response_status=str(result.get("status") or result.get("api_response_status") or ""),
            recent_activity=f"Replied in chat {chat_id}: {question[:120]}",
            errors=result.get("message") if result.get("status") != "ok" else None,
        )
    return result


class TelegramUpdateListener:
    """Background long-poll loop for Telegram inbound Q&A + welcomes."""

    def __init__(self) -> None:
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._offset: Optional[int] = None
        self._bot_id: Optional[int] = None
        self._bot_username = ""
        self._consecutive_failures = 0
        self._last_error_log_at = 0.0

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        if not telegram.listener_enabled():
            logger.info("Telegram listener disabled or bot token missing — not started.")
            return False
        if self.running:
            return True
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="veridiq-telegram-listener",
        )
        self._thread.start()
        return True

    def stop(self, *, join_timeout: float = 6.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=join_timeout)
        self._thread = None

    def reset_offset(self) -> None:
        """Drop the stored update offset so the next poll can re-read pending updates."""
        self._offset = None
        logger.info("Telegram listener update offset reset.")

    def _should_log_failure(self, n: int) -> bool:
        """Rate-limit listener errors: 1st, every 30th, or at most one ERROR per 60s."""
        if n == 1 or n % 30 == 0:
            return True
        return (time.time() - self._last_error_log_at) >= 60.0

    def _record_api_failure(self, stage: str, message: str) -> None:
        self._consecutive_failures += 1
        n = self._consecutive_failures
        message = telegram.redact_telegram_secrets(message)
        lower = message.lower()
        if "conflict" in lower and "getupdates" in lower:
            hint = (
                "Another getUpdates poller is already running for this bot "
                "(local uvicorn, another worker, or a second script). Stop the other "
                "instance, or set VERIDIQ_TELEGRAM_LISTENER_IN_API=0 on the FastAPI app "
                "when a dedicated Render worker owns inbound updates."
            )
        else:
            hint = (
                "api.telegram.org may be unreachable from this machine — bot cannot receive or send messages. "
                "On Render, a Background Worker (long-poll) or Web Service (webhook) usually reaches Telegram "
                "without a local VPN. Locally, set VERIDIQ_TELEGRAM_PROXY (or HTTPS_PROXY/HTTP_PROXY) if blocked. "
                "Only one getUpdates poller should run (dedicated worker OR backend listener — not both)."
            )
        if self._should_log_failure(n):
            self._last_error_log_at = time.time()
            logger.error(
                "Telegram listener %s failed (%s consecutive): %s — %s",
                stage,
                n,
                message,
                hint,
            )
        else:
            logger.debug("Telegram listener %s failed (%s consecutive): %s", stage, n, message)

    def _record_api_success(self) -> None:
        if self._consecutive_failures:
            logger.info(
                "Telegram listener recovered after %s consecutive failure(s).",
                self._consecutive_failures,
            )
        self._consecutive_failures = 0

    def _ensure_bot_identity(self) -> bool:
        if self._bot_id is not None:
            return True
        me = telegram.get_me(listener_fast=True)
        if me.get("status") != "ok":
            self._record_api_failure("getMe", str(me.get("message") or "unknown"))
            return False
        bot = me.get("result") or {}
        self._bot_id = bot.get("id")
        self._bot_username = (bot.get("username") or "").strip()
        self._record_api_success()
        logger.info("Telegram listener bot identity: @%s id=%s", self._bot_username, self._bot_id)
        return self._bot_id is not None

    def _log_update(self, update: dict[str, Any]) -> None:
        message = update.get("message") or update.get("edited_message") or {}
        chat = message.get("chat") or {}
        text = extract_message_text(message)
        members = message.get("new_chat_members") or []
        extra = f" new_members={len(members)}" if members else ""
        logger.info(
            "Telegram update_id=%s chat_id=%s thread=%s text=%r%s",
            update.get("update_id"),
            chat.get("id"),
            message.get("message_thread_id"),
            text[:120],
            extra,
        )

    def _ensure_webhook_cleared(self) -> None:
        webhook = telegram.get_webhook_info(listener_fast=True)
        if webhook.get("status") == "ok" and webhook.get("url"):
            logger.warning(
                "Telegram webhook is set (%s) — removing so getUpdates long-polling works.",
                webhook.get("url"),
            )
            cleared = telegram.delete_webhook(drop_pending_updates=False)
            if cleared.get("status") != "ok":
                logger.warning("Could not delete Telegram webhook: %s", cleared.get("message"))

    def _run(self) -> None:
        from veridiq.integrations.activity import global_platform_activity

        logger.info(
            "Telegram listener started (auto_reply=%s welcome=%s).",
            telegram.auto_reply_enabled(),
            telegram.welcome_enabled(),
        )
        self._ensure_webhook_cleared()
        while not self._stop.is_set():
            if not self._ensure_bot_identity():
                if self._stop.wait(5):
                    break
                continue
            poll = telegram.get_updates(offset=self._offset, timeout_sec=25, listener_fast=True)
            if poll.get("status") != "ok":
                self._record_api_failure("getUpdates", str(poll.get("message") or "unknown"))
                if self._stop.wait(3):
                    break
                continue
            self._record_api_success()
            updates = poll.get("result") or []
            if not updates and self._offset is not None:
                logger.debug("Telegram getUpdates returned 0 updates (offset=%s).", self._offset)
            for update in updates:
                update_id = update.get("update_id")
                if isinstance(update_id, int):
                    self._offset = update_id + 1
                self._log_update(update)
                try:
                    process_update(
                        update,
                        bot_id=self._bot_id,
                        bot_username=self._bot_username,
                        reply_only_mentions=telegram.reply_only_mentions_enabled(),
                        log_fn=global_platform_activity.record,
                    )
                except Exception:
                    logger.exception("Telegram update handler failed for update_id=%s", update_id)
            if self._stop.is_set():
                break
        logger.info("Telegram inbound listener stopped.")


def start_telegram_listener() -> bool:
    global _listener
    with _listener_lock:
        if _listener is None:
            _listener = TelegramUpdateListener()
        elif _listener.running:
            return True
        return _listener.start()


def stop_telegram_listener() -> None:
    global _listener
    with _listener_lock:
        if _listener is not None:
            _listener.stop()
            _listener = None


def run_telegram_listener_forever() -> None:
    """Block the current process on the long-poll loop (Render Background Worker entrypoint).

    Unlike ``start_telegram_listener`` (daemon thread for the FastAPI lifespan), this keeps
    the process alive until SIGTERM/SIGINT and runs the poller on a non-daemon thread.
    """
    if not telegram.listener_enabled():
        raise SystemExit(
            "Telegram listener disabled — set VERIDIQ_TELEGRAM_BOT_TOKEN and leave "
            "VERIDIQ_TELEGRAM_AUTO_REPLY / VERIDIQ_TELEGRAM_WELCOME enabled (default on)."
        )
    if telegram.delivery_mode() == "webhook":
        raise SystemExit(
            "VERIDIQ_TELEGRAM_MODE=webhook — use the webhook web service "
            "(scripts/run_telegram_webhook.py), not the long-poll worker."
        )

    listener = TelegramUpdateListener()
    # Reuse the same start() path but keep a strong reference for signal handling.
    global _listener
    with _listener_lock:
        _listener = listener
    if not listener.start():
        raise SystemExit("Telegram listener failed to start.")

    stop_event = threading.Event()

    def _shutdown(*_args: Any) -> None:
        logger.info("Telegram worker received shutdown signal.")
        stop_event.set()
        listener.stop()

    signal.signal(signal.SIGTERM, _shutdown)
    try:
        signal.signal(signal.SIGINT, _shutdown)
    except (ValueError, OSError):
        pass

    logger.info("Telegram worker running forever (long-poll getUpdates).")
    while not stop_event.is_set():
        if not listener.running:
            logger.error("Telegram listener thread exited unexpectedly — restarting.")
            if not listener.start():
                time.sleep(5)
                continue
        stop_event.wait(2.0)
    with _listener_lock:
        if _listener is listener:
            _listener = None
    logger.info("Telegram worker exited cleanly.")


def listener_status(*, include_webhook: bool = False, probe_api: bool = False) -> dict[str, Any]:
    with _listener_lock:
        running = _listener.running if _listener else False
        offset = _listener._offset if _listener else None
        bot_username = _listener._bot_username if _listener else ""
        consecutive_failures = _listener._consecutive_failures if _listener else 0
    out: dict[str, Any] = {
        "enabled": telegram.listener_enabled(),
        "auto_reply": telegram.auto_reply_enabled(),
        "welcome": telegram.welcome_enabled(),
        "running": running,
        "reply_only_mentions": telegram.reply_only_mentions_enabled(),
        "update_offset": offset,
        "bot_username": bot_username,
        "consecutive_failures": consecutive_failures,
        "proxy_configured": telegram.http_proxies() is not None,
        "delivery_mode": telegram.delivery_mode(),
        "privacy_note": (
            "Bot must be a group admin. If join events are missing, disable privacy mode "
            "via BotFather: /setprivacy → Disable."
        ),
    }
    if probe_api:
        probe = telegram.connectivity_probe(listener_fast=True)
        out["api_reachable"] = probe.get("api_reachable")
        out["connectivity_message"] = probe.get("message")
        out["get_me_status"] = probe.get("get_me_status")
    if include_webhook:
        webhook = telegram.get_webhook_info(listener_fast=True)
        out["webhook_url"] = webhook.get("url") if webhook.get("status") == "ok" else None
    return out


def main() -> None:
    """``python -m veridiq.integrations.telegram_listener`` — production long-poll worker."""
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    from veridiq.integrations.base import ensure_dotenv_loaded

    ensure_dotenv_loaded()
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    run_telegram_listener_forever()


if __name__ == "__main__":
    main()
