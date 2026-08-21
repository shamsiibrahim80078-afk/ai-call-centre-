"""Marketing Agency — campaign creation, daily content-pack generation,
comment/engagement drafting, Canva, and video storyboard coverage.

Mirrors the honesty rules exercised in `tests/test_social_publish.py`:
missing credentials must report `configuration_required` (or `unsupported`
when the platform itself has no such capability) — never a fabricated send.
Every generated post/comment must land as a `draft_only` comms draft and
require the existing approve step before any live platform call.
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app  # noqa: E402
from veridiq.integrations import canva, instagram, linkedin, telegram, threads, video_render, x_twitter  # noqa: E402
from veridiq.workforce import control as agent_control  # noqa: E402

client = TestClient(app)


def _create_campaign(name="VeriDiQ Launch Push", channels=None):
    resp = client.post(
        "/api/v1/veridiq/marketing/campaigns",
        json={"name": name, "product_brief": "VeriDiQ verifies claims with a live AI workforce.", "channels": channels},
    )
    assert resp.status_code == 200
    return resp.json()


# ---------------------------------------------------------------------------
# Campaign CRUD
# ---------------------------------------------------------------------------


def test_create_and_list_campaign():
    campaign = _create_campaign()
    assert campaign["status"] == "active"
    assert set(campaign["channels"]) == {"telegram", "x_twitter", "linkedin", "instagram", "threads"}

    listed = client.get("/api/v1/veridiq/marketing/campaigns").json()
    assert listed["count"] >= 1
    assert any(c["campaign_id"] == campaign["campaign_id"] for c in listed["campaigns"])

    detail = client.get(f"/api/v1/veridiq/marketing/campaigns/{campaign['campaign_id']}").json()
    assert detail["campaign_id"] == campaign["campaign_id"]
    assert "today_queue" in detail


def test_unknown_campaign_detail_returns_404():
    resp = client.get("/api/v1/veridiq/marketing/campaigns/not-a-real-id")
    assert resp.status_code == 404


def test_campaign_status_transition():
    campaign = _create_campaign(name="Status Toggle Campaign")
    paused = client.post(
        f"/api/v1/veridiq/marketing/campaigns/{campaign['campaign_id']}/status", json={"status": "paused"}
    ).json()
    assert paused["ok"] is True
    assert paused["campaign"]["status"] == "paused"

    # Paused campaigns refuse to generate content until reactivated.
    blocked = client.post(
        "/api/v1/veridiq/marketing/daily/run", json={"campaign_id": campaign["campaign_id"]}
    )
    assert blocked.status_code == 400

    client.post(f"/api/v1/veridiq/marketing/campaigns/{campaign['campaign_id']}/status", json={"status": "active"})


# ---------------------------------------------------------------------------
# Daily content pack -> comms drafts (draft_only, never a fabricated send)
# ---------------------------------------------------------------------------


def test_daily_run_queues_channel_specific_drafts_and_never_sends(monkeypatch):
    calls = []
    monkeypatch.setattr(telegram, "send_message", lambda **kw: (calls.append(kw), {"status": "ok"})[1])
    monkeypatch.delenv(telegram.BOT_TOKEN, raising=False)

    campaign = _create_campaign(name="Daily Pack Campaign", channels=["telegram", "x_twitter", "linkedin", "instagram"])
    run = client.post("/api/v1/veridiq/marketing/daily/run", json={"campaign_id": campaign["campaign_id"]}).json()
    assert run["ok"] is True
    assert run["count"] >= 4  # telegram + linkedin + instagram + >=1 tweet variant
    assert run["feature"] in {
        "truth_verification",
        "workforce_automation",
        "blockchain_attestation",
        "market_intelligence",
        "comms_growth_automation",
        "evidence_reporting",
    }
    for draft in run["drafts"]:
        assert draft["external_action_status"] == "draft_only"
        assert draft["requires_approval_before_send"] is True
    assert calls == []  # nothing was ever sent by generating a pack

    activity = client.get("/api/v1/veridiq/integrations/activity").json()
    assert activity["count"] >= 1
    assert any(e.get("workflow_stage") == "draft_queued" for e in activity["activity"])

    status = client.get(
        "/api/v1/veridiq/marketing/daily/status", params={"campaign_id": campaign["campaign_id"]}
    ).json()
    assert status["total"] == run["count"]
    assert status["pending_approval"] == run["count"]
    assert "telegram" in status["by_channel"]
    assert "x_twitter" in status["by_channel"]

    queue = client.get(
        "/api/v1/veridiq/marketing/queue", params={"campaign_id": campaign["campaign_id"], "channel": "telegram"}
    ).json()
    assert queue["count"] >= 1
    assert all(d["kind"] == "marketing_telegram" for d in queue["queue"])


def test_daily_run_respects_channel_filter():
    campaign = _create_campaign(name="Single Channel Campaign")
    run = client.post(
        "/api/v1/veridiq/marketing/daily/run",
        json={"campaign_id": campaign["campaign_id"], "channels": ["telegram"]},
    ).json()
    assert run["ok"] is True
    assert run["channels"] == ["telegram"]
    assert run["count"] == 1


def test_daily_run_unknown_campaign_is_404():
    resp = client.post("/api/v1/veridiq/marketing/daily/run", json={"campaign_id": "does-not-exist"})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Approving a queued marketing draft without credentials -> configuration_required
# ---------------------------------------------------------------------------


def test_approve_marketing_draft_without_credentials_reports_configuration_required(monkeypatch):
    monkeypatch.delenv(telegram.BOT_TOKEN, raising=False)
    campaign = _create_campaign(name="Approval Gate Campaign", channels=["telegram"])
    run = client.post("/api/v1/veridiq/marketing/daily/run", json={"campaign_id": campaign["campaign_id"]}).json()
    draft = run["drafts"][0]

    approved = client.post(
        "/api/v1/veridiq/comms/approve",
        json={"draft_id": draft["draft_id"], "approved": True, "channel": "telegram"},
    ).json()
    assert approved["ok"] is True
    assert approved["status"] == "approved_pending_integration"
    assert approved["draft"]["send_attempt"] is None

    activity = client.get("/api/v1/veridiq/integrations/activity", params={"platform": "telegram"}).json()
    assert activity["count"] >= 1
    assert any(e.get("completion_status") == "configuration_required" for e in activity["activity"])


def test_approve_marketing_draft_without_default_chat_id_reports_configuration_required():
    import os

    os.environ[telegram.BOT_TOKEN] = "bot123"
    os.environ.pop("VERIDIQ_TELEGRAM_DEFAULT_CHAT_ID", None)
    try:
        campaign = _create_campaign(name="No Default Target Campaign", channels=["telegram"])
        run = client.post("/api/v1/veridiq/marketing/daily/run", json={"campaign_id": campaign["campaign_id"]}).json()
        draft = run["drafts"][0]
        approved = client.post(
            "/api/v1/veridiq/comms/approve",
            json={"draft_id": draft["draft_id"], "approved": True, "channel": "telegram"},
        ).json()
        # No per-post recipient and no configured default broadcast target —
        # honestly reported, never a fabricated send.
        assert approved["status"] == "approved_pending_integration"
        assert approved["draft"]["send_attempt"] is None
    finally:
        os.environ.pop(telegram.BOT_TOKEN, None)


def test_approve_marketing_draft_with_default_chat_id_and_mocked_api_sends():
    import os

    os.environ[telegram.BOT_TOKEN] = "bot123"
    os.environ["VERIDIQ_TELEGRAM_DEFAULT_CHAT_ID"] = "@veridiq_channel"
    try:
        campaign = _create_campaign(name="Real Send Campaign", channels=["telegram"])
        run = client.post("/api/v1/veridiq/marketing/daily/run", json={"campaign_id": campaign["campaign_id"]}).json()
        draft = run["drafts"][0]

        class _FakeResponse:
            status_code = 200
            content = b"x"
            ok = True

            def json(self):
                return {"ok": True, "result": {"message_id": 99}}

        import veridiq.integrations.telegram as tg

        original_post = tg.requests.post
        tg.requests.post = lambda url, json=None, timeout=None, proxies=None, params=None: _FakeResponse()
        try:
            approved = client.post(
                "/api/v1/veridiq/comms/approve",
                json={"draft_id": draft["draft_id"], "approved": True, "channel": "telegram"},
            ).json()
        finally:
            tg.requests.post = original_post
        assert approved["status"] == "sent"
        assert approved["draft"]["send_attempt"]["status"] == "ok"
    finally:
        os.environ.pop(telegram.BOT_TOKEN, None)
        os.environ.pop("VERIDIQ_TELEGRAM_DEFAULT_CHAT_ID", None)


# ---------------------------------------------------------------------------
# Comments / engagement — real endpoints where officially supported, honest
# configuration_required / unsupported otherwise (never fabricated).
# ---------------------------------------------------------------------------


def test_comment_endpoint_rejects_unknown_channel():
    resp = client.post(
        "/api/v1/veridiq/marketing/comments", json={"channel": "facebook", "text": "hi", "target_ref": "1"}
    )
    assert resp.status_code == 400


def test_comment_preview_generates_influencer_voice_offline():
    preview = client.get(
        "/api/v1/veridiq/marketing/comments/preview",
        params={"channel": "x_twitter", "agent_type": "influencer_relations", "feature": "truth_verification"},
    ).json()
    assert preview["ok"] is True
    body = preview["text"].lower()
    assert "veridiq" in body or "truth" in body


def test_comment_auto_generates_when_text_empty():
    draft = client.post(
        "/api/v1/veridiq/marketing/comments",
        json={"channel": "instagram", "text": "", "target_ref": "comment123", "agent_type": "influencer_relations"},
    ).json()
    assert draft["ok"] is True
    assert draft["generated"] is True
    assert draft["draft"]["external_action_status"] == "draft_only"
    assert len(draft["draft"]["body"]) > 20


def test_x_twitter_comment_requires_credentials(monkeypatch):
    for var in x_twitter.POST_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    draft = client.post(
        "/api/v1/veridiq/marketing/comments",
        json={"channel": "x_twitter", "text": "Great thread!", "target_ref": "tweet123"},
    ).json()
    assert draft["ok"] is True
    assert draft["draft"]["external_action_status"] == "draft_only"

    approved = client.post(
        "/api/v1/veridiq/comms/approve",
        json={"draft_id": draft["draft"]["draft_id"], "approved": True, "channel": "x_twitter_comment"},
    ).json()
    assert approved["status"] == "approved_pending_integration"


def test_threads_comment_without_token_reports_configuration_required(monkeypatch):
    monkeypatch.delenv(threads.ACCESS_TOKEN, raising=False)
    monkeypatch.delenv(threads.THREADS_USER_ID, raising=False)
    draft = client.post(
        "/api/v1/veridiq/marketing/comments",
        json={"channel": "threads", "text": "Short Veridiq reply smoke", "target_ref": "parentmedia99"},
    ).json()
    assert draft["ok"] is True

    approved = client.post(
        "/api/v1/veridiq/comms/approve",
        json={"draft_id": draft["draft"]["draft_id"], "approved": True, "channel": "threads_comment"},
    ).json()
    assert approved["status"] == "approved_pending_integration"
    assert approved["draft"]["send_attempt"] is None
    activity = client.get("/api/v1/veridiq/integrations/activity").json()
    assert any(
        e.get("platform") == "threads" and e.get("completion_status") == "configuration_required"
        for e in activity.get("activity", [])
    )


def test_instagram_comment_without_comment_id_is_unsupported(monkeypatch):
    monkeypatch.setenv(instagram.ACCESS_TOKEN, "tok")
    monkeypatch.setenv(instagram.IG_USER_ID, "999")
    result = instagram.reply_to_comment(comment_id="", message="hi")
    assert result["status"] == "unsupported"


def test_linkedin_comment_requires_access_token(monkeypatch):
    monkeypatch.delenv(linkedin.ACCESS_TOKEN, raising=False)
    result = linkedin.comment_on_post(post_urn="urn:li:share:123", text="Nice post")
    assert result["status"] == "configuration_required"


def test_telegram_comment_reply_uses_reply_to_message_id(monkeypatch):
    monkeypatch.setenv(telegram.BOT_TOKEN, "bot123")
    captured = {}

    class _FakeResponse:
        status_code = 200
        content = b"x"
        ok = True

        def json(self):
            return {"ok": True, "result": {"message_id": 55}}

    def fake_post(url, json=None, timeout=None, proxies=None, params=None):
        captured.update(json or {})
        return _FakeResponse()

    monkeypatch.setattr(telegram.requests, "post", fake_post)
    result = telegram.send_message(chat_id="555", text="Thanks for asking!", reply_to_message_id=42)
    assert result["status"] == "ok"
    assert captured["reply_to_message_id"] == 42


# ---------------------------------------------------------------------------
# Team roster / assignment
# ---------------------------------------------------------------------------

_TEAM_AGENTS = (
    "marketing_manager",
    "content_creator",
    "social_poster",
    "telegram_community",
    "x_twitter_voice",
    "influencer_relations",
)


def test_marketing_team_roster_lists_all_six_roles():
    team = client.get("/api/v1/veridiq/marketing/team").json()
    agent_types = {c["agent_type"] for c in team["cards"]}
    for agent_type in _TEAM_AGENTS:
        assert agent_type in agent_types


def test_marketing_team_assign_queues_content_via_control_layer():
    for agent_type in _TEAM_AGENTS:
        agent_control.set_status(agent_type, "running")
    campaign = _create_campaign(name="Assign Flow Campaign", channels=["telegram"])
    result = client.post(
        "/api/v1/veridiq/marketing/team/assign",
        json={"agent_type": "telegram_community", "campaign_id": campaign["campaign_id"], "channels": ["telegram"]},
    ).json()
    assert result["ok"] is True
    assert result["assignment"]["status"] == "drafts_queued"
    assert result["assignment"]["result"]["count"] >= 1


def test_marketing_team_assign_unknown_agent_404():
    resp = client.post(
        "/api/v1/veridiq/marketing/team/assign", json={"agent_type": "not_a_real_agent", "campaign_id": "x"}
    )
    assert resp.status_code == 404


def test_running_marketing_agents_via_run_task_works():
    """Sanity check that the marketing agents are wired into the standard
    agent run pipeline (Start/Run buttons, live pool visibility)."""
    for agent_type in _TEAM_AGENTS:
        resp = client.post(f"/api/v1/veridiq/agents/{agent_type}/run", json={"payload": {}})
        assert resp.status_code == 200, agent_type


# ---------------------------------------------------------------------------
# Canva + video storyboard
# ---------------------------------------------------------------------------


def test_canva_status_configuration_required_without_keys(monkeypatch):
    monkeypatch.delenv(canva.CLIENT_ID, raising=False)
    monkeypatch.delenv(canva.CLIENT_SECRET, raising=False)
    monkeypatch.delenv(canva.ACCESS_TOKEN, raising=False)
    result = client.get("/api/v1/veridiq/marketing/canva/status").json()
    assert result["status"] == "configuration_required"
    assert result["configured"] is False


def test_canva_design_without_token_is_configuration_required(monkeypatch):
    monkeypatch.delenv(canva.ACCESS_TOKEN, raising=False)
    result = client.post("/api/v1/veridiq/marketing/canva/design", json={"title": "Launch Post"}).json()
    assert result["status"] == "configuration_required"


def test_canva_design_success_with_mocked_api(monkeypatch):
    monkeypatch.setenv(canva.ACCESS_TOKEN, "tok")

    class _FakeResponse:
        status_code = 200

        def json(self):
            return {"design": {"id": "d1", "urls": {"edit_url": "https://canva.com/edit/d1"}}}

        text = "{}"

    monkeypatch.setattr(canva.requests, "post", lambda url, headers=None, json=None, timeout=None: _FakeResponse())
    result = client.post("/api/v1/veridiq/marketing/canva/design", json={"title": "Launch Post"}).json()
    assert result["status"] == "ok"
    assert result["design_id"] == "d1"


def test_video_storyboard_always_generates_offline():
    resp = client.post(
        "/api/v1/veridiq/marketing/video/storyboard",
        json={"feature": "blockchain_attestation", "duration_sec": 30},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["feature"] == "blockchain_attestation"
    assert len(data["shot_list"]) >= 3
    assert data["script"]
    assert data["artifact_path"]
    assert Path(ROOT / data["artifact_path"]).exists()

    fetched = client.get(f"/api/v1/veridiq/marketing/video/storyboard/{data['storyboard_id']}").json()
    assert fetched["storyboard_id"] == data["storyboard_id"]


def test_video_render_without_provider_is_configuration_required(monkeypatch):
    monkeypatch.delenv(video_render.RENDER_API_KEY, raising=False)
    monkeypatch.delenv(video_render.RENDER_WEBHOOK_URL, raising=False)
    story = client.post("/api/v1/veridiq/marketing/video/storyboard", json={"feature": "truth_verification"}).json()
    result = client.post(
        "/api/v1/veridiq/marketing/video/render", json={"storyboard_id": story["storyboard_id"]}
    ).json()
    assert result["ok"] is True
    assert result["status"] == "configuration_required"


def test_video_render_unknown_storyboard_404():
    resp = client.post("/api/v1/veridiq/marketing/video/render", json={"storyboard_id": "not-real"})
    assert resp.status_code == 404


def test_marketing_features_endpoint_lists_core_features():
    data = client.get("/api/v1/veridiq/marketing/features").json()
    assert data["count"] >= 5
    assert "truth_verification" in data["features"]


def test_marketing_run_now_starts_team_on_default_campaign():
    for agent_type in _TEAM_AGENTS:
        agent_control.set_status(agent_type, "running")
    resp = client.post("/api/v1/veridiq/marketing/run-now")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    assert data["campaign_name"] == "Market VeriDiQ"
    assert data["campaign_id"]
    assert len(data["started"]) >= 1
    assert all(s.get("status") == "started" for s in data["started"])


def test_influencer_run_now_queues_influencer_voice_drafts():
    from veridiq.agents import get_agent
    from veridiq.marketing import get_or_create_default_campaign

    agent_control.set_status("influencer_relations", "running")
    campaign = get_or_create_default_campaign()
    result = get_agent("influencer_relations").process(
        {"campaign_id": campaign["campaign_id"], "channels": ["instagram", "x_twitter"], "max_drafts": 4}
    )
    assert result["voice"] == "influencer"
    pack = result["result"]
    assert pack["ok"] is True
    assert pack["count"] >= 2
    bodies = " ".join(d["body"] for d in pack["drafts"]).lower()
    assert "veridiq" in bodies
    assert any(marker in bodies for marker in ("hook", "cta", "link in bio", "hot take", "stop scrolling", "adrian"))
    for draft in pack["drafts"]:
        assert draft["external_action_status"] == "draft_only"


def test_marketing_manager_run_now_queues_drafts_not_status_only():
    from veridiq.agents import get_agent
    from veridiq.marketing import get_or_create_default_campaign

    agent_control.set_status("marketing_manager", "running")
    campaign = get_or_create_default_campaign()
    result = get_agent("marketing_manager").process({"campaign_id": campaign["campaign_id"], "max_drafts": 3})
    assert result["result"]["ok"] is True
    assert result["result"]["count"] >= 1


def test_marketing_run_now_shows_working_in_team_endpoint(monkeypatch):
    """POST run-now → immediate GET marketing/team must show Working > 0."""
    import time

    monkeypatch.setenv("VERIDIQ_MARKETING_MIN_VISIBLE_SEC", "0.4")
    for agent_type in _TEAM_AGENTS:
        agent_control.set_status(agent_type, "running")
    resp = client.post("/api/v1/veridiq/marketing/run-now")
    assert resp.status_code == 200, resp.text
    team = client.get("/api/v1/veridiq/marketing/team").json()
    working = sum(1 for c in team["cards"] if c["status"] == "working")
    assert working > 0, team["workforce"]
    assert team["workforce"]["active_workers"] > 0
    deadline = time.time() + 3
    while time.time() < deadline and working > 0:
        time.sleep(0.05)
        team = client.get("/api/v1/veridiq/marketing/team").json()
        working = sum(1 for c in team["cards"] if c["status"] == "working")


def test_team_run_draft_count_bounded(monkeypatch):
    """One team run must not flood hundreds of drafts."""
    from veridiq.marketing import daily_status, get_or_create_default_campaign

    monkeypatch.setenv("VERIDIQ_MARKETING_MAX_PENDING", "9999")
    for agent_type in _TEAM_AGENTS:
        agent_control.set_status(agent_type, "running")
    campaign = get_or_create_default_campaign()
    before = daily_status(campaign_id=campaign["campaign_id"])["total"]
    resp = client.post("/api/v1/veridiq/marketing/run-now")
    assert resp.status_code == 200
    import time

    deadline = time.time() + 8
    while time.time() < deadline:
        snap = client.get("/api/v1/veridiq/workforce").json()
        if snap.get("active_workers", 0) == 0:
            break
        time.sleep(0.1)
    after = daily_status(campaign_id=campaign["campaign_id"])["total"]
    new_drafts = after - before
    assert new_drafts <= 30, f"team run created {new_drafts} drafts (expected <= 30)"


def test_go_live_checklist_lists_platform_env_vars():
    data = client.get("/api/v1/veridiq/marketing/go-live-checklist").json()
    assert data["total"] == 5
    platforms = {p["platform"] for p in data["platforms"]}
    assert platforms == {"telegram", "x_twitter", "linkedin", "instagram", "threads"}
    # Send-ready is stricter than a status probe (e.g. X bearer alone is not send-ready).
    assert all("send_ready" in p for p in data["platforms"])
    assert data["ready_count"] == sum(1 for p in data["platforms"] if p["send_ready"])


def test_clear_pending_drafts_trims_queue():
    from veridiq.marketing import clear_pending_drafts, get_or_create_default_campaign

    campaign = get_or_create_default_campaign()
    for _ in range(5):
        client.post("/api/v1/veridiq/marketing/daily/run", json={"campaign_id": campaign["campaign_id"]})
    result = clear_pending_drafts(campaign_id=campaign["campaign_id"], keep_recent=2)
    assert result["ok"] is True
    assert result["removed"] >= 0
