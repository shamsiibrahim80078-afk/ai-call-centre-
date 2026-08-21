"""Unified creative media — Gemini-first images, rich free fallbacks.

One-command styles: photo, cartoon, anime, cinematic, song/lyrics+audio.
Never fabricates media files; always writes real bytes or returns honest errors.
Subject fidelity: preserve gender/identity; never rewrite boy→person or add conflicting cues.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

import requests

_ROOT = Path(__file__).resolve().parent.parent.parent
IMG_DIR = _ROOT / "marketing_out" / "images"
AUD_DIR = _ROOT / "marketing_out" / "audio"

# Exact Secret Quality Injection anchor — append every video prompt.
QUALITY_ANCHOR_SENTENCE = (
    "Photorealistic 4K render, 60fps smooth fluid motion, cinematic studio lighting, "
    "volumetric light rays, shallow depth of field with realistic bokeh background, "
    "sharp focus, ray-traced reflections, hyper-detailed textures, professional color grading, "
    "zero motion blur distortion."
)

# CFG / inference directives (API query params when supported; always baked into prompt text)
CFG_DEFAULT = 7.5
STEPS_DEFAULT = 40
CFG_STEPS_PROMPT = "CFG 7.5, high adherence to prompt, high inference detail 40 steps"

VIDEO_SYSTEM_RULE = (
    "Whenever you are asked to generate a video or create a prompt for video generation, "
    "never send raw text. Always enforce cinematic rules: specify 4K resolution, 60fps frame rate, "
    "volumetric lighting, shallow depth of field, and photorealistic texture anchors. "
    "Always structure the output scene with clear camera motion (panning/dolly/close-up) "
    "and millisecond-aligned audio directives. "
    "Subject fidelity: never replace fruits/animals/objects with humans. Always mux edge-tts VO."
)

# Gemini-quality cinematic recipe — applied to all free video stills + default images.
STYLE_ANCHORS = (
    "photorealistic, photorealistic textures, volumetric lighting, soft studio illumination, "
    "rim light, subsurface scattering, shallow depth of field, bokeh background, "
    "sharp foreground focus, smooth panning, 35mm, cinematic dolly, hyper-detailed textures, "
    "ray-traced reflections, cinematic composition, hyper-detailed 4K render, "
    "60fps fluid motion, crystal clear audio, studio-grade acoustics, faint ambient hum, "
    "natural room reverb, studio warmth, Rendering Engine: Hyper-realistic physics engine simulation"
)

NEGATIVE_PROMPT = (
    "dark shadows, blurry faces, low-resolution, pixelated, distorted limbs, "
    "oversaturated noise, mud textures, flicker, bad anatomy, "
    "global mush blur, distortion, low quality, jpeg artifacts, "
    "watermark, text gibberish, motion blur mush, deformed limbs, extra fingers, "
    "heavy grain mush, soft muddy render, pitch-black underexposed, "
    "no text, no captions, no words, no letters on image, "
    "text overlay, captions, words on image, letters on screen, typography, "
    "written prompt, command text, subtitle burn-in, scene 1, scene 2, "
    "scene label, UI chrome text dump, muddy creature, "
    "blurry monster, horror creature, unrelated objects, random stock photo drift, "
    "collage, grid, tile, sheet of faces, contact sheet, multiple panels, meme, "
    "title card, poster with text, distorted faces, blurry, "
    "4x4 grid, tiled collage, sprite sheet, face montage"
)

# Extra negatives for fruit / character stills — kill Pollinations junk grids
COLLAGE_NEGATIVE = (
    "collage, grid, tile, sheet of faces, contact sheet, multiple panels, meme, "
    "watermark, text, letters, words, title card, poster with text, "
    "distorted faces, blurry, low quality, 4x4 grid, tiled collage, sprite sheet, "
    "many faces, face montage, repeating tiles, comic panel layout"
)

FRUIT_SUBJECT_ANCHOR = (
    "single cute cartoon fruit character with a clear face, Pixar style, "
    "bright centered, clear fruit shape, one subject only, expressive mouth, "
    "vibrant colors, bright well-lit kitchen studio — NOT translucent blob, "
    "NOT abstract, NOT a grid"
)

BRIGHT_LIGHTING = (
    "bright studio daylight illumination, soft even key light, vibrant natural tones, "
    "soft shadows, cheerful colorful set — NOT pitch-black, NOT noir god-ray only"
)

VOLUMETRIC_LIGHTING = (
    "Volumetric top-down shaft lighting, cinematic studio illumination, soft shadows, "
    "vibrant natural tones"
)

CAMERA_PHYSICS_ANCHOR = (
    "Hyper-detailed 4K render, sharp focus, 35mm lens, shallow depth of field, "
    "crisp textures, zero noise, zero motion blur distortion"
)

NONHUMAN_NEGATIVE = (
    "dark shadows, blurry faces, low-resolution, pixelated, distorted limbs, "
    "oversaturated noise, mud textures, flicker, bad anatomy, humans, people, woman, man, "
    "no text, no captions, no words, no letters on image, "
    "text overlay, captions, words on image, letters on screen, typography, watermark, "
    f"{COLLAGE_NEGATIVE}"
)

# Standing 4-block Quality Injection formula (Mira / posting_studio)
CINEMATIC_PROMPT_FORMULA = (
    "Quality Injection: [Subject & Precise Action] + [Lighting & Ambiance] + "
    "[Camera Physics] + [Render Quality Anchors]\n"
    f"Always append: {QUALITY_ANCHOR_SENTENCE}\n"
    f"Also include: {CFG_STEPS_PROMPT}"
)

# Full 3-pillars standing instructions (Urdu/English mix intent from Gemini advice — FREE path)
THREE_PILLARS_STANDING = f"""VIDEO QUALITY — 3 PILLARS (standing instructions — every generation, FREE only):

1) Quality Control Parameters (always apply)
- Rendering Engine: Hyper-realistic physics engine simulation (prompt directive)
- Resolution: 1080p minimum / 4K native upscale (default free 1080p; 4K only via VERIDIQ_VIDEO_4K=1)
- Aspect: 16:9 landscape default; support 9:16 if user asks shorts/reels
- FPS: 30 default (VERIDIQ_VIDEO_FPS=60 optional)
- Guidance Scale (CFG): 7.0–8.0 — pass guidance/cfg=7.5 to image APIs when supported; else bake "{CFG_STEPS_PROMPT}"
- Inference Steps: 35–50 — pass steps=40 when supported; else prompt "high inference detail 40 steps"
- Subject fidelity: fruits/animals/objects talking ≠ humans — never swap characters

