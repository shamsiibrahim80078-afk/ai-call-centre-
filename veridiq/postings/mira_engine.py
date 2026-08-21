"""Mira Cinematic Engine — VERIDIQ first-party free video model.

HONESTY (do not overclaim in UI or agent replies):
- We cannot train a Veo-scale foundation model from scratch in this repo
  (needs massive GPU clusters + proprietary video corpora).
- Mira is NOT Google Veo and does not ship trained neural-video weights.
- What we ship: a branded multi-stage pipeline that chains the best *free*
  open techniques for higher quality than a soft turbo slideshow:
  Quality Injection prompts → Pollinations keyframes (turbo for long, Flux ≤15s) →
  local motion (Ken Burns short / fast holds for ≥60s) → assemble → edge-tts VO mux.
- Pollinations /video/* endpoints exist but require API keys (paid video
  models) — Mira does not call them on the free unlimited path.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent.parent
_CONFIG_PATH = Path(__file__).resolve().parent / "mira_engine_config.json"
IMG_DIR = _ROOT / "marketing_out" / "images"

ENGINE_NAME = "Mira Cinematic Engine"
ENGINE_ID = "mira_cinematic_v1"
ENGINE_TAGLINE = (
    "Mira Cinematic Engine — VERIDIQ first-party free video model "
    "(multi-scene photoreal pipeline). Not Google Veo."
)
RENDER_MESSAGE = "Rendered with Mira Cinematic Engine (free unlimited)"
VIDEO_NOTE_SHORT = ENGINE_TAGLINE

# Max free Pollinations still size (API clamps ~1280)
_STILL_W = 1280
_STILL_H = 720
_OUT_W = 1920
_OUT_H = 1080
_OUT_FPS = 30
_DEFAULT_STILLS = 3
_MAX_STILLS = 3  # hard cap for ANY duration (3-min = 3 stills held longer)
_STILL_TIMEOUT = 9.0  # per-still hard timeout (8–10s band)
_AI_PHASE_BUDGET_SEC = 35.0  # never block forever on Pollinations
_WALL_BUDGET_SEC = 120.0  # encode+VO room inside ~150s job ceiling
_MIN_BEST_EFFORT = 1  # AI best-effort; local stills guarantee completion
_STILL_WORKERS = 1  # Pollinations free IP queue max 1 (shared with images)
_VO_TIMEOUT_SEC = 12.0
_RELIABILITY_FPS = 12
_FAIL_STREAK_ABORT = 2  # consecutive AI failures → local stills immediately

# Optional progress hook: (message, progress_0_100 | None) -> None
_progress_hook = None


def set_progress_hook(fn) -> None:
    """Video jobs may register a status callback for UX messages."""
    global _progress_hook
    _progress_hook = fn


def clear_progress_hook() -> None:
    global _progress_hook
    _progress_hook = None


def _report(message: str, progress: int | None = None) -> None:
    hook = _progress_hook
    if hook is None:
        return
    try:
        hook(message, progress)
    except Exception:
        pass


def load_config() -> dict[str, Any]:
    """Load Mira model-card settings (CFG, steps, fps, shot templates)."""
    try:
        raw = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return raw
    except Exception:
        pass
    return {
        "model_id": ENGINE_ID,
        "display_name": ENGINE_NAME,
        "cfg": 7.5,
        "steps": 40,
        "fps": _OUT_FPS,
        "still_gen": {
            "width": _STILL_W,
            "height": _STILL_H,
            "model": "turbo",
            "default_stills": 3,
        },
        "motion": {"crossfade_sec": 0.45, "midframe_blend": False},
        "free_unlimited": True,
        "paid_apis": {"veo": False},
    }


def engine_identity() -> dict[str, Any]:
    cfg = load_config()
    return {
        "mira_engine": True,
        "free_unlimited": True,
        "paid_veo": False,
        "engine": ENGINE_NAME,
        "engine_id": cfg.get("model_id") or ENGINE_ID,
        "kind": cfg.get("kind") or "first_party_pipeline",
        "is_trained_foundation_model": False,
        "is_google_veo": False,
        "tagline": ENGINE_TAGLINE,
        "honesty": (cfg.get("honesty") or {}).get("description")
        or "Pipeline of free open techniques — not a trained Veo-scale model.",
    }


def _still_count_for_duration(duration_sec: int) -> int:
    """Unique stills capped at 3 for any length — long videos hold frames longer."""
    _ = duration_sec  # duration stretches holds, not still count
    cfg_n = int((load_config().get("still_gen") or {}).get("default_stills") or _DEFAULT_STILLS)
    return max(2, min(_MAX_STILLS, cfg_n, _DEFAULT_STILLS))


def _prefer_flux_for_duration(duration_sec: int) -> bool:
    """Free path: turbo only unless VERIDIQ_VIDEO_PREFER_FLUX=1 (Flux is slower)."""
    _ = duration_sec
    flag = (os.getenv("VERIDIQ_VIDEO_PREFER_FLUX") or "").strip().lower()
    return flag in ("1", "true", "yes", "on")


def _wall_budget_sec(duration_sec: int) -> float:
    """Overall Mira wall (AI ≤35s + encode + VO) — under job 150s ceiling."""
    _ = duration_sec
    return min(140.0, max(90.0, _WALL_BUDGET_SEC))


def _ai_deadline(t0: float, overall_deadline: float | None = None) -> float:
    """Hard cap for Pollinations phase — local stills take over after this."""
    ai_end = t0 + _AI_PHASE_BUDGET_SEC
    if overall_deadline is not None:
        return min(ai_end, float(overall_deadline))
    return ai_end


def compile_prompts(
    topic: str,
    *,
    duration_sec: int = 15,
    aspect: str = "16:9",
    style: str = "cinematic",
    n_stills: int | None = None,
    dialogue: str | None = None,
) -> list[str]:
    """Stage 1 — Quality Injection: always use build_cinematic_prompt."""
    from veridiq.integrations.pollinations_image import (
        clean_user_prompt,
        detect_subject_lock,
        expand_user_typos,
    )
    from veridiq.postings.creative import (
        BRIGHT_LIGHTING,
        CAMERA_PHYSICS_ANCHOR,
        FRUIT_SUBJECT_ANCHOR,
        QUALITY_ANCHOR_SENTENCE,
        build_cinematic_prompt,
        _is_veridiq_or_workspace_topic,
    )
    from veridiq.postings.local_stills import _clean_topic_title

    cfg = load_config()
    templates = cfg.get("shot_templates") or []
    topic_x = expand_user_typos(topic or "")
    lock = detect_subject_lock(topic_x)
    is_fruit = bool(lock.get("is_fruit"))
    is_nonhuman = bool(lock.get("is_nonhuman"))
    is_workspace = _is_veridiq_or_workspace_topic(topic_x) or bool(
        re.search(r"\b(agent|agents|workspace|office|desk)\b", topic_x, re.I)
        and not is_fruit
        and not is_nonhuman
    )
    look = str(
        cfg.get("look_matching")
        or "photoreal office, sharp subject, cinematic grade"
    )
    if is_fruit:
        look = (
            f"{FRUIT_SUBJECT_ANCHOR}, bright colorful fruit set, cheerful daylight studio"
        )
    elif is_nonhuman:
        look = "cute anthropomorphic characters, bright well-lit colorful set, Pixar-quality"
    elif is_workspace:
        look = (
            "cinematic agent desk / product UI B-roll, midnight + electric blue accents, "
            "curved ultrawide Agent Workspace dashboard, light wood desk, sharp well-lit, "
            "professional SaaS commercial — NOT muddy creatures, NOT horror, NOT monsters, "
            "no text, no captions, no words, no letters on image, no watermarks, no scene labels"
        )
    # Never feed raw user command text into the image model (causes text burn-in)
    subject_src = (
        lock.get("primary_subject")
        or clean_user_prompt(topic_x)
        or _clean_topic_title(topic_x)
        or "cinematic VERIDIQ scene"
    )
    subject = re.sub(r"\s+", " ", str(subject_src)).strip()[:180]
    if re.search(
        r"\b(create|make|generate)\s+(a\s+)?(video|clip|image|reel)\b",
        subject,
        re.I,
    ) or len(subject) > 120:
        subject = _clean_topic_title(topic_x) or "cinematic VERIDIQ scene"
    if is_workspace:
        # Shot 0 is always local branded hero — AI prompts are for supporting B-roll (1+)
        agent_subjects = (
            "Cinematic over-shoulder of a clean Agent Workspace product UI on a curved ultrawide, "
            "soft window light, electric blue accents, sharp focus, commercial desk setup",
            "Modern AI workforce office — light wood desk, dual monitors with abstract charts only "
            "(no readable text), electric blue glow, bright enough cinematic grade",
            "Product UI close-up of sleek dashboard chrome without letters, midnight room, "
            "rim light, photoreal commercial still — no creature, no monster",
        )
    n = int(n_stills or _still_count_for_duration(duration_sec))
    aspect_note = (
        "portrait 9:16 vertical framing"
        if aspect == "9:16"
        else "landscape 16:9 framing"
    )
    # One coherent character per still — never a face-grid / collage
    fruit_shots = (
        "ONE single cute cartoon Apple fruit character with a clear face, Pixar style, "
        "bright centered, clear fruit shape, NOT translucent blob, NOT abstract",
        "ONE single cute cartoon Banana fruit character with a clear face, Pixar style, "
        "bright centered, clear fruit shape, NOT translucent blob, NOT abstract",
        "ONE single cute cartoon Orange fruit character with a clear face, Pixar style, "
        "bright centered, clear fruit shape, NOT translucent blob, NOT abstract",
    )
    prompts: list[str] = []
    for i in range(n):
        tmpl = templates[i % len(templates)] if templates else {}
        label = str(tmpl.get("label") or f"Shot {i + 1}")
        camera = str(tmpl.get("camera") or "medium shot, eye-level")
        motion = str(tmpl.get("motion") or "smooth cinematic panning")
        if is_fruit:
            action = fruit_shots[i % len(fruit_shots)]
            env = f"{look}. {aspect_note}."
            pr = build_cinematic_prompt(
                f"{FRUIT_SUBJECT_ANCHOR}: {action}",
                f"{motion}: talking fruit character",
                env,
                lighting=BRIGHT_LIGHTING,
                camera=f"{camera}. {CAMERA_PHYSICS_ANCHOR}",
                dialogue=None,
                fruit=True,
                bright=True,
            )
            pr = (
                f"{pr}. Negative: collage, grid, tile, sheet of faces, contact sheet, "
                "multiple panels, meme, watermark, text, letters, words, title card, "
                "poster with text, distorted faces, blurry, low quality"
            )
        elif is_workspace:
            env = f"{look}. {aspect_note}."
            cam = (
                f"Photorealistic {camera}, {CAMERA_PHYSICS_ANCHOR}, "
                f"style={style}, commercial product B-roll"
            )
            # Prefer supporting B-roll subjects (index maps past opener)
            subj_i = agent_subjects[i % len(agent_subjects)]
            pr = build_cinematic_prompt(
                subj_i,
                f"{motion}",
                env,
                cam,
                dialogue=None,
                lighting=(
                    "soft natural window light mixed with electric blue screen glow, "
                    "bright enough cinematic commercial grade — "
                    "NOT pitch-black, NOT muddy, NOT blurry monster/creature"
                ),
            )
            pr = (
                f"{pr}. Negative: blurry, dark muddy, monster, creature, "
                "no text, no captions, no words, no letters on image, "
                "text overlay, captions, words on image, horror"
            )
        else:
            env = f"{look}. {aspect_note}."
            cam = (
                f"Photorealistic {camera}, {CAMERA_PHYSICS_ANCHOR}, "
                f"style={style}"
            )
            # Hard subject lock: every still prompt MUST lead with PRIMARY SUBJECT
            pr = build_cinematic_prompt(
                f"PRIMARY SUBJECT (CRITICAL): {subject}",
                f"{motion}: {subject}",
                env,
                cam,
                dialogue=None,
                lighting=BRIGHT_LIGHTING if is_nonhuman else "",
                nonhuman=is_nonhuman,
                bright=is_nonhuman,
            )
            if not is_nonhuman and not is_fruit:
                pr = (
                    f"{pr}. Negative: cat, dog, animal, unrelated objects, "
                    "wrong subject, subject drift"
                )
        # Always forbid text-in-image (strong negatives — models love burning prompts)
        if "no letters on image" not in pr.lower():
            pr = (
                f"{pr}. no text, no captions, no words, no letters on image, "
                "no watermarks, no scene 1 lettering, no written prompt on frame"
            )
        if QUALITY_ANCHOR_SENTENCE.split(",")[0].lower() not in pr.lower():
            pr = f"{pr}. {QUALITY_ANCHOR_SENTENCE}"
        try:
            from veridiq.postings.learning import apply_learned_quality

            pr = apply_learned_quality(pr, topic=topic_x or subject)
        except Exception:
            pass
        prompts.append(pr[:2000])
    return prompts


def _ensure_cinematic(prompts: list[str], topic: str) -> list[str]:
    """Wrap any plain shot lines with Quality Injection."""
    from veridiq.postings.creative import QUALITY_ANCHOR_SENTENCE, build_cinematic_prompt

    out: list[str] = []
    for p in prompts:
        text = (p or "").strip()
        if not text:
            continue
        low = text.lower()
        if "photorealistic 4k render" in low and "volumetric" in low:
            if QUALITY_ANCHOR_SENTENCE.split(",")[0].lower() not in low:
                text = f"{text}. {QUALITY_ANCHOR_SENTENCE}"
            out.append(text[:2000])
        else:
            out.append(
                build_cinematic_prompt(
                    topic or "cinematic subject",
                    text[:220],
                    "photoreal office, sharp subject, cinematic grade",
                )[:2000]
            )
    return out


def generate_keyframes(
    prompts: list[str],
    *,
    style: str = "cinematic",
    prefix: str | None = None,
    width: int | None = None,
    height: int | None = None,
    min_required: int = 4,
    duration_sec: int = 15,
    deadline: float | None = None,
) -> tuple[list[str], dict[str, Any]]:
    """Stage 2 — try free AI stills hard, abort fast to local fallback.

    Per-still ~9s; total AI phase capped by ``deadline`` (caller: ≤35s).
    On failure streak or wall → return whatever AI stills landed (0–N).
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from veridiq.postings.creative import generate_best_image

    use_flux = _prefer_flux_for_duration(duration_sec)
    os.environ["VERIDIQ_VIDEO_PREFER_FLUX"] = "1" if use_flux else "0"
    cfg = load_config()
    still = cfg.get("still_gen") or {}
    w = int(width or still.get("width") or _STILL_W)
    h = int(height or still.get("height") or _STILL_H)
    stem = prefix or f"mira_{uuid.uuid4().hex[:8]}"
    base_seed = int(time.time() * 1000) % 2_147_483_647
    paths: list[str] = []
    notes: list[str] = []
    models: list[str] = []
    primary_model = "flux" if use_flux else "turbo"
    workers = min(_STILL_WORKERS, max(1, len(prompts) or 1))
    fail_streak = 0
    aborted_early = False

    def _gen_one(i: int, pr: str, *, model: str, attempt: int) -> tuple[int, dict[str, Any]]:
        prev = os.environ.get("VERIDIQ_VIDEO_PREFER_FLUX")
        os.environ["VERIDIQ_VIDEO_PREFER_FLUX"] = "1" if model == "flux" else "0"
        try:
            img = generate_best_image(
                prompt=pr,
                style=style,
                width=w,
                height=h,
                filename_stem=f"{stem}_{i}" + (f"_r{attempt}" if attempt else ""),
                seed=(base_seed + i * 17 + attempt * 97) % 2_147_483_647,
                timeout=_STILL_TIMEOUT,
                prefer_pollinations=True,
                enhance=False,
                gemini_timeout=4.0,
                max_attempts=2,
            )
            return i, img
        finally:
            if prev is None:
                os.environ.pop("VERIDIQ_VIDEO_PREFER_FLUX", None)
            else:
                os.environ["VERIDIQ_VIDEO_PREFER_FLUX"] = prev

    def _past_deadline() -> bool:
        return deadline is not None and time.monotonic() >= deadline

    def _record(i: int, img: dict[str, Any]) -> bool:
        nonlocal fail_streak
        if img.get("ok") and img.get("absolute_path"):
            paths.append(str(img["absolute_path"]))
            fail_streak = 0
            if img.get("model"):
                models.append(str(img["model"]))
            return True
        fail_streak += 1
        notes.append(f"still[{i}] fail: {(img.get('message') or 'error')[:80]}")
        return False

    _report("Trying free AI scenes…", 22)

    indices = list(range(len(prompts)))
    if workers <= 1 or len(indices) <= 1:
        for i in indices:
            if _past_deadline():
                notes.append("AI phase budget hit — switching to Mira local scenes")
                aborted_early = True
                break
            if fail_streak >= _FAIL_STREAK_ABORT:
                notes.append(f"AI failure streak ({fail_streak}) — local scenes")
                aborted_early = True
                break
            _, img = _gen_one(i, prompts[i], model=primary_model, attempt=0)
            _record(i, img)
            time.sleep(0.2)
    else:
        pool = ThreadPoolExecutor(max_workers=workers)
        try:
            futs = {
                pool.submit(_gen_one, i, prompts[i], model=primary_model, attempt=0): i
                for i in indices
            }
            for fut in as_completed(futs):
                try:
                    i, img = fut.result(timeout=_STILL_TIMEOUT + 4)
                    _record(i, img)
                except Exception as exc:
                    fail_streak += 1
                    notes.append(f"still fail: {str(exc)[:80]}")
                if _past_deadline() or fail_streak >= _FAIL_STREAK_ABORT:
                    notes.append("AI phase abort — local scenes")
                    aborted_early = True
                    for pending in futs:
                        pending.cancel()
                    break
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    # One turbo retry only if we still have AI budget and < min_required
    if (
        len(paths) < min_required
        and not aborted_early
        and not _past_deadline()
        and fail_streak < _FAIL_STREAK_ABORT
    ):
        need = min(min_required - len(paths), max(1, len(prompts)))
        for j in range(need):
            if _past_deadline() or fail_streak >= _FAIL_STREAK_ABORT:
                aborted_early = True
                break
            i = len(paths) + j
            pr = prompts[i % len(prompts)] if prompts else "cinematic scene"
            _, img = _gen_one(i, pr, model="turbo", attempt=1)
            _record(i, img)
            time.sleep(0.2)

    meta = {
        "still_width": w,
        "still_height": h,
        "models": models or [primary_model],
        "primary_model": primary_model,
        "notes": notes,
        "count": len(paths),
        "min_required": min_required,
        "wall_aborted": bool(aborted_early or _past_deadline()),
        "ai_phase_budget_sec": _AI_PHASE_BUDGET_SEC,
        "fail_streak": fail_streak,
    }
    return paths, meta


