"""Marketing influencer smoke + postings handoff (no postings internals)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

os.environ.setdefault("VERIDIQ_TEST_MODE", "1")
os.environ.setdefault("VERIDIQ_MIN_VISIBLE_SEC", "0")
os.environ.setdefault("VERIDIQ_MARKETING_MIN_VISIBLE_SEC", "0")
os.environ.setdefault("VERIDIQ_MARKETING_POSTINGS_HANDOFF", "1")


def test_postings_handoff_writes_local_artifact(tmp_path, monkeypatch):
    from veridiq.marketing import postings_handoff as handoff

    monkeypatch.setattr(handoff, "HANDOFF_DIR", tmp_path / "handoff")
    monkeypatch.setattr(handoff, "_ROOT", tmp_path)
    result = handoff.handoff_draft_to_postings(
        body="VeriDiQ verifies claims with a live AI workforce.",
        subject="Truth verification",
        channel="instagram",
        created_by_agent="influencer_relations",
        use_http=False,
    )
    assert result["ok"] is True
    assert result["status"] == "queued_local"
    assert result["handoff"]["handoff_id"]
    artifact = tmp_path / "handoff" / f"{result['handoff']['handoff_id']}.json"
    assert artifact.is_file()


def test_influencer_agent_queues_drafts_and_handoff(monkeypatch):
    from veridiq.agents import get_agent
    from veridiq.marketing import get_or_create_default_campaign
    from veridiq.workforce import control as agent_control

    agent_control.set_status("influencer_relations", "running")
    campaign = get_or_create_default_campaign()

    # Avoid HTTP to live uvicorn (may be busy with postings jobs).
    result = get_agent("influencer_relations").process(
        {
            "campaign_id": campaign["campaign_id"],
            "max_drafts": 2,
            "channels": ["instagram"],
            "handoff_to_postings": True,
            "handoff_http": False,
            "skip_draft_generation": False,
        }
    )
    assert result.get("voice") == "influencer"
    pack = result.get("result") or {}
    assert pack.get("ok") is True
    assert int(pack.get("count") or 0) >= 1
    handoff = result.get("postings_handoff") or {}
    assert handoff.get("ok") is True
    assert int(handoff.get("count") or 0) >= 1


def test_prepare_queue_clears_when_flooded(monkeypatch):
    from veridiq.marketing import team_run

    monkeypatch.setattr(team_run, "MAX_PENDING_BEFORE_SKIP", 2)
    monkeypatch.setattr(team_run, "pending_count", lambda campaign_id=None: 5)

    cleared = {"removed": 3}

    def _clear(*, campaign_id=None, keep_recent=20):
        return {"ok": True, "removed": 3, "remaining": keep_recent}

    monkeypatch.setattr(
        "veridiq.marketing.campaigns.clear_pending_drafts",
        _clear,
        raising=False,
    )
    # After clear, pretend queue is healthy
    calls = {"n": 0}

    def _pending(campaign_id=None):
        calls["n"] += 1
        return 5 if calls["n"] == 1 else 1

    monkeypatch.setattr(team_run, "pending_count", _pending)
    prep = team_run.prepare_queue_for_run(campaign_id="x", auto_clear=True, keep_recent=2)
    assert prep["skipped"] is False
    assert prep["cleared"] == 3
