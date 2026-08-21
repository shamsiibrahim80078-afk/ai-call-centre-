"""Postings Studio agent — Mira drafts Gemini-style posts, optional Canva,
video storyboards, and creative chat.

Posts are generated with Google Gemini when the key works; otherwise the AI
Gateway falls back (Groq / OpenRouter / …). Canva is optional. Social publish
always goes through comms draft → approve — never invents a live post.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Optional

from veridiq.workforce.identities import identity_for

AGENT_TYPE = "posting_studio"

_VALID_INTENTS = frozenset(
    {
        "draft_post",
        "create_image",
        "create_design",
        "create_video",
        "create_song",
        "chat",
        "help",
    }
)

_CINEMATIC_STANDING = """VIDEO QUALITY — 3 PILLARS (standing instructions — every generation, FREE only):

1) Quality Control Parameters (always apply)
- Rendering Engine: Hyper-realistic physics engine simulation (prompt directive)
- Resolution: 1080p minimum / 4K native upscale (default free 1080p; 4K only via VERIDIQ_VIDEO_4K=1)
- Aspect: 16:9 landscape default; support 9:16 if user asks shorts/reels
- FPS: 30 default (VERIDIQ_VIDEO_FPS=60 optional)
- Guidance Scale (CFG): 7.0–8.0 — pass guidance/cfg=7.5 when API supports; else bake "CFG 7.5, high adherence to prompt"
- Inference Steps: 35–50 — pass steps=40 when supported; else "high inference detail 40 steps"
- Subject fidelity CRITICAL: fruits/animals/objects talking ≠ humans — never swap user's characters

2) Audio & Voice (free) — ALWAYS mux VO on create_video
- Neural audio: 24-bit/48kHz via edge-tts + ffmpeg mux every create_video
- If mux fails: return audio_url and fail loudly — never silent-success without audio
- Lipsync: align narration duration to video; true phoneme lip-sync N/A on stills path — include audio directive in prompts
- Acoustics: natural room reverb, studio warmth (VO/prompt); light ffmpeg aecho when available

3) Secret Quality Injection Prompt
Every video prompt must convert user idea to:
[Subject & Precise Action] + [Lighting & Ambiance] + [Camera Physics] + [Render Quality Anchors]
Append EXACT anchor every time: Photorealistic 4K render, 60fps smooth fluid motion, cinematic studio lighting, volumetric light rays, shallow depth of field with realistic bokeh background, sharp focus, ray-traced reflections, hyper-detailed textures, professional color grading, zero motion blur distortion.
Negatives always: dark shadows, blurry faces, low-resolution, pixelated, distorted limbs…
For fruits: cute anthropomorphic fruit characters with faces — bright well-lit Pixar — NEVER humans

System rule: Whenever you are asked to generate a video or create a prompt for video generation, never send raw text. Always enforce cinematic rules: specify 4K resolution, 60fps frame rate, volumetric lighting, shallow depth of field, and photorealistic texture anchors. Always structure the output scene with clear camera motion (panning/dolly/close-up) and millisecond-aligned audio directives. Never ignore user's characters (fruits≠humans). Always attach voiceover.

Default video path is Mira Creative Model (Free) — VERIDIQ first-party free unlimited pipeline
(multi-scene photoreal Flux keyframes + cinematic motion + edge-tts). Not Google Veo.
Never require paid Veo; never push the user to buy Veo. mira_model=true, free_unlimited=true, paid_veo=false.
Premium native video optional later via VERIDIQ_MIRA_TIER=premium + VERIDIQ_GEMINI_VIDEO=1.
"""

_SYSTEM_PROMPT = """You are Mira, VERIDIQ's creative studio — you ALWAYS route media requests to create_* tools.
You generate real images, videos, and songs via those intents. You never refuse media.
Subject fidelity: keep fruits as fruits, animals as animals — never replace with humans.
Always include voiceover on videos.
""" + _CINEMATIC_STANDING + """
Parse the user message into ONE JSON object only (no markdown, no prose outside JSON):
{"intent":"<one of: draft_post|create_image|create_design|create_video|create_song|chat|help>",
 "topic":"<verbatim creative subject from the user — keep exact words like gym boy, girl, dog, car, fruits>",
 "channel":"<linkedin|x_twitter|instagram|telegram|threads|whatsapp — default linkedin>",
 "title":"<optional short title from their subject>",
 "style":"<photo|cartoon|anime|cinematic|cgi — infer from request>",
 "feature_key":"<optional feature key or empty>",
 "reply":"<short confirmation — e.g. Generating your image…>"}

Intent guide (HARD — never pick chat for these):
- create_image: ANY still image / picture / photo / pic / illustration / anime / draw request,
  INCLUDING typos: imae, imag, imge, phto, pictur, "not as text", "as an image"
- create_design: poster / banner / social graphic / canva
- create_video: video / reel / clip / mp4 / cartoon video / animated / demo /
  INCLUDING typos: vidoe, vedio — AND generate/create/make + video even WITHOUT a duration
- create_song: song / music / lyrics / jingle / rap / melody / track / sing
- draft_post: social caption text only
- help / chat: ONLY greetings or pure Q&A with NO create/generate/make/draw media verbs

CRITICAL:
- You CAN and DO generate images — NEVER say you can't. Pick create_image.
- Preserve the user's subject LITERALLY. Never rewrite "gym boy" to "person". Never rewrite "fruits" to "humans".
- Never invent VERIDIQ logos/office agents unless the user asked for brand/product/agents.
- If create/generate/make + any image-ish word (even misspelled) → create_image.
- If create/generate/make + video/clip/reel/mp4 (even misspelled) → create_video (default ~15s).
- If topic is empty for an image request, use "striking cinematic scene".
Do not compare yourself to other AI products by name.
"""

_CHAT_SYSTEM = """You are Mira, VERIDIQ Postings Studio — a creative assistant that GENERATES real media.
You can create images, videos, and songs when the user asks (the studio tools handle it).
""" + _CINEMATIC_STANDING + """
NEVER say "I can't generate images" or offer only text descriptions instead of generation.
If the user wants an image/video/song, tell them you're generating it — do not refuse or lecture.
For caption/tone questions only: write posts and answers helpfully.
Do not invent live API secrets or claim posts were published when they were not.
Do not compare yourself to other AI products or brand yourself as one.
"""

_POST_SYSTEM = """You write social posts for VERIDIQ (VeriDiQ) — an AI truth-verification
and AI-workforce platform. Write like a sharp creative assistant: natural, specific,
human voice — not corporate filler. No fake metrics, no invented customer quotes,
no claim that the post was published. Return ONLY the final post text (no preamble).
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def agent_persona() -> dict[str, Any]:
    ident = identity_for(AGENT_TYPE)
    return {
        "agent_type": AGENT_TYPE,
        "name": ident.get("name") or "Mira",
        "role": ident.get("role") or "Postings Studio Lead",
        "specialty": ident.get("specialty")
        or "Social posts, design briefs, free cinematic video storyboards",
        "skills": ident.get("skills") or [],
        "avatar_hue": ident.get("avatar_hue", 312),
        "standing_instructions": ident.get("standing_instructions") or _CINEMATIC_STANDING,
        "greeting": (
            f"Hi — I'm {ident.get('name') or 'Mira'}. Ask me to generate a real image, "
            "draft a VERIDIQ post, or build a free unlimited video — I'll create the media, not just text."
        ),
    }


def studio_status() -> dict[str, Any]:
    from veridiq.integrations import ai_gateway, canva, video_render
    from veridiq.integrations.llm import google_ai
    from veridiq.postings import mira_engine, mira_model, tiers

    gemini = google_ai.status()
    veo_on = bool(google_ai.veo_enabled())
    mira_id = mira_engine.engine_identity()
    model_st = mira_model.status()
    tier_st = tiers.status()
    out: dict[str, Any] = {
        "agent": agent_persona(),
        "llm": ai_gateway.status(),
        "gemini": gemini,
        "canva": canva.status(),
        "video_render": video_render.status(),
        "veo_enabled": veo_on,
        "mira_engine": True,
        "mira_model": mira_model.MODEL_NAME,
        "tier": tier_st.get("tier") or "free",
        "premium_ready": True,
        "free_features": list(tiers.FREE_FEATURES),
        "premium_features": list(tiers.PREMIUM_FEATURES),
        "free_unlimited": True,
        "paid_veo": bool(tiers.premium_video_unlocked()),
        "engine": mira_model.MODEL_NAME,
        "engine_id": mira_model.MODEL_ID,
        "cinematic_engine": mira_engine.ENGINE_NAME,
        "cinematic_engine_id": mira_engine.ENGINE_ID,
        "message": (
            f"{mira_model.MODEL_TAGLINE} "
            "Default: free unlimited posts/images/designs/videos/songs via Mira. "
            "Premium native video (Veo) stays locked until VERIDIQ_MIRA_TIER=premium "
            "and VERIDIQ_GEMINI_VIDEO=1. Drafts need human approval before any social send."
        ),
        "mira": mira_id,
        "mira_creative": model_st,
        "tiers": tier_st,
    }
    try:
        from veridiq.postings.learning import learning_status

        learn = learning_status()
        out["learning"] = learn
        out["message"] = (
            f"{out['message']} Learning: ratings + uploads"
            f" ({learn.get('rated_examples', 0)} rated) — free, no Unsplash/Meta."
        )
    except Exception as exc:
        out["learning"] = {"ok": False, "enabled": False, "error": str(exc)[:120]}
    return out


def _gemini_generate(prompt: str, *, model: str = "gemini-2.0-flash") -> dict[str, Any]:
    """Prefer Gemini; return {ok, text, provider, message, status}."""
    try:
        from veridiq.integrations.llm import google_ai

        st = google_ai.status()
        if st.get("configured"):
            for mid in (model, "gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-flash-latest"):
                gen = google_ai.generate_text(prompt=prompt, model=mid)
                if gen.get("ok") and (gen.get("text") or "").strip():
                    return {
                        "ok": True,
                        "text": str(gen["text"]).strip(),
                        "provider": "google_ai",
                        "model": mid,
                        "status": "ok",
                        "message": gen.get("message"),
                    }
                # Quota / hard fail — stop trying Gemini models
                if gen.get("status") == "error" and "quota" in str(gen.get("message") or "").lower():
                    return {
                        "ok": False,
                        "text": "",
                        "provider": "google_ai",
                        "status": "error",
                        "message": gen.get("message") or "Gemini quota exceeded",
                    }
    except Exception as exc:
        return {"ok": False, "text": "", "provider": "google_ai", "status": "error", "message": str(exc)[:200]}
    return {"ok": False, "text": "", "provider": "google_ai", "status": "unavailable", "message": "Gemini unavailable"}


