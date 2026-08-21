"""Mira Cinematic Engine — unit tests (imports, Quality Injection, status flags)."""

from __future__ import annotations

from pathlib import Path


def test_mira_engine_imports_and_identity():
    from veridiq.postings import mira_engine

    assert mira_engine.ENGINE_NAME == "Mira Cinematic Engine"
    assert mira_engine.ENGINE_ID == "mira_cinematic_v1"
    assert "Not Google Veo" in mira_engine.ENGINE_TAGLINE
    assert "free unlimited" in mira_engine.RENDER_MESSAGE.lower()
    ident = mira_engine.engine_identity()
    assert ident["mira_engine"] is True
    assert ident["free_unlimited"] is True
    assert ident["paid_veo"] is False
    assert ident["is_trained_foundation_model"] is False
    assert ident["is_google_veo"] is False


def test_mira_config_model_card_exists():
    from veridiq.postings import mira_engine

    cfg = mira_engine.load_config()
    assert cfg.get("model_id") == "mira_cinematic_v1"
    assert float(cfg.get("cfg") or 0) == 7.5
    assert int(cfg.get("steps") or 0) == 40
    assert int(cfg.get("fps") or 0) == 30
    assert (cfg.get("honesty") or {}).get("is_trained_foundation_model") is False
    path = Path(mira_engine.__file__).parent / "mira_engine_config.json"
    assert path.is_file()


def test_mira_compile_prompts_use_quality_anchor():
    from veridiq.postings.creative import QUALITY_ANCHOR_SENTENCE
    from veridiq.postings import mira_engine

    prompts = mira_engine.compile_prompts(
        "professional woman agent at desk in bright office",
        duration_sec=15,
        aspect="16:9",
        style="cinematic",
        n_stills=4,
    )
    assert len(prompts) == 4
    for p in prompts:
        assert QUALITY_ANCHOR_SENTENCE in p or "Photorealistic 4K render" in p
        low = p.lower()
        assert "volumetric" in low
        assert "cfg 7.5" in low
        assert "shallow depth of field" in low or "bokeh" in low


def test_mira_ensure_cinematic_wraps_plain_lines():
    from veridiq.postings import mira_engine

    out = mira_engine._ensure_cinematic(
        ["gym boy lifting barbell", "close-up of hands on bar"],
        "gym boy lifting barbell",
    )
    assert len(out) == 2
    assert "photorealistic 4k" in out[0].lower()
    assert "volumetric" in out[0].lower()


def test_studio_status_reports_mira_engine():
    from veridiq.postings.studio import studio_status

    st = studio_status()
    assert st.get("mira_engine") is True
    assert st.get("mira_model") == "Mira Creative Model"
    assert st.get("tier") == "free"
    assert st.get("premium_ready") is True
    assert st.get("free_features") == ["posts", "images", "designs", "videos", "songs"]
    assert "veo_native_video" in (st.get("premium_features") or [])
    assert st.get("free_unlimited") is True
    assert st.get("paid_veo") is False
    assert "Mira" in str(st.get("engine") or "")
    assert "Not Google Veo" in str(st.get("message") or "") or "mira" in str(st.get("message") or "").lower()


def test_mira_identity_standing_mentions_engine():
    from veridiq.workforce.identities import identity_for

    standing = (identity_for("posting_studio").get("standing_instructions") or "").lower()
    assert "mira creative model" in standing or "first-party" in standing
    assert "not google veo" in standing
    assert "paid_veo=false" in standing or "paid_veo" in standing
    assert "premium" in standing
    assert "free" in standing


def test_local_video_mira_cinematic_kwargs_accepted(tmp_path, monkeypatch):
    """mira_cinematic=True path sets branding flags (encode mocked for speed)."""
    from PIL import Image

    from veridiq.integrations import local_video

    monkeypatch.setattr(local_video, "OUT_DIR", tmp_path)
    stills = []
    for i in range(4):
        p = tmp_path / f"still_{i}.png"
        Image.new("RGB", (1280, 720), (40 + i * 20, 60, 90)).save(p)
        stills.append(str(p))

    board = {
        "storyboard_id": "mira_unit_test",
        "duration_sec": 10,
        "aspect": "16:9",
        "title": "Mira unit",
        "shot_list": [{"duration_sec": 2.5} for _ in range(4)],
    }

    def _fake_stream(segments, out_path, *, target_sec, crossfade_sec=0.4, mira=False):
        assert mira is True
        assert crossfade_sec >= 0.4
        out_path.write_bytes(b"\x00" * 2048)
        return True, float(target_sec)

    monkeypatch.setattr(local_video, "_write_mp4_streaming", _fake_stream)
    render = local_video.render_storyboard_from_stills(
        board, stills, fast_hold=False, mira_cinematic=True, crossfade_sec=0.7
    )
    assert render.get("ok") or render.get("status") == "ok"
    assert render.get("mira_engine") is True
    assert render.get("veo_motion") is False
    assert render.get("generative_motion") is False
    assert (render.get("width"), render.get("height")) == (1920, 1080)


def test_is_brand_topic_keywords():
    from veridiq.postings.creative import is_brand_topic

    for topic in (
        "create a video for VERIDIQ",
        "create a video for my vridiq",
        "what is veridiq",
        "explain what verdiq is",
        "agent workspace promo",
        "truth verification demo",
        "our product explainer",
        "veridig platform tour",
    ):
        assert is_brand_topic(topic), topic
    assert not is_brand_topic("gym boy lifting weights")
    assert not is_brand_topic("talking fruits introducing themselves")


