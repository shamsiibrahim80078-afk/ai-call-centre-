"""Deep research task + host/calling research intent wiring."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app import app  # noqa: E402
from veridiq.calling.agent import handle_command, parse_intent  # noqa: E402
from veridiq.host_assistant import answer_host_question  # noqa: E402
from veridiq.research.deep_research import (  # noqa: E402
    deep_research,
    extract_research_query,
    looks_like_research_task,
)


def test_looks_like_research_task_english_and_urdu():
    assert looks_like_research_task("deep research bitcoin ETF approvals")
    assert looks_like_research_task("yahan se deep-research karke yeh cheez nikaal do: Solana TPS")
    assert looks_like_research_task("find out who invented the transistor")
    assert not looks_like_research_task("what is a blockchain")
    assert not looks_like_research_task("research influencers in AI")  # influencer path


def test_extract_research_query_strips_command_words():
    q = extract_research_query("Please deep research the latest Ethereum L2 fees")
    assert "ethereum" in q.lower()
    assert "deep" not in q.lower() or "research" not in q.lower()


def test_deep_research_configuration_required_without_keys(monkeypatch):
    monkeypatch.delenv("VERIDIQ_TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("VERIDIQ_EXA_API_KEY", raising=False)
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    monkeypatch.delenv("VERIDIQ_SERPAPI_API_KEY", raising=False)
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    result = deep_research(query="quantum computing breakthroughs", summarize=False)
    assert result["status"] == "configuration_required"
    assert result["count"] == 0
    assert "TAVILY" in (result.get("message") or "") or "research providers" in (result.get("message") or "").lower()


def test_deep_research_mocked_search_returns_extract():
    fake = {
        "status": "ok",
        "ok": True,
        "results": [
            {
                "title": "Example Source",
                "url": "https://example.com/a",
                "snippet": "Useful fact about the topic.",
                "provider": "tavily",
            }
        ],
        "providers_used": ["tavily"],
        "provider_errors": [],
        "message": "Merged 1 result(s).",
    }
    with patch("veridiq.research.multi_search.multi_search", return_value=fake):
        with patch("veridiq.integrations.ai_gateway.status", return_value={"configured": False}):
            result = deep_research(query="example topic", summarize=True)
    assert result["status"] == "ok"
    assert result["count"] == 1
    assert result["summary"]
    assert "example.com" in (result["summary"] or "")
    assert "invented" not in (result["summary"] or "").lower() or "Example Source" in (result["summary"] or "")


def test_host_research_intent_uses_deep_research():
    fake_research = {
        "ok": True,
        "status": "ok",
        "query": "Solana TPS",
        "results": [
            {"title": "Solana docs", "url": "https://solana.com", "snippet": "High throughput.", "provider": "exa"}
        ],
        "count": 1,
        "summary": "Solana targets high TPS per public docs (https://solana.com).",
        "providers_used": ["exa"],
        "message": "Found 1 source(s).",
    }
    with patch("veridiq.research.deep_research.deep_research", return_value=fake_research):
        with patch("veridiq.host_assistant._llm_answer", return_value=None):
            out = answer_host_question("yahan se deep-research karke Solana TPS nikaal do")
    assert out["source"] in {"deep_research", "deep_research_llm"}
    assert "Solana" in out["answer"] or "solana" in out["answer"].lower()
    assert out.get("research", {}).get("count") == 1


def test_calling_keyword_deep_research_intent():
    parsed = parse_intent("deep research latest OpenAI model releases")
    assert parsed["intent"] == "deep_research"
    assert "openai" in (parsed.get("query") or "").lower()


def test_calling_handle_command_deep_research_mocked():
    fake = {
        "ok": True,
        "status": "ok",
        "query": "OpenAI models",
        "results": [{"title": "Blog", "url": "https://openai.com", "snippet": "New model.", "provider": "tavily"}],
        "count": 1,
        "summary": "OpenAI published updates (https://openai.com).",
        "providers_used": ["tavily"],
        "message": "Found 1.",
    }
    with patch("veridiq.research.deep_research.deep_research", return_value=fake):
        result = handle_command("deep research OpenAI models")
    assert result["intent"] == "deep_research"
    assert result["action"]["action"] == "deep_research"
    assert "openai.com" in (result["reply"] or "").lower() or "OpenAI" in (result["reply"] or "")


def test_research_api_endpoint_configuration_or_ok():
    client = TestClient(app)
    resp = client.post("/api/v1/veridiq/research", json={"query": "test topic", "summarize": False})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in {"ok", "configuration_required", "error", "invalid_args"}
    if data["status"] == "configuration_required":
        assert data["count"] == 0
