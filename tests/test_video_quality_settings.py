"""Gemini 3-pillars quality recipe — Quality Injection, CFG/steps, free path."""

from __future__ import annotations


def test_quality_anchor_sentence_constant():
    from veridiq.postings.creative import QUALITY_ANCHOR_SENTENCE

    exact = (
        "Photorealistic 4K render, 60fps smooth fluid motion, cinematic studio lighting, "
        "volumetric light rays, shallow depth of field with realistic bokeh background, "
        "sharp focus, ray-traced reflections, hyper-detailed textures, professional color grading, "
        "zero motion blur distortion."
    )
    assert QUALITY_ANCHOR_SENTENCE == exact


def test_style_anchors_constant_has_gemini_keywords():
    from veridiq.postings.creative import NEGATIVE_PROMPT, STYLE_ANCHORS, apply_style_anchors

    required = [
        "volumetric lighting",
        "rim light",
        "soft studio illumination",
        "subsurface scattering",
        "shallow depth of field",
        "bokeh background",
        "sharp foreground focus",
        "smooth panning",
        "cinematic dolly",
        "ray-traced reflections",
        "photorealistic textures",
        "hyper-detailed 4k",
        "60fps fluid motion",
        "crystal clear audio",
        "studio-grade acoustics",
        "natural room reverb",
        "hyper-realistic physics",
    ]
    low = STYLE_ANCHORS.lower()
    for kw in required:
        assert kw in low, f"missing style anchor: {kw}"

    neg_bits = [
        "bad anatomy",
        "flicker",
        "distortion",
        "low quality",
        "jpeg artifacts",
        "watermark",
        "text gibberish",
        "collage",
        "grid",
        "title card",
    ]
    nlow = NEGATIVE_PROMPT.lower()
    for kw in neg_bits:
        assert kw in nlow, f"missing negative: {kw}"

    built = apply_style_anchors("a gym boy lifting weights")
    assert "volumetric light" in built.lower()
    assert "negative prompt" in built.lower()
    assert "photorealistic 4k render" in built.lower()
    assert "cfg 7.5" in built.lower()
    assert "everything in focus" not in built.lower()
    assert "deep depth of field" not in built.lower()


def test_build_cinematic_prompt_includes_quality_anchor():
    from veridiq.postings.creative import QUALITY_ANCHOR_SENTENCE, build_cinematic_prompt

    prompt = build_cinematic_prompt("gym boy lifting barbell", "explosive lift")
    assert QUALITY_ANCHOR_SENTENCE in prompt
    low = prompt.lower()
    assert "cfg 7.5" in low
    assert "40 steps" in low or "high inference detail" in low
    assert "hyper-realistic physics" in low
    assert "natural room reverb" in low or "studio warmth" in low


def test_build_cinematic_prompt_four_blocks_and_keywords():
    from veridiq.postings.creative import build_cinematic_prompt, build_veo_style_prompt

    # Alias kept for back-compat
    assert build_veo_style_prompt is build_cinematic_prompt

    prompt = build_cinematic_prompt(
        "sleek modern AI workspace screen with vibrant neon blue highlights",
        "Smooth cinematic panning shot",
        "Agent workspace office with soft plant bokeh",
        "Photorealistic close-up shot, volumetric studio lighting, shallow depth of field with a blurred background",
        "4K high-definition render, 60fps fluid motion, hyper-detailed textures, ray-traced reflections",
        dialogue="Welcome to your agents workspace.",
    )
    low = prompt.lower()
    # Four conceptual blocks present
    assert "ai workspace" in low or "neon blue" in low
    assert "agent workspace" in low or "plant bokeh" in low or "studio lighting" in low
    assert "volumetric" in low
    assert "photorealistic 4k render" in low
    # Mandatory keywords
    for kw in (
        "volumetric",
        "shallow depth of field",
        "hyper-detailed",
        "ray-traced",
        "60fps",
        "cfg 7.5",
    ):
        assert kw in low, f"missing keyword: {kw}"
    # Dialogue-in-quotes VO style
    assert "the character says with a warm voice:" in low
    assert "welcome to your agents workspace" in low


def test_build_cinematic_prompt_defaults_fill_camera_and_audio():
    from veridiq.postings.creative import build_cinematic_prompt

    prompt = build_cinematic_prompt("professional woman agent at desk", "reaches for headset")
    low = prompt.lower()
    assert "professional woman agent" in low
    assert "reaches for headset" in low
    assert "volumetric" in low
    assert "shallow depth of field" in low or "bokeh" in low
    assert "photorealistic 4k" in low
    assert "crystal clear audio" in low or "studio warmth" in low
    assert "35mm" in low or "cinematic" in low or "dolly" in low


def test_pollinations_enrich_applies_style_anchors():
    from veridiq.integrations.pollinations_image import enrich_scene_prompt

    full = enrich_scene_prompt("gym boy lifting heavy barbell", style="photo")
    low = full.lower()
    assert "volumetric lighting" in low
    assert "rim light" in low
    assert "shallow depth of field" in low or "bokeh" in low
    assert "negative prompt" in low
    assert "cfg 7.5" in low
    assert "photorealistic 4k render" in low
    assert "everything in focus" not in low


def test_style_suffix_uses_cinematic_anchors():
    from veridiq.postings.creative import style_suffix

    s = style_suffix("cinematic").lower()
    assert "volumetric lighting" in s
    assert "shallow depth of field" in s or "bokeh" in s
    assert "everything in focus" not in s


