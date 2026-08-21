"""Local Mira stills — guaranteed free frames when Pollinations fails."""

from __future__ import annotations

import re
import time
from pathlib import Path


def test_clean_topic_title_strips_create_a_video():
    """Unit: local still title sanitizer never keeps 'create a video' command text."""
    from veridiq.postings.local_stills import _clean_topic_title, frame_copy_for_topic

    prompts = (
        "create a video for my verdiq explaining what veridiq is",
        "Create a video for my product launch about the new AI features we shipped",
        "make a video about coffee brewing tips for beginners at home",
        "please generate a reel for my brand telling what we do",
        "create a video",
    )
    for topic in prompts:
        title = _clean_topic_title(topic)
        low = (title or "").lower()
        assert "create a video" not in low, (topic, title)
        assert "make a video" not in low, (topic, title)
        assert "generate a" not in low, (topic, title)
        assert "for my" not in low, (topic, title)
        # Brand → VERIDIQ; creative → empty (no multi-word prompt on screen)
        assert title in ("", "VERIDIQ") or len(title.split()) <= 3, (topic, title)
        assert len(title) <= 40, (topic, title)
        blob = " ".join(
            f"{f.get('eyebrow','')} {f.get('title','')} {f.get('subtitle','')} {f.get('footer','')}"
            for f in frame_copy_for_topic(topic, n=3)
        ).lower()
        assert "create a video" not in blob, blob
        assert "for my" not in blob or "veridiq" in blob, blob


def test_creative_topic_local_still_has_no_prompt_text(tmp_path):
    """Creative fruit topics: local fruit characters — never prompt text / abstract goo."""
    from PIL import Image

    from veridiq.postings.local_stills import (
        _clean_topic_title,
        frame_copy_for_topic,
        generate_local_stills,
    )

    topic = "Every Froot Describing Their Identity create a video"
    assert _clean_topic_title(topic) == ""
    frames = frame_copy_for_topic(topic, n=3)
    for fr in frames:
        assert fr.get("layout") == "fruit"
        blob = f"{fr.get('eyebrow','')} {fr.get('title','')} {fr.get('subtitle','')} {fr.get('footer','')}"
        low = blob.lower()
        assert "froot" not in low
        assert "describ" not in low
        assert "create" not in low
        assert "identity" not in low
        assert not (fr.get("title") or "").strip()

    paths = generate_local_stills(
        topic, n=3, width=640, height=360, prefix="fruit_char", out_dir=tmp_path
    )
    assert len(paths) >= 3
    for p in paths:
        assert "abstract" not in Path(p).name.lower()
        assert Path(p).is_file()
        img = Image.open(p)
        assert img.size[0] >= 320
        # Fruit filenames should mention apple/banana/orange
        assert any(k in Path(p).name.lower() for k in ("apple", "banana", "orange", "fruit"))


def test_fruit_talking_stills_have_mouth_variants(tmp_path):
    """Speaking fruit topic → mouth open + closed variants in still list."""
    from veridiq.postings.local_stills import (
        ensure_still_set,
        render_fruit_character_stills,
    )

    topic = "talking fruits introducing themselves"
    paths = render_fruit_character_stills(
        topic,
        n=3,
        width=640,
        height=360,
        speaking=True,
        duration_sec=6.0,
        mouth_hold_sec=0.45,
        prefix="talk",
        out_dir=tmp_path,
    )
    assert len(paths) >= 6  # multiple ticks across 3 fruits
    names = [Path(p).name.lower() for p in paths]
    assert any("_closed" in n for n in names)
    assert any("_open" in n for n in names)
    # Alternation present
    assert names[0] != names[1] or "_open" in names[1] or "_closed" in names[0]

    mixed, meta = ensure_still_set(
        [],
        topic,
        n=3,
        width=640,
        height=360,
        prefix="ens",
        force_local=True,
        duration_sec=6.0,
        speaking=True,
    )
    assert meta.get("creative_abstract") is False
    assert meta.get("mouth_variants") is True
    assert meta.get("opener") == "fruit_character"
    assert "abstract" not in str(meta.get("source") or "")
    assert len(mixed) >= 6
    for p in mixed:
        assert "abstract" not in Path(p).name.lower()