2) Audio & Voice (free) — ALWAYS for create_video
- Neural audio: 24-bit/48kHz via edge-tts + ffmpeg mux on every create_video
- If mux fails: return audio_url and fail loudly (never silent success without audio)
- Lipsync: align narration duration to video; true phoneme lip-sync N/A on stills path
- Acoustics: natural room reverb, studio warmth (VO/prompt); light ffmpeg aecho when available

3) Secret Quality Injection Prompt
Every video prompt must convert user idea to:
[Subject & Precise Action] + [Lighting & Ambiance] + [Camera Physics] + [Render Quality Anchors]
Append EXACT anchor every time: {QUALITY_ANCHOR_SENTENCE}
Lighting: prefer bright studio/daylight for colorful scenes; {VOLUMETRIC_LIGHTING}
Camera: {CAMERA_PHYSICS_ANCHOR}
Negatives always include: pixelated, dark shadows, blurry faces

System rule: {VIDEO_SYSTEM_RULE}

Default video path is FREE UNLIMITED via Mira Cinematic Engine
(Flux stills + local cinematic motion + edge-tts). Not Google Veo.
Never require paid Veo; never push the user to buy Veo. mira_engine=true, paid_veo=false, free_unlimited=true.
"""

# Default blocks for the 4-block Quality Injection formula
_DEFAULT_LIGHTING = (
    f"{VOLUMETRIC_LIGHTING}, soft studio illumination, rim light, "
    "subsurface scattering, natural room reverb ambiance cues, studio warmth"
)
_DEFAULT_CAMERA = (
    f"{CAMERA_PHYSICS_ANCHOR}, Photorealistic medium shot, eye-level, "
    "smooth cinematic panning, cinematic dolly, optional close-up beat"
)
_DEFAULT_AUDIO_DIRECTIVE = (
    "crystal clear audio, studio-grade acoustics, natural room reverb, studio warmth, "
    "faint ambient hum, millisecond-aligned narration duration to video; "
    "true phoneme lip-sync N/A on stills path"
)


def build_cinematic_prompt(
    subject: str,
    motion: str = "",
    environment: str = "",
    camera_lighting: str = "",
    audio_style: str = "",
    *,
    dialogue: str | None = None,
    lighting: str = "",
    camera: str = "",
    bright: bool | None = None,
    nonhuman: bool = False,
    fruit: bool = False,
) -> str:
    """Secret Quality Injection — 4-block formula for every free video still prompt.

    Structure:
      [Subject & Precise Action] + [Lighting & Ambiance]
      + [Camera Physics] + [Render Quality Anchors]
    Always appends QUALITY_ANCHOR_SENTENCE + CFG/steps.
    """
    subj = (subject or "").strip().rstrip(".")
    mot = (motion or "").strip().rstrip(".")
    low_subj = f"{subj} {mot}".lower()
    is_fruit = fruit or bool(re.search(r"\bfruits?\b|\bapple|\bbanana|\borange", low_subj))
    is_nonhuman = nonhuman or is_fruit or bool(
        re.search(r"\b(animal|dog|cat|robot|toy|creature)s?\b", low_subj)
    )
    prefer_bright = bright if bright is not None else (
        is_fruit
        or is_nonhuman
        or bool(re.search(r"\b(bright|colorful|cheerful|cartoon|pixar|daylight)\b", low_subj))
    )

    if is_fruit and "anthropomorphic" not in low_subj:
        subj = f"{FRUIT_SUBJECT_ANCHOR}: {subj}" if subj else FRUIT_SUBJECT_ANCHOR
    elif is_nonhuman and "anthropomorphic" not in low_subj and "human" not in low_subj:
        subj = f"cute anthropomorphic characters with expressive faces: {subj}" if subj else subj

    block_subject = f"{subj}. {mot}".strip(". ") if mot else subj
    if not block_subject:
        block_subject = "Photorealistic cinematic subject performing a precise action"

    # Lighting & Ambiance — bright bias for colorful/non-noir topics
    env = (environment or "").strip().rstrip(".")
    lit = (lighting or "").strip().rstrip(".")
    if not lit:
        lit = BRIGHT_LIGHTING if prefer_bright else _DEFAULT_LIGHTING
    if lit:
        block_lighting = f"{lit}. {env}".strip(". ") if env else lit
    elif env:
        block_lighting = f"{_DEFAULT_LIGHTING}. Environment: {env}"
    else:
        block_lighting = _DEFAULT_LIGHTING

    # Camera Physics — prefer explicit camera=; else camera_lighting= (back-compat)
    cam = (camera or camera_lighting or "").strip().rstrip(".")
    if cam and "35mm" not in cam.lower():
        cam = f"{cam}. {CAMERA_PHYSICS_ANCHOR}"
    block_camera = cam or _DEFAULT_CAMERA

    # Render Quality Anchors — exact sentence + CFG/steps + audio directives
    audio = (audio_style or "").strip().rstrip(".") or _DEFAULT_AUDIO_DIRECTIVE
    if dialogue and str(dialogue).strip():
        line = str(dialogue).strip().strip('"')
        audio = f'{audio}. The character says with a warm voice: "{line}"'
    block_render = (
        f"{QUALITY_ANCHOR_SENTENCE} {CFG_STEPS_PROMPT}. "
        f"Rendering Engine: Hyper-realistic physics engine simulation. {audio}"
    )

    parts = [block_subject, block_lighting, block_camera, block_render]
    out = ". ".join(p for p in parts if p)
    # Always attach negatives (pixelated etc.); extra human ban for fruits/non-humans
    neg = NONHUMAN_NEGATIVE if (is_fruit or is_nonhuman) else NEGATIVE_PROMPT
    if is_fruit:
        out = (
            f"{out}. ONE single fruit character centered, full scene, "
            "NOT a collage, NOT a grid of faces, NOT multiple panels."
        )
        neg = f"{neg}, {COLLAGE_NEGATIVE}"
    if "negative prompt" not in out.lower():
        out = f"{out}. Negative prompt: {neg}."
    while ".." in out:
        out = out.replace("..", ".")
    return out[:2000]


# Back-compat alias (older call sites / tests)
build_veo_style_prompt = build_cinematic_prompt


def apply_style_anchors(prompt: str, *, include_negative: bool = True) -> str:
    """Append Gemini-style cinematic anchors (+ optional negatives) to a scene prompt."""
    base = (prompt or "").strip().rstrip(".")
    # Prefer full 4-block Quality Injection formula when caller passed a plain subject line
    out = build_cinematic_prompt(base) if base else build_cinematic_prompt("cinematic subject")
    if QUALITY_ANCHOR_SENTENCE.split(",")[0].lower() not in out.lower():
        out = f"{out}. {QUALITY_ANCHOR_SENTENCE}"
    if "volumetric lighting" not in out.lower() and "volumetric light rays" not in out.lower():
        out = f"{out}. {STYLE_ANCHORS}"
    if "cfg 7.5" not in out.lower():
        out = f"{out}. {CFG_STEPS_PROMPT}"
    if include_negative:
        out = f"{out}. Negative prompt: {NEGATIVE_PROMPT}."
    return out[:2000]


_FRUIT_CAST = (
    ("Apple", "I'm Apple — shiny, crisp, and ready to chat!"),
    ("Banana", "I'm Banana — bright yellow, sweet, and a little silly!"),
    ("Orange", "I'm Orange — juicy, cheerful, and full of sunshine!"),
)


def wants_character_dialogue(text: str) -> bool:
    q = (text or "").lower()
    return bool(
        re.search(
            r"\b(talking|talk|speak|speaking|dialogue|conversation|convers|"
            r"describe|describing|themselves|each other|introduc)\b",
            q,
        )
    )


_SCENE_INDEX_RE = re.compile(
    r"\b(?:this\s+is\s+)?scene\s*(?:one|two|three|four|five|six|seven|eight|nine|ten|\d+)\b"
    r"|\[?\s*scene\s*\d+\s*\]?"
    r"|\bshot\s*\d+\b",
    re.I,
)


def strip_scene_index_speakables(text: str) -> str:
    """Remove 'scene 1/one' leftovers so VO never announces shot indices."""
    out = _SCENE_INDEX_RE.sub(" ", text or "")
    out = re.sub(r"\s*[—\-–]\s*", " — ", out)
    out = re.sub(r"\s{2,}", " ", out).strip(" .,—–-")
    return out


def is_brand_topic(topic: str) -> bool:
    """True for VERIDIQ / product / agent-workspace explainers — local branded stills only.

    Keywords: veridiq, verdiq, veridig, vridiq, agent workspace, truth verification,
    our product, explain what veridiq — never inject random AI B-roll.
    """
    try:
        from veridiq.integrations.pollinations_image import expand_user_typos

        t = expand_user_typos(topic or "").lower()
    except Exception:
        t = (topic or "").lower()
    if not t.strip():
        return True  # empty → default VERIDIQ product video
    return bool(
        re.search(
            r"\bver+i?diq\b|\bverdiq\b|\bveridig\b|\bvridiq\b|\bv[e]?rid[iq]g?\b|"
            r"\bagents?\s+workspace\b|\bai\s+workforce\b|\btruth\s+verif|"
            r"\bour\s+product\b|\bexplain\s+what\s+ver|"
            r"\bwhat\s+is\s+ver|"
            r"\bproduct\s+(demo|tour|explainer|video)\b|"
            r"\bplatform\s+(tour|demo|explainer)\b",
            t,
        )
        or (
            re.search(r"\b(agent|agents|workspace)\b", t)
            and re.search(r"\b(veridiq|verdiq|veridig|vridiq|verify|truth|workforce|product)\b", t)
        )
    )


def _is_veridiq_or_workspace_topic(topic: str) -> bool:
    """Alias — brand / product / workspace topics use local stills only."""
    return is_brand_topic(topic)


def build_narration_script(topic: str, *, duration_hint_sec: int = 15) -> str:
    """Natural ~15–25s VO — never scene indices or raw prompt dumps.

    VERIDIQ / agent-workspace topics get a polished branded script.
    Generic topics get 2–3 clean sentences from the subject words.
    """
    from veridiq.integrations.pollinations_image import (
        clean_user_prompt,
        expand_user_typos,
    )

    raw = expand_user_typos(topic or "")
    if _is_veridiq_or_workspace_topic(raw) or not (raw or "").strip():
        script = (
            "Welcome to VERIDIQ — where truth meets intelligence. "
            "Our AI agents work together in a live workspace to verify claims, "
            "investigate signals, and deliver trusted reports. "
            "Truth. Verified. Empowered."
        )
    else:
        # Fruits / talking characters get intro dialogue, not "here's a look at…"
        from veridiq.integrations.pollinations_image import detect_subject_lock

        lock = detect_subject_lock(raw)
        if lock.get("is_fruit") or wants_character_dialogue(raw):
            return build_character_dialogue_script(raw, duration_hint_sec=duration_hint_sec)
        cleaned = clean_user_prompt(raw) or raw
        cleaned = re.sub(
            r"^(create|make|generate|render)\s+(a\s+)?(video|clip|reel|mp4)\s+"
            r"(for|about|of|on)\s+",
            "",
            cleaned,
            flags=re.I,
        )
        cleaned = re.sub(
            r"\b(in that|that\s+)?(tell|explain|describ\w*)\s+(what|about)\s+",
            "",
            cleaned,
            flags=re.I,
        )
        cleaned = strip_scene_index_speakables(cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,-")
        # Title-case a short subject phrase; normalize brand typos
        words: list[str] = []
        for w in cleaned.split()[:8]:
            if re.match(r"^ver+i?diq$|^verdiq$|^veridig$", w, re.I):
                words.append("VERIDIQ")
            else:
                words.append(w[:1].upper() + w[1:] if w else w)
        subject = " ".join(words)[:72] or "this idea"
        script = (
            f"Here's a clear look at {subject}. "
            f"What matters most comes through in a few sharp beats — "
            f"simple, visual, and easy to remember. "
            f"Stay with it — this is {subject}, explained."
        )
    if duration_hint_sec >= 30 and _is_veridiq_or_workspace_topic(raw):
        script += (
            " From live investigations to verified reports, "
            "VERIDIQ keeps your team aligned on signal, not noise."
        )
    return strip_scene_index_speakables(script)[:900]


def build_character_dialogue_script(topic: str, *, duration_hint_sec: int = 15) -> str:
    """Multi-character VO lines for talking fruits / objects describing themselves."""
    from veridiq.integrations.pollinations_image import detect_subject_lock, expand_user_typos

    raw = expand_user_typos(topic or "")
    lock = detect_subject_lock(raw)
    if lock.get("is_fruit") or re.search(r"\bfruits?\b", raw, re.I):
        lines = [f"{name}: {line}" for name, line in _FRUIT_CAST]
        lines.append(
            "Together: We are talking fruits — friendly, colorful, and describing ourselves!"
        )
        script = " ".join(lines)
    elif lock.get("talking_characters") or wants_character_dialogue(raw):
        # Prefer branded/generic narration over dumping the raw prompt as dialogue
        if _is_veridiq_or_workspace_topic(raw):
            script = build_narration_script(raw, duration_hint_sec=duration_hint_sec)
        else:
            from veridiq.integrations.pollinations_image import clean_user_prompt

            primary = strip_scene_index_speakables(
                (lock.get("primary_subject") or clean_user_prompt(raw) or "this cast")[:80]
            )
            script = (
                f"Hello! I'm the first character in {primary}. "
                f"Hi there — I'm next, and I love describing myself. "
                f"And I'm the third — we talk to each other and share who we are!"
            )
    else:
        script = build_narration_script(raw, duration_hint_sec=duration_hint_sec)
    # Stretch a bit for longer videos
    if duration_hint_sec >= 30 and lock.get("is_fruit"):
        script += (
            " Apple again: I like being red and round. "
            "Banana: I curve with a smile. Orange: I glow like a tiny sun."
        )
    return strip_scene_index_speakables(script)[:900]


def build_caption_lines(script: str) -> list[str]:
    """Split polished VO into short caption lines (never scene indices)."""
    text = strip_scene_index_speakables(re.sub(r"\s+", " ", (script or "").strip()))
    if not text:
        return []
    # Split on character labels / sentence ends
    chunks = re.split(r"(?<=[.!?])\s+|(?<=:)\s+", text)
    lines: list[str] = []
    for c in chunks:
        c = strip_scene_index_speakables(c.strip())
        if not c:
            continue
        # Skip junk that still looks like a shot label
        if re.match(r"^(scene|shot)\b", c, re.I):
            continue
        if len(c) > 72:
            words = c.split()
            buf: list[str] = []
            for w in words:
                buf.append(w)
                if sum(len(x) + 1 for x in buf) > 60:
                    lines.append(" ".join(buf))
                    buf = []
            if buf:
                lines.append(" ".join(buf))
        else:
            lines.append(c)
    return lines[:24]


def detect_style(text: str) -> str:
    q = (text or "").lower()
    if any(w in q for w in ("anime", "manga")):
        return "anime"
    # Talking fruits/objects → cartoon/Pixar (never photoreal humans)
    if re.search(r"\bfruits?\b", q) or (
        re.search(r"\b(talking|describe|describing)\b", q)
        and re.search(r"\b(fruit|apple|banana|orange|animal|toy|robot)\b", q)
    ):
        return "cartoon"
    if any(w in q for w in ("cartoon", "pixar", "disney", "toon", "animated kids")):
        return "cartoon"
    if any(w in q for w in ("3d", "cgi", "unreal", "octane")):
        return "cgi"
    if any(w in q for w in ("cinematic", "film", "movie", "trailer")):
        return "cinematic"
    return "photo"


def style_suffix(style: str) -> str:
    """Quality/style tags only — must NOT introduce a different subject or gender."""
    # Gemini cinematic: subject sharp, soft bg bokeh — not deep-DoF everything-in-focus
    cine = STYLE_ANCHORS
    return {
        "anime": (
            "anime style illustration, vibrant colors, clean lineart, expressive characters, "
            f"high detail cel shading, {cine}, no watermark"
        ),
        "cartoon": (
            "2D cartoon animation style, bold outlines, colorful, Pixar-inspired characters, "
            f"friendly faces, storybook lighting, sharp edges, {cine}, no watermark"
        ),
        "cgi": f"3D CGI render, octane render, subsurface scattering, detailed materials, {cine}",
        "cinematic": (
            f"cinematic still, filmic color grade, {cine}"
        ),
        "photo": (
            f"highly detailed, detailed face, 8k, realistic proportions, high fidelity, {cine}, "
            "no watermark"
        ),
    }.get(style, f"high quality, detailed, {cine}, no watermark")


def looks_like_collage_or_grid(path: str | Path) -> bool:
    """Heuristic: reject Pollinations junk that looks like a tiled face sheet / collage.

    Checks edge-density regularity across a 4×4 cell grid. High, even edge density
    in many cells usually means a contact sheet / sprite grid rather than one subject.
    """
    try:
        from PIL import Image, ImageFilter, ImageStat
    except Exception:
        return False
    p = Path(path)
    if not p.is_file():
        return False
    try:
        img = Image.open(p).convert("L")
        img = img.resize((256, 256), Image.Resampling.BILINEAR)
        edges = img.filter(ImageFilter.FIND_EDGES)
        w, h = edges.size
        cols, rows = 4, 4
        cw, ch = w // cols, h // rows
        densities: list[float] = []
        for ry in range(rows):
            for cx in range(cols):
                cell = edges.crop((cx * cw, ry * ch, (cx + 1) * cw, (ry + 1) * ch))
                dens = float(ImageStat.Stat(cell).mean[0])
                densities.append(dens)
        if not densities:
            return False
        mean_d = sum(densities) / len(densities)
        if mean_d < 18.0:
            return False
        hot = sum(1 for d in densities if d > max(28.0, mean_d * 0.75))
        var = sum((d - mean_d) ** 2 for d in densities) / len(densities)
        if hot >= 10 and var < (mean_d * mean_d * 0.35):
            return True
        if hot >= 12 and mean_d > 32.0:
            return True
        px = edges.load()
        seam_hits = 0
        for frac in (0.25, 0.5, 0.75):
            x = min(w - 1, max(0, int(w * frac)))
            col_vals = [px[x, y] for y in range(h)]
            if sum(col_vals) / h > mean_d * 1.35:
                seam_hits += 1
            y = min(h - 1, max(0, int(h * frac)))
            row_vals = [px[x2, y] for x2 in range(w)]
            if sum(row_vals) / w > mean_d * 1.35:
                seam_hits += 1
        if seam_hits >= 4 and mean_d > 24.0:
            return True
    except Exception:
        return False
    return False


def generate_best_image(
    *,
    prompt: str,
    style: Optional[str] = None,
    width: int = 1280,
    height: int = 1280,
    filename_stem: str | None = None,
    seed: int | None = None,
    timeout: float = 55.0,
    prefer_pollinations: bool = True,
    enhance: bool = True,
    gemini_timeout: float = 45.0,
    max_attempts: int | None = None,
) -> dict[str, Any]:
    """Free path: Pollinations first. Gemini image only if explicitly enabled.

    prefer_pollinations=True (default) skips Gemini — free tier must not call
    broken/paid Gemini image models. Set VERIDIQ_USE_GEMINI_IMAGE=1 and
    prefer_pollinations=False to try Gemini.

    After download, rejects collage/grid junk and retries once with a stricter prompt.
    """
    import os

    from veridiq.integrations import pollinations_image
    from veridiq.integrations.llm import google_ai

    lock = pollinations_image.detect_subject_lock(prompt)
    scene = lock["scene"]
    st = style or detect_style(prompt)

    # Continuous improvement: inject quality anchors from past ratings + legal refs
    try:
        from veridiq.postings.learning import apply_learned_quality

        prompt = apply_learned_quality(prompt, topic=scene or prompt)
        lock = pollinations_image.detect_subject_lock(prompt)
        scene = lock["scene"]
    except Exception:
        pass

    # HARD SKIP: fruit / talking-fruit topics never hit Pollinations.
    # Local render_talking_fruit_stills() is the only reliable free path.
    try:
        from veridiq.postings.local_stills import is_fruit_topic

        fruitish = bool(lock.get("is_fruit")) or is_fruit_topic(prompt) or is_fruit_topic(scene)
    except Exception:
        fruitish = bool(lock.get("is_fruit")) or bool(
            re.search(r"\bfruits?\b|\bfroots?\b|\bapple|\bbanana|\borange", prompt or "", re.I)
        )
    if fruitish:
        return {
            "status": "fruit_local_only",
            "ok": False,
            "retry": False,
            "pollinations_calls": 0,
            "message": "Fruit topic — skipped Pollinations (local_talking_fruits only).",
            "user_prompt": (scene or "")[:300],
            "primary_subject": (lock.get("primary_subject") or "")[:200],
            "gender_lock": lock.get("gender"),
            "local_talking_fruits": True,
        }

    # HARD SKIP: VERIDIQ / brand / product topics never hit Pollinations.
    # Random free-tier models often drift to stock animals (cats); local branded
    # stills are the only reliable path for "create an image for my veridiq".
    brandish = bool(
        lock.get("is_brand_request")
        or is_brand_topic(prompt)
        or is_brand_topic(scene)
    )
    if brandish:
        try:
            from pathlib import Path

            from veridiq.postings.local_stills import ensure_still_set

            topic = (scene or prompt or "VERIDIQ").strip() or "VERIDIQ"
            paths, meta = ensure_still_set(
                [],
                topic,
                n=1,
                width=max(640, int(width or 1280)),
                height=max(360, int(height or 1280)),
                prefix=filename_stem or "brand",
                force_local=True,
                hero_opener=True,
            )
            if paths:
                path = Path(paths[0])
                return {
                    "status": "ok",
                    "ok": True,
                    "provider": "local_branded",
                    "model": "local_hero",
                    "prompt": f"VERIDIQ branded still: {topic}"[:800],
                    "user_prompt": topic[:300],
                    "primary_subject": "VERIDIQ",
                    "gender_lock": None,
                    "image_url": f"/api/v1/veridiq/marketing/image/file/{path.name}",
                    "absolute_path": str(path),
                    "image_path": str(path),
                    "bytes": path.stat().st_size if path.is_file() else 0,
                    "width": max(640, int(width or 1280)),
                    "height": max(360, int(height or 1280)),
                    "pollinations_calls": 0,
                    "brand_local_only": True,
                    "local_stills": meta,
                    "message": (
                        "VERIDIQ branded still (local) — Pollinations skipped to avoid "
                        "animal/subject drift."
                    ),
                    "style": st,
                    "fallback": False,
                }
        except Exception as exc:
            return {
                "status": "brand_local_only",
                "ok": False,
                "retry": True,
                "pollinations_calls": 0,
                "brand_local_only": True,
                "message": f"Brand local still failed: {str(exc)[:120]}",
                "user_prompt": (scene or "")[:300],
                "primary_subject": "VERIDIQ",
                "gender_lock": lock.get("gender"),
            }
        return {
            "status": "brand_local_only",
            "ok": False,
            "retry": True,
            "pollinations_calls": 0,
            "brand_local_only": True,
            "message": "Brand topic — local still unavailable; retry.",
            "user_prompt": (scene or "")[:300],
            "primary_subject": "VERIDIQ",
            "gender_lock": lock.get("gender"),
        }

    # Hard subject lock: refuse AI when we cannot lock a primary subject
    # (caller falls back to abstract local stills — never random Pollinations).
    primary = (lock.get("primary_subject") or "").strip()
    if not primary or (not lock.get("concrete") and not lock.get("is_brand_request")):
        return {
            "status": "subject_lock_failed",
            "ok": False,
            "retry": False,
            "message": "Subject lock failed — using local topic illustration (no random AI).",
            "user_prompt": (scene or "")[:300],
            "primary_subject": primary[:200],
            "gender_lock": lock.get("gender"),
        }

    # Style AFTER subject — never let style rewrite gender/identity
    locked = pollinations_image.enrich_scene_prompt(
        prompt,
        style=st,
        extra=style_suffix(st),
    )
    # Never omit topic / primary from the final prompt sent to providers
    if primary.lower() not in locked.lower() and (scene or "").lower() not in locked.lower():
        locked = f"PRIMARY SUBJECT (CRITICAL): {primary}. Exact scene: {scene}. {locked}"
    locked = (
        f"{locked} Single coherent scene, one primary subject centered. "
        f"Negative: {COLLAGE_NEGATIVE}."
    )
    gem_prompt = (
        f"{locked} "
        "Follow the user's subject EXACTLY. Do not change gender, age, or identity. "
        "Do not replace the scene with a logo or office agents unless requested. "
        f"{STYLE_ANCHORS}. "
        f"Avoid: {NEGATIVE_PROMPT}."
    )

    gem_err = "Gemini image skipped (free Pollinations path)"
    use_gemini_flag = (os.getenv("VERIDIQ_USE_GEMINI_IMAGE") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if (
        not prefer_pollinations
        and use_gemini_flag
        and google_ai.status().get("configured")
    ):
        gem = google_ai.generate_image(
            prompt=gem_prompt,
            filename_stem=filename_stem,
            timeout=max(12.0, float(gemini_timeout or 45.0)),
        )
        if gem.get("ok"):
            gem["style"] = st
            gem["fallback"] = False
            gem["prompt"] = gem_prompt[:800]
            gem["user_prompt"] = scene[:300]
            gem["primary_subject"] = lock["primary_subject"][:200]
            gem["gender_lock"] = lock["gender"]
            return gem
        # Short note only — never dump model-not-found + 429 bodies into UX
        raw = str(gem.get("message") or "unavailable")
        if "not found" in raw.lower() or "404" in raw:
            gem_err = "Gemini image model unavailable"
        elif "429" in raw or "quota" in raw.lower():
            gem_err = "Gemini image quota busy"
        else:
            gem_err = raw[:80]
    elif not prefer_pollinations and not use_gemini_flag:
        gem_err = "Gemini image off (set VERIDIQ_USE_GEMINI_IMAGE=1 to enable)"

    # Free path: turbo when prefer_pollinations (video/fast); Flux otherwise
    flux_pref = (os.getenv("VERIDIQ_VIDEO_PREFER_FLUX") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    primary_model = "flux" if (flux_pref or not prefer_pollinations) else "turbo"

    def _pollinate(pr: str, *, stem: str | None, attempt: int) -> dict[str, Any]:
        return pollinations_image.generate_image(
            prompt=pr,
            width=width,
            height=height,
            filename_stem=stem,
            style=st if st in ("cartoon", "anime", "cinematic", "cgi") else "photo",
            model=primary_model,
            timeout=timeout,
            seed=(None if seed is None else (seed + attempt * 41) % 2_147_483_647),
            enhance=enhance,
            allow_turbo_retry=True,
            max_attempts=max_attempts,
        )

    work_prompt = prompt
    if lock.get("is_fruit"):
        work_prompt = (
            f"{prompt}. ONE single cute cartoon fruit with a clear face, Pixar, bright, "
            f"centered, clear fruit shape, NOT translucent blob, NOT abstract, "
            f"NOT a grid, NOT a collage. Negative: {COLLAGE_NEGATIVE}, "
            f"translucent goo, orange blob, abstract gradient, bokeh-only, muddy mush."
        )

    pol = _pollinate(work_prompt, stem=filename_stem, attempt=0)
    if pol.get("ok") and pol.get("absolute_path"):
        reject_goo = False
        try:
            from veridiq.postings.local_stills import looks_like_goo_or_blob

            reject_goo = looks_like_goo_or_blob(str(pol["absolute_path"]))
        except Exception:
            reject_goo = False
        if looks_like_collage_or_grid(str(pol["absolute_path"])) or reject_goo:
            strict = (
                f"{work_prompt}. STRICT: single subject only, centered portrait of one "
                f"clear cartoon fruit character with face, full colorful kitchen background, "
                f"absolutely NO collage NO grid NO translucent goo NO abstract blob. "
                f"Negative: {COLLAGE_NEGATIVE}."
            )
            retry_stem = f"{filename_stem}_strict" if filename_stem else None
            pol2 = _pollinate(strict, stem=retry_stem, attempt=1)
            if pol2.get("ok") and pol2.get("absolute_path"):
                reject2 = looks_like_collage_or_grid(str(pol2["absolute_path"]))
                try:
                    from veridiq.postings.local_stills import looks_like_goo_or_blob as _goo

                    reject2 = reject2 or _goo(str(pol2["absolute_path"]))
                except Exception:
                    pass
                if reject2:
                    return {
                        "status": "quality_rejected",
                        "ok": False,
                        "retry": False,
                        "message": (
                            "AI still looked like collage/goo — using local fruit character still."
                        ),
                        "user_prompt": scene[:300],
                        "quality_gate": "collage_or_goo_rejected",
                    }
                pol = pol2
                pol["quality_gate"] = "collage_retry_ok"
            else:
                return {
                    "status": "quality_rejected",
                    "ok": False,
                    "retry": bool(pol2.get("retry")),
                    "message": (
                        "AI still rejected (collage/goo) and retry failed — "
                        "local fruit character still."
                    ),
                    "user_prompt": scene[:300],
                    "quality_gate": "collage_or_goo_rejected",
                }
        else:
            pol["quality_gate"] = "ok"

    if pol.get("ok"):
        pol["style"] = st
        pol["fallback"] = True
        pol["gemini_note"] = gem_err[:80]
        model_note = pol.get("model") or primary_model
        pol["message"] = (
            f"{pol.get('message')} (Pollinations {model_note} @ {width}px, style={st}.)"
        )
        return pol
    # Short UX — never concatenate Gemini dump + Pollinations 429 body
    short = pol.get("message") or "Image busy — retry in a few seconds."
    if len(short) > 140:
        short = "Image busy — free queue full. Wait a few seconds and retry."
    return {
        "status": "error",
        "ok": False,
        "retry": True,
        "message": short[:160],
        "prompt": locked[:500],
        "user_prompt": scene[:300],
        "gender_lock": lock["gender"],
    }


def _music_prompt_for_theme(theme: str) -> str:
    """Music-oriented prompt — never 'read these lyrics' TTS wording."""
    t = (theme or "inspiration").strip()[:200]
    return (
        f"Original song instrumental about {t}: catchy melody, clear drum beat at 118 BPM, "
        f"bass line, warm synth pads, pop electronic production, verse-chorus energy, "
        f"studio mix, not speech, not spoken word, not audiobook narration"
    )


def _synth_instrumental_wav(path: Path, *, duration_sec: float = 24.0, bpm: float = 118.0) -> Path:
    """Generate a simple free instrumental bed (kick/snare/bass/chords) — real music, not TTS."""
    import wave

    import numpy as np

    sr = 22050
    n = int(sr * duration_sec)
    t = np.arange(n, dtype=np.float64) / sr
    beat = 60.0 / bpm
    bar = beat * 4
    out = np.zeros(n, dtype=np.float64)

    # Chord progression (Am–F–C–G) as soft pads
    chord_freqs = np.array(
        [
            [220.00, 261.63, 329.63],  # Am
            [174.61, 220.00, 261.63],  # F
            [130.81, 164.81, 196.00],  # C
            [196.00, 246.94, 293.66],  # G
        ],
        dtype=np.float64,
    )
    bar_idx = (t / bar).astype(np.int64) % 4
    for bi in range(4):
        mask = bar_idx == bi
        if not np.any(mask):
            continue
        tt = t[mask]
        for f in chord_freqs[bi]:
            phase = 2 * np.pi * f * tt
            out[mask] += 0.08 * np.sin(phase) + 0.03 * np.sin(2 * phase) + 0.015 * np.sin(3 * phase)

    # Bass following root (eighth-note plucks)
    roots = np.array([110.0, 87.31, 65.41, 98.0], dtype=np.float64)
    eighth = beat / 2
    local_eighth = (t % eighth) / eighth
    bass_env = np.exp(-3.5 * local_eighth)
    for bi in range(4):
        mask = bar_idx == bi
        f = roots[bi]
        out[mask] += 0.22 * bass_env[mask] * np.sin(2 * np.pi * f * t[mask])

    # Four-on-floor kick
    pos = t % beat
    kick_mask = pos < 0.12
    kick_env = np.exp(-pos[kick_mask] * 28)
    kick_f = 90 - pos[kick_mask] * 200
    out[kick_mask] += 0.55 * kick_env * np.sin(2 * np.pi * kick_f * t[kick_mask])

    # Snare on beats 2 and 4
    beat_in_bar = ((t % bar) / beat).astype(np.int64)
    snare_mask = ((beat_in_bar == 1) | (beat_in_bar == 3)) & (pos < 0.08)
    snare_env = np.exp(-pos[snare_mask] * 40)
    rng = np.random.default_rng(42)
    noise = rng.uniform(-1.0, 1.0, size=int(np.count_nonzero(snare_mask))) * 0.35
    out[snare_mask] += snare_env * noise

    # Lead melody motif
    melody = np.array([440.0, 523.25, 587.33, 659.25, 587.33, 523.25, 440.0, 392.0], dtype=np.float64)
    note_len = beat / 2
    ni = (t / note_len).astype(np.int64) % len(melody)
    local = (t % note_len) / note_len
    mel_env = np.sin(np.pi * np.minimum(1.0, local * 1.2)) * np.exp(-1.2 * local)
    freqs = melody[ni]
    out += 0.12 * mel_env * np.sin(2 * np.pi * freqs * t)

    peak = float(np.max(np.abs(out))) or 1.0
    out = out / peak * 0.85
    pcm = (out * 32767.0).astype(np.int16)

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())
    return path


def _try_pollinations_music(theme: str, sid: str) -> tuple[Optional[Path], str]:
    """Try Pollinations music models (not TTS). Returns (path, note)."""
    music_prompt = _music_prompt_for_theme(theme)
    attempts = [
        ("https://gen.pollinations.ai/audio/" + quote(music_prompt), {"model": "lyria-3-clip"}),
        (
            "https://audio.pollinations.ai/" + quote(music_prompt[:180]),
            {"model": "lyria-3-clip"},
        ),
    ]
    notes: list[str] = []
    for url, params in attempts:
        try:
            r = requests.get(url, params=params, timeout=18)
            ctype = (r.headers.get("content-type") or "").lower()
            if r.status_code != 200 or len(r.content) < 4000:
                notes.append(f"{params.get('model')}: HTTP {r.status_code}")
                continue
            if "audio" not in ctype and "mpeg" not in ctype and "ogg" not in ctype and "wav" not in ctype:
                if len(r.content) < 8000:
                    notes.append(f"{params.get('model')}: not audio")
                    continue
            model = str(params.get("model") or "")
            ext = "mp3" if ("mpeg" in ctype or "mp3" in ctype) else "wav"
            path = AUD_DIR / f"song_{sid}_music.{ext}"
            path.write_bytes(r.content)
            return path, f"Music via Pollinations ({model or 'audio'})."
        except Exception as exc:
            notes.append(f"{params.get('model')}: {str(exc)[:60]}")
    return None, " | ".join(notes[:3]) if notes else "Pollinations music unavailable"


def _try_edge_tts_vocals(lyrics: str, sid: str) -> tuple[Optional[Path], str]:
    """Optional vocal layer (speech-sung demo) — mixed later when possible."""
    try:
        import asyncio
        import edge_tts

        path = AUD_DIR / f"song_{sid}_vocals.mp3"
        text = re.sub(r"\[.*?\]", ". ", lyrics)
        text = re.sub(r"\s+", " ", text).strip()[:900]
        # Slightly slower + expressive voice for a more song-like delivery
        async def _run() -> None:
            communicate = edge_tts.Communicate(text, "en-US-JennyNeural", rate="-8%", pitch="+2Hz")
            await communicate.save(str(path))

        asyncio.run(_run())
        if path.exists() and path.stat().st_size > 500:
            return path, "Vocals via edge-tts (layered when mix available)."
    except Exception as exc:
        return None, f"TTS vocals skipped: {str(exc)[:80]}"
    return None, "TTS vocals unavailable"


def _mix_wav_with_mp3_ffmpeg(bed: Path, vocals: Path, out: Path) -> bool:
    """Mix instrumental + vocals with ffmpeg if present."""
    import shutil
    import subprocess

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    try:
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(bed),
                "-i",
                str(vocals),
                "-filter_complex",
                "[0:a]volume=0.85[a0];[1:a]volume=0.55[a1];[a0][a1]amix=inputs=2:duration=longest:dropout_transition=2",
                "-c:a",
                "libmp3lame",
                "-q:a",
                "4",
                str(out),
            ],
            check=True,
            capture_output=True,
            timeout=120,
        )
        return out.exists() and out.stat().st_size > 1000
    except Exception:
        return False


def generate_song(*, topic: str) -> dict[str, Any]:
    """Lyrics + musical audio (instrumental bed / music API), not speech-only TTS."""
    from veridiq.integrations import ai_gateway
    from veridiq.integrations.pollinations_image import clean_user_prompt

    theme = clean_user_prompt(topic) or topic
    lyrics = ""
    if ai_gateway.status().get("configured"):
        gen = ai_gateway.generate(
            prompt=(
                "Write an original short song (3 verses + chorus) about this theme. "
                "Return ONLY lyrics with [Verse]/[Chorus] labels.\n\n"
                f"Theme: {theme[:500]}"
            ),
            task_type="fast",
            max_providers=3,
            max_tokens=900,
        )
        if gen.get("ok"):
            lyrics = str(gen.get("text") or "").strip()
    if not lyrics:
        lyrics = (
            f"[Verse 1]\nIn the glow of midnight screens, {theme}\n"
            "We chase the truth through quiet code and dreams.\n\n"
            "[Chorus]\nRise up, VERIDIQ light — verify tonight.\n"
            "Agents at their desks, making wrong things right.\n"
        )

    AUD_DIR.mkdir(parents=True, exist_ok=True)
    sid = uuid.uuid4().hex[:12]
    lyrics_path = AUD_DIR / f"song_{sid}.txt"
    lyrics_path.write_text(lyrics, encoding="utf-8")

    audio_url = None
    audio_path: Optional[Path] = None
    audio_note = ""
    music_kind = "none"

    # 1) Prefer Pollinations music models (genre/beat/melody — not "read lyrics")
    pol_path, pol_note = _try_pollinations_music(theme, sid)
    if pol_path and pol_path.exists():
        audio_path = pol_path
        audio_note = pol_note
        music_kind = "pollinations_music"

    # 2) Always ensure a musical instrumental bed exists (free, local)
    bed_path = AUD_DIR / f"song_{sid}_bed.wav"
    try:
        bed_dur = 24.0
        # Longer beds when caller embeds duration in topic like "[duration=180]"
        dm = re.search(r"\[duration=(\d+)\]", topic or "")
        if dm:
            bed_dur = max(24.0, min(300.0, float(dm.group(1))))
        _synth_instrumental_wav(bed_path, duration_sec=bed_dur, bpm=118.0)
        if not audio_path:
            audio_path = bed_path
            audio_note = "Instrumental music bed (synth drums + bass + melody, 118 BPM)."
            music_kind = "synth_instrumental"
        else:
            audio_note = (audio_note + " Local instrumental bed also generated.").strip()
    except Exception as exc:
        if not audio_note:
            audio_note = f"Instrumental synth failed: {str(exc)[:80]}"

    # 3) Optional vocals — only when ffmpeg can mix onto the bed (never TTS-alone as the song)
    vocals_path = None
    vnote = ""
    import shutil

    if bed_path.exists() and shutil.which("ffmpeg"):
        vocals_path, vnote = _try_edge_tts_vocals(lyrics, sid)
        if vocals_path:
            mixed = AUD_DIR / f"song_{sid}_mix.mp3"
            if _mix_wav_with_mp3_ffmpeg(bed_path, vocals_path, mixed):
                audio_path = mixed
                music_kind = "instrumental_plus_vocals"
                audio_note = (
                    "Lyrics + music track (instrumental bed mixed with vocal demo). "
                    "Free path — not Suno/Udio studio quality."
                )
            else:
                audio_note = ((audio_note or "Music track ready.") + f" {vnote}").strip()
    else:
        vnote = "Vocal mix skipped (ffmpeg not installed) — instrumental track is the song audio."
        if audio_note and "Vocal" not in audio_note:
            audio_note = f"{audio_note} {vnote}".strip()

    if audio_path and audio_path.exists():
        audio_url = f"/api/v1/veridiq/marketing/audio/file/{audio_path.name}"

    included = "lyrics + music track"
    if music_kind == "instrumental_plus_vocals":
        included = "lyrics + instrumental bed + vocal layer"
    elif music_kind == "pollinations_music":
        included = "lyrics + AI music clip"
    elif music_kind == "synth_instrumental":
        included = "lyrics + instrumental music bed (beat/bass/melody)"

    return {
        "status": "ok",
        "ok": True,
        "provider": "creative_media",
        "lyrics": lyrics,
        "lyrics_path": str(lyrics_path.relative_to(_ROOT)).replace("\\", "/"),
        "audio_url": audio_url,
        "audio_path": str(audio_path.relative_to(_ROOT)).replace("\\", "/") if audio_path and audio_path.exists() else None,
        "vocals_url": (
            f"/api/v1/veridiq/marketing/audio/file/{vocals_path.name}"
            if vocals_path and vocals_path.exists() and music_kind != "instrumental_plus_vocals"
            else None
        ),
        "music_kind": music_kind,
        "theme": theme[:200],
        "message": (
            f"Song ready — includes {included}. {audio_note} "
            "Free music ≠ Suno/GPT-quality production, but this is a real track with tempo/beat, not speech-only TTS."
            if audio_url
            else f"Lyrics ready. Audio pending — {audio_note or 'generation failed'}."
        ),
    }


def generate_video_narration_audio(
    *,
    script: str,
    duration_hint_sec: int = 15,
) -> dict[str, Any]:
    """Neural VO for video mux — ElevenLabs → Azure Speech → edge-tts.

    Does not apply facial lip-sync (stills cannot drive phoneme mouth shapes).
    Audio duration is trimmed/padded to match video length at mux time.
    """
    from veridiq.voice.tts import generate_narration

    try:
        return generate_narration(script=script, duration_hint_sec=duration_hint_sec)
    except Exception as exc:
        return {"ok": False, "status": "error", "message": f"Narration failed: {str(exc)[:120]}"}