def _upscale_unsharp_stills(still_paths: list[str], *, portrait: bool = False) -> list[str]:
    """Stage 3 prep — Lanczos to 1080p + mild unsharp for crispness (Pillow)."""
    from PIL import Image, ImageFilter

    from veridiq.integrations import local_video

    cfg = load_config()
    unsharp = (cfg.get("motion") or {}).get("unsharp") or {}
    radius = float(unsharp.get("radius") or 1.2)
    percent = int(unsharp.get("percent") or 120)
    threshold = int(unsharp.get("threshold") or 2)

    w, h, _ = local_video._sync_wh_fps(portrait=portrait)
    out_paths: list[str] = []
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    for path_str in still_paths:
        p = Path(path_str)
        if not p.is_file():
            continue
        try:
            img = Image.open(p).convert("RGB")
            resample = getattr(Image, "Resampling", Image).LANCZOS
            if img.size != (w, h):
                img = img.resize((w, h), resample)
            img = img.filter(
                ImageFilter.UnsharpMask(radius=radius, percent=percent, threshold=threshold)
            )
            dest = IMG_DIR / f"{p.stem}_mira1080{p.suffix or '.png'}"
            img.save(dest, quality=95)
            out_paths.append(str(dest))
        except Exception:
            out_paths.append(path_str)
    return out_paths or still_paths


