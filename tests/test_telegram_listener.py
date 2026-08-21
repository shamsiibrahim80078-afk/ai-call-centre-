"""Telegram inbound auto-reply listener tests."""

from __future__ import annotations

import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from veridiq.integrations import telegram  # noqa: E402
from veridiq.integrations.telegram_listener import (  # noqa: E402
    build_reply_text,
    handle_inbound_message,
    process_update,
    should_skip_message,
)


def _user_message(**overrides) -> dict:
    base = {
        "message_id": 99,
        "from": {"id": 12345, "is_bot": False, "first_name": "Tester"},
        "chat": {"id": -1001, "type": "supergroup", "title": "Veridiq"},
        "text": "What is VeriDiQ?",
    }
    base.update(overrides)
    return base


def test_handle_inbound_message_produces_reply_text():
    reply = handle_inbound_message(_user_message(), bot_id=999, bot_username="Ibrahimshamsi_bot")
    assert reply
    assert "truth" in reply.lower() or "veridiq" in reply.lower()


def test_skips_bot_own_messages():
    msg = _user_message()
    msg["from"] = {"id": 999, "is_bot": True, "username": "Ibrahimshamsi_bot"}
    assert handle_inbound_message(msg, bot_id=999, bot_username="Ibrahimshamsi_bot") is None
    assert should_skip_message(msg, bot_id=999) == "bot_message"


def test_skips_empty_and_sticker_only():
    assert handle_inbound_message(_user_message(text="   "), bot_id=1) is None
    assert handle_inbound_message(_user_message(text=None, sticker={"file_id": "abc"}), bot_id=1) is None


def test_mention_only_mode_skips_unless_tagged():
    msg = _user_message(text="hello everyone")
    assert (
        handle_inbound_message(
            msg,
            bot_id=42,
            bot_username="Ibrahimshamsi_bot",
            reply_only_mentions=True,
        )
        is None
    )
    tagged = _user_message(text="hey @Ibrahimshamsi_bot what is rag?")
    reply = handle_inbound_message(
        tagged,
        bot_id=42,
        bot_username="Ibrahimshamsi_bot",
        reply_only_mentions=True,
    )
    assert reply
    assert len(reply) > 20


def test_process_update_mocks_send():
    sent = []

    def fake_send(**kwargs):
        sent.append(kwargs)
        return {"status": "ok", "message_id": 555}

    logged = []

    def fake_log(**kwargs):
        logged.append(kwargs)
        return {"id": 1}

    update = {"update_id": 7, "message": _user_message(text="How do uploads work?")}
    result = process_update(
        update,
        bot_id=999,
        bot_username="Ibrahimshamsi_bot",
        reply_only_mentions=False,
        send_fn=fake_send,
        log_fn=fake_log,
    )
    assert result and result["status"] == "ok"
    assert len(sent) == 1
    assert sent[0]["chat_id"] == -1001
    assert sent[0]["reply_to_message_id"] == 99
    assert sent[0]["text"]
    assert logged and logged[0]["platform"] == "telegram"
    assert logged[0]["workflow_stage"] == "inbound_auto_reply"


def test_process_update_forwards_message_thread_id_for_forum_topics():
    sent = []

    def fake_send(**kwargs):
        sent.append(kwargs)
        return {"status": "ok", "message_id": 556}

    update = {
        "update_id": 8,
        "message": _user_message(
            text="What is VeriDiQ?",
            message_thread_id=42,
            is_topic_message=True,
        ),
    }
    result = process_update(
        update,
        bot_id=999,
        bot_username="Ibrahimshamsi_bot",
        reply_only_mentions=False,
        send_fn=fake_send,
    )
    assert result and result["status"] == "ok"
    assert len(sent) == 1
    assert sent[0]["message_thread_id"] == 42
    assert sent[0]["chat_id"] == -1001
    assert sent[0]["reply_to_message_id"] == 99


def test_short_greeting_hi_gets_reply():
    reply = handle_inbound_message(_user_message(text="Hi"), bot_id=999, bot_username="Ibrahimshamsi_bot")
    assert reply
    assert "veridiq" in reply.lower() or "hi" in reply.lower()


def test_send_auto_reply_includes_message_thread_id(monkeypatch):
    monkeypatch.setenv(telegram.BOT_TOKEN, "bot123")
    captured = {}

    def fake_post(url, json=None, timeout=None, proxies=None, params=None):
        captured["payload"] = json
        class Resp:
            ok = True
            status_code = 200
            content = b'{"ok": true, "result": {"message_id": 1}}'

            @staticmethod
            def json():
                return {"ok": True, "result": {"message_id": 1}}

        return Resp()

    monkeypatch.setattr(telegram.requests, "post", fake_post)
    result = telegram.send_auto_reply(
        chat_id=-1001,
        text="Hello from test",
        reply_to_message_id=99,
        message_thread_id=42,
    )
    assert result["status"] == "ok"
    assert captured["payload"]["message_thread_id"] == 42
    assert captured["payload"]["reply_to_message_id"] == 99