def test_fruit_topic_never_uses_abstract_gradient(tmp_path):
    """Fruit topic local path must not produce abstract_* files."""
    from veridiq.postings.local_stills import ensure_still_set, generate_local_stills

    topic = "cute apple banana orange fruits"
    paths = generate_local_stills(
        topic, n=3, width=480, height=270, prefix="nofall", out_dir=tmp_path
    )
    assert len(paths) >= 3
    assert all("abstract" not in Path(p).name.lower() for p in paths)
    mixed, meta = ensure_still_set(
        [], topic, n=3, width=480, height=270, prefix="nofall2", force_local=True
    )
    assert meta.get("creative_abstract") is False
    assert meta.get("is_fruit") is True
    assert all("abstract" not in Path(p).name.lower() for p in mixed)


def test_generate_local_stills_veridiq(tmp_path):
    from veridiq.postings.local_stills import frame_copy_for_topic, generate_local_stills

    frames = frame_copy_for_topic("create a video for my verdiq explaining what veridiq is", n=3)
    assert len(frames) == 3
    assert frames[0].get("layout") == "hero"
    assert frames[0]["title"].upper() == "VERIDIQ"
    assert "empowered" in (frames[0].get("subtitle") or "").lower()
    titles = " ".join(f["title"] for f in frames).lower()
    assert "veridiq" in titles or "truth" in titles or "workforce" in titles
    joined = " ".join(
        f"{f.get('eyebrow','')} {f.get('title','')} {f.get('subtitle','')} {f.get('footer','')}"
        for f in frames
    ).lower()
    assert "scene" not in joined

    paths = generate_local_stills(
        "what is VERIDIQ",
        n=3,
        width=1280,
        height=720,
        prefix="test_vq",
        out_dir=tmp_path,
    )
    assert len(paths) == 3
    assert "hero" in Path(paths[0]).name.lower()
    for p in paths:
        assert Path(p).is_file()
        assert Path(p).stat().st_size > 2000


def test_first_still_is_local_hero_opener(tmp_path, monkeypatch):
    """Brand opening shot: frame 0 is always local branded hero, never AI muddy still."""
    from PIL import Image

    from veridiq.postings import local_stills
    from veridiq.postings.local_stills import (
        ensure_still_set,
        frame_copy_for_topic,
        generate_local_hero_opener,
    )

    monkeypatch.setattr(local_stills, "IMG_DIR", tmp_path)

    hero = generate_local_hero_opener(
        "what is VERIDIQ",
        width=1280,
        height=720,
        prefix="hero_unit",
        out_dir=tmp_path,
    )
    assert hero and Path(hero).is_file()
    assert "hero" in Path(hero).name.lower()

    copy0 = frame_copy_for_topic("agent workspace promo", n=1)[0]
    assert copy0["title"].upper() == "VERIDIQ"
    assert "truth" in copy0["subtitle"].lower() and "empowered" in copy0["subtitle"].lower()

    ai_paths = []
    for i in range(3):
        p = tmp_path / f"ai{i}.png"
        Image.new("RGB", (1280, 720), (10, 10, 10)).save(p)
        ai_paths.append(str(p))

    mixed, meta = ensure_still_set(
        ai_paths,
        "create a video for my verdiq explaining what veridiq is",
        n=3,
        prefix="opener",
        width=1280,
        height=720,
    )
    assert meta.get("hero_opener") is True
    assert meta.get("opener") == "local_hero"
    assert len(mixed) == 3
    assert "hero" in Path(mixed[0]).name.lower()
    assert Path(mixed[0]).name != Path(ai_paths[0]).name
    assert meta.get("ai_used_after_hero", 0) <= 2


