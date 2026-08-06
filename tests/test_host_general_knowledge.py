"""Host / calling assistant prompts must allow general knowledge (not VERIDIQ-only)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app import app  # noqa: E402
from veridiq.calling import agent as calling_agent  # noqa: E402
from veridiq.host_assistant import (  # noqa: E402
    HOST_SYSTEM_PROMPT,
    answer_host_question,
    prompt_allows_general_knowledge,
)

_FORBIDDEN = (
    "only answer about veridiq",
    "refuse off-topic",
    "off-topic",
    "everything must relate",
    "only discuss veridiq",
    "do not answer general",
    "stay on topic about veridiq",
)


def _assert_no_chatgpt_self_brand(text: str) -> None:
    """Allow mentioning ChatGPT only as an explicit ban; never as a self-claim."""
    lower = text.lower()
    # Strip quoted ban examples so leftover claims are easier to spot.
    cleaned = lower.replace('"talk like chatgpt"', "").replace("'talk like chatgpt'", "")
    cleaned = cleaned.replace("talk like chatgpt", "")
    cleaned = cleaned.replace("like chatgpt", "")
    cleaned = cleaned.replace("are like chatgpt", "")
    # After removing ban examples, ChatGPT should not remain as a product claim.
    if "chatgpt" in cleaned:
        # Ban wording may still say "ChatGPT" once; require an explicit never/do-not nearby.
        assert "never" in lower or "do not" in lower


def test_host_system_prompt_allows_general_knowledge():
    assert prompt_allows_general_knowledge() is True
    text = HOST_SYSTEM_PROMPT.lower()
    assert "general" in text
    assert "any topic" in text
    _assert_no_chatgpt_self_brand(HOST_SYSTEM_PROMPT)
    assert "not" in text and "force" in text
    for phrase in _FORBIDDEN:
        assert phrase not in text


def test_calling_prompts_allow_general_knowledge():
    for blob in (calling_agent._SYSTEM_PROMPT, calling_agent._CHAT_SYSTEM_PROMPT):
        lower = blob.lower()
        assert "general" in lower
        assert "any" in lower
        _assert_no_chatgpt_self_brand(blob)
        for phrase in _FORBIDDEN:
            assert phrase not in lower


def test_offline_blockchain_definition_not_veridiq_pitch():
    """Without LLM, 'what is a blockchain' must not be forced into attestation marketing."""
    with patch("veridiq.host_assistant._llm_answer", return_value=None):
        out = answer_host_question("what is a blockchain")
    answer = (out.get("answer") or "").lower()
    assert "attest" not in answer
    assert "truthattestation" not in answer
    assert out.get("topic") == "general_needs_llm"


def test_offline_product_langgraph_still_works():
    with patch("veridiq.host_assistant._llm_answer", return_value=None):
        out = answer_host_question("How does LangGraph work?")
    assert "LangGraph" in out["answer"]
    assert out.get("ok") is True


def test_host_chat_endpoint_langgraph():
    client = TestClient(app)
    with patch("veridiq.host_assistant._llm_answer", return_value=None):
        resp = client.post("/api/v1/veridiq/host/chat", json={"question": "How does LangGraph work?"})
    assert resp.status_code == 200
    assert "LangGraph" in resp.json()["answer"]
