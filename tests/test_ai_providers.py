"""AI / LLM / speech provider connectors — status shapes, registry, platform_api."""

from __future__ import annotations

import os

import pytest

from veridiq.integrations.llm import PROVIDERS, all_ai_provider_statuses
from veridiq.integrations.llm import (
    assemblyai,
    cohere,
    deepgram,
    fireworks,
    google_ai,
    groq,
    huggingface,
    mistral,
    openrouter,
    together,
)
from veridiq.integrations.platform_api import PLATFORM_ACTIONS, MODULE_ALIASES, dispatch, list_platforms
from veridiq.integrations.registry import TEST_FUNCS, all_integrations

AI_PLATFORMS = [
    "google_ai",
    "groq",
    "openrouter",
    "huggingface",
    "cohere",
    "mistral",
    "together",
    "fireworks",
]
SPEECH_PLATFORMS = ["assemblyai", "deepgram"]
ALL_NEW = AI_PLATFORMS + SPEECH_PLATFORMS

ENV_KEYS = [
    "VERIDIQ_GOOGLE_AI_API_KEY",
    "GOOGLE_API_KEY",
    "VERIDIQ_GROQ_API_KEY",
    "VERIDIQ_OPENROUTER_API_KEY",
    "VERIDIQ_HF_TOKEN",
    "VERIDIQ_COHERE_API_KEY",
    "VERIDIQ_MISTRAL_API_KEY",
    "VERIDIQ_TOGETHER_API_KEY",
    "VERIDIQ_FIREWORKS_API_KEY",
    "VERIDIQ_ASSEMBLYAI_API_KEY",
    "VERIDIQ_DEEPGRAM_API_KEY",
]

MODULES = {
    "google_ai": google_ai,
    "groq": groq,
    "openrouter": openrouter,
    "huggingface": huggingface,
    "cohere": cohere,
    "mistral": mistral,
    "together": together,
    "fireworks": fireworks,
    "assemblyai": assemblyai,
    "deepgram": deepgram,
}


@pytest.fixture
def clear_ai_env(monkeypatch):
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_status_configuration_required_without_keys(clear_ai_env):
    for name, mod in MODULES.items():
        result = mod.status()
        assert result["platform"] == name
        assert result["status"] == "configuration_required"
        assert result["configured"] is False
        assert result["env_vars"]
        assert result["category"] in {"ai", "speech"}


def test_test_connection_configuration_required_without_keys(clear_ai_env):
    for name, mod in MODULES.items():
        result = mod.test_connection()
        assert result["status"] == "configuration_required"
        assert result.get("platform") == name


def test_generate_or_transcribe_configuration_required_without_keys(clear_ai_env):
    for name in AI_PLATFORMS:
        result = MODULES[name].generate_text(prompt="hello")
        assert result["status"] == "configuration_required"
    for name in SPEECH_PLATFORMS:
        result = MODULES[name].transcribe(audio_url="https://example.com/a.wav")
        assert result["status"] == "configuration_required"


def test_all_ai_provider_statuses_shape(clear_ai_env):
    items = all_ai_provider_statuses()
    assert len(items) == len(PROVIDERS) == len(ALL_NEW)
    platforms = {i["platform"] for i in items}
    assert platforms == set(ALL_NEW)


def test_registry_lists_ai_providers(clear_ai_env):
    data = all_integrations(force_refresh=True)
    platforms = {i["platform"] for i in data["integrations"]}
    for p in ALL_NEW:
        assert p in platforms
        assert p in TEST_FUNCS
    assert "ai" in data["categories"] or any(
        i["category"] == "ai" for i in data["integrations"]
    )
    assert "speech" in data["categories"] or any(
        i["category"] == "speech" for i in data["integrations"]
    )


def test_platform_api_wires_actions():
    for p in AI_PLATFORMS:
        assert p in PLATFORM_ACTIONS
        assert set(PLATFORM_ACTIONS[p].keys()) >= {"status", "test", "generate_text"}
        assert MODULE_ALIASES[p].startswith("llm.")
    for p in SPEECH_PLATFORMS:
        assert p in PLATFORM_ACTIONS
        assert set(PLATFORM_ACTIONS[p].keys()) >= {"status", "test", "transcribe"}
        assert MODULE_ALIASES[p].startswith("llm.")
    listed = {row["platform"] for row in list_platforms()["platforms"]}
    assert set(ALL_NEW).issubset(listed)


def test_dispatch_status_without_keys(clear_ai_env):
    for p in ALL_NEW:
        result = dispatch(p, "status")
        assert result["status"] == "configuration_required"


def test_google_ai_accepts_google_api_key_alias(monkeypatch):
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "test-alias-key-not-live")
    st = google_ai.status()
    assert st["configured"] is True
    assert st["status"] == "configured"


