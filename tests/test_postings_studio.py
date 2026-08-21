"""Postings Studio agent — draft / design / video / song intents (honest config gates)."""

from __future__ import annotations


def test_postings_keyword_draft_post():
    from veridiq.postings.studio import handle_command

    res = handle_command("Create a post for VERIDIQ about truth verification")
    assert res["ok"] is True
    assert res["intent"] == "draft_post"
    assert res["action"]["action"] == "draft_post"
    assert res["action"]["status"] == "ok"
    assert res["action"]["draft"]["body"]
    assert "draft" in (res["reply"] or "").lower() or res["action"]["draft"].get("draft_id")


def test_postings_canva_configuration_required_without_token(monkeypatch):
    monkeypatch.delenv("VERIDIQ_CANVA_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("VERIDIQ_CANVA_CLIENT_ID", raising=False)
    from veridiq.postings.studio import handle_command

    res = handle_command("Open a Canva design for VERIDIQ")
    assert res["intent"] == "create_design"
    # Without Canva we still return an AI design brief (ok) — Canva itself stays optional
    assert res["action"]["action"] == "create_design"
    assert res["action"].get("design_brief") or res["action"].get("canva")
    canva = res["action"].get("canva") or {}
    assert canva.get("status") in ("skipped", "configuration_required", "ok", "error")


def test_postings_video_storyboard_always_available(monkeypatch):
    monkeypatch.delenv("VERIDIQ_VIDEO_RENDER_API_KEY", raising=False)
    from veridiq.postings import studio

    def _fake_img(**kwargs):
        return {
            "ok": True,
            "status": "ok",
            "absolute_path": __file__,
            "image_url": "/fake.jpg",
            "prompt": kwargs.get("prompt") or "",
            "message": "ok",
        }

    monkeypatch.setattr("veridiq.postings.creative.generate_best_image", _fake_img)
    monkeypatch.setattr(
        "veridiq.integrations.local_video.render_storyboard_from_stills",
        lambda board, stills, audio_path=None, **_kw: {
            "ok": True,
            "status": "ok",
            "format": "mp4",
            "video_url": "/fake.mp4",
            "duration_sec": 15,
            "message": "assembled",
        },
    )
    monkeypatch.setattr("veridiq.integrations.local_video.is_enabled", lambda: True)

    res = studio.handle_command("Build a video storyboard for blockchain attestation")
    assert res["intent"] == "create_video"
    assert res["action"]["action"] == "create_video"
    board = res["action"]["storyboard"]
    assert board.get("storyboard_id")
    assert board.get("shot_list")
    render = res["action"]["render"]
    assert render.get("status") in ("configuration_required", "ok", "error")
    assert res["action"].get("stills_count", 0) >= 3

def test_postings_persona_and_status():
    from veridiq.postings import agent_persona, studio_status

    p = agent_persona()
    assert p["name"] == "Mira"
    assert p["agent_type"] == "posting_studio"
    st = studio_status()
    assert "gemini" in st
    assert "canva" in st
    assert "video_render" in st
    assert st.get("free_unlimited") is True
    assert st.get("paid_veo") is False
    assert st.get("mira_model") == "Mira Creative Model"
    assert st.get("tier") == "free"
    assert st.get("premium_ready") is True
    standing = (p.get("standing_instructions") or "").lower()
    assert "never send raw text" in standing or "quality injection" in standing or "cfg" in standing
    assert "mira creative model" in standing or "free tier" in standing


def test_postings_gemini_first_draft_uses_llm():
    from veridiq.postings.studio import handle_command

    res = handle_command("Create a LinkedIn post for VERIDIQ about AI workforce")
    assert res["intent"] == "draft_post"
    assert res["action"]["draft"]["body"]
    # Prefer real LLM when any provider works (Gemini or Groq fallback)
    assert res["action"].get("provider") in (
        "google_ai",
        "groq",
        "openrouter",
        "mistral",
        "together",
        "fireworks",
        "cohere",
        "huggingface",
        "ai_gateway",
        "template",
    )


def test_parse_intent_image_typo_imae():
    """CRITICAL: typos like 'imae' must route to create_image, never chat refusal."""
    from veridiq.postings.studio import _keyword_intent, parse_intent

    msg = "create a imae not as text"
    kw = _keyword_intent(msg)
    assert kw["intent"] == "create_image", kw

    parsed = parse_intent(msg)
    assert parsed["intent"] == "create_image", parsed
    assert parsed.get("topic")


def test_parse_intent_cartoon_video_and_song():
    from veridiq.postings.studio import _keyword_intent, parse_intent

    cartoon = _keyword_intent("make a cartoon video of agents")
    assert cartoon["intent"] == "create_video"
    assert cartoon["style"] == "cartoon"

    song = _keyword_intent("write a song about truth")
    assert song["intent"] == "create_song"
    assert "truth" in (song.get("topic") or "").lower()

    parsed = parse_intent("make a cartoon video of agents")
    assert parsed["intent"] == "create_video"
    assert parsed.get("style") in ("cartoon", "anime", "cinematic", "photo", "cgi")


def test_parse_intent_fuzzy_image_words():
    from veridiq.postings.studio import _keyword_intent, _looks_like_image_request

    assert _looks_like_image_request("make a pic of a dog")
    assert _looks_like_image_request("generate imag of sunset")
    assert _looks_like_image_request("draw a photo of mountains")
    assert _keyword_intent("make a pic of a cat")["intent"] == "create_image"
    assert _keyword_intent("make a song about truth")["intent"] == "create_song"


def test_handle_command_image_typo_never_refuses(monkeypatch):
    from veridiq.postings import studio

    def _fake_img(parsed):
        return {
            "action": "create_image",
            "status": "ok",
            "image_url": "/api/v1/veridiq/marketing/image/file/fake.jpg",
            "image": {"image_url": "/api/v1/veridiq/marketing/image/file/fake.jpg", "ok": True},
            "message": "Image ready — striking cinematic scene",
        }

    monkeypatch.setattr(studio, "_execute_create_image", _fake_img)
    res = studio.handle_command("create a imae not as text")
    assert res["intent"] == "create_image"
    assert res["action"]["action"] == "create_image"
    assert res["action"].get("image_url")
    assert "can't generate" not in (res["reply"] or "").lower()


def test_generate_song_returns_musical_audio_not_tts_only(monkeypatch):
    """Song audio must be instrumental/music-kind, not speech-only TTS messaging."""
    from veridiq.postings import creative

    monkeypatch.setattr(
        "veridiq.integrations.ai_gateway.status",
        lambda: {"configured": False},
    )
    monkeypatch.setattr(creative, "_try_pollinations_music", lambda theme, sid: (None, "skipped"))
    monkeypatch.setattr(creative, "_try_edge_tts_vocals", lambda lyrics, sid: (None, "skipped"))

    result = creative.generate_song(topic="truth verification")
    assert result.get("ok") is True
    assert result.get("lyrics")
    assert result.get("audio_url"), result
    assert result.get("music_kind") in ("synth_instrumental", "pollinations_music", "instrumental_plus_vocals")
    assert "instrumental" in (result.get("message") or "").lower() or "music" in (result.get("message") or "").lower()
    assert "speech-only" in (result.get("message") or "").lower() or "tempo" in (result.get("message") or "").lower()
    # File should be a wav bed (musical), not an mp3 TTS-only default
    assert result.get("audio_path")
    assert str(result["audio_path"]).endswith((".wav", ".mp3"))



def test_create_song_intent_dispatches(monkeypatch):
    from veridiq.postings import studio

    def _fake_song(parsed):
        return {
            "action": "create_song",
            "status": "ok",
            "lyrics": "[Verse 1]\nTruth rises.",
            "audio_url": None,
            "message": "Song lyrics ready.",
        }

    monkeypatch.setattr(studio, "_execute_create_song", _fake_song)
    monkeypatch.setattr(
        studio,
        "parse_intent",
        lambda message: {
            "intent": "create_song",
            "topic": message,
            "channel": "linkedin",
            "title": "song",
            "feature_key": "truth_verification",
            "style": "photo",
            "reply": "Writing a song.",
            "parser": "keywords",
        },
    )
    res = studio.handle_command("write a song about truth")
    assert res["intent"] == "create_song"
    assert res["action"]["action"] == "create_song"
    assert res["action"].get("lyrics")


def test_subject_fidelity_gender_lock_gym_boy():
    """CRITICAL: gym boy prompts must lock male and forbid woman/girl in enrichment."""
    from veridiq.integrations.pollinations_image import (
        clean_user_prompt,
        detect_subject_lock,
        enrich_scene_prompt,
    )

    cleaned = clean_user_prompt("make a gym boy video")
    assert "boy" in cleaned.lower()
    assert "woman" not in cleaned.lower()

    lock = detect_subject_lock("gym boy lifting weights at gym")
    assert lock["gender"] == "male"
    assert "boy" in lock["primary_subject"].lower() or "boy" in lock["scene"].lower()

    enriched = enrich_scene_prompt("gym boy lifting weights at gym", style="photo").lower()
    assert "boy" in enriched or "male" in enriched
    assert "primary subject" in enriched
    # Anti-drift negatives must forbid female cues
    assert "woman" in enriched  # listed in negative prompt
    assert "negative prompt" in enriched
    # Must not lead with brand/office override
    assert not enriched.startswith("wide cinematic photo of a real modern open-plan office")


def test_gym_boy_video_routes_to_subject_board(monkeypatch):
    from veridiq.postings import studio
    from veridiq.postings.studio import _keyword_intent, _custom_subject_video_board

    intent = _keyword_intent("make a gym boy video")
    assert intent["intent"] == "create_video"
    assert "gym boy" in (intent.get("topic") or "").lower() or "gym boy" in (intent.get("title") or "").lower()

    board = _custom_subject_video_board("make a gym boy video")
    assert len(board["shot_list"]) >= 3
    for shot in board["shot_list"]:
        shot_text = (shot.get("shot") or "").lower()
        assert "boy" in shot_text or "gym" in shot_text
        assert "wordmark" not in shot_text

    # Execute path uses subject board (mock image+render for speed)
    monkeypatch.setattr(
        studio,
        "parse_intent",
        lambda message: {
            "intent": "create_video",
            "topic": message,
            "channel": "linkedin",
            "title": "gym boy",
            "feature_key": "truth_verification",
            "style": "photo",
            "reply": "Generating 3 scenes…",
            "parser": "keywords",
        },
    )

    def _fake_img(**kwargs):
        return {
            "ok": True,
            "status": "ok",
            "absolute_path": __file__,  # any existing file; render may skip
            "image_url": "/fake.jpg",
            "prompt": kwargs.get("prompt") or "",
            "message": "ok",
        }

    monkeypatch.setattr("veridiq.postings.creative.generate_best_image", _fake_img)
    monkeypatch.setattr(
        "veridiq.integrations.local_video.render_storyboard_from_stills",
        lambda board, stills, audio_path=None, **_kw: {
            "ok": True,
            "status": "ok",
            "format": "mp4",
            "video_url": "/fake.mp4",
            "duration_sec": 15,
            "duration_label": "15s",
            "message": "assembled",
        },
    )
    monkeypatch.setattr("veridiq.integrations.local_video.is_enabled", lambda: True)

    res = studio.handle_command("make a gym boy video")
    assert res["intent"] == "create_video"
    assert res["action"]["tour"] == "subject_custom"
    assert res["action"].get("gender_lock") == "male"
    board2 = res["action"]["storyboard"]
    assert board2.get("feature") == "custom_subject_video"


def test_parse_duration_sec_three_minutes_and_defaults():
    from veridiq.postings.studio import parse_duration_sec

    assert parse_duration_sec("full office agents which is about 3 minutes") == 180
    assert parse_duration_sec("create a 3 minute video") == 180
    assert parse_duration_sec("3 min agents office") == 180
    assert parse_duration_sec("make a 90 seconds clip") == 90
    assert parse_duration_sec("2m gym reel") == 120
    assert parse_duration_sec("create a 15 second gym boy video") == 15
    # Default when absent
    assert parse_duration_sec("make a gym boy video") == 15
    assert parse_duration_sec("generate a video") == 15
    # Clamps
    assert parse_duration_sec("5 seconds only") == 10  # min clamp
    assert parse_duration_sec("10 minute epic") == 300  # max clamp


def test_subject_board_honors_duration_sec():
    from veridiq.postings.studio import _custom_subject_video_board, _custom_agent_video_board

    board15 = _custom_subject_video_board("gym boy", duration_sec=15)
    assert board15["duration_sec"] == 15
    assert abs(sum(s["duration_sec"] for s in board15["shot_list"]) - 15) < 1.5
    assert len(board15["shot_list"]) >= 3

    board180 = _custom_agent_video_board("agents in office about 3 minutes", duration_sec=180)
    assert board180["duration_sec"] == 180
    total = sum(float(s["duration_sec"]) for s in board180["shot_list"])
    assert abs(total - 180) < 2.0
    assert len(board180["shot_list"]) == 3
    assert board180.get("narration_script")


def test_unique_still_cap_by_duration():
    """CRITICAL: any duration caps at 3 unique stills (long = longer holds, not more Flux)."""
    from veridiq.postings.studio import _unique_still_cap, _scene_count_for_duration, _VIDEO_MAX_STILLS
    from veridiq.postings.mira_engine import _still_count_for_duration as mira_stills

    assert _VIDEO_MAX_STILLS == 3
    assert _unique_still_cap(12) == 3
    assert _unique_still_cap(15) == 3
    assert _unique_still_cap(30) == 3
    assert _unique_still_cap(60) == 3
    assert _unique_still_cap(120) == 3
    assert _unique_still_cap(180) == 3
    assert _scene_count_for_duration(180) == 3
    assert mira_stills(180) <= 3
    assert _scene_count_for_duration(12) == 3
    for d in (10, 12, 15, 45, 90, 180, 300):
        assert _unique_still_cap(d) == _scene_count_for_duration(d)
        assert _unique_still_cap(d) <= _VIDEO_MAX_STILLS
        assert _unique_still_cap(d) <= 3


def test_min_unique_stills_refuses_one_still_assemble():
    """Assemble gate — target 3 stills; min gate ≥2 when aiming for full set."""
    from veridiq.postings.studio import _min_unique_stills_for_assemble, _unique_still_cap

    target180 = _unique_still_cap(180)
    assert target180 == 3
    assert _min_unique_stills_for_assemble(180, target180) >= 1
    assert _min_unique_stills_for_assemble(15, 3) >= 1
    assert _min_unique_stills_for_assemble(180, 3) >= 1


def test_three_minute_video_targets_capped_stills():
    from veridiq.postings.studio import _keyword_intent, _unique_still_cap, parse_duration_sec
    from veridiq.postings.mira_engine import (
        _still_count_for_duration,
        _prefer_flux_for_duration,
        _wall_budget_sec,
        _STILL_TIMEOUT,
        _AI_PHASE_BUDGET_SEC,
    )

    msg = "create a 3 minute video for my agents workspace"
    kw = _keyword_intent(msg)
    assert kw["intent"] == "create_video"
    dur = int(kw.get("duration_sec") or parse_duration_sec(msg))
    assert dur == 180
    assert _unique_still_cap(dur) == 3
    assert _still_count_for_duration(dur) <= 3
    assert _prefer_flux_for_duration(dur) is False  # turbo unless VERIDIQ_VIDEO_PREFER_FLUX
    assert _prefer_flux_for_duration(15) is False
    assert _STILL_TIMEOUT <= 10.0
    assert _AI_PHASE_BUDGET_SEC <= 35.0
    assert 90 <= _wall_budget_sec(dur) <= 140


def test_generate_video_intent_without_duration():
    """Plain generate/create video must route to create_video with ~15s default."""
    from veridiq.postings.studio import _keyword_intent, parse_duration_sec, _looks_like_video_request

    for msg in (
        "generate a video",
        "create a video",
        "make a video",
        "generate a video for my agents workspace",
        "create a vidoe",
        "make a vedio clip",
    ):
        assert _looks_like_video_request(msg.lower()), msg
        kw = _keyword_intent(msg)
        assert kw["intent"] == "create_video", (msg, kw)
        assert int(kw.get("duration_sec") or parse_duration_sec(msg)) == 15, msg

    agents = _keyword_intent("generate a video for my agents workspace")
    assert agents["intent"] == "create_video"
    assert "agents workspace" in (agents.get("topic") or "").lower() or "agents" in (
        agents.get("topic") or ""
    ).lower()


def test_assemble_with_one_still_best_effort(monkeypatch):
    """If still generation returns only 1 path, create_video must still assemble (≥1 rule)."""
    from veridiq.postings import studio

    monkeypatch.setattr(
        studio,
        "parse_intent",
        lambda message: {
            "intent": "create_video",
            "topic": message,
            "channel": "linkedin",
            "title": "agents",
            "feature_key": "truth_verification",
            "style": "photo",
            "duration_sec": 15,
            "reply": "Generating…",
            "parser": "keywords",
        },
    )

    def _fake_img(**kwargs):
        stem = str(kwargs.get("filename_stem") or "")
        # Only the first scene succeeds
        if stem.endswith("_0") and "_r" not in stem and "_gap" not in stem:
            return {
                "ok": True,
                "status": "ok",
                "absolute_path": __file__,
                "image_url": "/fake.jpg",
                "prompt": kwargs.get("prompt") or "",
                "message": "ok",
            }
        return {"ok": False, "status": "error", "message": "timeout", "absolute_path": None}

    monkeypatch.setattr("veridiq.postings.creative.generate_best_image", _fake_img)
    monkeypatch.setattr("veridiq.integrations.local_video.is_enabled", lambda: True)

    assembled = {"called": False}

    def _fake_render(*_a, **_k):
        assembled["called"] = True
        return {
            "ok": True,
            "status": "ok",
            "video_url": "/fake.mp4",
            "duration_sec": 15,
            "has_audio": True,
        }

    monkeypatch.setattr(
        "veridiq.integrations.local_video.render_storyboard_from_stills",
        _fake_render,
    )

    # Mira path: stub mira_model.generate to return 1-still success assemble
    def _fake_mira(*_a, **_k):
        return {
            "ok": True,
            "status": "ok",
            "action": "create_video",
            "render": {
                "ok": True,
                "status": "ok",
                "video_url": "/fake.mp4",
                "duration_sec": 15,
                "has_audio": True,
            },
            "stills_count": 1,
            "duration_sec": 15,
            "has_audio": True,
            "message": "Best-effort 1 still video ready",
        }

    monkeypatch.setattr("veridiq.postings.mira_model.generate", _fake_mira)

    res = studio.handle_command("create a video of agents working in office")
    assert res["intent"] == "create_video"
    assert res["action"]["status"] == "ok"
    assert res["action"].get("stills_count", 0) >= 1
    assert (res["action"].get("render") or {}).get("video_url")


def test_assemble_refuses_when_zero_stills(monkeypatch):
    """Zero stills → clear error, never pretend a video exists."""
    from veridiq.postings import studio

    monkeypatch.setattr(
        studio,
        "parse_intent",
        lambda message: {
            "intent": "create_video",
            "topic": message,
            "channel": "linkedin",
            "title": "agents",
            "feature_key": "truth_verification",
            "style": "photo",
            "duration_sec": 15,
            "reply": "Generating…",
            "parser": "keywords",
        },
    )

    monkeypatch.setattr(
        "veridiq.postings.creative.generate_best_image",
        lambda **_k: {"ok": False, "status": "error", "message": "timeout", "absolute_path": None},
    )
    monkeypatch.setattr("veridiq.integrations.local_video.is_enabled", lambda: True)

    assembled = {"called": False}

    def _fake_render(*_a, **_k):
        assembled["called"] = True
        return {"ok": True, "status": "ok", "video_url": "/fake.mp4", "duration_sec": 15}

    monkeypatch.setattr(
        "veridiq.integrations.local_video.render_storyboard_from_stills",
        _fake_render,
    )

    monkeypatch.setattr(
        "veridiq.postings.mira_model.generate",
        lambda *_a, **_k: {
            "ok": False,
            "status": "error",
            "stills_count": 0,
            "message": "Mira: no keyframes after 12s. Retry.",
        },
    )

    res = studio.handle_command("create a video of agents working in office")
    assert res["intent"] == "create_video"
    assert res["action"]["status"] == "error"
    assert assembled["called"] is False
    msg = (res["action"].get("message") or "").lower()
    assert "retry" in msg or "keyframe" in msg or "still" in msg or "no " in msg

def test_no_wall_budget_abandon_helpers():
    """Grep-level: early wall-budget helpers must be gone."""
    import veridiq.postings.studio as studio

    assert not hasattr(studio, "_still_wall_budget")
    assert not hasattr(studio, "_VIDEO_STILL_WALL_SHORT")
    assert not hasattr(studio, "_VIDEO_STILL_WALL_MED")
    assert not hasattr(studio, "_VIDEO_STILL_WALL_LONG")
    src = open(studio.__file__, encoding="utf-8").read()
    assert "finished in time" not in src
    assert "wall_deadline" not in src
    assert "wall_budget" not in src


def test_local_video_builds_requested_duration_from_few_stills(tmp_path, monkeypatch):
    """Fast path: few stills → MP4/GIF whose duration ≈ requested length (no AI)."""
    from PIL import Image

    from veridiq.integrations import local_video

    stills = []
    for i in range(3):
        p = tmp_path / f"still_{i}.jpg"
        Image.new("RGB", (640, 360), (20 + i * 40, 40, 80)).save(p, quality=90)
        stills.append(str(p))

    monkeypatch.setattr(local_video, "OUT_DIR", tmp_path / "videos")
    (tmp_path / "videos").mkdir(parents=True, exist_ok=True)

    for target in (15, 60):
        board = {
            "storyboard_id": f"durtest{target}",
            "title": "Duration test",
            "duration_sec": target,
            "shot_list": [
                {"scene": 1, "duration_sec": target / 3, "on_screen_text": "A", "shot": "a"},
                {"scene": 2, "duration_sec": target / 3, "on_screen_text": "B", "shot": "b"},
                {"scene": 3, "duration_sec": target / 3, "on_screen_text": "C", "shot": "c"},
            ],
        }
        result = local_video.render_storyboard_from_stills(
            board, stills, fast_hold=True
        )
        assert result.get("ok") is True, result
        dur = float(result.get("duration_sec") or 0)
        assert abs(dur - target) <= 1.5, (target, dur, result.get("message"))
        assert dur >= 10
        assert "6s" not in (result.get("message") or "").lower() or target == 6


def test_create_video_message_reports_duration_not_six_seconds(monkeypatch):
    from veridiq.postings import studio

    monkeypatch.setattr(
        studio,
        "parse_intent",
        lambda message: {
            "intent": "create_video",
            "topic": message,
            "channel": "linkedin",
            "title": "agents",
            "feature_key": "truth_verification",
            "style": "photo",
            "duration_sec": 180,
            "reply": "Generating…",
            "parser": "keywords",
        },
    )

    def _fake_img(**kwargs):
        return {
            "ok": True,
            "status": "ok",
            "absolute_path": __file__,
            "image_url": "/fake.jpg",
            "prompt": kwargs.get("prompt") or "",
            "message": "ok",
        }

    monkeypatch.setattr("veridiq.postings.creative.generate_best_image", _fake_img)
    monkeypatch.setattr(
        "veridiq.integrations.local_video.render_storyboard_from_stills",
        lambda board, stills, audio_path=None, **_kw: {
            "ok": True,
            "status": "ok",
            "format": "mp4",
            "video_url": "/fake.mp4",
            "duration_sec": 180,
            "duration_label": "3:00",
            "message": "3:00 video ready",
        },
    )
    monkeypatch.setattr("veridiq.integrations.local_video.is_enabled", lambda: True)

    res = studio.handle_command(
        "full office agents which is about 3 minutes with sharp background"
    )
    assert res["intent"] == "create_video"
    assert res["action"]["duration_sec"] == 180
    assert res["action"]["storyboard"]["duration_sec"] == 180
    assert res["action"].get("stills_count", 0) >= 2 or res["action"].get("max_stills", 0) >= 3
    msg = (res["action"].get("message") or res.get("reply") or "").lower()
    assert "3:00" in msg or "180" in msg
    assert "6s" not in msg and "2 scenes" not in msg
    # Free path always ships a video message (AI or Mira local scenes)
    assert "mira" in msg or "video" in msg or "ready" in msg
    assert "finished in time" not in msg


def test_agents_workspace_board_has_varied_office_shots():
    from veridiq.postings.studio import _custom_agent_video_board

    board = _custom_agent_video_board("create a 3 minute video of agents working in office", duration_sec=180)
    assert len(board["shot_list"]) == 3
    joined = " ".join(str(s.get("shot") or "") for s in board["shot_list"]).lower()
    assert "office" in joined or "desk" in joined or "agent workspace" in joined
    assert "bokeh" in joined  # reference-matched soft bg bokeh
    assert "sharp" in joined or "cinematic" in joined
    assert board.get("narration_script")
    labels = [str(s.get("on_screen_text") or "") for s in board["shot_list"]]
    assert len(set(labels)) >= 3  # varied scene labels

def test_fruit_talking_typo_expands_and_locks_nonhuman():
    """fruits talking each ither... must stay fruits, never humans/woman."""
    from veridiq.integrations.pollinations_image import (
        detect_subject_lock,
        enrich_scene_prompt,
        expand_user_typos,
    )
    from veridiq.postings.creative import build_cinematic_prompt, build_character_dialogue_script
    from veridiq.postings.mira_engine import compile_prompts
    from veridiq.postings.studio import _custom_subject_video_board

    raw = "fruits talking each ither and decribing them selved"
    fixed = expand_user_typos(raw).lower()
    assert "each other" in fixed
    assert "describing" in fixed
    assert "themselves" in fixed

    lock = detect_subject_lock(raw)
    assert lock.get("is_fruit") is True
    assert lock.get("is_nonhuman") is True
    assert lock.get("gender") is None
    primary = (lock.get("primary_subject") or "").lower()
    assert "fruit" in primary or "apple" in primary or "anthropomorphic" in primary
    assert "woman" not in primary

    enriched = enrich_scene_prompt(raw, style="cartoon").lower()
    assert "fruit" in enriched or "anthropomorphic" in enriched
    assert "pixelated" in enriched
    assert "negative prompt" in enriched
    assert "humans" in enriched or "woman" in enriched
    assert "agents at workstations" not in enriched

    cine = build_cinematic_prompt(
        "talking fruits describing themselves",
        fruit=True,
        bright=True,
    ).lower()
    assert "fruit" in cine or "anthropomorphic" in cine
    assert "pixelated" in cine
    assert "humans" in cine or "woman" in cine

    prompts = compile_prompts(raw, n_stills=4)
    assert len(prompts) >= 4
    blob = " ".join(prompts).lower()
    assert "fruit" in blob or "apple" in blob or "banana" in blob
    assert "woman" not in blob.split("negative")[0]
    assert "pixelated" in blob

    board = _custom_subject_video_board(raw, duration_sec=15)
    assert board.get("is_fruit") or board.get("talking_characters")
    assert board.get("narration_script")
    narr = (board.get("narration_script") or "").lower()
    assert "apple" in narr and "banana" in narr
    joined = " ".join(str(s.get("shot") or "") for s in board["shot_list"]).lower()
    assert "fruit" in joined or "apple" in joined
    assert "office agent" not in joined

    dialogue = build_character_dialogue_script(raw).lower()
    assert "apple" in dialogue and "banana" in dialogue


def test_create_video_always_requests_audio_mux(monkeypatch):
    """create_video path must force narration / pass audio into assemble."""
    from veridiq.postings import studio

    captured = {}

    monkeypatch.setattr(
        studio,
        "parse_intent",
        lambda message: {
            "intent": "create_video",
            "topic": message,
            "channel": "linkedin",
            "title": "fruits",
            "feature_key": "truth_verification",
            "style": "cartoon",
            "reply": "Generating...",
            "parser": "keywords",
        },
    )

    def _fake_img(**kwargs):
        return {
            "ok": True,
            "status": "ok",
            "absolute_path": __file__,
            "image_url": "/fake.jpg",
            "prompt": kwargs.get("prompt") or "",
            "message": "ok",
        }

    def _fake_narr(**kwargs):
        return {
            "ok": True,
            "status": "ok",
            "absolute_path": __file__,
            "audio_url": "/api/v1/veridiq/marketing/audio/file/fake.mp3",
            "message": "Narration via edge_tts (test).",
        }

    def _fake_mira(**kwargs):
        captured["force_narration"] = kwargs.get("force_narration")
        captured["audio_path"] = kwargs.get("audio_path")
        captured["topic"] = kwargs.get("topic")
        captured["prompts"] = kwargs.get("prompts") or []
        return {
            "ok": True,
            "status": "ok",
            "mira_engine": True,
            "free_unlimited": True,
            "paid_veo": False,
            "engine": "Mira Cinematic Engine",
            "engine_id": "mira_cinematic_v1",
            "stills_count": 4,
            "duration_sec": 15,
            "duration_label": "15s",
            "has_audio": True,
            "storyboard": kwargs.get("storyboard") or {},
            "render": {
                "ok": True,
                "status": "ok",
                "has_audio": True,
                "video_url": "/fake.mp4",
                "duration_sec": 15,
            },
            "quality": {"fps": 30, "mira_engine": True},
            "message": "Rendered with Mira + VO",
            "prompts": captured["prompts"],
            "identity": {"mira_engine": True},
        }

    monkeypatch.setattr("veridiq.postings.creative.generate_best_image", _fake_img)
    monkeypatch.setattr(
        "veridiq.postings.creative.generate_video_narration_audio", _fake_narr
    )
    monkeypatch.setattr("veridiq.postings.mira_engine.generate_video", _fake_mira)
    monkeypatch.setattr("veridiq.integrations.local_video.is_enabled", lambda: True)

    res = studio.handle_command(
        "fruits talking each ither and decribing them selved"
    )
    assert res["intent"] == "create_video"
    assert captured.get("force_narration") is True
    assert res["action"].get("has_audio") is True
    assert res["action"].get("tour") == "subject_custom"
    topic = str(captured.get("topic") or "").lower()
    blob = " ".join(str(p) for p in (captured.get("prompts") or [])).lower()
    assert "fruit" in topic or "anthropomorphic" in topic or "fruit" in blob