def test_creative_prefer_ai_no_title_hero(tmp_path, monkeypatch):
    """Non-fruit creative: AI stills used as-is; no topic-title hero prepended."""
    from PIL import Image

    from veridiq.postings import local_stills

    monkeypatch.setattr(local_stills, "IMG_DIR", tmp_path)
    ai = []
    for i in range(3):
        p = tmp_path / f"ai_gym_{i}.png"
        Image.new("RGB", (1280, 720), (40 + i * 30, 120, 60)).save(p)
        ai.append(str(p))

    mixed, meta = local_stills.ensure_still_set(
        ai,
        "gym workout montage motivation",
        n=3,
        width=1280,
        height=720,
        prefix="gym_ai",
        hero_opener=False,
    )
    assert meta.get("source") == "ai"
    assert meta.get("creative_abstract") is False
    assert len(mixed) == 3
    assert mixed == ai[:3]
    for p in mixed:
        assert "hero" not in Path(p).name.lower()
        assert "abstract" not in Path(p).name.lower()


def test_talking_fruits_prefer_local_not_ai(tmp_path, monkeypatch):
    """Fruit+speak: local talking fruits win even if AI paths are provided."""
    from PIL import Image

    from veridiq.postings import local_stills

    monkeypatch.setattr(local_stills, "IMG_DIR", tmp_path)
    ai = []
    for i in range(3):
        p = tmp_path / f"ai_fruit_{i}.png"
        Image.new("RGB", (1280, 720), (40 + i * 30, 120, 60)).save(p)
        ai.append(str(p))

    mixed, meta = local_stills.ensure_still_set(
        ai,
        "talking fruits introducing themselves",
        n=3,
        width=1280,
        height=720,
        prefix="fruit_ai",
        hero_opener=False,
        duration_sec=6.0,
        speaking=True,
    )
    assert meta.get("creative_abstract") is False
    assert meta.get("mouth_variants") is True
    assert meta.get("source") == "local_talking_fruits"
    assert meta.get("local_talking_fruits") is True
    assert meta.get("pollinations_calls") == 0
    assert meta.get("ai_count") == 0
    assert len(mixed) >= 6
    for p in mixed:
        assert "abstract" not in Path(p).name.lower()
        assert any(k in Path(p).name.lower() for k in ("apple", "banana", "orange"))
        # AI paths must not win
        assert "ai_fruit" not in Path(p).name.lower()


def test_fruit_topic_never_schedules_pollinations(monkeypatch, tmp_path):
    """Fruit topic forces local_talking_fruits — generate_best_image never called."""
    from veridiq.integrations import local_video
    from veridiq.postings import mira_engine

    monkeypatch.setattr(local_video, "OUT_DIR", tmp_path)
    monkeypatch.setattr("veridiq.postings.local_stills.IMG_DIR", tmp_path)

    calls: list[str] = []

    def _must_not_call(**kwargs):
        calls.append(str(kwargs.get("prompt") or "")[:80])
        raise AssertionError("Pollinations must not be called for fruit topics")

    def _fake_narr(**_kwargs):
        wav = tmp_path / "vo.wav"
        wav.write_bytes(b"RIFF" + b"\x00" * 200)
        return {"ok": True, "absolute_path": str(wav), "message": "test vo"}

    monkeypatch.setattr("veridiq.postings.creative.generate_best_image", _must_not_call)
    monkeypatch.setattr(
        "veridiq.postings.creative.generate_video_narration_audio", _fake_narr
    )

    out = mira_engine.generate_video(
        "Create a video of talking fruits describing themselves",
        duration_sec=15,
        force_narration=True,
        n_stills=3,
    )
    assert calls == [], f"Pollinations was scheduled: {calls}"
    assert out.get("ok") is True, out.get("message")
    assert out.get("local_talking_fruits") is True
    assert out.get("pollinations_calls") == 0
    local = out.get("local_stills") or {}
    assert local.get("source") == "local_talking_fruits"
    assert local.get("pollinations_calls") == 0
    assert local.get("creative_abstract") is False
    assert "local_talking_fruits" in str(out.get("message") or "")
    assert out.get("provider") == "local_talking_fruits"
    # Still paths are local fruit PNGs
    notes = " ".join(str(n) for n in ((out.get("keyframe_meta") or {}).get("notes") or []))
    assert "local_talking_fruits" in notes or "Pollinations" in notes
    # Open first still — must not be multi-panel grid / abstract
    from PIL import Image

    from veridiq.postings.local_stills import render_talking_fruit_stills

    paths = render_talking_fruit_stills(
        "talking fruits",
        n=3,
        width=640,
        height=360,
        speaking=True,
        duration_sec=6,
        prefix="proof",
        out_dir=tmp_path,
    )
    assert paths
    img = Image.open(paths[0]).convert("RGB")
    assert img.size == (640, 360)
    # Center region should be strongly colored (fruit body), not uniform green blur
    cx, cy = img.size[0] // 2, img.size[1] // 2
    r, g, b = img.getpixel((cx, cy))
    assert not (g > r + 40 and g > b + 40 and g > 150), (r, g, b)  # not abstract green goo