def test_huggingface_status_mentions_optional_local_ocr(clear_ai_env):
    msg = huggingface.status()["message"] or ""
    assert "OCR" in msg or "transformers" in msg or "Inference" in msg


def test_live_test_connection_resilient():
    """When keys are present in the process env, allow ok/error/configuration_required."""
    # Load .env the same way app.py does (without printing secrets)
    from pathlib import Path

    env_path = Path(__file__).resolve().parents[1] / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

    allowed = {"ok", "error", "configuration_required"}
    for name, mod in MODULES.items():
        result = mod.test_connection()
        assert result["status"] in allowed, f"{name}: unexpected {result.get('status')}"
        # Never leak full secrets in message
        for key in ENV_KEYS:
            val = os.environ.get(key)
            if val and len(val) > 12:
                assert val not in str(result.get("message") or "")


class _FakeResp:
    def __init__(self, status_code: int):
        self.status_code = status_code


def test_fireworks_test_connection_success_mocked(monkeypatch):
    monkeypatch.setenv("VERIDIQ_FIREWORKS_API_KEY", "fw_test_key_not_live")

    def fake_get(url, *, headers=None, params=None, timeout=12):
        assert "inference/v1/models" in url
        assert headers and headers.get("Authorization", "").startswith("Bearer ")
        return _FakeResp(200), {"data": [{"id": "accounts/fireworks/models/gpt-oss-20b"}]}, None

    monkeypatch.setattr(fireworks, "http_get_json", fake_get)
    result = fireworks.test_connection()
    assert result["ok"] is True
    assert result["status"] == "ok"
    assert result["model_count"] == 1
    assert "models listed" in (result.get("message") or "")


def test_fireworks_test_connection_accounts_fallback_mocked(monkeypatch):
    monkeypatch.setenv("VERIDIQ_FIREWORKS_API_KEY", "fw_test_key_not_live")
    calls = {"n": 0}

    def fake_get(url, *, headers=None, params=None, timeout=12):
        calls["n"] += 1
        if "inference/v1/models" in url:
            return _FakeResp(500), {"error": {"message": "upstream"}}, None
        assert "accounts/fireworks/models" in url
        assert params and params.get("filter") == "supports_serverless=true"
        return _FakeResp(200), {"models": [{"name": "accounts/fireworks/models/gpt-oss-20b"}]}, None

    monkeypatch.setattr(fireworks, "http_get_json", fake_get)
    result = fireworks.test_connection()
    assert result["ok"] is True
    assert result["model_count"] == 1
    assert "serverless" in (result.get("message") or "").lower()
    assert calls["n"] == 2


def test_fireworks_test_connection_412_honest_message(monkeypatch):
    monkeypatch.setenv("VERIDIQ_FIREWORKS_API_KEY", "fw_test_key_not_live")
    suspended = {
        "error": {
            "message": "Account example-acct is suspended, possibly due to billing.",
            "code": "PRECONDITION_FAILED",
        }
    }

    def fake_get(url, *, headers=None, params=None, timeout=12):
        return _FakeResp(412), suspended, None

    def fake_post(url, *, headers=None, json_body=None, timeout=30):
        assert json_body["model"] == fireworks.DEFAULT_MODEL
        assert "llama-v3p1" not in json_body["model"]
        return _FakeResp(412), suspended, None

    monkeypatch.setattr(fireworks, "http_get_json", fake_get)
    monkeypatch.setattr(fireworks, "http_post_json", fake_post)
    result = fireworks.test_connection()
    assert result["ok"] is False
    assert result["status"] == "error"
    assert result["api_response_status"] == 412
    msg = result.get("message") or ""
    assert "412" in msg
    assert "billing" in msg.lower() or "suspended" in msg.lower()
    assert "fw_test_key_not_live" not in msg


def test_fireworks_generate_text_success_mocked(monkeypatch):
    monkeypatch.setenv("VERIDIQ_FIREWORKS_API_KEY", "fw_test_key_not_live")

    def fake_post(url, *, headers=None, json_body=None, timeout=30):
        assert url.endswith("/chat/completions")
        assert json_body["model"] == fireworks.DEFAULT_MODEL
        return (
            _FakeResp(200),
            {"choices": [{"message": {"content": "hello from fireworks"}}]},
            None,
        )

    monkeypatch.setattr(fireworks, "http_post_json", fake_post)
    result = fireworks.generate_text(prompt="hi")
    assert result["ok"] is True
    assert result["text"] == "hello from fireworks"


def test_fireworks_default_model_is_serverless_path():
    assert fireworks.DEFAULT_MODEL.startswith("accounts/fireworks/models/")
    assert "llama-v3p1-8b-instruct" not in fireworks.DEFAULT_MODEL
