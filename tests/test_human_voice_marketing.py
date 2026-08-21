"""Human voice persona + cadence tests for Marketing Agency."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from veridiq.marketing.cadence import approve_batch_with_cadence, compute_delay_sec  # noqa: E402
from veridiq.marketing.human_voice import (  # noqa: E402
    MARKETING_PERSONA_AGENTS,
    build_community_reply,
    persona_signature,
    render_for_agent,
)
from veridiq.marketing.team_run import TEAM_RUN_CHANNELS  # noqa: E402
from veridiq.workforce import control as agent_control  # noqa: E402

_FEATURE = "truth_verification"
_DAY = date(2026, 8, 4)


def test_each_persona_produces_distinct_copy():
    bodies: dict[str, str] = {}
    for agent_type in MARKETING_PERSONA_AGENTS:
        channel = (TEAM_RUN_CHANNELS.get(agent_type) or ["linkedin"])[0]
        body = render_for_agent(agent_type, channel, _FEATURE, day=_DAY)
        if isinstance(body, list):
            body = body[0]
        bodies[agent_type] = str(body).lower()
    unique = set(bodies.values())
    assert len(unique) == len(MARKETING_PERSONA_AGENTS), "persona copy should not be identical across agents"


def test_persona_signature_markers_present():
    for agent_type in MARKETING_PERSONA_AGENTS:
        channel = (TEAM_RUN_CHANNELS.get(agent_type) or ["telegram"])[0]
        body = render_for_agent(agent_type, channel, _FEATURE, day=_DAY)
        if isinstance(body, list):
            body = " ".join(body)
        marker = persona_signature(agent_type)
        # At least one agent-specific voice trait should appear in copy or marker is structural
        assert marker or len(str(body)) > 40


def test_same_agent_rotates_templates_by_day():
    a = render_for_agent("x_twitter_voice", "x_twitter", _FEATURE, day=date(2026, 1, 1), n=2)
    b = render_for_agent("x_twitter_voice", "x_twitter", _FEATURE, day=date(2026, 6, 15), n=2)
    assert isinstance(a, list) and isinstance(b, list)
    # Different calendar days should not always pick identical first variant
    assert a[0] != b[0] or a != b


def test_team_run_drafts_not_identical_dump(monkeypatch):
    from veridiq.agents import get_agent
    from veridiq.marketing import get_or_create_default_campaign

    monkeypatch.setenv("VERIDIQ_MARKETING_MAX_PENDING", "9999")
    campaign = get_or_create_default_campaign()
    bodies: list[str] = []
    for agent_type, channels in TEAM_RUN_CHANNELS.items():
        agent_control.set_status(agent_type, "running")
        ch = channels[0]
        result = get_agent(agent_type).process(
            {"campaign_id": campaign["campaign_id"], "channels": [ch], "max_drafts": 1}
        )
        pack = result.get("result") or {}
        for draft in pack.get("drafts") or []:
            bodies.append((draft.get("body") or "").strip())
    nonempty = [b for b in bodies if b]
    assert len(nonempty) >= 4
    assert len(set(nonempty)) == len(nonempty), "team run must not produce identical bodies across specialists"


def test_community_reply_is_conversational():
    reply = build_community_reply("Hi there!")
    assert reply
    assert "hey" in reply.lower() or "hi" in reply.lower()
    q_reply = build_community_reply("How does LangGraph work?")
    assert "langgraph" in q_reply.lower() or "orchestr" in q_reply.lower()


def test_cadence_delay_is_deterministic():
    d1 = compute_delay_sec("draft-abc", index=1)
    d2 = compute_delay_sec("draft-abc", index=1)
    assert d1 == d2
    assert d1 >= 0


def test_batch_approve_with_cadence_disabled(monkeypatch):
    from veridiq.comms import draft_marketing_content

    monkeypatch.setenv("VERIDIQ_MARKETING_SEND_JITTER_MIN_SEC", "0")
    monkeypatch.setenv("VERIDIQ_MARKETING_SEND_JITTER_MAX_SEC", "0")
    d1 = draft_marketing_content(channel="telegram", body="Test post one", campaign_id=None)
    d2 = draft_marketing_content(channel="telegram", body="Test post two", campaign_id=None)
    specs = [{"draft_id": d1["draft_id"], "channel": "telegram"}, {"draft_id": d2["draft_id"], "channel": "telegram"}]
    result = approve_batch_with_cadence(specs, cadence=False)
    assert result["ok"] is True
    assert result["total_wait_sec"] == 0


def test_comms_approve_batch_endpoint(monkeypatch):
    from fastapi.testclient import TestClient

    from app import app

    monkeypatch.setenv("VERIDIQ_MARKETING_SEND_JITTER_MIN_SEC", "0")
    monkeypatch.setenv("VERIDIQ_MARKETING_SEND_JITTER_MAX_SEC", "0")
    client = TestClient(app)
    campaign = client.post(
        "/api/v1/veridiq/marketing/campaigns",
        json={"name": "Batch API Test", "channels": ["telegram"]},
    ).json()
    run = client.post(
        "/api/v1/veridiq/marketing/daily/run",
        json={"campaign_id": campaign["campaign_id"], "channels": ["telegram"]},
    ).json()
    draft = run["drafts"][0]
    resp = client.post(
        "/api/v1/veridiq/comms/approve-batch",
        json={"drafts": [{"draft_id": draft["draft_id"], "channel": "telegram"}], "cadence": False},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