def test_build_reply_text_is_fast_heuristic():
    text = build_reply_text("tell me about langgraph orchestration")
    assert "langgraph" in text.lower()


def test_welcome_text_includes_first_name():
    from veridiq.integrations.telegram_listener import build_welcome_text, member_display_name

    user = {"id": 55, "is_bot": False, "first_name": "Ayesha", "username": "ayesha_x"}
    assert member_display_name(user) == "Ayesha"
    text = build_welcome_text(user)
    assert "Welcome, Ayesha!" in text


def test_process_update_welcomes_new_chat_members(monkeypatch):
    monkeypatch.setenv(telegram.BOT_TOKEN, "bot123")
    monkeypatch.delenv(telegram.WELCOME, raising=False)
    assert telegram.welcome_enabled() is True

    sent = []

    def fake_send(**kwargs):
        sent.append(kwargs)
        return {"status": "ok", "message_id": 777}

    logged = []

    def fake_log(**kwargs):
        logged.append(kwargs)
        return {"id": 1}

    update = {
        "update_id": 42,
        "message": {
            "message_id": 10,
            "from": {"id": 1, "is_bot": False, "first_name": "Admin"},
            "chat": {"id": -10099, "type": "supergroup", "title": "Veridiq"},
            "new_chat_members": [
                {"id": 88, "is_bot": False, "first_name": "Bilal", "username": "bilal_v"},
                {"id": 999, "is_bot": True, "username": "some_bot"},
            ],
        },
    }
    result = process_update(
        update,
        bot_id=999,
        bot_username="Ibrahimshamsi_bot",
        reply_only_mentions=False,
        send_fn=fake_send,
        log_fn=fake_log,
    )
    assert result and result["status"] == "ok"
    assert len(sent) == 1  # human only; bot member skipped
    assert sent[0]["chat_id"] == -10099
    assert "Welcome, Bilal!" in sent[0]["text"]
    assert logged and logged[0]["workflow_stage"] == "new_member_welcome"


def test_welcome_disabled_skips_new_members(monkeypatch):
    monkeypatch.setenv(telegram.BOT_TOKEN, "bot123")
    monkeypatch.setenv(telegram.WELCOME, "0")
    assert telegram.welcome_enabled() is False
    sent = []

    update = {
        "update_id": 43,
        "message": {
            "message_id": 11,
            "chat": {"id": -10099, "type": "supergroup"},
            "new_chat_members": [{"id": 88, "is_bot": False, "first_name": "Noor"}],
        },
    }
    result = process_update(
        update,
        bot_id=999,
        bot_username="bot",
        reply_only_mentions=False,
        send_fn=lambda **kw: sent.append(kw) or {"status": "ok"},
    )
    assert result is None
    assert sent == []


def test_welcome_enabled_defaults_on_with_token(monkeypatch):
    monkeypatch.setenv(telegram.BOT_TOKEN, "bot123")
    monkeypatch.delenv(telegram.WELCOME, raising=False)
    assert telegram.welcome_enabled() is True
    monkeypatch.setenv(telegram.WELCOME, "0")
    assert telegram.welcome_enabled() is False
    # conftest often forces AUTO_REPLY=0; with welcome off, listener may be off too
    monkeypatch.setenv(telegram.AUTO_REPLY, "1")
    assert telegram.listener_enabled() is True
    monkeypatch.setenv(telegram.AUTO_REPLY, "0")
    monkeypatch.setenv(telegram.WELCOME, "1")
    assert telegram.listener_enabled() is True


def test_auto_reply_enabled_defaults_on_with_token(monkeypatch):
    monkeypatch.setenv(telegram.BOT_TOKEN, "bot123")
    monkeypatch.delenv(telegram.AUTO_REPLY, raising=False)
    assert telegram.auto_reply_enabled() is True
    monkeypatch.setenv(telegram.AUTO_REPLY, "0")
    assert telegram.auto_reply_enabled() is False


def test_auto_reply_disabled_without_token(monkeypatch):
    monkeypatch.delenv(telegram.BOT_TOKEN, raising=False)
    assert telegram.auto_reply_enabled() is False