def test_local_still_drawn_text_has_no_scene(tmp_path):
    """Unit: local still generator does not include 'scene' in drawn text."""
    from veridiq.postings.local_stills import frame_copy_for_topic

    for topic in (
        "create a video for my veridig in that tell what veridig is",
        "agent workspace promo",
        "random topic about coffee",
    ):
        frames = frame_copy_for_topic(topic, n=3)
        blob = " ".join(
            f"{f.get('eyebrow','')} {f.get('title','')} {f.get('subtitle','')} {f.get('footer','')}"
            for f in frames
        ).lower()
        assert "scene" not in blob, blob


def test_ensure_still_set_pads_ai_shortfall(tmp_path, monkeypatch):
    from PIL import Image

    from veridiq.postings import local_stills
    from veridiq.postings.local_stills import ensure_still_set

    monkeypatch.setattr(local_stills, "IMG_DIR", tmp_path)
    ai = tmp_path / "ai0.png"
    Image.new("RGB", (1280, 720), (20, 40, 80)).save(ai)
    mixed, meta = ensure_still_set(
        [str(ai)],
        "VERIDIQ truth verification",
        n=3,
        prefix="mix",
        width=1280,
        height=720,
    )
    assert len(mixed) == 3
    assert meta["source"] == "mixed"
    assert meta["ai_count"] == 1
    assert meta.get("opener") == "local_hero"
    assert "hero" in Path(mixed[0]).name.lower()
    assert meta["local_count"] >= 1


def test_ensure_still_set_force_local_when_ai_empty(tmp_path, monkeypatch):
    from veridiq.postings import local_stills

    monkeypatch.setattr(local_stills, "IMG_DIR", tmp_path)
    paths, meta = local_stills.ensure_still_set(
        [],
        "veridiq",
        n=3,
        force_local=True,
        prefix="force",
    )
    assert len(paths) == 3
    assert meta["source"] == "local"
    assert "hero" in Path(paths[0]).name.lower()


def test_mira_generate_video_uses_local_when_pollinations_fails(monkeypatch, tmp_path):
    """AI stills all fail → local Pillow stills → ok MP4 (reliability path)."""
    from veridiq.integrations import local_video
    from veridiq.postings import mira_engine

    monkeypatch.setattr(local_video, "OUT_DIR", tmp_path)
    monkeypatch.setattr("veridiq.postings.local_stills.IMG_DIR", tmp_path)

    def _fail_img(**_kwargs):
        return {"ok": False, "status": "error", "message": "429 rate limited"}

    def _fake_narr(**_kwargs):
        wav = tmp_path / "vo.wav"
        wav.write_bytes(b"RIFF" + b"\x00" * 200)
        return {"ok": True, "absolute_path": str(wav), "message": "test vo"}

    monkeypatch.setattr("veridiq.postings.creative.generate_best_image", _fail_img)
    monkeypatch.setattr(
        "veridiq.postings.creative.generate_video_narration_audio", _fake_narr
    )
    monkeypatch.setattr(mira_engine, "_AI_PHASE_BUDGET_SEC", 2.0)
    monkeypatch.setattr(mira_engine, "_STILL_TIMEOUT", 1.0)

    t0 = time.monotonic()
    out = mira_engine.generate_video(
        "create a video for my verdiq in that tell what veridiq is",
        duration_sec=15,
        force_narration=True,
        n_stills=3,
    )
    elapsed = time.monotonic() - t0
    assert out.get("ok") is True, out.get("message")
    assert out.get("status") == "ok"
    render = out.get("render") or {}
    assert render.get("video_url") or render.get("absolute_path")
    assert int(out.get("stills_count") or 0) >= 3
    assert (out.get("local_stills") or {}).get("source") == "local"
    assert (out.get("quality") or {}).get("reliability_path") is True
    assert elapsed < 90, f"local fallback took too long: {elapsed:.1f}s"
    narr = str((out.get("storyboard") or {}).get("narration_script") or "")
    assert "scene one" not in narr.lower()
    assert "scene 1" not in narr.lower()