def test_brand_topic_skips_pollinations_entirely(monkeypatch, tmp_path):
    """Brand path: 0 Pollinations calls — 100% local VERIDIQ stills."""
    from veridiq.integrations import local_video
    from veridiq.postings import mira_engine

    monkeypatch.setattr(local_video, "OUT_DIR", tmp_path)
    monkeypatch.setattr("veridiq.postings.local_stills.IMG_DIR", tmp_path)

    calls: list[str] = []

    def _must_not_call(**kwargs):
        calls.append(str(kwargs.get("prompt") or "")[:80])
        raise AssertionError("Pollinations must not be called for brand topics")

    def _fake_narr(**_kwargs):
        wav = tmp_path / "vo.wav"
        wav.write_bytes(b"RIFF" + b"\x00" * 200)
        return {"ok": True, "absolute_path": str(wav), "message": "test vo"}

    monkeypatch.setattr("veridiq.postings.creative.generate_best_image", _must_not_call)
    monkeypatch.setattr(
        "veridiq.postings.creative.generate_video_narration_audio", _fake_narr
    )

    out = mira_engine.generate_video(
        "create a video for my verdiq explaining what veridiq is",
        duration_sec=15,
        force_narration=True,
        n_stills=3,
    )
    assert calls == []
    assert out.get("ok") is True, out.get("message")
    assert (out.get("local_stills") or {}).get("source") == "local"
    assert (out.get("local_stills") or {}).get("brand_local_only") is True
    assert (out.get("local_stills") or {}).get("pollinations_calls") == 0
    assert (out.get("keyframe_meta") or {}).get("brand_local_only") is True
    assert "VERIDIQ branded scenes only" in str(out.get("message") or "")
    assert int(out.get("stills_count") or 0) >= 3
    # All still paths are local (hero + branded cards), not pollinations jpg
    for note in (out.get("keyframe_meta") or {}).get("notes") or []:
        if "VERIDIQ branded scenes only" in str(note):
            break
    else:
        notes = (out.get("keyframe_meta") or {}).get("notes") or []
        assert any("VERIDIQ branded" in str(n) for n in notes), notes


def test_gym_boy_still_allows_ai_with_subject_lock(monkeypatch):
    """Regression: non-brand topics still use AI with PRIMARY SUBJECT / boy lock."""
    from veridiq.integrations.pollinations_image import (
        detect_subject_lock,
        enrich_scene_prompt,
    )
    from veridiq.postings import mira_engine
    from veridiq.postings.creative import is_brand_topic

    assert not is_brand_topic("gym boy lifting weights at gym")
    lock = detect_subject_lock("gym boy lifting weights at gym")
    assert lock.get("concrete") is True
    assert lock.get("gender") == "male"
    assert "boy" in (lock.get("primary_subject") or "").lower() or "gym" in (
        lock.get("primary_subject") or ""
    ).lower()
    negs = " ".join(lock.get("negatives") or []).lower()
    assert "cat" in negs and "dog" in negs
    assert "woman" in negs or "girl" in negs

    enriched = enrich_scene_prompt("gym boy lifting weights at gym", style="photo")
    low = enriched.lower()
    assert "primary subject" in low
    assert "gym boy" in low or "boy" in low
    assert "cat" in low  # in negatives

    prompts = mira_engine.compile_prompts(
        "gym boy lifting barbell",
        duration_sec=15,
        n_stills=3,
    )
    assert len(prompts) == 3
    for p in prompts:
        assert "PRIMARY SUBJECT" in p or "gym boy" in p.lower()
        assert "cat" in p.lower()  # negative drift guard


def test_veridiq_image_prompt_uses_brand_local_not_pollinations(monkeypatch, tmp_path):
    """'create an image for my veridiq' must never call Pollinations (cat drift)."""
    from veridiq.integrations.pollinations_image import (
        detect_subject_lock,
        enrich_scene_prompt,
    )
    from veridiq.postings import creative
    from veridiq.postings.creative import is_brand_topic

    prompt = "create an image for my veridiq"
    assert is_brand_topic(prompt)
    lock = detect_subject_lock(prompt)
    assert lock.get("is_brand_request") is True
    negs = " ".join(lock.get("negatives") or []).lower()
    assert "cat" in negs and "dog" in negs

    enriched = enrich_scene_prompt(prompt, style="photo").lower()
    assert "veridiq" in enriched
    assert "cat" in enriched  # present as negative guard, not as subject
    # Subject lead must be brand — not a stock animal
    assert "primary subject" in enriched
    assert "cute cat" not in enriched.split("negative")[0]

    pol_calls = {"n": 0}

    def _no_pol(**kwargs):
        pol_calls["n"] += 1
        return {"ok": False, "message": "should not be called"}

    monkeypatch.setattr("veridiq.integrations.pollinations_image.generate_image", _no_pol)
    out = creative.generate_best_image(prompt=prompt, prefer_pollinations=True, width=640, height=640)
    assert pol_calls["n"] == 0
    assert out.get("brand_local_only") is True or out.get("provider") == "local_branded"
    assert out.get("ok") is True
    assert out.get("pollinations_calls") == 0
    assert out.get("image_url")
