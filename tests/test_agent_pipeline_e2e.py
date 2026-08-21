"""E2E-ish checks for Marketing → Postings handoff → Calling modules.

Does not rewrite postings core — only GETs postings agent persona and exercises
marketing handoff artifacts + calling budget helpers.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

os.environ.setdefault("VERIDIQ_TEST_MODE", "1")
os.environ.setdefault("VERIDIQ_CALLING_WORKER", "0")
os.environ.setdefault("VERIDIQ_MARKETING_POSTINGS_HANDOFF", "1")
os.environ["VERIDIQ_CALLING_MAX_SECONDS"] = "5"
os.environ["VERIDIQ_CALLING_DAILY_BUDGET_SECONDS"] = "20"


@pytest.fixture()
def unique_user():
    return f"pipe-{os.getpid()}-{time.time_ns()}"


def test_imports_do_not_crash():
    import veridiq.calling.agent_presence  # noqa: F401
    import veridiq.calling.budget  # noqa: F401
    import veridiq.calling.chain_hooks  # noqa: F401
    import veridiq.calling.timed_calls  # noqa: F401
    import veridiq.marketing.postings_handoff  # noqa: F401


def test_marketing_handoff_writes_artifact(tmp_path, monkeypatch):
    from veridiq.marketing import postings_handoff as handoff

    monkeypatch.setattr(handoff, "HANDOFF_DIR", tmp_path / "handoff")
    monkeypatch.setattr(handoff, "_http_postings_draft", lambda **kwargs: {"ok": False, "status": "skipped"})
    result = handoff.handoff_draft_to_postings(
        body="Ship a VeriDiQ truth-score teaser caption.",
        subject="pipeline e2e",
        channel="x",
        created_by_agent="marketing",
        use_http=True,
    )
    assert result["ok"] is True
    assert result["handoff"]["handoff_id"]
    artifact = tmp_path / "handoff" / f"{result['handoff']['handoff_id']}.json"
    assert artifact.is_file()


def test_greeting_script_helper():
    from veridiq.calling.agent_presence import build_greeting_script

    text = build_greeting_script(
        {"topic": "Canva daily posts", "agenda": ["Logo", "Caption"]},
        agent_name="Marcus",
    )
    assert "Marcus" in text
    assert "Canva" in text
    assert "Logo" in text


def test_pipeline_health_and_module_gets(unique_user):
    from app import app

    client = TestClient(app)
    health = client.get("/api/v1/health")
    assert health.status_code == 200

    pipe = client.get("/api/v1/veridiq/agents/pipeline/health")
    assert pipe.status_code == 200
    body = pipe.json()
    assert "modules" in body
    assert body["modules"].get("marketing", {}).get("ok") is True
    assert body["modules"].get("postings", {}).get("ok") is True
    assert body["modules"].get("calling", {}).get("ok") is True

    postings = client.get("/api/v1/veridiq/postings/agent")
    assert postings.status_code == 200

    budget = client.get("/api/v1/veridiq/calling/budget", params={"user_key": unique_user})
    assert budget.status_code == 200
    assert "per_call_max_seconds" in budget.json()


def test_schedule_meeting_and_list(unique_user):
    from app import app

    client = TestClient(app)
    # Far-future PKT so it shows as upcoming
    created = client.post(
        "/api/v1/veridiq/calling/meetings",
        json={
            "topic": "Pipeline e2e meeting",
            "scheduled_at_pkt": "2099-01-15T18:30",
            "agenda": ["Greeting", "Agenda"],
            "agent_types": ["ai_calling"],
        },
    )
    assert created.status_code == 200
    data = created.json()
    assert data.get("ok") is True
    mid = data["meeting"]["meeting_id"]

    listed = client.get("/api/v1/veridiq/calling/meetings")
    assert listed.status_code == 200
    ids = [m["meeting_id"] for m in listed.json().get("meetings") or []]
    assert mid in ids

    # Enter without LiveKit should fail clearly (or return livekit_not_configured via quick)
    quick = client.post(
        "/api/v1/veridiq/calling/meetings/quick",
        json={"topic": "Quick pipe meet", "user_key": unique_user},
    )
    assert quick.status_code == 200
    q = quick.json()
    # Either livekit configured (ok) or graceful degrade
    assert q.get("ok") is True or q.get("error") == "livekit_not_configured"