def test_mira_fruit_fallback_uses_fruit_not_abstract(monkeypatch, tmp_path):
    """Fruit topic with AI fail → local fruit characters, no abstract / title cards."""
    from veridiq.integrations import local_video
    from veridiq.postings import mira_engine

    monkeypatch.setattr(local_video, "OUT_DIR", tmp_path)
    monkeypatch.setattr("veridiq.postings.local_stills.IMG_DIR", tmp_path)

    def _fail_img(**_kwargs):
        return {"ok": False, "status": "error", "message": "429"}

    def _fake_narr(**_kwargs):
        wav = tmp_path / "vo.wav"
        wav.write_bytes(b"RIFF" + b"\x00" * 200)
        return {"ok": True, "absolute_path": str(wav), "message": "test vo"}

    monkeypatch.setattr("veridiq.postings.creative.generate_best_image", _fail_img)
    monkeypatch.setattr(
        "veridiq.postings.creative.generate_video_narration_audio", _fake_narr
    )
    monkeypatch.setattr(mira_engine, "_AI_PHASE_BUDGET_SEC", 2.0)
    monkeypatch.setattr(mira_engine, "_STILL_TIMEOUT", 1.0)

    out = mira_engine.generate_video(
        "Every Froot Describing Their Identity",
        duration_sec=15,
        force_narration=True,
        n_stills=3,
    )
    assert out.get("ok") is True, out.get("message")
    local = out.get("local_stills") or {}
    assert local.get("creative_abstract") is False
    assert local.get("opener") == "fruit_character" or "fruit" in str(local.get("source") or "")
    assert local.get("source") == "local_talking_fruits"
    assert local.get("mouth_variants") is True or local.get("speaking") is True
    assert out.get("local_talking_fruits") is True
    assert "local_talking_fruits" in str(out.get("message") or "")
    title = str((out.get("storyboard") or {}).get("title") or "")
    assert "froot" not in title.lower()
    assert "describ" not in title.lower()
    assert "identity" not in title.lower()
    narr = str((out.get("storyboard") or {}).get("narration_script") or "").lower()
    assert "apple" in narr or "banana" in narr or "orange" in narr
    msg = str(out.get("message") or "").lower()
    assert "abstract" not in msg or "no abstract" in msg
    assert "talking fruit" in msg or "mouth" in msg or "fruit" in msg or "local_talking_fruits" in msg


def test_local_stills_assemble_under_10s(tmp_path, monkeypatch):
    from veridiq.integrations import local_video
    from veridiq.postings.local_stills import generate_local_stills

    monkeypatch.setattr(local_video, "OUT_DIR", tmp_path)
    stills = generate_local_stills("VERIDIQ", n=3, out_dir=tmp_path, prefix="enc")
    assert len(stills) == 3
    board = {
        "storyboard_id": "local_enc_test",
        "duration_sec": 15,
        "aspect": "16:9",
        "title": "VERIDIQ",
        "shot_list": [{"duration_sec": 5} for _ in range(3)],
    }
    t0 = time.monotonic()
    render = local_video.render_storyboard_from_stills(
        board,
        stills,
        fast_hold=True,
        mira_cinematic=False,
        force_fps=12,
        crossfade_sec=0.25,
        burn_captions=False,
    )
    elapsed = time.monotonic() - t0
    assert render.get("ok") or render.get("status") == "ok"
    assert render.get("video_url")
    assert elapsed < 10.0, f"encode took {elapsed:.1f}s"


