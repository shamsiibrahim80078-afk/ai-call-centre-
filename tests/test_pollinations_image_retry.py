"""Free-path image generation: skip broken Gemini, Pollinations retry/backoff."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest


def test_google_ai_skips_image_without_opt_in(monkeypatch):
    monkeypatch.delenv("VERIDIQ_USE_GEMINI_IMAGE", raising=False)
    monkeypatch.setenv("VERIDIQ_GOOGLE_AI_API_KEY", "fake-key-for-test")
    from veridiq.integrations.llm import google_ai

    # Dead preview model must never be in the try list
    assert "gemini-2.0-flash-preview-image-generation" not in google_ai.IMAGE_MODELS

    out = google_ai.generate_image(prompt="a red apple")
    assert out.get("ok") is False
    assert out.get("status") == "skipped"
    assert "skipped" in (out.get("message") or "").lower()


def test_google_ai_never_calls_dead_preview_model(monkeypatch):
    monkeypatch.setenv("VERIDIQ_USE_GEMINI_IMAGE", "1")
    monkeypatch.setenv("VERIDIQ_GOOGLE_AI_API_KEY", "fake-key-for-test")
    from veridiq.integrations.llm import google_ai

    called_urls: list[str] = []

    def _fake_post(url, **kwargs):
        called_urls.append(url)
        r = MagicMock()
        r.status_code = 404
        r.headers = {"content-type": "application/json"}
        r.json.return_value = {
            "error": {"message": "models/gemini-2.0-flash-preview-image-generation is not found"}
        }
        return r

    with patch("veridiq.integrations.llm.google_ai.requests.post", side_effect=_fake_post):
        out = google_ai.generate_image(
            prompt="test",
            model="gemini-2.0-flash-preview-image-generation",
            timeout=5,
        )
    assert out.get("ok") is False
    assert not any("gemini-2.0-flash-preview-image-generation" in u for u in called_urls)


def test_generate_best_image_skips_gemini_by_default(monkeypatch):
    monkeypatch.delenv("VERIDIQ_USE_GEMINI_IMAGE", raising=False)
    from veridiq.postings import creative

    calls = {"gemini": 0, "pol": 0}

    def _no_gem(**kwargs):
        calls["gemini"] += 1
        return {"ok": False, "message": "should not be called"}

    def _ok_pol(**kwargs):
        calls["pol"] += 1
        return {
            "ok": True,
            "status": "ok",
            "provider": "pollinations_image",
            "model": "turbo",
            "image_url": "/api/v1/veridiq/marketing/image/file/x.jpg",
            "absolute_path": "x.jpg",
            "message": "Image ready (10 KB, turbo)",
        }

    monkeypatch.setattr("veridiq.integrations.llm.google_ai.generate_image", _no_gem)
    monkeypatch.setattr("veridiq.integrations.pollinations_image.generate_image", _ok_pol)
    monkeypatch.setattr(
        "veridiq.integrations.pollinations_image.detect_subject_lock",
        lambda p: {
            "scene": p,
            "primary_subject": p[:40],
            "gender": None,
            "is_fruit": False,
            "is_nonhuman": False,
            "talking_characters": False,
            "negatives": [],
            "concrete": True,
            "is_brand_request": False,
            "nouns": [],
            "fruit_hits": [],
        },
    )
    monkeypatch.setattr(
        "veridiq.integrations.pollinations_image.enrich_scene_prompt",
        lambda p, **kw: p,
    )

    out = creative.generate_best_image(prompt="gym boy", prefer_pollinations=True)
    assert out.get("ok") is True
    assert calls["gemini"] == 0
    assert calls["pol"] == 1
    assert out.get("image_url")
    assert "Gemini:" not in (out.get("message") or "")


def test_generate_best_image_short_error_no_gemini_dump(monkeypatch):
    from veridiq.postings import creative

    monkeypatch.setattr(
        "veridiq.integrations.pollinations_image.generate_image",
        lambda **kw: {
            "ok": False,
            "status": "error",
            "message": "Free image queue busy (rate limit). Wait a few seconds and retry.",
            "retry": True,
        },
    )
    monkeypatch.setattr(
        "veridiq.integrations.pollinations_image.detect_subject_lock",
        lambda p: {
            "scene": p,
            "primary_subject": "cat",
            "gender": None,
            "is_fruit": False,
            "is_nonhuman": False,
            "talking_characters": False,
            "negatives": [],
            "concrete": True,
            "is_brand_request": False,
            "nouns": [],
            "fruit_hits": [],
        },
    )
    monkeypatch.setattr(
        "veridiq.integrations.pollinations_image.enrich_scene_prompt",
        lambda p, **kw: p,
    )

    out = creative.generate_best_image(prompt="a cat", prefer_pollinations=True)
    assert out.get("ok") is False
    assert out.get("retry") is True
    msg = out.get("message") or ""
    assert "models/gemini" not in msg.lower()
    assert "queue" in msg.lower() or "retry" in msg.lower()
    assert len(msg) < 200


def test_pollinations_retries_429_with_backoff(monkeypatch):
    from veridiq.integrations import pollinations_image

    sleeps: list[float] = []
    monkeypatch.setattr(pollinations_image.time, "sleep", lambda s: sleeps.append(float(s)))

    # Ensure enrich/detect stay light
    monkeypatch.setattr(
        pollinations_image,
        "detect_subject_lock",
        lambda q: {
            "scene": q,
            "primary_subject": q[:40],
            "gender": None,
            "is_fruit": False,
            "is_nonhuman": False,
            "talking_characters": False,
            "negatives": [],
            "concrete": True,
            "is_brand_request": False,
            "nouns": [],
            "fruit_hits": [],
        },
    )
    monkeypatch.setattr(pollinations_image, "enrich_scene_prompt", lambda q, **kw: q)

    hits = {"n": 0}

    def _fake_get(url, **kwargs):
        hits["n"] += 1
        r = MagicMock()
        if hits["n"] < 3:
            r.status_code = 429
            r.headers = {"content-type": "text/plain"}
            r.text = "Queue full for IP xxx max: 1"
            r.content = b""
            return r
        r.status_code = 200
        r.headers = {"content-type": "image/jpeg"}
        r.text = ""
        r.content = b"JPEG" + (b"\x00" * 3000)
        return r

    with patch.object(pollinations_image.requests, "get", side_effect=_fake_get):
        out = pollinations_image.generate_image(
            prompt="blue square",
            model="turbo",
            timeout=5,
            enhance=False,
            max_attempts=4,
            backoff_sec=(3.0, 6.0, 10.0),
        )

    assert out.get("ok") is True
    assert out.get("image_url")
    assert hits["n"] == 3
    assert sleeps == [3.0, 6.0]


def test_pollinations_global_semaphore_serializes(monkeypatch):
    from veridiq.integrations import pollinations_image

    monkeypatch.setattr(
        pollinations_image,
        "detect_subject_lock",
        lambda q: {
            "scene": q,
            "primary_subject": "x",
            "gender": None,
            "is_fruit": False,
            "is_nonhuman": False,
            "talking_characters": False,
            "negatives": [],
            "concrete": True,
            "is_brand_request": False,
            "nouns": [],
            "fruit_hits": [],
        },
    )
    monkeypatch.setattr(pollinations_image, "enrich_scene_prompt", lambda q, **kw: q)

    in_flight = {"n": 0, "max": 0}

    def _fake_get(url, **kwargs):
        in_flight["n"] += 1
        in_flight["max"] = max(in_flight["max"], in_flight["n"])
        time.sleep(0.05)
        in_flight["n"] -= 1
        r = MagicMock()
        r.status_code = 200
        r.headers = {"content-type": "image/jpeg"}
        r.text = ""
        r.content = b"JPEG" + (b"\x00" * 3000)
        return r

    with patch.object(pollinations_image.requests, "get", side_effect=_fake_get):
        from concurrent.futures import ThreadPoolExecutor

        def _one(i):
            return pollinations_image.generate_image(
                prompt=f"scene {i}",
                model="turbo",
                timeout=5,
                enhance=False,
                max_attempts=1,
            )

        with ThreadPoolExecutor(max_workers=3) as pool:
            outs = list(pool.map(_one, range(3)))

    assert all(o.get("ok") for o in outs)
    assert in_flight["max"] == 1


def test_typo_va_image_and_verdiq_route():
    from veridiq.postings.studio import _keyword_intent, _looks_like_image_request
    from veridiq.integrations.pollinations_image import expand_user_typos

    assert _looks_like_image_request("create va image of a cat")
    assert _keyword_intent("create va image of a cat")["intent"] == "create_image"
    assert _keyword_intent("make a verdiq logo image")["intent"] == "create_image"
    assert "veridiq" in expand_user_typos("explain what verdiq is").lower()
    assert "veridiq" in expand_user_typos("what is veridiqw").lower()
    assert "veridiq" in expand_user_typos("create a video for my vridiq").lower()
    assert "create a image" in expand_user_typos("create va image of agents").lower()


def test_parse_duration_mints():
    from veridiq.postings.studio import parse_duration_sec

    assert parse_duration_sec("create a video 3 mints long") == 180
    assert parse_duration_sec("video 2 mins") == 120
