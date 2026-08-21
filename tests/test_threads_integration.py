"""Threads (Meta) integration — honest configuration_required without keys."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from veridiq.integrations import threads  # noqa: E402
from veridiq.integrations.platform_api import PLATFORM_ACTIONS, dispatch  # noqa: E402
from veridiq.integrations.registry import TEST_FUNCS, all_integrations  # noqa: E402


def test_threads_status_configuration_required_without_keys(monkeypatch):
    monkeypatch.delenv(threads.ACCESS_TOKEN, raising=False)
    monkeypatch.delenv(threads.THREADS_USER_ID, raising=False)
    result = threads.status()
    assert result["platform"] == "threads"
    assert result["status"] == "configuration_required"
    assert result["configured"] is False
    assert threads.ACCESS_TOKEN in result["env_vars"]
    assert threads.THREADS_USER_ID in result["env_vars"]
    assert result["message"]


def test_threads_test_connection_configuration_required_without_token(monkeypatch):
    monkeypatch.delenv(threads.ACCESS_TOKEN, raising=False)
    result = threads.test_connection()
    assert result["status"] == "configuration_required"
    assert threads.ACCESS_TOKEN in result["message"]


def test_threads_publish_text_configuration_required_without_keys(monkeypatch):
    monkeypatch.delenv(threads.ACCESS_TOKEN, raising=False)
    monkeypatch.delenv(threads.THREADS_USER_ID, raising=False)
    result = threads.publish_text(text="Hello Threads")
    assert result["status"] == "configuration_required"
    assert "VERIDIQ_THREADS" in result["message"]


def test_threads_reply_configuration_required_without_keys(monkeypatch):
    monkeypatch.delenv(threads.ACCESS_TOKEN, raising=False)
    monkeypatch.delenv(threads.THREADS_USER_ID, raising=False)
    result = threads.reply_to_post(text="Nice point", reply_to_id="12345")
    assert result["status"] == "configuration_required"


def test_threads_reply_without_parent_id_is_unsupported(monkeypatch):
    monkeypatch.setenv(threads.ACCESS_TOKEN, "tok")
    monkeypatch.setenv(threads.THREADS_USER_ID, "99")
    result = threads.reply_to_post(text="hi", reply_to_id="")
    assert result["status"] == "unsupported"


def test_threads_in_registry_and_platform_actions(monkeypatch):
    monkeypatch.delenv(threads.ACCESS_TOKEN, raising=False)
    assert "threads" in TEST_FUNCS
    assert "threads" in PLATFORM_ACTIONS
    assert set(PLATFORM_ACTIONS["threads"].keys()) >= {"status", "test", "publish_text", "reply"}
    board = all_integrations(force_refresh=True)
    platforms = {i["platform"] for i in board["integrations"]}
    assert "threads" in platforms
    status = dispatch("threads", "status")
    assert status["status"] == "configuration_required"


def test_threads_authorize_url_uses_app_id(monkeypatch):
    monkeypatch.setenv(threads.APP_ID, "1026312886913915")
    monkeypatch.setenv(threads.REDIRECT_URI, "https://localhost/")
    url = threads.authorize_url()
    assert "client_id=1026312886913915" in url
    assert "redirect_uri=https%3A%2F%2Flocalhost%2F" in url
    assert "threads_basic" in url
    assert "threads_content_publish" in url
    assert "threads_manage_replies" in url
    assert url.startswith("https://threads.com/oauth/authorize?")


def test_threads_exchange_code_requires_app_secret(monkeypatch):
    monkeypatch.setenv(threads.APP_ID, "1026312886913915")
    monkeypatch.delenv(threads.APP_SECRET, raising=False)
    result = threads.exchange_code("fake-code")
    assert result["status"] == "configuration_required"
    assert threads.APP_SECRET in result["message"]
