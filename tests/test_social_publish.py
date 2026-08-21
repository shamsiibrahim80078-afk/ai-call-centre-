"""Real send/publish coverage for LinkedIn, X, Instagram, Telegram, WhatsApp, Marketing.

Missing credentials must report `configuration_required` (never a fabricated
success); mocked HTTP responses must produce a real "sent" result that is
logged to the activity feed; the comms draft/approve gate must block any send
until explicit approval.
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app  # noqa: E402
from veridiq.integrations import instagram, linkedin, marketing, telegram, whatsapp, x_twitter  # noqa: E402

client = TestClient(app)


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None, text="", headers=None):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.text = text
        self.headers = headers or {}
        self.content = b"x" if json_data is not None else b""
        self.ok = 200 <= status_code < 300

    def json(self):
        return self._json


# ---------------------------------------------------------------------------
# Missing credentials -> configuration_required (never fabricated)
# ---------------------------------------------------------------------------


def test_linkedin_share_post_requires_access_token(monkeypatch):
    monkeypatch.delenv(linkedin.ACCESS_TOKEN, raising=False)
    result = linkedin.share_post("Hello world")
    assert result["status"] == "configuration_required"
    assert linkedin.ACCESS_TOKEN in result["message"]


def test_linkedin_share_post_rejects_empty_text(monkeypatch):
    monkeypatch.setenv(linkedin.ACCESS_TOKEN, "tok")
    monkeypatch.setenv(linkedin.PERSON_URN, "urn:li:person:abc")
    result = linkedin.share_post("   ")
    assert result["status"] == "error"


def test_x_post_tweet_requires_oauth1_credentials(monkeypatch):
    for var in x_twitter.POST_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    result = x_twitter.post_tweet("Hello world")
    assert result["status"] == "configuration_required"
    assert x_twitter.ACCESS_TOKEN in result["message"]


def test_instagram_publish_requires_credentials(monkeypatch):
    monkeypatch.delenv(instagram.ACCESS_TOKEN, raising=False)
    monkeypatch.delenv(instagram.IG_USER_ID, raising=False)
    result = instagram.publish_media(caption="hi", image_url="https://example.com/x.jpg")
    assert result["status"] == "configuration_required"


def test_instagram_publish_requires_image_url_when_configured(monkeypatch):
    monkeypatch.setenv(instagram.ACCESS_TOKEN, "tok")
    monkeypatch.setenv(instagram.IG_USER_ID, "123")
    result = instagram.publish_media(caption="hi", image_url="")
    assert result["status"] == "error"


def test_telegram_send_message_requires_bot_token(monkeypatch):
    monkeypatch.delenv(telegram.BOT_TOKEN, raising=False)
    result = telegram.send_message(chat_id="123", text="hi")
    assert result["status"] == "configuration_required"


def test_whatsapp_send_message_requires_credentials(monkeypatch):
    monkeypatch.delenv(whatsapp.TOKEN, raising=False)
    monkeypatch.delenv(whatsapp.PHONE_NUMBER_ID, raising=False)
    result = whatsapp.send_message(to="+15551234567", text="hi")
    assert result["status"] == "configuration_required"


def test_marketing_send_campaign_requires_key_and_webhook(monkeypatch):
    monkeypatch.delenv(marketing.MARKETING_KEY, raising=False)
    monkeypatch.delenv(marketing.WEBHOOK_URL, raising=False)
    result = marketing.send_campaign(subject="s", body="b")
    assert result["status"] == "configuration_required"

    monkeypatch.setenv(marketing.MARKETING_KEY, "key")
    result2 = marketing.send_campaign(subject="s", body="b")
    assert result2["status"] == "configuration_required"
    assert marketing.WEBHOOK_URL in result2["message"]


# ---------------------------------------------------------------------------
# Mocked HTTP success -> real send + honest result shape
# ---------------------------------------------------------------------------


def test_linkedin_share_post_success_with_mocked_api(monkeypatch):
    monkeypatch.setenv(linkedin.ACCESS_TOKEN, "tok")
    monkeypatch.setenv(linkedin.PERSON_URN, "urn:li:person:abc123")

    def fake_post(url, headers=None, json=None, timeout=None):
        assert url == "https://api.linkedin.com/v2/ugcPosts"
        assert json["author"] == "urn:li:person:abc123"
        return _FakeResponse(201, json_data={}, headers={"x-restli-id": "post123"})

    monkeypatch.setattr(linkedin.requests, "post", fake_post)
    result = linkedin.share_post("Hello from VERIDIQ")
    assert result["status"] == "ok"
    assert result["post_id"] == "post123"


def test_x_post_tweet_success_with_mocked_api(monkeypatch):
    monkeypatch.setenv(x_twitter.API_KEY, "ck")
    monkeypatch.setenv(x_twitter.API_SECRET, "cs")
    monkeypatch.setenv(x_twitter.ACCESS_TOKEN, "at")
    monkeypatch.setenv(x_twitter.ACCESS_TOKEN_SECRET, "ats")

    def fake_post(url, headers=None, json=None, timeout=None):
        assert url == "https://api.twitter.com/2/tweets"
        assert headers["Authorization"].startswith("OAuth ")
        return _FakeResponse(201, json_data={"data": {"id": "tweet123", "text": json["text"]}})

    monkeypatch.setattr(x_twitter.requests, "post", fake_post)
    result = x_twitter.post_tweet("Hello from VERIDIQ")
    assert result["status"] == "ok"
    assert result["tweet_id"] == "tweet123"


def test_instagram_publish_success_with_mocked_api(monkeypatch):
    monkeypatch.setenv(instagram.ACCESS_TOKEN, "tok")
    monkeypatch.setenv(instagram.IG_USER_ID, "999")
    calls = []

    def fake_post(url, data=None, timeout=None):
        calls.append(url)
        if url.endswith("/999/media"):
            return _FakeResponse(200, json_data={"id": "container1"})
        if url.endswith("/999/media_publish"):
            return _FakeResponse(200, json_data={"id": "media1"})
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setattr(instagram.requests, "post", fake_post)
    result = instagram.publish_media(caption="hi", image_url="https://example.com/a.jpg")
    assert result["status"] == "ok"
    assert result["media_id"] == "media1"
    assert len(calls) == 2


def test_telegram_send_message_success_with_mocked_api(monkeypatch):
    monkeypatch.setenv(telegram.BOT_TOKEN, "bot123")

    def fake_post(url, json=None, timeout=None, proxies=None, params=None):
        assert url == "https://api.telegram.org/botbot123/sendMessage"
        return _FakeResponse(200, json_data={"ok": True, "result": {"message_id": 42}})

    monkeypatch.setattr(telegram.requests, "post", fake_post)
    result = telegram.send_message(chat_id="555", text="hi there")
    assert result["status"] == "ok"
    assert result["message_id"] == 42


def test_whatsapp_send_message_success_with_mocked_api(monkeypatch):
    monkeypatch.setenv(whatsapp.TOKEN, "wtok")
    monkeypatch.setenv(whatsapp.PHONE_NUMBER_ID, "phone1")

    def fake_post(url, headers=None, json=None, timeout=None):
        assert url == "https://graph.facebook.com/v19.0/phone1/messages"
        return _FakeResponse(200, json_data={"messages": [{"id": "wamid.123"}]})

    monkeypatch.setattr(whatsapp.requests, "post", fake_post)
    result = whatsapp.send_message(to="+15559999999", text="hi")
    assert result["status"] == "ok"
    assert result["message_id"] == "wamid.123"


def test_marketing_send_campaign_success_with_mocked_webhook(monkeypatch):
    monkeypatch.setenv(marketing.MARKETING_KEY, "mkey")
    monkeypatch.setenv(marketing.WEBHOOK_URL, "https://example.com/webhook")

    def fake_post(url, headers=None, json=None, timeout=None):
        assert url == "https://example.com/webhook"
        return _FakeResponse(202)

    monkeypatch.setattr(marketing.requests, "post", fake_post)
    result = marketing.send_campaign(subject="s", body="b")
    assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# Approval gate: draft-only until approved; approve routes to the real sender
# ---------------------------------------------------------------------------


def test_draft_never_sends_before_approval(monkeypatch):
    calls = []
    monkeypatch.setattr(telegram, "send_message", lambda **kw: (calls.append(kw), {"status": "ok"})[1])

    draft = client.post(
        "/api/v1/veridiq/comms/draft",
        json={"kind": "outreach", "context": "Telegram approval-gate smoke test", "recipient_hint": "12345"},
    ).json()
    assert draft["external_action_status"] == "draft_only"
    assert draft["requires_approval_before_send"] is True
    assert calls == []  # never sent without approval


def test_comms_approve_routes_to_telegram_when_configured(monkeypatch):
    monkeypatch.setenv(telegram.BOT_TOKEN, "bot123")

    def fake_post(url, json=None, timeout=None, proxies=None, params=None):
        return _FakeResponse(200, json_data={"ok": True, "result": {"message_id": 7}})

    monkeypatch.setattr(telegram.requests, "post", fake_post)

    draft = client.post(
        "/api/v1/veridiq/comms/draft",
        json={"kind": "outreach", "context": "Telegram send test", "recipient_hint": "998877"},
    ).json()
    approved = client.post(
        "/api/v1/veridiq/comms/approve",
        json={"draft_id": draft["draft_id"], "approved": True, "channel": "telegram"},
    ).json()
    assert approved["ok"] is True
    assert approved["status"] == "sent"
    assert approved["draft"]["send_attempt"]["status"] == "ok"

    activity = client.get("/api/v1/veridiq/integrations/activity", params={"platform": "telegram"}).json()
    assert activity["count"] >= 1
    assert activity["activity"][0]["completion_status"] == "completed"


def test_comms_approve_for_linkedin_without_credentials_reports_configuration_required(monkeypatch):
    monkeypatch.delenv(linkedin.ACCESS_TOKEN, raising=False)
    draft = client.post(
        "/api/v1/veridiq/comms/draft",
        json={"kind": "outreach", "context": "LinkedIn approval-gate smoke test"},
    ).json()
    approved = client.post(
        "/api/v1/veridiq/comms/approve",
        json={"draft_id": draft["draft_id"], "approved": True, "channel": "linkedin"},
    ).json()
    assert approved["ok"] is True
    assert approved["status"] == "approved_pending_integration"
    assert approved["draft"]["external_action_status"] == "approved_pending_integration"
    assert approved["draft"]["send_attempt"] is None


def test_comms_approve_for_whatsapp_without_credentials_never_fabricates_send(monkeypatch):
    monkeypatch.delenv(whatsapp.TOKEN, raising=False)
    monkeypatch.delenv(whatsapp.PHONE_NUMBER_ID, raising=False)
    draft = client.post(
        "/api/v1/veridiq/comms/draft",
        json={"kind": "follow_up", "context": "WhatsApp approval-gate smoke test", "recipient_hint": "+15551234567"},
    ).json()
    approved = client.post(
        "/api/v1/veridiq/comms/approve",
        json={"draft_id": draft["draft_id"], "approved": True, "channel": "whatsapp"},
    ).json()
    assert approved["ok"] is True
    assert approved["status"] == "approved_pending_integration"
    assert approved["draft"]["send_attempt"] is None


def test_comms_approve_for_x_twitter_with_mocked_api_sends_and_logs(monkeypatch):
    monkeypatch.setenv(x_twitter.API_KEY, "ck")
    monkeypatch.setenv(x_twitter.API_SECRET, "cs")
    monkeypatch.setenv(x_twitter.ACCESS_TOKEN, "at")
    monkeypatch.setenv(x_twitter.ACCESS_TOKEN_SECRET, "ats")

    def fake_post(url, headers=None, json=None, timeout=None):
        return _FakeResponse(201, json_data={"data": {"id": "tw1"}})

    monkeypatch.setattr(x_twitter.requests, "post", fake_post)

    draft = client.post(
        "/api/v1/veridiq/comms/draft",
        json={"kind": "outreach", "context": "X send test"},
    ).json()
    approved = client.post(
        "/api/v1/veridiq/comms/approve",
        json={"draft_id": draft["draft_id"], "approved": True, "channel": "x_twitter"},
    ).json()
    assert approved["status"] == "sent"
    assert approved["draft"]["send_attempt"]["tweet_id"] == "tw1"

    activity = client.get("/api/v1/veridiq/integrations/activity", params={"platform": "x_twitter"}).json()
    assert activity["count"] >= 1
    assert activity["activity"][0]["completion_status"] == "completed"


def test_reject_never_triggers_a_send(monkeypatch):
    calls = []
    monkeypatch.setattr(telegram, "send_message", lambda **kw: (calls.append(kw), {"status": "ok"})[1])
    monkeypatch.setenv(telegram.BOT_TOKEN, "bot123")

    draft = client.post(
        "/api/v1/veridiq/comms/draft",
        json={"kind": "outreach", "context": "Reject before send test", "recipient_hint": "111"},
    ).json()
    rejected = client.post(
        "/api/v1/veridiq/comms/approve",
        json={"draft_id": draft["draft_id"], "approved": False, "channel": "telegram"},
    ).json()
    assert rejected["status"] == "rejected_by_user"
    assert calls == []