def test_ensure_still_set_force_local_brand_cards(tmp_path, monkeypatch):
    """Brand force_local → hero + local cards only (no AI support slots used)."""
    from PIL import Image

    from veridiq.postings import local_stills

    monkeypatch.setattr(local_stills, "IMG_DIR", tmp_path)
    ai = []
    for i in range(2):
        p = tmp_path / f"ai_noise_{i}.png"
        Image.new("RGB", (1280, 720), (200, 10, 10)).save(p)
        ai.append(str(p))

    mixed, meta = local_stills.ensure_still_set(
        ai,
        "what is VERIDIQ",
        n=3,
        width=1280,
        height=720,
        prefix="brand_force",
        force_local=True,
        hero_opener=True,
    )
    assert meta.get("source") == "local"
    assert meta.get("ai_used_after_hero", 0) == 0
    assert len(mixed) == 3
    assert "hero" in Path(mixed[0]).name.lower()
    for p in mixed:
        assert "ai_noise" not in Path(p).name


def test_veridiq_narration_script():
    from veridiq.postings.local_stills import veridiq_narration_script

    s = veridiq_narration_script("tell what veridiq is")
    assert "VERIDIQ" in s
    assert "truth" in s.lower() or "verif" in s.lower() or "intelligence" in s.lower()
    assert "scene one" not in s.lower()
    assert "scene 1" not in s.lower()
    assert len(s.split(".")) >= 2


def test_build_narration_no_scene_indices():
    from veridiq.postings.creative import build_narration_script, strip_scene_index_speakables

    for topic in (
        "create a video for my veridig that explain what veridig is",
        "agent workspace promo",
        "coffee brewing tips scene 1",
    ):
        s = build_narration_script(topic)
        low = s.lower()
        assert "scene one" not in low
        assert "scene 1" not in low
        assert "this is scene" not in low
    dirty = "Welcome. This is scene one. Then scene 2 happens."
    clean = strip_scene_index_speakables(dirty).lower()
    assert "scene one" not in clean
    assert "scene 2" not in clean


def test_custom_subject_board_voiceover_no_scene():
    from veridiq.postings.studio import _custom_subject_video_board

    board = _custom_subject_video_board(
        "create a video for my verdiq explaining what veridiq is",
        duration_sec=15,
    )
    narr = str(board.get("narration_script") or "").lower()
    assert "scene one" not in narr
    assert "scene 1" not in narr
    for shot in board.get("shot_list") or []:
        vo = str(shot.get("voiceover") or "").lower()
        assert not re.search(r"scene\s*\d+", vo)
        assert shot.get("on_screen_text") in ("", None)


def test_looks_like_collage_or_grid_detects_tiles(tmp_path):
    """4x4 tiled image should trip the collage heuristic; solid color should not."""
    from PIL import Image, ImageDraw

    from veridiq.postings.creative import looks_like_collage_or_grid

    solid = tmp_path / "solid.png"
    Image.new("RGB", (256, 256), (80, 120, 160)).save(solid)
    assert looks_like_collage_or_grid(solid) is False

    grid = tmp_path / "grid.png"
    img = Image.new("RGB", (256, 256), (20, 20, 20))
    draw = ImageDraw.Draw(img)
    for i in range(4):
        for j in range(4):
            x0, y0 = i * 64, j * 64
            draw.rectangle([x0 + 4, y0 + 4, x0 + 60, y0 + 60], fill=(200, 100, 80))
            draw.ellipse([x0 + 16, y0 + 16, x0 + 48, y0 + 48], fill=(240, 200, 160))
            draw.ellipse([x0 + 22, y0 + 24, x0 + 28, y0 + 30], fill=(20, 20, 20))
            draw.ellipse([x0 + 36, y0 + 24, x0 + 42, y0 + 30], fill=(20, 20, 20))
            draw.line([(x0, 0), (x0, 255)], fill=(255, 255, 255), width=2)
            draw.line([(0, y0), (255, y0)], fill=(255, 255, 255), width=2)
    img.save(grid)
    assert looks_like_collage_or_grid(grid) is True