def assemble_cinematic(
    storyboard: dict[str, Any],
    still_paths: list[str],
    *,
    audio_path: Optional[str] = None,
    caption_lines: list[str] | None = None,
    reliability: bool = False,
    fruit_talking: bool = False,
) -> dict[str, Any]:
    """Stages 3-4 — Motion enhance + assemble.

    reliability=True (local/mixed stills): 12fps fast holds, no Ken Burns.
    fruit_talking=True: slight Ken Burns @ 12–15fps (mouth-pair slideshow).
    Short AI clips: Mira cinematic Ken Burns @ 30fps.
    Long ≥60s: fast holds so encode stays within wall budget.
    """
    from veridiq.integrations import local_video

    cfg = load_config()
    motion = cfg.get("motion") or {}
    crossfade = float(motion.get("crossfade_sec") or 0.7)
    aspect = str(storyboard.get("aspect") or storyboard.get("aspect_ratio") or "16:9")
    portrait = aspect in ("9:16", "9/16", "portrait", "vertical")
    dur = int(storyboard.get("duration_sec") or 15)
    long_form = dur >= 60
    use_reliability = (bool(reliability) or long_form) and not fruit_talking

    if fruit_talking:
        # Talking fruits: mouth open/close pairs carry the “speaking” look.
        # Slight Ken Burns is optional — prefer reliable 12–15fps holds so encode
        # finishes quickly (full Mira Ken Burns @1080p was starving the free path).
        fruit_fps = 15 if dur <= 30 else _RELIABILITY_FPS
        render = local_video.render_storyboard_from_stills(
            storyboard,
            still_paths,
            audio_path=audio_path,
            fast_hold=True,
            mira_cinematic=False,
            crossfade_sec=min(0.2, crossfade),
            caption_lines=caption_lines,
            force_fps=fruit_fps,
            burn_captions=False,
        )
        motion_mode = "mira_fruit_mouth_hold"
    elif use_reliability:
        # Fast path: hold stills @ 12fps — guaranteed encode under ~10s for 15s clips
        sharpened = still_paths
        render = local_video.render_storyboard_from_stills(
            storyboard,
            sharpened,
            audio_path=audio_path,
            fast_hold=True,
            mira_cinematic=False,
            crossfade_sec=min(crossfade, 0.35),
            caption_lines=caption_lines,
            force_fps=_RELIABILITY_FPS,
            burn_captions=False,
        )
        motion_mode = "mira_fast_hold_reliability" if reliability else "mira_fast_hold_long"
    else:
        sharpened = _upscale_unsharp_stills(still_paths, portrait=portrait)
        render = local_video.render_storyboard_from_stills(
            storyboard,
            sharpened,
            audio_path=audio_path,
            fast_hold=False,
            mira_cinematic=True,
            crossfade_sec=crossfade,
            caption_lines=caption_lines,
            burn_captions=False,
        )
        motion_mode = "mira_cinematic"

    if isinstance(render, dict):
        render["mira_engine"] = True
        render["provider"] = ENGINE_ID
        render["engine"] = ENGINE_NAME
        render["motion_mode"] = motion_mode
        render["generative_motion"] = False
        render["veo_motion"] = False
        render["reliability_path"] = bool(reliability) and not fruit_talking
        render["local_talking_fruits"] = bool(fruit_talking)
        return render
    return {
        "ok": False,
        "status": "error",
        "message": "Mira assemble returned no result.",
    }