def _llm_generate(prompt: str, *, task_type: str = "fast") -> dict[str, Any]:
    """Gemini first, then AI Gateway fallback (Groq etc.)."""
    gem = _gemini_generate(prompt)
    if gem.get("ok"):
        return gem
    try:
        from veridiq.integrations import ai_gateway

        if ai_gateway.status().get("configured"):
            gen = ai_gateway.generate(prompt=prompt, task_type=task_type, max_providers=4, max_tokens=1200)
            if gen.get("ok") and (gen.get("text") or "").strip():
                return {
                    "ok": True,
                    "text": str(gen["text"]).strip(),
                    "provider": gen.get("provider_used") or "ai_gateway",
                    "model": gen.get("model"),
                    "status": "ok",
                    "message": gem.get("message") or gen.get("message"),
                    "gemini_fallback_reason": gem.get("message"),
                }
    except Exception as exc:
        return {"ok": False, "text": "", "status": "error", "message": str(exc)[:200]}
    return {
        "ok": False,
        "text": "",
        "status": gem.get("status") or "configuration_required",
        "message": gem.get("message") or "No LLM configured for post generation.",
    }


def _detect_style_keyword(message: str) -> str:
    from veridiq.postings.creative import detect_style

    return detect_style(message)


# Image tokens incl. common typos — NEVER miss these as chat
_IMAGE_WORD_RE = re.compile(
    r"\b("
    r"images?|imgs?|imae|imag|imge|imgae|imagge|"
    r"pics?|pictures?|pictur|picure|"
    r"photos?|phto|photoo|"
    r"illustrations?|drawings?|draw|sketch|"
    r"art|visuals?|artwork|"
    r"va\s+images?|va\s+imae|va\s+imag|va\s+pic"
    r")\b",
    re.I,
)
_CREATE_VERB_RE = re.compile(
    r"\b(create|generate|make|draw|render|paint|produce|show me|give me|need|want)\b",
    re.I,
)
_SONG_WORD_RE = re.compile(
    r"\b(songs?|music|lyrics?|jingles?|raps?|melody|melodies|sing|singing|tracks?|beats?|instrumental)\b",
    re.I,
)
_VIDEO_WORD_RE = re.compile(
    r"\b("
    r"videos?|vidoe|vedio|vido|"
    r"storyboards?|reels?|mp4|clips?|gifs?|"
    r"animation|animated|demo\s*reel|cartoon\s+video"
    r")\b",
    re.I,
)
_NOT_TEXT_RE = re.compile(r"\b(not\s+as\s+text|as\s+(an?\s+)?image|no\s+text|visual\s+only)\b", re.I)


def _looks_like_image_request(q: str) -> bool:
    """True for image asks including typos (imae, imag) and 'create … not as text'."""
    if not q:
        return False
    if _IMAGE_WORD_RE.search(q):
        return True
    if _NOT_TEXT_RE.search(q) and _CREATE_VERB_RE.search(q):
        return True
    # create/generate/make + fuzzy image stem (typo-tolerant)
    if _CREATE_VERB_RE.search(q) and re.search(r"\bim+[ae]?g|pict|phot|draw", q, re.I):
        return True
    return False


def _looks_like_song_request(q: str) -> bool:
    return bool(q and _SONG_WORD_RE.search(q))


def _looks_like_video_request(q: str) -> bool:
    """True for video/clip/reel asks incl. typos (vidoe) and generate/create/make + video."""
    if not q:
        return False
    if _VIDEO_WORD_RE.search(q):
        return True
    # create/generate/make + fuzzy video stem (typo-tolerant) — duration optional
    if _CREATE_VERB_RE.search(q) and re.search(r"\bvid|reel|mp4|clip|storyboard", q, re.I):
        return True
    return False


def _looks_like_design_request(q: str) -> bool:
    return bool(q and any(w in q for w in ("design", "canva", "poster", "banner", "graphic", "square post")))


# Duration: default 15s when unspecified, clamp 10–300s (never return 6s again)
_DURATION_DEFAULT_SEC = 15
_DURATION_MIN_SEC = 10
_DURATION_MAX_SEC = 300
# Unique AI stills: hard-capped at 3 for ANY duration (speed — long = longer holds).
_VIDEO_MAX_STILLS = 3
_VIDEO_MIN_STILLS = 3
_VIDEO_BEST_EFFORT_MIN = 1  # assemble if ≥1 still; 0 → clear error
# Still gen size — Pollinations caps ~1280; local_video upscales to 1920×1080
_VIDEO_STILL_W = 1280
_VIDEO_STILL_H = 720
# Output quality (assembled MP4) — Gemini recipe defaults
_VIDEO_OUT_W = 1920
_VIDEO_OUT_H = 1080
_VIDEO_OUT_FPS = 30
# Per-still timeout — hard 12s; fail → turbo retry, never block forever
_VIDEO_STILL_TIMEOUT = 12.0
# Serial stills only — Pollinations free IP queue max 1 (shared semaphore)
_VIDEO_STILL_WORKERS = 1
_VIDEO_STILL_GEMINI_TIMEOUT = 6.0
_VIDEO_STILL_RETRY_PASSES = 1
_VIDEO_WALL_BUDGET_SEC = 65.0

# Reference-matched look + Gemini-quality STYLE_ANCHORS (cinematic subject-sharp / soft bg)
_REF_AGENT_LOOK = (
    "photoreal cinematic commercial B-roll, soft natural window light, warm-neutral grade, "
    "bright minimalist office, light wood desk, grey mesh ergonomic chair, "
    "curved ultrawide Agent Workspace dark-mode UI with green charts, "
    "professional woman agent neat bun grey cardigan, boom headset, "
    "volumetric lighting, soft studio illumination, rim light, subsurface scattering, "
    "shallow depth of field, bokeh background, sharp foreground focus, "
    "smooth panning, cinematic dolly, photorealistic textures, "
    "ray-traced reflections, hyper-detailed 4K render, 60fps fluid motion, "
    "crystal clear audio, studio-grade acoustics, faint ambient hum, no watermark"
)

_AUDIO_ON_VIDEO_RE = re.compile(
    r"\b("
    r"with\s+this\s+voice|with\s+this\s+song|with\s+the\s+song|"
    r"add\s+(music|a\s+soundtrack|soundtrack|narration|voice|audio)|"
    r"soundtrack|narration|background\s+music|bgm|"
    r"with\s+(music|song|voice|audio|narration)"
    r")\b",
    re.I,
)

_SHORTS_RE = re.compile(
    r"\b(shorts?|reels?|tiktok|vertical|portrait|9\s*[:/x]\s*16)\b",
    re.I,
)


def detect_video_aspect(text: str) -> str:
    """16:9 landscape default; 9:16 when user asks shorts/reels/vertical."""
    if _SHORTS_RE.search(text or ""):
        return "9:16"
    return "16:9"


def parse_duration_sec(text: str, *, default: int = _DURATION_DEFAULT_SEC) -> int:
    """Parse user duration phrases → seconds (clamped 10–300). Default 15s when absent."""
    from veridiq.integrations.local_video import clamp_duration_sec

    q = (text or "").strip().lower()
    if not q:
        return clamp_duration_sec(default)

    # mm:ss
    m = re.search(r"\b(\d{1,2})\s*:\s*(\d{2})\b", q)
    if m:
        return clamp_duration_sec(int(m.group(1)) * 60 + int(m.group(2)))

    # "3 minutes" / "3 mints" / "3 mint" / "3 mins" / "3 minuts" / "3 min" / "3m"
    _MIN_UNIT = r"(?:minutes?|minuts?|mints?|mins?|mint|min|m)\b"
    m = re.search(
        rf"\b(?:about|around|approx(?:imately)?|~)?\s*(\d+(?:\.\d+)?)\s*{_MIN_UNIT}",
        q,
    )
    if m:
        return clamp_duration_sec(float(m.group(1)) * 60)

    # "90 seconds" / "90 sec" / "90s"
    m = re.search(
        r"\b(?:about|around|approx(?:imately)?|~)?\s*(\d+(?:\.\d+)?)\s*"
        r"(?:seconds?|secs?|s)\b",
        q,
    )
    if m:
        return clamp_duration_sec(float(m.group(1)))

    # compact "3min" / "3mints" without space
    m = re.search(rf"\b(\d+(?:\.\d+)?)\s*{_MIN_UNIT}", q)
    if m:
        return clamp_duration_sec(float(m.group(1)) * 60)

    return clamp_duration_sec(default)


def _prefer_flux_video_stills(duration_sec: int = 15) -> bool:
    """Free Mira path: turbo only (skip Flux) unless VERIDIQ_VIDEO_PREFER_FLUX=1.

    VERIDIQ_VIDEO_PREFER_GEMINI=1 skips Pollinations preference (Gemini-first).
    """
    import os

    _ = duration_sec
    flag = (os.getenv("VERIDIQ_VIDEO_PREFER_GEMINI") or "").strip().lower()
    if flag in ("1", "true", "yes", "on"):
        return False
    flux = (os.getenv("VERIDIQ_VIDEO_PREFER_FLUX") or "").strip().lower()
    if flux in ("1", "true", "yes", "on"):
        return True
    if flux in ("0", "false", "no", "off"):
        return False
    return False  # free video: turbo only


def _unique_still_cap(duration_sec: int) -> int:
    """Unique stills capped at 3 for any duration (long videos hold frames longer)."""
    _ = duration_sec
    return min(_VIDEO_MAX_STILLS, max(_VIDEO_MIN_STILLS, 3))


def _scene_count_for_duration(duration_sec: int) -> int:
    """Instant multi-shot template count (no LLM storyboard)."""
    return _unique_still_cap(duration_sec)


def _min_unique_stills_for_assemble(duration_sec: int, target: int) -> int:
    """Assemble with any usable still (≥1). Zero stills → caller errors."""
    _ = duration_sec, target
    return 1


def _wants_soundtrack(text: str) -> bool:
    return bool(text and _AUDIO_ON_VIDEO_RE.search(text))


def _wants_voice_narration(text: str) -> bool:
    q = (text or "").lower()
    return bool(re.search(r"\b(with\s+this\s+voice|narration|voiceover|voice\s+over)\b", q))


def _format_duration_label(sec: int | float) -> str:
    from veridiq.integrations.local_video import format_duration_label

    return format_duration_label(sec)


def _find_session_audio(
    history: Optional[list[dict[str, Any]]] = None,
    message: str = "",
) -> Optional[str]:
    """Resolve prior song/voice from history or URL in message (not random disk files)."""
    # Explicit URL / path in message
    for m in re.finditer(
        r"(https?://[^\s]+|/api/v1/veridiq/marketing/audio/file/[^\s]+|"
        r"marketing_out/audio/[^\s]+)",
        message or "",
        re.I,
    ):
        return m.group(1).rstrip(".,);]")

    for turn in reversed(history or []):
        for key in ("audio_url", "audio_path", "absolute_path"):
            val = turn.get(key)
            if val and (
                "audio" in str(val).lower()
                or str(val).endswith((".mp3", ".wav", ".m4a", ".aac"))
            ):
                return str(val)
        meta = turn.get("meta") or turn.get("action") or {}
        if isinstance(meta, dict):
            for key in ("audio_url", "audio_path"):
                val = meta.get(key) or (meta.get("song") or {}).get(key)
                if val:
                    return str(val)
    return None