def test_local_video_default_resolution_and_fps(monkeypatch):
    monkeypatch.delenv("VERIDIQ_VIDEO_4K", raising=False)
    monkeypatch.delenv("VERIDIQ_VIDEO_FPS", raising=False)
    from veridiq.integrations import local_video

    assert local_video._output_size() == (1920, 1080)
    assert local_video._output_size(portrait=True) == (1080, 1920)
    assert local_video._target_fps() == 30
    w, h, fps = local_video._sync_wh_fps()
    assert (w, h, fps) == (1920, 1080, 30)
    assert local_video.DEFAULT_DURATION_SEC == 15
    assert local_video._effective_fps(15) == 30
    assert local_video._effective_fps(60) == 15
    assert local_video._effective_fps(180) == 15


def test_local_video_4k_and_60fps_env(monkeypatch):
    monkeypatch.setenv("VERIDIQ_VIDEO_4K", "1")
    monkeypatch.setenv("VERIDIQ_VIDEO_FPS", "60")
    from veridiq.integrations import local_video

    assert local_video._output_size() == (3840, 2160)
    assert local_video._output_size(portrait=True) == (2160, 3840)
    assert local_video._target_fps() == 60
    monkeypatch.delenv("VERIDIQ_VIDEO_4K", raising=False)
    monkeypatch.delenv("VERIDIQ_VIDEO_FPS", raising=False)


def test_local_video_concat_helper_exists():
    from veridiq.integrations import local_video

    assert callable(local_video.concat_video_segments)


def test_studio_video_output_quality_constants():
    from veridiq.postings import studio

    assert studio._VIDEO_OUT_W == 1920
    assert studio._VIDEO_OUT_H == 1080
    assert studio._VIDEO_OUT_FPS == 30
    assert studio._VIDEO_MIN_STILLS == 4
    assert studio._VIDEO_MAX_STILLS == 4
    assert studio._DURATION_DEFAULT_SEC == 15
    assert studio._VIDEO_STILL_TIMEOUT <= 20.0
    assert studio._veo_clip_plan(15) == [5, 5, 5]
    assert studio._veo_clip_plan(8) == [8]
    assert len(studio._veo_clip_plan(30)) >= 3
    assert studio.detect_video_aspect("make a youtube video") == "16:9"
    assert studio.detect_video_aspect("instagram reel of gym boy") == "9:16"
    assert studio.detect_video_aspect("tiktok shorts vertical") == "9:16"


def test_agent_look_includes_style_anchors():
    from veridiq.postings.studio import _REF_AGENT_LOOK, _custom_agent_video_board

    low = _REF_AGENT_LOOK.lower()
    assert "volumetric lighting" in low
    assert "rim light" in low
    assert "shallow depth of field" in low
    assert "hyper-detailed 4k" in low
    assert "everything in focus" not in low

    board = _custom_agent_video_board("agents workspace intro", duration_sec=15)
    shot0 = (board["shot_list"][0]["shot"] or "").lower()
    assert "volumetric" in shot0 or "photorealistic 4k" in shot0
    assert "shallow depth of field" in shot0 or "bokeh" in shot0
    assert "the character says with a warm voice" in shot0 or "photorealistic 4k" in shot0


def test_veo_enabled_defaults_off_unless_explicit(monkeypatch):
    from veridiq.integrations.llm import google_ai

    monkeypatch.delenv("VERIDIQ_GEMINI_VIDEO", raising=False)
    monkeypatch.setattr(google_ai, "status", lambda: {"configured": True})
    # Key present alone does NOT enable paid Veo
    assert google_ai.veo_enabled() is False
    monkeypatch.setenv("VERIDIQ_GEMINI_VIDEO", "0")
    assert google_ai.veo_enabled() is False
    monkeypatch.setenv("VERIDIQ_GEMINI_VIDEO", "false")
    assert google_ai.veo_enabled() is False
    monkeypatch.setenv("VERIDIQ_GEMINI_VIDEO", "1")
    assert google_ai.veo_enabled() is True
    monkeypatch.setenv("VERIDIQ_GEMINI_VIDEO", "true")
    assert google_ai.veo_enabled() is True


def test_mira_identity_has_three_pillars_standing():
    from veridiq.workforce.identities import identity_for
    from veridiq.postings.studio import _CINEMATIC_STANDING, agent_persona, _SYSTEM_PROMPT, studio_status

    ident = identity_for("posting_studio")
    standing = (ident.get("standing_instructions") or "").lower()
    assert "quality injection" in standing or "[subject & precise action]" in standing
    assert "never send raw text" in standing
    assert "cfg" in standing
    assert "free unlimited" in standing
    assert "never push the user to buy veo" in standing
    assert "lip-sync n/a" in standing or "phoneme lip-sync" in standing

    persona = agent_persona()
    pstanding = (persona.get("standing_instructions") or "").lower()
    assert "never send raw text" in pstanding or "quality injection" in pstanding or "cfg" in pstanding
    assert "never send raw text" in _SYSTEM_PROMPT.lower() or "quality injection" in _CINEMATIC_STANDING.lower()
    assert "cfg" in _CINEMATIC_STANDING.lower()
    assert "free unlimited" in _CINEMATIC_STANDING.lower()

    st = studio_status()
    assert st.get("free_unlimited") is True
    assert st.get("paid_veo") is False
    assert st.get("mira_engine") is True
    assert st.get("mira_model") == "Mira Creative Model"
    assert st.get("tier") == "free"
    assert st.get("premium_ready") is True