def test_http_proxies_precedence(monkeypatch):
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv(telegram.TELEGRAM_PROXY, raising=False)
    assert telegram.http_proxies() is None

    monkeypatch.setenv(telegram.TELEGRAM_PROXY, "http://127.0.0.1:7890")
    assert telegram.http_proxies() == {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"}

    monkeypatch.delenv(telegram.TELEGRAM_PROXY, raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.local:8080")
    assert telegram.http_proxies()["https"] == "http://proxy.local:8080"


def test_api_get_passes_proxies(monkeypatch):
    monkeypatch.setenv(telegram.BOT_TOKEN, "bot123")
    monkeypatch.setenv(telegram.TELEGRAM_PROXY, "http://127.0.0.1:7890")
    captured = {}

    def fake_get(url, params=None, timeout=None, proxies=None):
        captured["proxies"] = proxies

        class Resp:
            ok = True
            status_code = 200
            content = b'{"ok": true, "result": {"id": 1, "username": "testbot"}}'

            @staticmethod
            def json():
                return {"ok": True, "result": {"id": 1, "username": "testbot"}}

        return Resp()

    monkeypatch.setattr(telegram.requests, "get", fake_get)
    result = telegram.get_me(listener_fast=True)
    assert result["status"] == "ok"
    assert captured["proxies"] == {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"}


def test_redact_telegram_secrets_strips_bot_token_from_urls():
    raw = (
        "HTTPSConnectionPool(host='api.telegram.org', port=443): "
        "Max retries exceeded with url: /bot8805098849:AAHsecretTOKEN/getUpdates"
    )
    redacted = telegram.redact_telegram_secrets(raw)
    assert "8805098849" not in redacted
    assert "AAHsecretTOKEN" not in redacted
    assert "/bot***/getUpdates" in redacted


def test_get_me_redacts_token_in_exception_message(monkeypatch):
    monkeypatch.setenv(telegram.BOT_TOKEN, "8805098849:AAHsecretTOKEN")

    def fake_get(url, params=None, timeout=None, proxies=None):
        raise requests.exceptions.ReadTimeout(
            "HTTPSConnectionPool(host='api.telegram.org'): Read timed out. "
            "url: /bot8805098849:AAHsecretTOKEN/getMe"
        )

    monkeypatch.setattr(telegram.requests, "get", fake_get)
    result = telegram.get_me(listener_fast=True)
    assert result["status"] == "error"
    msg = result["message"]
    assert "8805098849" not in msg
    assert "/bot***/" in msg


def test_get_webhook_info_and_delete_webhook(monkeypatch):
    monkeypatch.setenv(telegram.BOT_TOKEN, "bot123")
    calls = []

    def fake_get(url, timeout=None, params=None, proxies=None):
        calls.append(("get", url))
        class Resp:
            ok = True
            status_code = 200
            content = b'{"ok": true, "result": {"url": "https://example.com/hook", "pending_update_count": 2}}'

            @staticmethod
            def json():
                return {"ok": True, "result": {"url": "https://example.com/hook", "pending_update_count": 2}}

        return Resp()

    def fake_post(url, params=None, timeout=None, json=None, proxies=None):
        calls.append(("post", url, params, json))
        class Resp:
            ok = True
            status_code = 200
            content = b'{"ok": true, "result": true}'

            @staticmethod
            def json():
                return {"ok": True, "result": True}

        return Resp()

    monkeypatch.setattr(telegram.requests, "get", fake_get)
    monkeypatch.setattr(telegram.requests, "post", fake_post)
    info = telegram.get_webhook_info(listener_fast=True)
    assert info["status"] == "ok"
    assert info["url"] == "https://example.com/hook"
    cleared = telegram.delete_webhook(drop_pending_updates=True)
    assert cleared["status"] == "ok"
    assert any(c[0] == "post" for c in calls)


def test_set_webhook_and_resolve_url(monkeypatch):
    monkeypatch.setenv(telegram.BOT_TOKEN, "bot123")
    monkeypatch.setenv(telegram.WEBHOOK_SECRET, "sec-xyz")
    monkeypatch.delenv(telegram.WEBHOOK_URL, raising=False)
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://tg.onrender.com")
    assert telegram.resolve_webhook_url() == "https://tg.onrender.com/telegram/webhook"

    posted = {}

    def fake_post(url, params=None, timeout=None, json=None, proxies=None):
        posted["url"] = url
        posted["json"] = json
        class Resp:
            ok = True
            status_code = 200
            content = b'{"ok": true, "result": true}'

            @staticmethod
            def json():
                return {"ok": True, "result": True}

        return Resp()

    monkeypatch.setattr(telegram.requests, "post", fake_post)
    result = telegram.set_webhook()
    assert result["status"] == "ok"
    assert posted["json"]["url"] == "https://tg.onrender.com/telegram/webhook"
    assert posted["json"]["secret_token"] == "sec-xyz"


def test_listener_in_api_respects_mode_and_flag(monkeypatch):
    monkeypatch.setenv(telegram.BOT_TOKEN, "bot123")
    monkeypatch.delenv(telegram.AUTO_REPLY, raising=False)
    monkeypatch.delenv(telegram.WELCOME, raising=False)
    monkeypatch.delenv(telegram.LISTENER_IN_API, raising=False)
    monkeypatch.setenv(telegram.TELEGRAM_MODE, "longpoll")
    assert telegram.listener_in_api_enabled() is True
    monkeypatch.setenv(telegram.LISTENER_IN_API, "0")
    assert telegram.listener_in_api_enabled() is False
    monkeypatch.setenv(telegram.LISTENER_IN_API, "1")
    monkeypatch.setenv(telegram.TELEGRAM_MODE, "webhook")
    assert telegram.listener_in_api_enabled() is False


def test_bot_token_alias(monkeypatch):
    monkeypatch.delenv(telegram.BOT_TOKEN, raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "alias-token")
    assert telegram.bot_token() == "alias-token"