def _default_narration(topic: str, duration_sec: int, storyboard: dict[str, Any] | None = None) -> tuple[Optional[str], str, list[str]]:
    """Stage 5 — edge-tts free VO (always attempted for Mira agent videos).

    Prefer real VO; on TTS failure return (None, note, captions) so silent MP4
    can still ship — never block video on audio alone.
    """
    try:
        from veridiq.postings.creative import (
            build_caption_lines,
            build_character_dialogue_script,
            build_narration_script,
            generate_video_narration_audio,
            strip_scene_index_speakables,
        )

        board = storyboard or {}
        vo_hint = min(45, max(12, int(duration_sec or 15)))
        if int(duration_sec or 0) >= 60:
            vo_hint = 40
        script = str(
            board.get("narration_script")
            or board.get("script")
            or ""
        ).strip()
        if not script or re.search(r"\bscene\s*(?:one|two|three|\d+)\b", script, re.I):
            try:
                from veridiq.postings.local_stills import is_fruit_topic, wants_speaking

                if is_fruit_topic(topic) or wants_speaking(topic):
                    script = build_character_dialogue_script(topic, duration_hint_sec=vo_hint)
                else:
                    script = build_narration_script(topic, duration_hint_sec=vo_hint)
            except Exception:
                script = build_character_dialogue_script(topic, duration_hint_sec=vo_hint)
        script = strip_scene_index_speakables(script)[:550]
        # Captions collected for optional burn — Mira leaves burn OFF by default
        captions = build_caption_lines(script)
        narr = generate_video_narration_audio(script=script, duration_hint_sec=vo_hint)
        if narr.get("ok") and narr.get("absolute_path"):
            return (
                str(narr["absolute_path"]),
                f"{narr.get('message') or 'edge-tts VO'} (free neural narration, ~{vo_hint}s bed).",
                captions,
            )
        # Soft tone fallback so mux still has a track when possible
        tone = _write_fallback_tone(min(45, int(duration_sec or 15)))
        if tone:
            return (
                tone,
                f"VO FAILED ({narr.get('message') or 'edge-tts unavailable'}) — "
                "muxed fallback tone; fix edge-tts for real dialogue.",
                captions,
            )
        return None, f"VO FAILED: {narr.get('message') or 'edge-tts unavailable'} — silent video.", captions
    except Exception as exc:
        tone = _write_fallback_tone(min(45, int(duration_sec or 15)))
        if tone:
            return tone, f"VO FAILED: {str(exc)[:80]} — muxed fallback tone.", []
        return None, f"VO FAILED: {str(exc)[:80]} — silent video.", []