def _keyword_intent(message: str) -> dict[str, Any]:
    q = (message or "").strip().lower()
    style = _detect_style_keyword(message)
    if not q:
        return {
            "intent": "help",
            "topic": "",
            "channel": "linkedin",
            "title": "",
            "feature_key": "truth_verification",
            "style": style,
            "reply": "Tell me what to post — e.g. create a LinkedIn post for VERIDIQ about truth verification.",
        }

    channel = "linkedin"
    for ch, keys in (
        ("telegram", ("telegram", "tg ")),
        ("instagram", ("instagram", "ig ", "reel")),
        ("x_twitter", ("twitter", "tweet", " x ")),
        ("threads", ("threads",)),
        ("whatsapp", ("whatsapp", "wa ")),
        ("linkedin", ("linkedin", "li ")),
    ):
        if any(k in q for k in keys):
            channel = ch
            break

    feature_key = "truth_verification"
    feature_map = {
        "workforce": "workforce_automation",
        "blockchain": "blockchain_attestation",
        "market": "market_intelligence",
        "comms": "comms_growth_automation",
        "growth": "comms_growth_automation",
        "evidence": "evidence_reporting",
        "report": "evidence_reporting",
        "truth": "truth_verification",
        "verify": "truth_verification",
    }
    for needle, key in feature_map.items():
        if needle in q:
            feature_key = key
            break

    if any(w in q for w in ("help", "what can", "commands", "capabilities")) and not (
        _looks_like_image_request(q) or _looks_like_song_request(q) or _looks_like_video_request(q)
    ):
        return {
            "intent": "help",
            "topic": "",
            "channel": channel,
            "title": "",
            "feature_key": feature_key,
            "style": style,
            "reply": (
                "I can generate real images (photo/cartoon/anime), free unlimited videos "
                "(cinematic multi-scene stills + local assemble), songs/lyrics+music, "
                "design posters, and social drafts — one command. Nothing posts live until you approve."
            ),
        }

    if _looks_like_song_request(q):
        return {
            "intent": "create_song",
            "topic": (message or "").strip()[:400],
            "channel": channel,
            "title": _extract_title(message) or "VERIDIQ song",
            "feature_key": feature_key,
            "style": style,
            "reply": "Writing lyrics and generating a music track.",
        }

    if _looks_like_video_request(q) or any(
        w in q for w in ("poori app", "full app", "demo reel", "short video", "generate video", "create video", "make video")
    ):
        from veridiq.integrations.pollinations_image import clean_user_prompt

        scene = clean_user_prompt(message) or (message or "").strip()
        title = _extract_title(message) or scene[:60] or "custom video"
        # Photo/real subject videos stay photoreal unless user asked cartoon/anime
        video_style = style if style in ("cartoon", "anime", "cgi", "cinematic") else (
            "cartoon" if any(w in q for w in ("cartoon", "anime", "pixar", "animated")) else "photo"
        )
        dur = parse_duration_sec(message)
        label = _format_duration_label(dur)
        scenes = _unique_still_cap(dur)
        return {
            "intent": "create_video",
            "topic": (message or "").strip()[:400],
            "channel": channel,
            "title": title,
            "feature_key": feature_key,
            "style": video_style,
            "duration_sec": dur,
            "reply": f"Generating {scenes} scenes for a {label} video of “{title}” ({video_style})…",
        }

    if _looks_like_image_request(q) or _looks_like_design_request(q) or any(
        w in q for w in ("cartoon", "anime")
    ):
        title = _extract_title(message) or "VERIDIQ visual"
        intent = "create_design" if _looks_like_design_request(q) else "create_image"
        topic = (message or "").strip()[:400] or "striking cinematic scene"
        return {
            "intent": intent,
            "topic": topic,
            "channel": channel,
            "title": title,
            "feature_key": feature_key,
            "style": style,
            "reply": f"Generating a real image for “{title}”.",
        }

    if any(
        w in q
        for w in (
            "post",
            "caption",
            "write",
            "draft",
            "create a post",
            "make a post",
            "social",
            "content",
        )
    ):
        return {
            "intent": "draft_post",
            "topic": (message or "").strip()[:400],
            "channel": channel,
            "title": "",
            "feature_key": feature_key,
            "style": style,
            "reply": f"Drafting a {channel} post for you.",
        }

    if any(w in q for w in ("hi", "hello", "hey", "namaste")):
        return {
            "intent": "chat",
            "topic": "",
            "channel": channel,
            "title": "",
            "feature_key": feature_key,
            "style": style,
            "reply": agent_persona()["greeting"],
        }

    return {
        "intent": "chat",
        "topic": (message or "").strip()[:400],
        "channel": channel,
        "title": "",
        "feature_key": feature_key,
        "style": style,
        "reply": "",
    }


def _extract_title(message: str) -> str:
    m = re.search(r"(?:titled|title|called|named)\s+[\"']?([^\"'\n.]{3,80})", message or "", re.I)
    if m:
        return m.group(1).strip()
    m2 = re.search(r"for\s+(.{3,60})$", (message or "").strip(), re.I)
    if m2 and "veridiq" not in m2.group(1).lower()[:8]:
        return m2.group(1).strip()[:80]
    # Prefer cleaned subject ("gym boy video" → "gym boy")
    try:
        from veridiq.integrations.pollinations_image import clean_user_prompt

        cleaned = clean_user_prompt(message or "")
        if cleaned and cleaned.lower() != (message or "").strip().lower():
            return cleaned[:80]
    except Exception:
        pass
    return ""


def _preserve_subject_topic(original: str, topic: str) -> str:
    """Keep gender/identity words from the user message if the LLM dropped them."""
    from veridiq.integrations.pollinations_image import clean_user_prompt, detect_subject_lock

    orig_lock = detect_subject_lock(original or "")
    topic_lock = detect_subject_lock(topic or "")
    cleaned = clean_user_prompt(original or "") or (original or "").strip()
    if not topic or len(topic.strip()) < 3:
        return cleaned[:400]
    # Gender mismatch or lost male/female cue → restore original cleaned scene
    if orig_lock.get("gender") and orig_lock.get("gender") != topic_lock.get("gender"):
        return cleaned[:400]
    identity_bits = ("boy", "girl", "man", "woman", "male", "female", "guy", "lady")
    orig_low = cleaned.lower()
    topic_low = (topic or "").lower()
    for bit in identity_bits:
        if re.search(rf"\b{bit}\b", orig_low) and not re.search(rf"\b{bit}\b", topic_low):
            return cleaned[:400]
    # Prefer user scene when LLM swapped in brand/office fluff
    if orig_lock.get("concrete") and (
        "veridiq logo" in topic_low or "wordmark" in topic_low or "office agents" in topic_low
    ):
        return cleaned[:400]
    return topic.strip()


def _extract_json_object(text: str) -> Optional[dict[str, Any]]:
    raw = (text or "").strip()
    if not raw:
        return None
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", raw)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            return None
    return None


def parse_intent(message: str) -> dict[str, Any]:
    fallback = _keyword_intent(message)
    q = (message or "").strip().lower()

    # HARD RULE: creative keyword hits never go to chat — skip LLM override risk
    creative_kw = fallback["intent"] in (
        "create_image",
        "create_design",
        "create_video",
        "create_song",
    )
    if creative_kw and (
        _looks_like_image_request(q)
        or _looks_like_song_request(q)
        or _looks_like_video_request(q)
        or _looks_like_design_request(q)
    ):
        return {**fallback, "parser": "keywords_forced", "llm": {"skipped": True, "reason": "creative_media"}}

    try:
        from veridiq.integrations import ai_gateway

        st = ai_gateway.status()
        if not st.get("configured"):
            return {**fallback, "parser": "keywords", "llm": {"configured": False}}

        prompt = f"{_SYSTEM_PROMPT}\n\nUser message:\n{(message or '').strip()[:1500]}\n\nJSON:"
        gen = ai_gateway.generate(prompt=prompt, task_type="fast", max_providers=3, max_tokens=800)
        if not gen.get("ok"):
            return {**fallback, "parser": "keywords", "llm": {"configured": True, "ok": False}}

        parsed = _extract_json_object(str(gen.get("text") or ""))
        if not parsed:
            return {**fallback, "parser": "keywords", "llm": {"configured": True, "ok": True, "status": "parse_failed"}}

        intent = str(parsed.get("intent") or "chat").strip().lower()
        if intent not in _VALID_INTENTS:
            intent = fallback["intent"]

        # Never let LLM demote media requests to chat/help
        if fallback["intent"] in (
            "create_image",
            "create_design",
            "create_video",
            "create_song",
        ) and intent in ("chat", "help"):
            intent = fallback["intent"]

        # Fuzzy image typos → force create_image even if LLM missed
        if intent in ("chat", "help") and _looks_like_image_request(q):
            intent = "create_design" if _looks_like_design_request(q) else "create_image"
        if intent in ("chat", "help") and _looks_like_song_request(q):
            intent = "create_song"
        if intent in ("chat", "help") and _looks_like_video_request(q):
            intent = "create_video"

        channel = str(parsed.get("channel") or fallback["channel"]).strip().lower() or "linkedin"
        if channel not in ("linkedin", "x_twitter", "instagram", "telegram", "threads", "whatsapp"):
            channel = fallback["channel"]
        topic = str(parsed.get("topic") or fallback.get("topic") or "").strip()[:400]
        # If LLM erased identity/subject words, restore from the original message
        topic = _preserve_subject_topic(message, topic)[:400]
        if intent in ("create_image", "create_design") and len(topic.strip()) < 3:
            topic = "striking cinematic scene"
        title = str(parsed.get("title") or fallback.get("title") or "").strip()[:120]
        feature_key = str(parsed.get("feature_key") or fallback.get("feature_key") or "truth_verification").strip()
        reply = str(parsed.get("reply") or fallback["reply"]).strip()[:4000]
        raw_style = str(parsed.get("style") or fallback.get("style") or "").strip().lower()
        if raw_style in ("photo", "cartoon", "anime", "cinematic", "cgi", "3d"):
            style = "cgi" if raw_style == "3d" else raw_style
        else:
            style = str(fallback.get("style") or _detect_style_keyword(message))
        return {
            "intent": intent,
            "topic": topic or fallback.get("topic") or "",
            "channel": channel,
            "title": title,
            "feature_key": feature_key,
            "style": style,
            "duration_sec": fallback.get("duration_sec") or parse_duration_sec(message),
            "reply": reply or fallback["reply"],
            "parser": "llm",
            "llm": {"configured": True, "ok": True, "provider_used": gen.get("provider_used")},
        }
    except Exception as exc:
        return {**fallback, "parser": "keywords", "llm": {"ok": False, "message": str(exc)[:200]}}


