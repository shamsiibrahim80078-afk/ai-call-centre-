"""Mira Creative Model facade + freemium tier stub."""

from __future__ import annotations


def test_tier_defaults_to_free(monkeypatch):
    monkeypatch.delenv("VERIDIQ_MIRA_TIER", raising=False)
    monkeypatch.delenv("VERIDIQ_GEMINI_VIDEO", raising=False)
    monkeypatch.delenv("VERIDIQ_VIDEO_PREFER_FAL", raising=False)

    from veridiq.postings import tiers

    assert tiers.current_tier() == "free"
    assert tiers.is_premium() is False
    assert tiers.premium_video_unlocked() is False
    assert tiers.premium_ready() is True
    st = tiers.status()
    assert st["tier"] == "free"
    assert st["free_features"] == ["posts", "images", "designs", "videos", "songs"]
    assert "veo_native_video" in st["premium_features"]


def test_premium_requires_tier_and_flag(monkeypatch):
    from veridiq.postings import tiers

    monkeypatch.setenv("VERIDIQ_GEMINI_VIDEO", "1")
    monkeypatch.setenv("VERIDIQ_MIRA_TIER", "free")
    assert tiers.is_premium() is False
    assert tiers.premium_video_unlocked() is False

    monkeypatch.setenv("VERIDIQ_MIRA_TIER", "premium")
    assert tiers.is_premium() is True
    assert tiers.premium_video_unlocked() is True

    monkeypatch.setenv("VERIDIQ_GEMINI_VIDEO", "0")
    monkeypatch.setenv("VERIDIQ_VIDEO_PREFER_FAL", "1")
    assert tiers.is_premium() is True
    assert tiers.premium_video_unlocked() is False  # fal unlocks premium but not Veo


def test_mira_model_generate_routes_video(monkeypatch):
    from veridiq.postings import mira_model

    monkeypatch.delenv("VERIDIQ_MIRA_TIER", raising=False)
    monkeypatch.delenv("VERIDIQ_GEMINI_VIDEO", raising=False)

    captured: dict = {}

    def _fake_video(**kwargs):
        captured.update(kwargs)
        return {
            "ok": True,
            "status": "ok",
            "mira_engine": True,
            "free_unlimited": True,
            "paid_veo": False,
            "engine": "Mira Cinematic Engine",
            "render": {"ok": True, "video_url": "/fake.mp4", "has_audio": True},
            "has_audio": True,
            "message": "Rendered with Mira",
        }

    monkeypatch.setattr(
        "veridiq.postings.mira_engine.generate_video", _fake_video
    )

    out = mira_model.generate(
        "create_video",
        topic="gym boy lifting",
        duration_sec=15,
        aspect="16:9",
        force_narration=True,
        n_stills=4,
    )
    assert out.get("ok") is True
    assert out.get("mira_model") == "Mira Creative Model"
    assert out.get("tier") == "free"
    assert out.get("paid_veo") is False
    assert captured.get("force_narration") is True
    assert captured.get("topic") == "gym boy lifting"


def test_mira_model_status_and_identity(monkeypatch):
    monkeypatch.delenv("VERIDIQ_MIRA_TIER", raising=False)
    monkeypatch.delenv("VERIDIQ_GEMINI_VIDEO", raising=False)

    from veridiq.postings import mira_model

    ident = mira_model.model_identity()
    assert ident["mira_model"] == "Mira Creative Model"
    assert ident["tier"] == "free"
    assert ident["premium_ready"] is True
    assert ident["is_trained_foundation_model"] is False
    assert ident["is_google_veo"] is False

    st = mira_model.status()
    assert st["mira_model"] == "Mira Creative Model"
    assert st["tier"] == "free"
    assert st["video_backend"] == "mira_cinematic_free"


def test_mira_model_does_not_call_veo_on_free(monkeypatch):
    """Even with VERIDIQ_GEMINI_VIDEO=1, free tier must not unlock Veo."""
    monkeypatch.setenv("VERIDIQ_GEMINI_VIDEO", "1")
    monkeypatch.setenv("VERIDIQ_MIRA_TIER", "free")

    from veridiq.postings import mira_model, tiers

    assert tiers.premium_video_unlocked() is False
    assert mira_model.try_premium_veo_video(
        prompts=["test"],
        duration_sec=8,
        filename_stem="unit",
    ) is None