def _write_fallback_tone(duration_sec: int) -> Optional[str]:
    """Minimal 48kHz WAV tone so create_video never ships with zero audio track."""
    try:
        import math
        import struct
        import wave

        from veridiq.postings.creative import AUD_DIR

        AUD_DIR.mkdir(parents=True, exist_ok=True)
        path = AUD_DIR / f"mira_fallback_{uuid.uuid4().hex[:10]}.wav"
        sr = 48000
        dur = max(2.0, min(60.0, float(duration_sec or 15)))
        n = int(sr * dur)
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            for i in range(n):
                # Soft 440Hz beep pulses every ~2s so silence is obvious vs real VO
                t = i / sr
                env = 0.25 if (t % 2.0) < 0.15 else 0.0
                sample = int(env * 16000 * math.sin(2 * math.pi * 440 * t))
                wf.writeframes(struct.pack("<h", sample))
        if path.is_file() and path.stat().st_size > 400:
            return str(path)
    except Exception:
        return None
    return None


def generate_video(
    topic: str,
    duration_sec: int = 15,
    aspect: str = "16:9",
    *,
    prompts: list[str] | None = None,
    style: str = "cinematic",
    storyboard: dict[str, Any] | None = None,
    audio_path: Optional[str] = None,
    force_narration: bool = True,
    n_stills: int | None = None,
    attachments: list[Any] | None = None,
) -> dict[str, Any]:
    """Run the full Mira Cinematic pipeline.

    Free path always returns an MP4 when local stills can be written:
    AI phase ≤35s → local Pillow stills if 0–1 AI frames → fast 12fps encode.
    User ``attachments`` (upload paths/urls) are preferred as video stills.
    """
    from concurrent.futures import ThreadPoolExecutor

    from veridiq.integrations.local_video import clamp_duration_sec, format_duration_label
    from veridiq.postings.creative import (
        build_caption_lines,
        build_character_dialogue_script,
        build_narration_script,
        is_brand_topic,
        strip_scene_index_speakables,
    )
    from veridiq.postings.local_stills import ensure_still_set
    from veridiq.postings.uploads import resolve_attachment_paths

    t0 = time.monotonic()
    dur = clamp_duration_sec(duration_sec)
    budget = _wall_budget_sec(dur)
    deadline = t0 + budget
    ai_deadline = _ai_deadline(t0, deadline)
    asp = aspect if aspect in ("16:9", "9:16") else "16:9"
    still_n = min(_MAX_STILLS, int(n_stills or _still_count_for_duration(dur)))
    min_req = max(1, min(still_n, _MAX_STILLS))
    brand_only = is_brand_topic(topic)
    upload_stills = resolve_attachment_paths(attachments)

    # Fruit / speaking detection — local drawn talking fruits preferred.
    # Also honor storyboard flags + prompt text (studio may rewrite primary).
    board = dict(storyboard or {})
    try:
        from veridiq.postings.local_stills import is_fruit_topic, wants_speaking

        fruit_topic = (
            is_fruit_topic(topic)
            or bool(board.get("is_fruit"))
            or bool(board.get("local_talking_fruits"))
            or any(is_fruit_topic(str(p)) for p in (prompts or [])[:4])
        )
        speaking_topic = (
            wants_speaking(topic)
            or bool(board.get("talking_characters"))
            or bool(board.get("is_fruit"))
        )
    except Exception:
        fruit_topic = bool(
            re.search(r"\bfruits?\b|\bfroots?\b|\bapple|\bbanana|\borange", topic or "", re.I)
        ) or bool(board.get("is_fruit"))
        speaking_topic = bool(
            re.search(r"\b(talk|speak|describ|introduc|voice)\w*", topic or "", re.I)
        ) or bool(board.get("talking_characters"))
    # Any fruit topic uses local talking fruits (mouth pairs when speak/describe)
    if fruit_topic and not speaking_topic:
        speaking_topic = bool(
            re.search(r"\b(describ|introduc|themselves|identity)\w*", topic or "", re.I)
        )
    fruit_local_primary = bool(fruit_topic)  # all fruit → local_talking_fruits path

    if not board.get("narration_script") or re.search(
        r"\bscene\s*(?:one|two|three|\d+)\b",
        str(board.get("narration_script") or ""),
        re.I,
    ):
        vo_hint = 40 if dur >= 60 else min(45, dur)
        try:
            if fruit_topic or speaking_topic:
                board["narration_script"] = build_character_dialogue_script(
                    topic, duration_hint_sec=vo_hint
                )[:550]
            else:
                board["narration_script"] = build_narration_script(
                    topic, duration_hint_sec=vo_hint
                )[:550]
        except Exception:
            board["narration_script"] = build_character_dialogue_script(
                topic, duration_hint_sec=vo_hint
            )[:550]
    board["narration_script"] = strip_scene_index_speakables(
        str(board.get("narration_script") or "")
    )[:550]

    if brand_only and not upload_stills:
        # Brand path: no AI prompts — 100% local branded stills (no random Pollinations B-roll)
        compiled = []
    elif prompts:
        compiled = _ensure_cinematic(list(prompts)[:still_n], topic)
        while len(compiled) < still_n:
            compiled.extend(
                compile_prompts(
                    topic, duration_sec=dur, aspect=asp, style=style, n_stills=1
                )
            )
            compiled = compiled[:still_n]
    else:
        compiled = compile_prompts(
            topic,
            duration_sec=dur,
            aspect=asp,
            style=style,
            n_stills=still_n,
            dialogue=str(board.get("narration_script") or "")[:200] or None,
        )

    if not board.get("storyboard_id"):
        board["storyboard_id"] = f"mira_{uuid.uuid4().hex[:10]}"
    board["duration_sec"] = dur
    board["aspect"] = asp
    board["aspect_ratio"] = asp
    # Never store raw user command as board title (leaks into title-card slides)
    try:
        from veridiq.postings.local_stills import _clean_topic_title

        safe_title = _clean_topic_title(str(board.get("title") or topic or ""))
    except Exception:
        safe_title = "VERIDIQ" if brand_only else ""
    # Creative topics: short generic label only — never the cleaned prompt sentence
    if not brand_only:
        safe_title = "Mira"
    existing = str(board.get("title") or "").strip()
    if (
        not existing
        or len(existing) > 40
        or len(existing.split()) >= 4
        or re.search(
            r"\b(create|make|generate|describ\w*|froot|fruit|identity)\b",
            existing,
            re.I,
        )
        or existing.lower().startswith("mira ·")
    ):
        board["title"] = safe_title or ("VERIDIQ" if brand_only else "Mira")
    board["engine"] = ENGINE_NAME
    if brand_only and not upload_stills:
        board["brand_local_only"] = True
    if upload_stills:
        board["user_uploads"] = len(upload_stills)

    still_w, still_h = (_STILL_H, _STILL_W) if asp == "9:16" else (_STILL_W, _STILL_H)
    prefix = f"mira_{(board.get('storyboard_id') or 'x')[:8]}"

    audio_note = ""
    captions = build_caption_lines(str(board.get("narration_script") or ""))
    vo_path = audio_path

    # --- User uploads as stills: skip Pollinations; pad with local if needed ---
    if upload_stills:
        _report(f"Using {len(upload_stills)} uploaded image(s) as scenes…", 18)
        stills = list(upload_stills[:still_n])
        kf_meta = {
            "notes": [f"user uploads as stills ({len(stills)})"],
            "count": len(stills),
            "upload_count": len(upload_stills),
            "pollinations_calls": 0,
        }
        if force_narration and not vo_path:
            # Prefer a fast fallback tone so upload→video stays snappy; optionally
            # try a short edge-tts wait without blocking pool shutdown.
            tone = _write_fallback_tone(40 if dur >= 60 else min(45, dur))
            vo_path = tone
            audio_note = "Muxed fallback tone (upload stills path)." if tone else "Silent upload video."
            vo_pool = ThreadPoolExecutor(max_workers=1)
            try:
                vo_fut = vo_pool.submit(_default_narration, topic, dur, board)
                try:
                    got_path, got_note, got_caps = vo_fut.result(timeout=min(6.0, _VO_TIMEOUT_SEC))
                    if got_path:
                        vo_path = got_path
                        audio_note = got_note or "Narration ready."
                    if got_caps:
                        captions = got_caps
                except Exception as exc:
                    audio_note = f"{audio_note} TTS skip: {str(exc)[:60]}"
            finally:
                vo_pool.shutdown(wait=False)
        if not captions:
            captions = build_caption_lines(str(board.get("narration_script") or topic))
        if len(stills) < still_n:
            stills, local_meta = ensure_still_set(
                stills,
                topic,
                n=still_n,
                width=still_w,
                height=still_h,
                prefix=prefix,
                force_local=False,
                hero_opener=False,
                duration_sec=float(dur),
                speaking=speaking_topic,
            )
        else:
            local_meta = {
                "source": "upload",
                "upload_count": len(stills),
                "local_count": 0,
                "ai_count": 0,
                "hero_opener": False,
                "opener": "user_upload",
            }
        kf_meta["local_stills"] = local_meta
        ai_count = 0
        brand_only = False
    else:
        if brand_only:
            _report("VERIDIQ branded scenes only…", 18)
        elif fruit_topic:
            _report("Drawing local_talking_fruits (Apple/Banana/Orange)…", 18)
        else:
            _report("Trying free AI scenes…", 18)

        # Brand: skip Pollinations (local titled cards only).
        # Fruit: ALWAYS skip Pollinations — local_talking_fruits only (no goo/grids).
        # Other creative: try AI stills with strict prompts.
        skip_ai = bool(brand_only or fruit_topic)
        ai_prompts = [] if skip_ai else list(compiled[:still_n])
        ai_min = 0 if skip_ai else min_req

        stills = []
        kf_meta = {}
        with ThreadPoolExecutor(max_workers=2) as pool:
            vo_fut = None
            if force_narration and not vo_path:
                vo_fut = pool.submit(_default_narration, topic, dur, board)
            still_fut = None
            if ai_prompts:
                still_fut = pool.submit(
                    generate_keyframes,
                    ai_prompts,
                    style=style,
                    prefix=prefix,
                    width=still_w,
                    height=still_h,
                    min_required=max(1, ai_min) if ai_min else 1,
                    duration_sec=dur,
                    deadline=ai_deadline,
                )
            try:
                if still_fut is not None:
                    remaining = max(3.0, ai_deadline - time.monotonic())
                    stills, kf_meta = still_fut.result(timeout=remaining + 2.0)
                elif brand_only:
                    kf_meta = {
                        "notes": ["VERIDIQ branded scenes only — skipped Pollinations"],
                        "count": 0,
                        "brand_local_only": True,
                        "pollinations_calls": 0,
                    }
                    stills = []
                elif fruit_topic:
                    kf_meta = {
                        "notes": [
                            "local_talking_fruits — skipped Pollinations; "
                            "Apple/Banana/Orange mouth open/close pairs; no abstract pad"
                        ],
                        "count": 0,
                        "fruit_local_primary": True,
                        "local_talking_fruits": True,
                        "pollinations_calls": 0,
                    }
                    stills = []
                else:
                    kf_meta = {"notes": ["no AI prompts compiled"], "count": 0}
                    stills = []
            except Exception as exc:
                kf_meta = {"notes": [f"still gen aborted: {str(exc)[:100]}"], "count": 0}
                stills = []
            if vo_fut is not None:
                try:
                    vo_remaining = max(2.0, min(_VO_TIMEOUT_SEC + 5.0, deadline - time.monotonic()))
                    vo_path, audio_note, captions = vo_fut.result(timeout=vo_remaining)
                except Exception as exc:
                    audio_note = f"Narration deferred/timeout: {str(exc)[:80]}"
                    tone = _write_fallback_tone(40 if dur >= 60 else min(45, dur))
                    vo_path = tone
                    if tone:
                        audio_note += " — muxed fallback tone."
            elif not captions:
                captions = build_caption_lines(str(board.get("narration_script") or topic))

        ai_count = len(stills)
        # Brand: force 100% local titled cards.
        # Fruit: local_talking_fruits only — never abstract pad, never AI mix.
        # Creative: prefer AI stills; pad with abstract locals (never topic-title slides).
        _report(
            "Assembling VERIDIQ branded scenes…"
            if brand_only
            else (
                "Assembling local_talking_fruits stills…"
                if fruit_topic
                else "Assembling AI scenes (topic illustration pad if needed)…"
            ),
            48,
        )
        stills, local_meta = ensure_still_set(
            stills,
            topic,
            n=still_n,
            width=still_w,
            height=still_h,
            prefix=prefix,
            force_local=brand_only or fruit_topic or (ai_count == 0),
            hero_opener=brand_only,  # creative: no topic-title hero
            duration_sec=float(dur),
            speaking=True if fruit_topic else speaking_topic,
        )
        if brand_only:
            local_meta["brand_local_only"] = True
            local_meta["pollinations_calls"] = 0
            local_meta["source"] = "local"
        if fruit_topic:
            local_meta["fruit_local_primary"] = True
            local_meta["pollinations_calls"] = 0
            local_meta["creative_abstract"] = False
            local_meta["local_talking_fruits"] = True
            local_meta["source"] = "local_talking_fruits"
            local_meta["ai_count"] = 0
        (kf_meta or {}).setdefault("notes", []).append(
            f"stills: source={local_meta.get('source')} opener={local_meta.get('opener')} "
            f"ai={0 if fruit_topic else ai_count} local={local_meta.get('local_count')}"
            + (
                " — VERIDIQ branded scenes only"
                if brand_only
                else (
                    " — local_talking_fruits (no Pollinations, no abstract pad)"
                    if fruit_topic
                    else " — creative (no title cards)"
                )
            )
        )
        kf_meta["local_stills"] = local_meta
        kf_meta["brand_local_only"] = brand_only
        kf_meta["fruit_local_primary"] = fruit_topic
        kf_meta["local_talking_fruits"] = bool(fruit_topic)
        if fruit_topic:
            kf_meta["pollinations_calls"] = 0
            ai_count = 0

    wall_hit = bool((kf_meta or {}).get("wall_aborted")) or (
        (not brand_only) and (not upload_stills) and (not fruit_topic) and time.monotonic() >= ai_deadline
    )

    n_stills_got = len(stills)
    source_key = str(local_meta.get("source") or "ai")
    # Fruit: Ken Burns @ 12–15fps (not abstract fast-hold). Brand/abstract local: reliability.
    # Fix prior bug: `… or True` made EVERY video use fast_hold.
    if fruit_topic:
        reliability = False
    else:
        reliability = source_key in ("local", "mixed", "local_fruit", "local_fruit_talking")

    if n_stills_got < 1:
        # Should be unreachable if Pillow works — surface honest error
        return {
            "ok": False,
            "status": "error",
            "mira_engine": True,
            "free_unlimited": True,
            "paid_veo": False,
            "engine": ENGINE_NAME,
            "stills_count": 0,
            "max_stills": still_n,
            "min_stills": 1,
            "duration_sec": dur,
            "prompts": compiled,
            "storyboard": board,
            "wall_sec": round(time.monotonic() - t0, 1),
            "wall_budget_sec": budget,
            "message": (
                "Mira: could not write local stills (Pillow). "
                + VIDEO_NOTE_SHORT
            ),
            "keyframe_meta": kf_meta,
        }

    # Prefer VO; allow silent MP4 if TTS totally unavailable
    if force_narration and not vo_path:
        audio_note = (audio_note or "VO unavailable") + " — shipping silent video."

    _report("Assembling video…", 70)
    render = assemble_cinematic(
        board,
        stills,
        audio_path=vo_path,
        caption_lines=captions,
        reliability=reliability,
        fruit_talking=bool(fruit_topic),
    )
    ok = bool(render.get("ok") or render.get("status") == "ok")
    has_audio = bool(render.get("has_audio"))
    sep_audio = render.get("audio_url")
    if vo_path and not has_audio and not sep_audio:
        try:
            from pathlib import Path as _P

            name = _P(vo_path).name
            sep_audio = f"/api/v1/veridiq/marketing/audio/file/{name}"
            render["audio_url"] = sep_audio
            render["audio_separate"] = True
        except Exception:
            pass
    actual = render.get("duration_sec") or dur
    label = format_duration_label(actual)
    out_w = _OUT_H if asp == "9:16" else _OUT_W
    out_h = _OUT_W if asp == "9:16" else _OUT_H
    out_fps = _RELIABILITY_FPS if reliability else (15 if dur >= 60 else _OUT_FPS)
    model_note = (kf_meta or {}).get("primary_model") or "turbo"
    source_note = str(local_meta.get("source") or "ai")
    if fruit_topic:
        source_note = "local_talking_fruits"
        out_fps = int(render.get("fps") or 15)

    if ok and vo_path and not has_audio:
        audio_note = (
            f"AUDIO NOT MUXED INTO MP4 — play video + audio separately "
            f"({sep_audio or vo_path}). {audio_note}"
        )

    best_effort = ""
    if upload_stills:
        best_effort = f"User uploads as scenes ({len(upload_stills)} file(s)). "
    elif brand_only:
        best_effort = "VERIDIQ branded scenes only (0 Pollinations calls). "
    elif fruit_topic:
        best_effort = "local_talking_fruits (0 Pollinations calls, no abstract pad). "
    elif reliability or wall_hit or ai_count < still_n:
        best_effort = (
            f"Reliability path ({source_note}: {ai_count} AI + "
            f"{int(local_meta.get('local_count') or 0)} local, AI≤{_AI_PHASE_BUDGET_SEC:.0f}s). "
        )

    msg_bits = [
        f'{label} video of "{(topic or "")[:60]}" ready' if ok else "Video assemble incomplete",
        (
            f"Using {len(upload_stills)} uploaded image(s) as stills"
            if upload_stills
            else (
                "VERIDIQ branded scenes only"
                if brand_only
                else (
                    "local_talking_fruits — Apple/Banana/Orange mouth open/close stills"
                    if fruit_topic
                    else RENDER_MESSAGE
                )
            )
        ),
        f"{best_effort}{n_stills_got} {source_note} keyframes @ {still_w}x{still_h} -> {out_w}x{out_h} @{out_fps}fps",
        f"motion: {render.get('motion_mode') or 'mira'}",
        str(render.get("message") or ""),
        audio_note,
        (
            "Honest: your uploads + free VO — not generative AI B-roll."
            if upload_stills
            else (
                "Honest: local branded stills + free VO — not generative AI B-roll."
                if brand_only
                else (
                    "Honest: local_talking_fruits drawn stills + free VO — mouth open/close, not Veo lip-sync."
                    if fruit_topic
                    else "Honest: multi-scene photoreal pipeline — not trained Veo-scale generative video."
                )
            )
        ),
    ]

    return {
        "ok": ok,
        "status": "ok" if ok else "error",
        "mira_engine": True,
        "free_unlimited": True,
        "paid_veo": False,
        "engine": ENGINE_NAME,
        "engine_id": ENGINE_ID,
        "provider": ENGINE_ID if not fruit_topic else "local_talking_fruits",
        "storyboard": board,
        "render": render,
        "stills_count": n_stills_got,
        "max_stills": still_n,
        "min_stills": 1,
        "duration_sec": actual,
        "duration_label": label,
        "style": style,
        "aspect": asp,
        "prompts": [] if fruit_topic else compiled,
        "keyframe_meta": kf_meta,
        "local_stills": local_meta,
        "local_talking_fruits": bool(fruit_topic),
        "pollinations_calls": 0 if fruit_topic or brand_only else None,
        "attachments_used": upload_stills[:8] if upload_stills else [],
        "audio_url": sep_audio,
        "has_audio": has_audio,
        "wall_sec": round(time.monotonic() - t0, 1),
        "wall_budget_sec": budget,
        "ai_phase_sec": round(min(time.monotonic() - t0, _AI_PHASE_BUDGET_SEC), 1),
        "quality": {
            "width": render.get("width") or out_w,
            "height": render.get("height") or out_h,
            "fps": render.get("fps") or out_fps,
            "aspect": asp,
            "label": f"1080p · {render.get('fps') or out_fps}fps · Mira · {asp}",
            "veo_motion": False,
            "generative_motion": False,
            "lip_sync": False,
            "free_unlimited": True,
            "paid_veo": False,
            "mira_engine": True,
            "still_gen": f"{still_w}x{still_h}",
            "upscale": f"{out_w}x{out_h}",
            "has_audio": has_audio,
            "still_source": source_note,
            "reliability_path": reliability,
            "local_talking_fruits": bool(fruit_topic),
        },
        "message": " — ".join(b for b in msg_bits if b),
        "identity": engine_identity(),
    }