def test_fruit_kitchen_bg_not_bare_void(tmp_path):
    """Fruit still corners should not be near-white empty beige; no huge white rect."""
    from PIL import Image

    from veridiq.postings.local_stills import render_fruit_character

    img = render_fruit_character("orange", mouth_open=False, width=640, height=360)
    path = tmp_path / "orange_bg.png"
    img.save(path)
    rgb = Image.open(path).convert("RGB")
    w, h = rgb.size
    # Sample four corners — must not all be near-white / empty beige void
    corners = [
        rgb.getpixel((2, 2)),
        rgb.getpixel((w - 3, 2)),
        rgb.getpixel((2, h - 3)),
        rgb.getpixel((w - 3, h - 3)),
    ]

    def _near_white_beige(px: tuple[int, int, int]) -> bool:
        r, g, b = px
        return r > 235 and g > 230 and b > 210 and (r - b) < 50

    assert not all(_near_white_beige(c) for c in corners), corners
    # Top-left should show sky/wall tint (not flat white window void)
    tl = corners[0]
    assert not (tl[0] > 250 and tl[1] > 248 and tl[2] > 240), tl
    # No large empty white rectangle in classic window slot (sample mid window area)
    # Old artifact was fill~(255,252,240) solid block — require outdoor-ish chroma variety
    wx0, wy0 = int(w * 0.10), int(h * 0.18)
    wx1, wy1 = int(w * 0.26), int(h * 0.40)
    samples = [
        rgb.getpixel((x, y))
        for x in (wx0, (wx0 + wx1) // 2, wx1)
        for y in (wy0, (wy0 + wy1) // 2, wy1)
    ]
    near_white = sum(1 for p in samples if p[0] > 248 and p[1] > 245 and p[2] > 235)
    assert near_white <= 2, samples  # window should show sky/hills, not empty white
    # Center fruit still strongly orange
    cx, cy = w // 2, int(h * 0.46)
    r, g, b = rgb.getpixel((cx, cy))
    assert r > 180 and r > b + 40, (r, g, b)


def test_topic_illustration_dog_and_car(tmp_path):
    """Non-fruit creative local fallback draws topic-aware subjects, not abstract_*."""
    from PIL import Image

    from veridiq.postings.local_stills import (
        detect_illustration_subject,
        ensure_still_set,
        generate_local_stills,
        render_topic_illustration_stills,
    )

    assert detect_illustration_subject("create a video of a cute dog") == "dog"
    assert detect_illustration_subject("red sports car racing") == "car"
    assert detect_illustration_subject("gym workout montage") == "gym"

    dog_paths = render_topic_illustration_stills(
        "talking dog introducing itself",
        n=3,
        width=480,
        height=270,
        speaking=True,
        duration_sec=4.0,
        prefix="doggo",
        out_dir=tmp_path,
    )
    assert len(dog_paths) >= 4
    names = [Path(p).name.lower() for p in dog_paths]
    assert any("_open" in n for n in names)
    assert any("_closed" in n for n in names)
    assert all("abstract" not in n for n in names)

    car_paths = generate_local_stills(
        "create a video of a red car",
        n=3,
        width=480,
        height=270,
        prefix="carloc",
        out_dir=tmp_path,
    )
    assert len(car_paths) >= 3
    assert all("abstract" not in Path(p).name.lower() for p in car_paths)
    img = Image.open(car_paths[0]).convert("RGB")
    # Background should have sky/road structure — not uniform brown/green pad
    tl = img.getpixel((4, 4))
    assert not (tl[1] > tl[0] + 40 and tl[1] > 150), tl  # not orchard-green abstract

    mixed, meta = ensure_still_set(
        [],
        "robot dancing in neon city",
        n=3,
        width=480,
        height=270,
        prefix="robo",
        force_local=True,
    )
    assert meta.get("source") == "local_illustration"
    assert meta.get("creative_abstract") is False
    assert meta.get("illustration_subject") == "robot"
    assert len(mixed) >= 3
    assert all("abstract" not in Path(p).name.lower() for p in mixed)