def _compose_post_body(*, topic: str, channel: str, feature_key: str) -> dict[str, Any]:
    from veridiq.marketing.content import (
        CORE_FEATURES,
        DEFAULT_PRODUCT_BRIEF,
        render_instagram_caption,
        render_linkedin_post,
        render_telegram_post,
        render_threads_post,
        render_tweet_variants,
    )

    feature = CORE_FEATURES.get(feature_key) or CORE_FEATURES["truth_verification"]
    brief = topic.strip() or f"Create a post highlighting {feature['title']}"
    subject = f"VERIDIQ — {feature['title']}"
    channel_hints = {
        "linkedin": "LinkedIn post (~120–220 words), professional but human, short paragraphs.",
        "x_twitter": "X/Twitter post under 280 characters, punchy hook, 1–3 hashtags max.",
        "instagram": "Instagram caption with hook + line breaks + soft CTA + hashtags.",
        "telegram": "Telegram community post, clear and educational, light emoji ok.",
        "threads": "Threads post, conversational, under ~500 chars preferred.",
        "whatsapp": "WhatsApp broadcast style — short, friendly, no heavy hashtags.",
    }
    hint = channel_hints.get(channel, channel_hints["linkedin"])

    prompt = (
        f"{_POST_SYSTEM}\n\n"
        f"Channel: {channel}\nFormat: {hint}\n"
        f"Feature focus: {feature['title']} — {feature['summary']}\n"
        f"Product brief: {DEFAULT_PRODUCT_BRIEF}\n"
        f"User request: {brief}\n\n"
        "Write the post now."
    )
    gen = _llm_generate(prompt, task_type="reason")
    body = (gen.get("text") or "").strip()
    provider = gen.get("provider")

    if not body:
        # Offline template fallback if every LLM fails
        try:
            if channel == "linkedin":
                body = render_linkedin_post(feature_key, DEFAULT_PRODUCT_BRIEF)
            elif channel == "x_twitter":
                variants = render_tweet_variants(feature_key, DEFAULT_PRODUCT_BRIEF, n=1)
                body = variants[0] if variants else ""
            elif channel == "instagram":
                body = render_instagram_caption(feature_key, DEFAULT_PRODUCT_BRIEF)
            elif channel in ("telegram", "whatsapp"):
                body = render_telegram_post(feature_key, DEFAULT_PRODUCT_BRIEF)
            elif channel == "threads":
                body = render_threads_post(feature_key, DEFAULT_PRODUCT_BRIEF)
        except Exception:
            body = ""
        if not body:
            tags = feature.get("hashtags") or "#VeriDiQ"
            body = f"{brief.strip()}\n\n{feature['summary']}\n\n{tags} #VeriDiQ"
        provider = provider or "template"

    # Strip accidental markdown fences
    if body.startswith("```"):
        body = re.sub(r"^```(?:\w+)?\s*", "", body)
        body = re.sub(r"\s*```$", "", body)

    return {
        "subject": subject,
        "body": body[:4000],
        "feature_key": feature_key,
        "channel": channel,
        "provider": provider,
        "model": gen.get("model"),
        "gemini_fallback_reason": gen.get("gemini_fallback_reason") or gen.get("message"),
    }


def _execute_draft_post(parsed: dict[str, Any]) -> dict[str, Any]:
    """Compose via studio LLM helpers, persist draft through Mira Creative Model."""
    from veridiq.postings import mira_model

    composed = _compose_post_body(
        topic=str(parsed.get("topic") or ""),
        channel=str(parsed.get("channel") or "linkedin"),
        feature_key=str(parsed.get("feature_key") or "truth_verification"),
    )
    return mira_model.generate(
        "create_post",
        topic=str(parsed.get("topic") or ""),
        composed=composed,
        created_by_agent=AGENT_TYPE,
    )


def _execute_create_image(
    parsed: dict[str, Any],
    *,
    attachments: Optional[list[str]] = None,
) -> dict[str, Any]:
    from veridiq.postings import mira_model

    title = (parsed.get("title") or "").strip() or "VERIDIQ image"
    return mira_model.generate(
        "create_image",
        topic=str(parsed.get("topic") or title),
        title=title,
        style=parsed.get("style"),
        attachments=list(attachments or parsed.get("attachments") or []),
    )


def _execute_create_design(parsed: dict[str, Any]) -> dict[str, Any]:
    """Generate a REAL social graphic image via Mira Creative Model."""
    from veridiq.postings import mira_model

    title = (parsed.get("title") or "").strip() or "VERIDIQ social design"
    return mira_model.generate(
        "create_design",
        topic=str(parsed.get("topic") or title),
        title=title,
        style=parsed.get("style") or "cartoon",
    )


def _execute_create_song(parsed: dict[str, Any]) -> dict[str, Any]:
    from veridiq.postings import mira_model

    topic = str(parsed.get("topic") or parsed.get("title") or "VERIDIQ")
    return mira_model.generate("create_song", topic=topic, title=parsed.get("title"))


