"""Influencer research helpers + API + SDK tool wiring."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app  # noqa: E402
from veridiq.influencer.research import research_creators  # noqa: E402
from veridiq.sdk.tools import execute_tool, list_tools  # noqa: E402
from veridiq.workforce.departments import DEPARTMENTS, department_for_agent  # noqa: E402
from veridiq.workforce.stage_labels import friendly_stage  # noqa: E402

client = TestClient(app)


def test_research_requires_query():
    result = research_creators(query="")
    assert result["status"] == "invalid_args"
    assert result["ok"] is False


def test_research_configuration_required_without_keys(monkeypatch):
    for key in (
        "VERIDIQ_TAVILY_API_KEY",
        "TAVILY_API_KEY",
        "VERIDIQ_EXA_API_KEY",
        "EXA_API_KEY",
        "VERIDIQ_SERPAPI_API_KEY",
        "SERPAPI_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    result = research_creators(query="AI creators", summarize=False)
    assert result["status"] == "configuration_required"
    assert result["count"] == 0
    assert "no fabricated" in (result.get("note") or "").lower()


def test_sdk_tool_registered():
    tools = list_tools()
    assert "influencer.research" in tools
    assert "research.multi_search" in tools
    out = execute_tool("influencer.research", query="", summarize=False)
    assert out.get("status") == "invalid_args"


def test_influencer_research_api():
    resp = client.post(
        "/api/v1/veridiq/influencer/research",
        json={"query": "truth verification creators", "summarize": False, "max_results": 3},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert "results" in data
    assert "note" in data


def test_influencer_relations_home_department():
    dept = department_for_agent("influencer_relations")
    assert dept is not None
    assert dept["id"] == "marketing_agency"
    assert "influencer_relations" in DEPARTMENTS["influencer_intelligence"]["agents"]
    assert "content_creator" in DEPARTMENTS["marketing"]["agents"]


def test_marketing_stage_labels():
    assert friendly_stage("content_generation") == "Generating content"
    assert friendly_stage("draft_queue") == "Queuing drafts for approval"
    assert friendly_stage("Waiting for Assignment") == "Waiting for Assignment"