def _custom_agent_video_board(topic: str, *, duration_sec: int | None = None) -> dict[str, Any]:
    """Multi-shot agents/office/workspace board — Gemini-quality 4-block prompts."""
    import uuid
    from datetime import datetime, timezone

    from veridiq.integrations.pollinations_image import clean_user_prompt
    from veridiq.postings.creative import build_cinematic_prompt

    if duration_sec is not None:
        from veridiq.integrations.local_video import clamp_duration_sec

        dur = clamp_duration_sec(duration_sec)
    else:
        dur = parse_duration_sec(topic)

    scene = clean_user_prompt(topic) or topic
    sid = str(uuid.uuid4())
    n = _scene_count_for_duration(dur)
    env = (
        "bright minimalist AI agents office, light wood desk, grey mesh ergonomic chair, "
        "curved ultrawide Agent Workspace dark-mode UI with green charts, sheer curtains and soft plant bokeh"
    )
    # Shot list — each beat uses the Gemini-quality 4-block formula
    beat_templates = [
        (
            "Headset ready",
            build_cinematic_prompt(
                "Professional woman agent at her Agent Workspace desk",
                "reaches for a black boom headset beside the curved ultrawide",
                env,
                "Photorealistic medium shot, eye-level, shallow depth of field with bokeh background, "
                "sharp foreground focus, smooth cinematic panning, volumetric lighting, soft studio illumination, rim light",
                dialogue="Welcome to your agents workspace.",
            ),
            "Welcome to your agents workspace.",
        ),
        (
            "Live on headset",
            build_cinematic_prompt(
                "Same professional woman agent wearing the boom headset",
                "speaking and gesturing at her desk, hands in motion",
                env + ", ultrawide dark-mode dashboard glowing behind her",
                "Photorealistic side-angle medium shot, eye-level, cinematic dolly, "
                "shallow depth of field, bokeh background, volumetric lighting, rim light, subsurface scattering",
                dialogue="Professional agents ready at every desk — headset on, dashboards live.",
            ),
            "Professional agents ready at every desk — headset on, dashboards live.",
        ),
        (
            "Over-shoulder ops",
            build_cinematic_prompt(
                "Agent typing at a curved ultrawide showing Performance and Incoming Chat Queue",
                "fingers moving across the keyboard, green line charts updating",
                env,
                "Cinematic over-the-shoulder medium shot, shallow depth of field, "
                "sharp foreground focus, smooth panning, volumetric lighting, ray-traced reflections on the screen glass",
                dialogue="Chat queues move in real time while performance stays in view.",
            ),
            "Chat queues move in real time while performance stays in view.",
        ),
        (
            "Face + Chat Queue",
            build_cinematic_prompt(
                "Medium close-up of the agent speaking toward camera",
                "subtle head movement, confident expression",
                "partial monitor shows Chat Queue with Available status and agent avatars, " + env,
                "Photorealistic close-up, eye-level, shallow depth of field with creamy bokeh background, "
                "sharp foreground focus, soft studio illumination, rim light, subsurface scattering",
                dialogue="Soft light, sharp focus, and real work happening now.",
            ),
            "Soft light, sharp focus, and real work happening now.",
        ),
        (
            "Agent Workspace UI",
            build_cinematic_prompt(
                "Sleek modern AI Agent Workspace screen with vibrant neon blue and green highlights",
                "UI panels animate gently, success checkmark appears",
                "side profile of agent at the desk, bright sheer curtains softly blurred",
                "Photorealistic close-up of the screen with cinematic panning, volumetric studio lighting, "
                "shallow depth of field with a blurred background, ray-traced reflections, hyper-detailed 4K render, 60fps fluid motion",
                dialogue="Your Agent Workspace is online — pick up, connect, and deliver.",
            ),
            "Your Agent Workspace is online — pick up, connect, and deliver.",
        ),
        (
            "Hero ready",
            build_cinematic_prompt(
                "Confident agent looking at camera beside the Agent Workspace monitor",
                "subtle confident smile, ready posture",
                env,
                "Hero medium shot, eye-level, cinematic dolly in, shallow depth of field, "
                "bokeh background, volumetric lighting, rim light, photorealistic textures",
                dialogue="VERIDIQ agents — ready when you are.",
            ),
            "VERIDIQ agents — ready when you are.",
        ),
        (
            "Standing collab",
            build_cinematic_prompt(
                "Two agents collaborating at a standing desk reviewing a laptop",
                "gesturing at the screen together",
                "same bright minimalist office, soft window light",
                "Wide establishing shot, eye-level, smooth panning, shallow depth of field, "
                "volumetric lighting, soft studio illumination",
                dialogue="Teams huddle fast — then get back to the queue.",
            ),
            "Teams huddle fast — then get back to the queue.",
        ),
        (
            "Ops wall",
            build_cinematic_prompt(
                "Glass-walled ops corner with live dashboard screens and agents reviewing metrics",
                "slow camera glide across the floor",
                "cinematic commercial office atmosphere",
                "Wide shot, slight low-angle, cinematic dolly, volumetric lighting, "
                "ray-traced reflections, hyper-detailed 4K render, 60fps fluid motion",
                dialogue="Live ops stay sharp across the floor.",
            ),
            "Live ops stay sharp across the floor.",
        ),
    ]
    beats = beat_templates[:n]
    per = max(2.0, dur / max(1, len(beats)))
    shots = []
    for i, (label, visual, vo) in enumerate(beats):
        shots.append(
            {
                "scene": i + 1,
                "duration_sec": round(per, 2),
                # No burned prompt / scene labels on frames — AI stills carry the look
                "on_screen_text": "",
                "shot": visual,
                "voiceover": vo,
            }
        )
    if shots:
        spent = sum(float(s["duration_sec"]) for s in shots[:-1])
        shots[-1]["duration_sec"] = round(max(2.0, dur - spent), 2)

    narration = (
        "Welcome to VERIDIQ — where truth meets intelligence. "
        "Our AI agents work together in a live workspace to verify claims, "
        "investigate signals, and deliver trusted reports. "
        "Truth. Verified. Empowered."
    )
    try:
        from veridiq.postings.creative import build_narration_script

        narration = build_narration_script(topic or "VERIDIQ agents workspace", duration_hint_sec=dur)
    except Exception:
        pass
    # Keep VO short even for 3-min videos (~30–45s bed, padded at mux)

    return {
        "storyboard_id": sid,
        "feature": "custom_user_video",
        "feature_title": "Custom agent video",
        "style": "agent_intro",
        "duration_sec": dur,
        "title": "VERIDIQ — Agents at work",
        "logline": (scene or topic)[:240],
        "script": narration,
        "narration_script": narration,
        "shot_list": shots,
        "call_to_action": "Open VERIDIQ Postings",
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


def _custom_subject_video_board(
    topic: str,
    *,
    long_form: bool = False,
    duration_sec: int | None = None,
) -> dict[str, Any]:
    """Fast subject-locked storyboard — every shot uses Veo 4-block prompt quality."""
    import uuid
    from datetime import datetime, timezone

    from veridiq.integrations.local_video import clamp_duration_sec
    from veridiq.integrations.pollinations_image import clean_user_prompt, detect_subject_lock
    from veridiq.postings.creative import (
        BRIGHT_LIGHTING,
        CAMERA_PHYSICS_ANCHOR,
        FRUIT_SUBJECT_ANCHOR,
        build_character_dialogue_script,
        build_cinematic_prompt,
        wants_character_dialogue,
    )

    if duration_sec is not None:
        dur = clamp_duration_sec(duration_sec)
    else:
        dur = parse_duration_sec(topic)
        if long_form and dur <= _DURATION_DEFAULT_SEC:
            dur = clamp_duration_sec(60)

    lock = detect_subject_lock(topic)
    scene = lock["scene"] or clean_user_prompt(topic) or topic
    primary = lock["primary_subject"] or scene
    is_fruit = bool(lock.get("is_fruit"))
    is_nonhuman = bool(lock.get("is_nonhuman"))
    talking = bool(lock.get("talking_characters") or wants_character_dialogue(topic))
    sid = str(uuid.uuid4())
    n = _scene_count_for_duration(dur)

    if is_fruit and talking:
        fruit_beats = (
            (
                "Apple close-up speaking",
                "close-up of cute anthropomorphic red Apple character with expressive face and mouth speaking",
                "I'm Apple — shiny, crisp, and ready to chat!",
            ),
            (
                "Banana close-up speaking",
                "close-up of cute anthropomorphic yellow Banana character with expressive face speaking",
                "I'm Banana — bright yellow, sweet, and a little silly!",
            ),
            (
                "Orange close-up speaking",
                "close-up of cute anthropomorphic Orange character with expressive face speaking",
                "I'm Orange — juicy, cheerful, and full of sunshine!",
            ),
            (
                "Apple wave finale",
                "Apple fruit character waving hello, bright studio, Pixar-quality",
                "Thanks for listening — stay colorful!",
            ),
            (
                "Banana tip bow",
                "Banana fruit character bowing politely, bright colorful kitchen set",
                "We love describing ourselves to friends!",
            ),
            (
                "Orange smile hold",
                "Orange fruit character smiling at camera, cheerful daylight kitchen",
                "Together we are talking fruits!",
            ),
        )
        all_beats = []
        for i, (label, action, line) in enumerate(fruit_beats):
            visual = build_cinematic_prompt(
                f"{FRUIT_SUBJECT_ANCHOR}: {action}",
                f"subtle speaking mouth motion beat: {scene}",
                "bright colorful cartoon set, cheerful fruit world, daylight studio",
                lighting=BRIGHT_LIGHTING,
                camera=f"Photorealistic close-up framing, eye-level. {CAMERA_PHYSICS_ANCHOR}",
                dialogue=line,
                fruit=True,
                bright=True,
            )
            all_beats.append((label, visual, line))
        beats = all_beats[:n]
        narration = build_character_dialogue_script(topic, duration_hint_sec=dur)
        per = max(2.0, dur / max(1, len(beats)))
        shots = [
            {
                "scene": i + 1,
                "duration_sec": round(per, 2),
                "on_screen_text": "",
                "shot": visual,
                "voiceover": line,
            }
            for i, (label, visual, line) in enumerate(beats)
        ]
        if shots:
            spent = sum(float(s["duration_sec"]) for s in shots[:-1])
            shots[-1]["duration_sec"] = round(max(2.0, dur - spent), 2)
        return {
            "storyboard_id": sid,
            "feature": "custom_subject_video",
            "feature_title": "Talking fruits",
            "style": "cartoon",
            "duration_sec": dur,
            "title": "Mira",
            "logline": scene[:240],
            "script": narration,
            "narration_script": narration,
            "shot_list": shots,
            "call_to_action": "",
            "primary_subject": primary[:200],
            "gender_lock": None,
            "is_fruit": True,
            "talking_characters": True,
            "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        }

    framing = (
        ("Wide establishing shot", "wide framing, eye-level", "slow cinematic dolly in"),
        ("Medium action", "medium shot, eye-level", "smooth cinematic panning across the subject"),
        ("Close-up detail", "close-up framing, eye-level", "subtle slow-motion 60fps fluid motion"),
        ("Dynamic angle", "medium shot, slight low-angle", "cinematic dolly circling the subject"),
        ("Environment context", "wide framing, bird's-eye", "smooth panning over the environment"),
        ("Hero finale", "medium hero shot, eye-level", "slow push-in cinematic dolly"),
        ("Side three-quarter", "medium shot, eye-level three-quarter", "smooth panning"),
        ("Final hold", "close-up framing, eye-level", "gentle hold with soft motion"),
        ("Action beat", "medium shot, eye-level", "dynamic motion, cinematic dolly"),
        ("Finale wide", "wide framing, eye-level", "smooth cinematic pull-back"),
    )
    env = (
        f"bright colorful environment for {scene}"
        if (is_fruit or is_nonhuman)
        else f"cinematic environment for {scene}"
    )
    all_beats = []
    for i, (label, cam, motion) in enumerate(framing):
        visual = build_cinematic_prompt(
            primary,
            f"{motion}: {scene}",
            env,
            f"Photorealistic {cam}, shallow depth of field with bokeh background, "
            f"sharp foreground focus. {CAMERA_PHYSICS_ANCHOR}",
            lighting=BRIGHT_LIGHTING if (is_fruit or is_nonhuman) else "",
            fruit=is_fruit,
            nonhuman=is_nonhuman,
            bright=bool(is_fruit or is_nonhuman),
        )
        all_beats.append((label, visual))
    beats = all_beats[:n]
    per = max(2.0, dur / max(1, len(beats)))

    from veridiq.postings.creative import build_narration_script, strip_scene_index_speakables

    if talking or is_fruit or is_nonhuman:
        narration = build_character_dialogue_script(topic, duration_hint_sec=dur)
    else:
        narration = build_narration_script(topic, duration_hint_sec=dur)
    narration = strip_scene_index_speakables(narration)

    # Split polished VO into per-shot lines (never "scene N")
    vo_chunks = [c.strip() for c in re.split(r"(?<=[.!?])\s+", narration) if c.strip()]
    if not vo_chunks:
        vo_chunks = [narration]
    while len(vo_chunks) < len(beats):
        vo_chunks.append(vo_chunks[-1])

    shots = [
        {
            "scene": i + 1,
            "duration_sec": round(per, 2),
            # Short designed label only — never raw prompt / scene index
            "on_screen_text": "",
            "shot": visual,
            "voiceover": vo_chunks[i][:200],
        }
        for i, (label, visual) in enumerate(beats)
    ]
    if shots:
        spent = sum(float(s["duration_sec"]) for s in shots[:-1])
        shots[-1]["duration_sec"] = round(max(2.0, dur - spent), 2)

    return {
        "storyboard_id": sid,
        "feature": "custom_subject_video",
        "feature_title": (primary[:40] if len(primary or "") <= 40 else "VERIDIQ"),
        "style": "cartoon" if (is_fruit or (is_nonhuman and talking)) else "subject_locked",
        "duration_sec": dur,
        "title": (primary[:40] if primary and len(primary) <= 40 and not re.search(
            r"\b(create|make|generate)\s+(a\s+)?(video|clip)\b", primary or "", re.I
        ) else "VERIDIQ"),
        "logline": scene[:240],
        "script": narration,
        "narration_script": narration,
        "shot_list": shots,
        "call_to_action": "",
        "primary_subject": primary[:200],
        "gender_lock": lock.get("gender"),
        "is_fruit": is_fruit,
        "talking_characters": talking,
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


def _prepare_video_audio(
    topic_raw: str,
    board: dict[str, Any],
    *,
    history: Optional[list[dict[str, Any]]] = None,
    force_narration: bool = False,
) -> tuple[Optional[str], str]:
    """Return (audio_path, note) when soundtrack/voice is wanted (or agents VO forced)."""
    if not force_narration and not _wants_soundtrack(topic_raw):
        return None, ""

    prior = _find_session_audio(history, topic_raw)
    if prior and not force_narration:
        return prior, "Using session/attached audio soundtrack."

    try:
        from veridiq.postings.creative import generate_song, generate_video_narration_audio

        dur = int(board.get("duration_sec") or _DURATION_DEFAULT_SEC)
        if force_narration or _wants_voice_narration(topic_raw):
            from veridiq.postings.creative import (
                build_narration_script,
                strip_scene_index_speakables,
            )

            script = str(
                board.get("narration_script")
                or board.get("script")
                or board.get("logline")
                or topic_raw
            )[:900]
            if re.search(r"\bscene\s*(?:one|two|three|\d+)\b|\[Scene\s*\d+\]", script, re.I):
                script = build_narration_script(topic_raw, duration_hint_sec=dur)
            script = strip_scene_index_speakables(script)[:900]
            narr = generate_video_narration_audio(script=script, duration_hint_sec=dur)
            if narr.get("ok") and narr.get("absolute_path"):
                return str(narr["absolute_path"]), (
                    f"{narr.get('message') or 'Neural narration attached'} "
                    "(duration aligned at mux; no facial lip-sync on stills)."
                )
            if force_narration:
                return None, f"Narration skipped: {narr.get('message') or 'unavailable'}"
        if force_narration:
            return None, "Narration unavailable."
        song = generate_song(
            topic=f"{str(board.get('title') or topic_raw)[:180]} [duration={dur}]"
        )
        ap = song.get("audio_path")
        if ap:
            from pathlib import Path

            root = Path(__file__).resolve().parent.parent.parent
            path = Path(ap)
            if not path.is_file():
                path = root / ap
            if path.is_file():
                return str(path), "Generated instrumental soundtrack for video."
            if song.get("audio_url"):
                name = Path(str(song["audio_url"])).name
                cand = root / "marketing_out" / "audio" / name
                if cand.is_file():
                    return str(cand), "Generated instrumental soundtrack for video."
    except Exception as exc:
        return None, f"Soundtrack skipped: {str(exc)[:80]}"
    return None, "Soundtrack requested but no audio file was produced."


def _collect_video_stills(
    prompts: list[str],
    *,
    style: str,
    prefix: str,
    base_seed: int,
    min_required: int = 4,
    width: int | None = None,
    height: int | None = None,
    duration_sec: int = 15,
) -> tuple[dict[int, dict], list[str]]:
    """Generate stills with hard 20s timeout; turbo for long, Flux for short ≤15s.

    Parallel workers=2 when allowed. Failed indices get one turbo retry.
    """
    import os
    import time
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from veridiq.postings.creative import generate_best_image

    flux_first = _prefer_flux_video_stills(duration_sec)
    os.environ["VERIDIQ_VIDEO_PREFER_FLUX"] = "1" if flux_first else "0"

    still_w = int(width or _VIDEO_STILL_W)
    still_h = int(height or _VIDEO_STILL_H)
    target = list(prompts)
    ordered: dict[int, dict] = {}
    workers = min(_VIDEO_STILL_WORKERS, max(1, len(target) or 1))

    def _one(i: int, pr: str, attempt: int, *, prefer_pol: bool) -> tuple[int, dict]:
        stem = f"{prefix}_{i}" if attempt == 0 else f"{prefix}_{i}_r{attempt}"
        return i, generate_best_image(
            prompt=pr,
            style=style,
            width=still_w,
            height=still_h,
            filename_stem=stem,
            seed=(base_seed + i * 17 + attempt * 97) % 2_147_483_647,
            timeout=_VIDEO_STILL_TIMEOUT,
            prefer_pollinations=prefer_pol,
            enhance=False,
            gemini_timeout=_VIDEO_STILL_GEMINI_TIMEOUT,
            max_attempts=2,
        )

    def _run_batch(indices: list[int], attempt: int, *, prefer_pol: bool) -> None:
        if not indices:
            return
        with ThreadPoolExecutor(max_workers=min(workers, len(indices))) as pool:
            # Sequential when workers=1 (Pollinations IP queue); small gap avoids 429 storms
            if workers <= 1:
                for i in indices:
                    if 0 <= i < len(target):
                        try:
                            idx, img = _one(i, target[i], attempt, prefer_pol=prefer_pol)
                            ordered[idx] = img
                        except Exception as exc:
                            ordered[i] = {"ok": False, "message": str(exc)[:160]}
                        time.sleep(0.6)
                return
            futs = {
                pool.submit(_one, i, target[i], attempt, prefer_pol=prefer_pol): i
                for i in indices
                if 0 <= i < len(target)
            }
            for fut in as_completed(futs):
                i = futs[fut]
                try:
                    idx, img = fut.result()
                    ordered[idx] = img
                except Exception as exc:
                    ordered[i] = {"ok": False, "message": str(exc)[:160]}

    def _ok_stills() -> list[str]:
        out: list[str] = []
        for i in range(len(target)):
            img = ordered.get(i) or {}
            if img.get("ok") and img.get("absolute_path"):
                out.append(str(img["absolute_path"]))
        return out

    def _failed_indices() -> list[int]:
        return [
            i
            for i in range(len(target))
            if not (ordered.get(i) or {}).get("ok")
            or not (ordered.get(i) or {}).get("absolute_path")
        ]

    # Pass 0: Flux-first (default) or Gemini-first when VERIDIQ_VIDEO_PREFER_GEMINI=1
    pending = list(range(len(target)))
    for start in range(0, len(pending), _VIDEO_STILL_WORKERS):
        _run_batch(
            pending[start : start + _VIDEO_STILL_WORKERS],
            0,
            prefer_pol=flux_first,
        )

    # Retries: always Flux-preferred for reliability
    max_passes = max(_VIDEO_STILL_RETRY_PASSES, 2 if flux_first else 3)
    for attempt in range(1, max_passes + 1):
        stills_now = _ok_stills()
        failed = _failed_indices()
        if not failed:
            break
        if len(stills_now) >= min_required and attempt > _VIDEO_STILL_RETRY_PASSES:
            if attempt > _VIDEO_STILL_RETRY_PASSES + 1:
                break
        for start in range(0, len(failed), _VIDEO_STILL_WORKERS):
            _run_batch(
                failed[start : start + _VIDEO_STILL_WORKERS],
                attempt,
                prefer_pol=True,
            )

    return ordered, _ok_stills()


def _veo_clip_plan(duration_sec: int) -> list[int]:
    """Split target length into 4–8s Veo clip durations (2–4 clips for ~15s)."""
    d = max(4, int(duration_sec or 15))
    # Cap Veo stitch at ~32s (4×8) — longer stays on stills fallback after a Veo attempt
    if d <= 8:
        return [max(4, min(8, d))]
    if d <= 12:
        return [6, 6]
    if d <= 16:
        return [5, 5, 5]
    if d <= 24:
        return [8, 8, 8]
    return [8, 8, 8, 8]


def _try_gemini_veo_video(
    *,
    prompts: list[str],
    duration_sec: int,
    filename_stem: str,
    audio_path: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Optional paid Veo path — locked until Mira premium + VERIDIQ_GEMINI_VIDEO=1.

    Requires ``VERIDIQ_MIRA_TIER=premium`` AND Veo flag (see tiers.is_premium).
    Generates 1–4 short clips (4–8s) and concatenates with ffmpeg for ~15s+.
    Returns None when premium/Veo is disabled (normal free-path default).
    """
    try:
        from veridiq.integrations.llm import google_ai
        from veridiq.postings import tiers

        # Free tier never uses Veo even if VERIDIQ_GEMINI_VIDEO=1 alone
        if not tiers.premium_video_unlocked():
            return None
        if not google_ai.veo_enabled():
            return None
        if not hasattr(google_ai, "generate_video"):
            return {
                "ok": False,
                "status": "error",
                "message": "Veo generate_video missing from google_ai module.",
                "provider": "google_ai_veo",
            }
    except Exception as exc:
        return {
            "ok": False,
            "status": "error",
            "message": f"Veo unavailable: {str(exc)[:160]}",
            "provider": "google_ai_veo",
        }

    clip_durs = _veo_clip_plan(duration_sec)
    # Multi-minute: still try a short Veo sample then caller may fall back — but for
    # >32s we attempt 4 clips and note shortfall rather than skipping Veo entirely.
    prompt_list = [p for p in (prompts or []) if (p or "").strip()]
    if not prompt_list:
        from veridiq.postings.creative import build_cinematic_prompt

        prompt_list = [build_cinematic_prompt("cinematic VERIDIQ scene", "smooth motion")]

    segment_paths: list[str] = []
    used_models: list[str] = []
    last_err = "Veo produced no clips"
    for i, clip_dur in enumerate(clip_durs):
        pr = prompt_list[i % len(prompt_list)]
        try:
            result = google_ai.generate_video(
                prompt=pr,
                duration_sec=clip_dur,
                filename_stem=f"{filename_stem}_c{i}",
                max_wait_sec=240.0,
            )
        except Exception as exc:
            last_err = str(exc)[:200]
            break
        if isinstance(result, dict) and result.get("ok") and result.get("absolute_path"):
            segment_paths.append(str(result["absolute_path"]))
            if result.get("model"):
                used_models.append(str(result["model"]))
        else:
            last_err = (result or {}).get("message") if isinstance(result, dict) else last_err
            # If first clip fails hard, abort; if later clips fail, concat what we have
            if not segment_paths:
                return {
                    "ok": False,
                    "status": "error",
                    "message": str(last_err or "Veo failed")[:240],
                    "provider": "google_ai_veo",
                    "api_response_status": (result or {}).get("api_response_status") if isinstance(result, dict) else None,
                }
            break

    if not segment_paths:
        return {
            "ok": False,
            "status": "error",
            "message": str(last_err or "Veo returned no video")[:240],
            "provider": "google_ai_veo",
        }

    from veridiq.integrations import local_video

    if len(segment_paths) == 1 and not audio_path:
        from pathlib import Path

        path = Path(segment_paths[0])
        try:
            rel = str(path.relative_to(Path(__file__).resolve().parent.parent.parent)).replace("\\", "/")
        except ValueError:
            rel = str(path).replace("\\", "/")
        return {
            "ok": True,
            "status": "ok",
            "provider": "google_ai_veo",
            "model": used_models[0] if used_models else "veo",
            "format": "mp4",
            "duration_sec": clip_durs[0],
            "video_path": rel,
            "video_url": f"/api/v1/veridiq/marketing/video/file/{path.name}",
            "absolute_path": str(path),
            "bytes": path.stat().st_size,
            "segments": 1,
            "veo_motion": True,
            "message": f"Veo video ready ({path.stat().st_size // 1024} KB).",
        }

    concat = local_video.concat_video_segments(
        segment_paths,
        filename_stem=filename_stem,
        audio_path=audio_path,
    )
    if concat.get("ok"):
        concat["model"] = used_models[0] if used_models else "veo"
        concat["veo_motion"] = True
        return concat
    # Single segment salvage if concat failed
    if len(segment_paths) >= 1:
        from pathlib import Path

        path = Path(segment_paths[0])
        return {
            "ok": True,
            "status": "ok",
            "provider": "google_ai_veo",
            "model": used_models[0] if used_models else "veo",
            "format": "mp4",
            "duration_sec": clip_durs[0],
            "video_path": str(path).replace("\\", "/"),
            "video_url": f"/api/v1/veridiq/marketing/video/file/{path.name}",
            "absolute_path": str(path),
            "bytes": path.stat().st_size if path.is_file() else 0,
            "segments": 1,
            "veo_motion": True,
            "message": (
                f"Veo clip ready; concat note: {concat.get('message') or 'n/a'} "
                f"({path.stat().st_size // 1024 if path.is_file() else 0} KB)."
            ),
        }
    return {
        "ok": False,
        "status": "error",
        "message": str(concat.get("message") or last_err)[:240],
        "provider": "google_ai_veo",
    }

def _execute_create_video(
    parsed: dict[str, Any],
    *,
    history: Optional[list[dict[str, Any]]] = None,
    attachments: Optional[list[str]] = None,
) -> dict[str, Any]:
    from veridiq.integrations import local_video
    from veridiq.integrations.local_video import clamp_duration_sec
    from veridiq.marketing import generate_product_tour_storyboard, render_storyboard

    topic_raw = str(parsed.get("topic") or "")
    attach_refs = list(attachments or parsed.get("attachments") or [])
    from veridiq.integrations.pollinations_image import expand_user_typos

    topic_raw = expand_user_typos(topic_raw)
    topic = topic_raw.lower()
    title = str(parsed.get("title") or "").lower()
    full_markers = (
        "full app",
        "whole app",
        "entire",
        "poori",
        "puri app",
        "platform tour",
        "product demo",
        "product tour",
        "complete app",
        "all pages",
        "whole platform",
        "full platform",
        "demo reel",
        "meri app",
        "my app",
    )
    agent_markers = (
        "agent",
        "agents",
        "desk",
        "office",
        "workspace",
        "workstation",
        "team",
        "standup",
        "huddle",
    )
    # Pronouns alone ("describing themselves") must NOT route to office agents —
    # that was turning talking fruits into dark human silhouettes.
    want_full = any(m in topic or m in title for m in full_markers)
    want_agents = any(m in topic for m in agent_markers) and not want_full
    long_form = any(w in topic for w in ("long", "longer", "extended", "full length"))

    if parsed.get("duration_sec") is not None:
        duration_sec = clamp_duration_sec(parsed.get("duration_sec"))
    else:
        duration_sec = parse_duration_sec(topic_raw)
    if long_form and duration_sec <= _DURATION_DEFAULT_SEC:
        duration_sec = clamp_duration_sec(60)

    from veridiq.integrations.pollinations_image import detect_subject_lock

    lock = detect_subject_lock(topic_raw)
    # Never use agent office board for fruits / non-human talking characters
    if want_agents and (
        lock.get("concrete")
        or lock.get("is_fruit")
        or lock.get("is_nonhuman")
        or lock.get("talking_characters")
    ):
        # Keep agents only when user explicitly asked for agents/office AND not fruit/object
        if lock.get("is_fruit") or lock.get("is_nonhuman") or lock.get("talking_characters"):
            want_agents = False
        elif lock.get("gender"):
            want_agents = False
        elif lock.get("concrete") and not any(
            m in topic for m in ("agent", "agents", "office", "workspace", "desk")
        ):
            want_agents = False

    if want_agents:
        board = _custom_agent_video_board(topic_raw, duration_sec=duration_sec)
        tour = "agent_custom"
    elif want_full:
        board = generate_product_tour_storyboard(duration_sec=max(45, min(180, duration_sec)))
        tour = "full_product"
    else:
        board = _custom_subject_video_board(topic_raw, long_form=long_form, duration_sec=duration_sec)
        tour = "subject_custom"

    board["duration_sec"] = int(board.get("duration_sec") or duration_sec)
    duration_sec = int(board["duration_sec"])
    aspect = detect_video_aspect(topic_raw)
    board["aspect"] = aspect
    board["aspect_ratio"] = aspect
    still_w, still_h = (_VIDEO_STILL_H, _VIDEO_STILL_W) if aspect == "9:16" else (_VIDEO_STILL_W, _VIDEO_STILL_H)

    shots = [s for s in (board.get("shot_list") or []) if isinstance(s, dict)]
    from veridiq.postings.creative import build_cinematic_prompt, detect_style

    style = str(parsed.get("style") or detect_style(topic_raw))
    if lock.get("is_fruit") or board.get("is_fruit") or board.get("talking_characters"):
        if style not in ("cartoon", "anime", "cgi"):
            style = "cartoon"
    if tour == "agent_custom" and style not in ("cartoon", "anime", "cgi"):
        style = "cinematic"
    max_stills = _unique_still_cap(duration_sec)
    min_stills = _min_unique_stills_for_assemble(duration_sec, max_stills)
    prompts: list[str] = []
    primary = str(board.get("primary_subject") or lock.get("primary_subject") or lock.get("scene") or topic_raw)
    fruitish = bool(lock.get("is_fruit") or board.get("is_fruit"))
    nonhumanish = bool(lock.get("is_nonhuman") or fruitish)

    if tour == "agent_custom":
        # Board shots already carry full cinematic 4-block prompts
        for shot in shots[:max_stills]:
            visual = str(shot.get("shot") or shot.get("on_screen_text") or primary)
            prompts.append(visual[:2000])
    else:
        for shot in shots[:max_stills]:
            visual = str(shot.get("shot") or shot.get("on_screen_text") or primary)
            # If board already used build_cinematic_prompt, keep it; else wrap
            if "anthropomorphic fruit" in visual.lower() or (
                "volumetric" in visual.lower() and "hyper-detailed" in visual.lower()
            ):
                prompts.append(visual[:2000])
            else:
                if primary and not visual.lower().startswith(primary.lower()[: min(12, len(primary))]):
                    visual = f"{primary}. {visual}"
                prompts.append(
                    build_cinematic_prompt(
                        primary,
                        visual[:220],
                        f"bright colorful environment for {primary}" if fruitish else f"cinematic environment for {primary}",
                        dialogue=str(shot.get("voiceover") or "")[:200] or None,
                        fruit=fruitish,
                        nonhuman=nonhumanish,
                        bright=fruitish or nonhumanish,
                    )[:2000]
                )

    # Pad to still_cap with varied cinematic angles if board was short
    pad_angles = (
        ("Wide establishing shot", "wide framing, eye-level", "slow cinematic dolly in"),
        ("Medium action shot", "medium shot, eye-level", "smooth cinematic panning"),
        ("Close-up detail", "close-up framing, eye-level", "subtle slow-motion 60fps fluid motion"),
        ("Dynamic camera angle", "medium shot, slight low-angle", "cinematic dolly"),
        ("Environment context", "wide framing, bird's-eye", "smooth panning"),
        ("Hero finale frame", "medium hero shot, eye-level", "slow push-in"),
        ("Side three-quarter", "medium shot, eye-level", "smooth panning"),
        ("Overhead establishing", "wide framing, bird's-eye", "gentle orbit"),
        ("Collaboration beat", "medium shot, eye-level", "cinematic dolly"),
        ("Final hold", "close-up framing, eye-level", "soft hold with ambient motion"),
    )
    while len(prompts) < max_stills and primary:
        idx = len(prompts)
        label, cam, motion = pad_angles[idx % len(pad_angles)]
        prompts.append(
            build_cinematic_prompt(
                primary,
                f"{motion}: {primary}",
                f"bright colorful set — {label}" if fruitish else f"cinematic environment — {label}",
                f"Photorealistic {cam}, shallow depth of field with bokeh background, "
                "sharp foreground focus, volumetric lighting, soft studio illumination, rim light",
                fruit=fruitish,
                nonhuman=nonhumanish,
                bright=fruitish or nonhumanish,
            )[:2000]
        )

    prefix = f"vid_{(board.get('storyboard_id') or 'x')[:8]}"
    from concurrent.futures import ThreadPoolExecutor

    # --- Mira Creative Model FIRST (free pipeline; not Veo) ---
    # Honest: Mira is VERIDIQ's branded free pipeline, not a trained Veo-scale model.
    from veridiq.postings import mira_engine, mira_model
    from veridiq.postings.creative import build_character_dialogue_script, build_narration_script, strip_scene_index_speakables
    from veridiq.postings.local_stills import is_fruit_topic as _is_fruit_topic

    fruit_local = bool(fruitish or lock.get("is_fruit") or _is_fruit_topic(topic_raw))
    if fruit_local:
        board["is_fruit"] = True
        board["talking_characters"] = True
        board["local_talking_fruits"] = True
        # Never feed Pollinations prompts for fruit — mira_engine skips AI anyway
        prompts = []

    # ALWAYS mux edge-tts VO for create_video (user requirement)
    want_narration = True
    existing = str(board.get("narration_script") or "")
    if not existing or re.search(r"\bscene\s*(?:one|two|three|\d+)\b|\[Scene\s*\d+\]", existing, re.I):
        vo_hint = 40 if duration_sec >= 60 else min(45, duration_sec)
        try:
            if fruit_local or lock.get("talking_characters"):
                board["narration_script"] = build_character_dialogue_script(
                    topic_raw, duration_hint_sec=vo_hint
                )[:550]
            else:
                board["narration_script"] = build_narration_script(
                    topic_raw, duration_hint_sec=vo_hint
                )[:550]
        except Exception:
            board["narration_script"] = build_character_dialogue_script(
                topic_raw, duration_hint_sec=vo_hint
            )[:550]
    elif duration_sec >= 60:
        # Don't TTS a 3-min essay — keep short VO bed
        board["narration_script"] = str(board["narration_script"])[:550]
    board["narration_script"] = strip_scene_index_speakables(
        str(board.get("narration_script") or "")
    )[:550]

    audio_future = None
    audio_pool = ThreadPoolExecutor(max_workers=1) if want_narration else None
    session_audio = None
    if audio_pool is not None:
        # Prefer session/attached audio when present; else Mira edge-tts
        audio_future = audio_pool.submit(
            _prepare_video_audio,
            topic_raw,
            board,
            history=history,
            force_narration=True,
        )

    pre_audio_path: Optional[str] = None
    pre_audio_note = ""
    # Do NOT wait up to 90s for VO before stills — brief head-start only;
    # Mira generates VO in parallel with stills when audio isn't ready yet.
    if audio_future is not None:
        try:
            pre_audio_path, pre_audio_note = audio_future.result(timeout=2.0)
        except Exception:
            pre_audio_path, pre_audio_note = None, "Narration runs in parallel with stills."
        finally:
            if audio_pool is not None:
                audio_pool.shutdown(wait=False)
        session_audio = pre_audio_path

    # Pass the USER topic (not rewritten primary) so fruit detection never misses
    mira_topic = topic_raw if fruit_local else str(primary or topic_raw or "cinematic scene")
    mira = mira_model.generate(
        "create_video",
        topic=mira_topic,
        duration_sec=duration_sec,
        aspect=aspect,
        prompts=[] if fruit_local else prompts[:max_stills],
        style=style,
        storyboard=board,
        audio_path=session_audio,
        force_narration=True,
        n_stills=max_stills,
        attachments=attach_refs,
    )

    if isinstance(mira, dict) and mira.get("ok"):
        render = mira.get("render") if isinstance(mira.get("render"), dict) else {}
        actual = mira.get("duration_sec") or duration_sec
        label = _format_duration_label(actual)
        n_stills = int(mira.get("stills_count") or 0)
        sep_audio = mira.get("audio_url") or render.get("audio_url")
        has_audio = bool(
            mira.get("has_audio")
            or render.get("has_audio")
            or (session_audio and render.get("ok"))
        )
        out_w = 1080 if aspect == "9:16" else _VIDEO_OUT_W
        out_h = 1920 if aspect == "9:16" else _VIDEO_OUT_H
        msg = mira.get("message") or mira_engine.RENDER_MESSAGE
        if pre_audio_note and pre_audio_note not in str(msg):
            msg = f"{msg} — {pre_audio_note}"
        # Prefer VO; allow silent MP4 with clear message (local stills still succeed)
        if not has_audio and not sep_audio:
            msg = (
                f"VIDEO READY (silent — edge-tts/mux unavailable). {msg} "
                "Re-try for voiceover; install ffmpeg if mux unavailable."
            )
            # Still return ok so free path always delivers an MP4
        elif not has_audio and sep_audio:
            msg = (
                f"AUDIO NOT MUXED INTO MP4 — play video + audio separately ({sep_audio}). {msg}"
            )
            # Still ok with separate audio_url, but has_audio stays false
        return {
            "action": "create_video",
            "status": "ok",
            "ok": True,
            "storyboard": mira.get("storyboard") or board,
            "render": render,
            "stills_count": n_stills,
            "max_stills": max_stills,
            "min_stills": min_stills,
            "duration_sec": actual,
            "duration_label": label,
            "style": style,
            "tour": tour,
            "primary_subject": primary[:200],
            "gender_lock": lock.get("gender") or board.get("gender_lock"),
            "audio_url": sep_audio,
            "has_audio": bool(has_audio),
            "mira_engine": True,
            "free_unlimited": True,
            "paid_veo": False,
            "engine": mira_engine.ENGINE_NAME,
            "provider": (
                "local_talking_fruits"
                if fruit_local
                else (mira.get("provider") or mira_engine.ENGINE_ID)
            ),
            "quality": mira.get("quality")
            or {
                "width": out_w,
                "height": out_h,
                "fps": _VIDEO_OUT_FPS,
                "aspect": aspect,
                "label": f"1080p · 30fps · Mira · {aspect}",
                "veo_motion": False,
                "lip_sync": False,
                "free_unlimited": True,
                "paid_veo": False,
                "mira_engine": True,
            },
            "message": msg,
            "links": {"postings": "/dashboard/postings", "marketing": "/dashboard/marketing"},
            "identity": mira.get("identity") or mira_engine.engine_identity(),
            "video_url": render.get("video_url"),
            "local_talking_fruits": bool(mira.get("local_talking_fruits") or fruit_local),
            "pollinations_calls": 0 if fruit_local else mira.get("pollinations_calls"),
            "local_stills": mira.get("local_stills"),
        }

    mira_fail_note = ""
    if isinstance(mira, dict) and not mira.get("ok"):
        mira_fail_note = str(mira.get("message") or "Mira engine could not finish keyframes")[:200]

    # Optional paid Veo ONLY when Mira failed AND premium unlocked.
    # Free path must NOT re-run Pollinations stills (doubles wall clock past browser patience).
    veo_audio_path = session_audio
    veo = _try_gemini_veo_video(
        prompts=prompts[: max(1, len(_veo_clip_plan(duration_sec)))],
        duration_sec=duration_sec,
        filename_stem=prefix,
        audio_path=None,
    )
    if isinstance(veo, dict) and veo.get("ok") and (veo.get("video_url") or veo.get("absolute_path")):
        audio_note = pre_audio_note or ""
        if veo_audio_path and veo.get("absolute_path"):
            try:
                from pathlib import Path

                from veridiq.integrations import local_video

                mux = local_video._maybe_mux_audio(
                    Path(str(veo["absolute_path"])),
                    veo_audio_path,
                    prefix,
                )
                if mux.get("path"):
                    path = mux["path"]
                    veo["absolute_path"] = str(path)
                    veo["video_url"] = f"/api/v1/veridiq/marketing/video/file/{path.name}"
                    if mux.get("muxed"):
                        veo["has_audio"] = True
                    elif mux.get("audio_url"):
                        veo["audio_url"] = mux["audio_url"]
                    if mux.get("message"):
                        audio_note = mux["message"]
            except Exception:
                pass

        label = _format_duration_label(veo.get("duration_sec") or duration_sec)
        segs = veo.get("segments") or len(_veo_clip_plan(duration_sec))
        return {
            "action": "create_video",
            "status": "ok",
            "ok": True,
            "storyboard": board,
            "render": veo,
            "stills_count": 0,
            "max_stills": max_stills,
            "duration_sec": veo.get("duration_sec") or duration_sec,
            "duration_label": label,
            "style": style,
            "tour": tour,
            "primary_subject": primary[:200],
            "gender_lock": lock.get("gender") or board.get("gender_lock"),
            "mira_engine": False,
            "free_unlimited": False,
            "paid_veo": True,
            "quality": {
                "width": veo.get("width") or _VIDEO_OUT_W,
                "height": veo.get("height") or _VIDEO_OUT_H,
                "fps": veo.get("fps") or _VIDEO_OUT_FPS,
                "label": "1080p · Veo native",
                "veo_motion": True,
                "lip_sync": False,
                "mira_engine": False,
                "paid_veo": True,
            },
            "message": (
                f'{label} Veo video of "{primary[:60]}" ready — '
                f"native Gemini Veo ({segs} clip(s), {veo.get('model') or 'veo-3.1'}). "
                f"(Mira note: {mira_fail_note or 'n/a'}) {audio_note or ''}"
            ).strip(),
            "links": {"postings": "/dashboard/postings", "marketing": "/dashboard/marketing"},
            "provider": "google_ai_veo",
            "video_url": veo.get("video_url"),
        }

    # Free Mira only — surface Mira's error; never hang on a second still round
    n_fail = int((mira or {}).get("stills_count") or 0) if isinstance(mira, dict) else 0
    label = _format_duration_label(duration_sec)
    msg = mira_fail_note or (
        f"Mira could not finish the {label} video. Retry — free path only (no Veo)."
    )
    return {
        "action": "create_video",
        "status": "error",
        "ok": False,
        "storyboard": board,
        "render": {
            "ok": False,
            "status": "error",
            "message": msg,
        },
        "stills_count": n_fail,
        "max_stills": max_stills,
        "min_stills": min_stills,
        "duration_sec": duration_sec,
        "duration_label": label,
        "style": style,
        "tour": tour,
        "primary_subject": primary[:200],
        "gender_lock": lock.get("gender") or board.get("gender_lock"),
        "mira_engine": True,
        "free_unlimited": True,
        "paid_veo": False,
        "message": msg,
        "links": {"postings": "/dashboard/postings", "marketing": "/dashboard/marketing"},
        "keyframe_meta": (mira or {}).get("keyframe_meta") if isinstance(mira, dict) else None,
    }


def _execute_chat(message: str, history: Optional[list[dict[str, str]]] = None) -> dict[str, Any]:
    hist_bits = ""
    for turn in (history or [])[-6:]:
        role = turn.get("role") or "user"
        text = (turn.get("text") or "")[:400]
        hist_bits += f"{role}: {text}\n"
    prompt = f"{_CHAT_SYSTEM}\n\nRecent turns:\n{hist_bits}\nUser: {(message or '').strip()[:1500]}\n\nAssistant:"
    gen = _llm_generate(prompt, task_type="reason")
    if gen.get("ok") and gen.get("text"):
        return {
            "action": "chat",
            "status": "ok",
            "message": str(gen["text"]).strip()[:4000],
            "provider": gen.get("provider"),
            "llm": {"provider_used": gen.get("provider"), "model": gen.get("model")},
        }
    return {
        "action": "chat",
        "status": "ok",
        "message": (
            agent_persona()["greeting"]
            + " Say “create a post for VERIDIQ …” and I’ll draft one. "
            + (f"(LLM note: {gen.get('message')})" if gen.get("message") else "")
        ),
        "provider": gen.get("provider"),
    }


def handle_command(
    message: str,
    *,
    history: Optional[list[dict[str, str]]] = None,
    _force_sync_video: bool = False,
    _parsed_override: Optional[dict[str, Any]] = None,
    async_video: bool = False,
    attachments: Optional[list[str]] = None,
    chat_id: Optional[str] = None,
) -> dict[str, Any]:
    """Run a Postings Studio command.

    When ``async_video`` is True and intent is create_video, enqueue a background
    job and return ``{status: started, job_id}`` immediately (HTTP path).
    Workers call with ``_force_sync_video=True`` so create_video runs in-thread.
    ``attachments`` are user-uploaded image refs (filenames / upload URLs).
    ``chat_id`` is forwarded to the video job so completion can persist media.
    """
    attach_refs = [str(a).strip() for a in (attachments or []) if str(a).strip()]
    chat_ref = str(chat_id or "").strip() or None
    parsed = dict(_parsed_override) if isinstance(_parsed_override, dict) else parse_intent(message)
    if attach_refs:
        parsed = {**parsed, "attachments": attach_refs}
    intent = parsed.get("intent") or "chat"
    reply = parsed.get("reply") or ""
    q = (message or "").lower()

    # Promote chat → create_video early so async kickoff can return <1s
    if intent in ("chat", "help") and _looks_like_video_request(q):
        intent = "create_video"
        parsed = {**parsed, "intent": "create_video", "topic": parsed.get("topic") or message}
    # Uploads with image-ish (or bare) prompts default to create_image;
    # explicit video words still win via the branch above.
    elif intent in ("chat", "help") and attach_refs:
        if _looks_like_video_request(q):
            intent = "create_video"
            parsed = {**parsed, "intent": "create_video", "topic": parsed.get("topic") or message}
        else:
            intent = "create_image"
            parsed = {
                **parsed,
                "intent": "create_image",
                "topic": parsed.get("topic") or message or "uploaded image",
            }

    if async_video and not _force_sync_video and intent == "create_video":
        from veridiq.postings.video_jobs import start_video_job

        job_id = start_video_job(
            message=message,
            history=list(history or []),
            parsed=parsed,
            attachments=attach_refs,
            chat_id=chat_ref,
        )
        dur = parsed.get("duration_sec") or parse_duration_sec(message)
        label = _format_duration_label(dur)
        start_msg = (
            f"Starting {label} Mira video - generating up to 3 scenes in the background. "
            "This usually takes about a minute."
        )
        action = {
            "action": "create_video",
            "status": "started",
            "ok": True,
            "job_id": job_id,
            "duration_sec": dur,
            "message": start_msg,
        }
        out = {
            "ok": True,
            "status": "started",
            "job_id": job_id,
            "intent": "create_video",
            "reply": start_msg,
            "action": action,
            "parser": parsed.get("parser"),
            "llm": parsed.get("llm"),
            "agent": agent_persona(),
            "at": _utc_now(),
        }
        if chat_ref:
            out["chat_id"] = chat_ref
        return out

    if intent == "help":
        action = {
            "action": "help",
            "status": "ok",
            "message": reply
            or (
                "I generate real images, songs, draft posts, and free unlimited videos via "
                "Mira Creative Model (Free) — not Google Veo. Premium native video is optional later. "
                "Nothing publishes until you approve."
            ),
        }
    elif intent == "draft_post":
        action = _execute_draft_post(parsed)
        if not reply:
            reply = action.get("message") or "Draft ready."
    elif intent == "create_image":
        action = _execute_create_image(parsed, attachments=attach_refs)
        reply = action.get("message") or reply or "Image ready."
    elif intent == "create_design":
        action = _execute_create_design(parsed)
        reply = action.get("message") or reply or "Design image ready."
    elif intent == "create_video":
        action = _execute_create_video(parsed, history=history, attachments=attach_refs)
        reply = action.get("message") or reply or "Video ready."
    elif intent == "create_song":
        action = _execute_create_song(parsed)
        reply = action.get("message") or reply or "Song ready."
    else:
        # Safety: if chat but message clearly wants media, force the right create_* path
        if _looks_like_song_request(q):
            action = _execute_create_song({**parsed, "topic": message, "title": "VERIDIQ song"})
            intent = "create_song"
            reply = action.get("message") or "Song ready."
        elif attach_refs and _looks_like_video_request(q):
            action = _execute_create_video(
                {**parsed, "topic": message}, history=history, attachments=attach_refs
            )
            intent = "create_video"
            reply = action.get("message") or "Video ready."
        elif attach_refs or _looks_like_image_request(q) or _looks_like_design_request(q):
            if _looks_like_design_request(q) and not attach_refs:
                action = _execute_create_design({**parsed, "topic": message, "title": "VERIDIQ design"})
                intent = "create_design"
            else:
                action = _execute_create_image(
                    {**parsed, "topic": message or "striking cinematic scene", "title": "VERIDIQ image"},
                    attachments=attach_refs,
                )
                intent = "create_image"
            reply = action.get("message") or "Image ready."
        elif _looks_like_video_request(q):
            action = _execute_create_video(
                {**parsed, "topic": message}, history=history, attachments=attach_refs
            )
            intent = "create_video"
            reply = action.get("message") or "Video ready."
        else:
            action = _execute_chat(message, history=history)
            # Never surface ChatGPT-style image refusals — regenerate via tools instead
            refuse = re.search(
                r"can'?t generate (images?|pictures?|photos?)|unable to (generate|create) (images?|pictures?)",
                str(action.get("message") or ""),
                re.I,
            )
            if refuse:
                action = _execute_create_image(
                    {**parsed, "topic": message or "striking cinematic scene", "title": "VERIDIQ image"},
                    attachments=attach_refs,
                )
                intent = "create_image"
                reply = action.get("message") or "Image ready."
            else:
                reply = action.get("message") or reply or agent_persona()["greeting"]

    # Prefer action message for media/draft so failures are visible
    if intent in ("create_design", "create_image", "create_video", "create_song", "draft_post") and action.get("message"):
        if action.get("status") in ("configuration_required", "error") or not reply:
            reply = action["message"]
        elif (
            action.get("image_url")
            or action.get("audio_url")
            or (isinstance(action.get("render"), dict) and action["render"].get("video_url"))
        ):
            reply = action["message"]
    return {
        "ok": True,
        "intent": intent,
        "reply": reply,
        "action": action,
        "parser": parsed.get("parser"),
        "llm": parsed.get("llm"),
        "agent": agent_persona(),
        "at": _utc_now(),
    }
