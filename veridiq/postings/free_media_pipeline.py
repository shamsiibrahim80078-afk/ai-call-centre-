"""Zero-cost modular media pipeline for VERIDIQ posting agents.

Stack (no paid APIs / no API keys):
  1. Pollinations.ai HD stills (free tier — may 429 / IP-queue)
  2. MoviePy Ken Burns MP4 from local images
  3. edge-tts neural voiceover muxed into the video

Import for agents::

    from veridiq.postings.free_media_pipeline import run_pipeline

CLI::

    python scripts/free_media_agent.py --topic "Bitcoin rally" --voice en-US-AriaNeural

Honest limits: Pollinations free hosts share a per-IP queue (~1 in-flight).
Expect occasional HTTP 429; this module retries with backoff and optionally
reuses the shared ``pollinations_image.pollinations_slot`` lock when present.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
import uuid
from pathlib import Path
from typing import Any, Optional, Sequence
from urllib.parse import quote

# Pillow ≥10 removed Image.ANTIALIAS; MoviePy 1.0.3 still references it.
# Apply before any moviepy import (eager on module load).
try:
    from PIL import Image as _PILImage

    if not hasattr(_PILImage, "ANTIALIAS"):
        _PILImage.ANTIALIAS = _PILImage.Resampling.LANCZOS  # type: ignore[attr-defined]
    if not hasattr(_PILImage, "BICUBIC"):
        _PILImage.BICUBIC = _PILImage.Resampling.BICUBIC  # type: ignore[attr-defined]
    if not hasattr(_PILImage, "BILINEAR"):
        _PILImage.BILINEAR = _PILImage.Resampling.BILINEAR  # type: ignore[attr-defined]
except Exception:
    pass

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_OUT = _ROOT / "marketing_out" / "free_media"

# Pollinations free image host (no API key). Alternate path for soft failover.
_POLL_BASES = (
    "https://image.pollinations.ai/prompt",
    "https://gen.pollinations.ai/image",
)
_RETRY_BACKOFF_SEC = (2.0, 5.0, 10.0, 18.0)
_DEFAULT_VOICE = "en-US-AriaNeural"

_CRYPTO_STYLE_SUFFIX = (
    "cinematic 4K crypto marketing still, neon-glow cyberpunk lighting, "
    "volumetric god rays, holographic HUD accents, ultra-sharp detail, "
    "dramatic depth of field, high-end fintech advertisement, "
    "bitcoin ethereum aesthetic, no watermark, no logo, no text, no captions, no words, no letters on image, no text overlay"
)


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


def enhance_crypto_prompt(user_text: str) -> str:
    """Inject neon-glow / 4K / cinematic crypto marketing keywords into a basic topic.

    Idempotent enough for re-runs: if the text already looks enhanced, still
    append a compact style trailer so Pollinations gets consistent guidance.
    """
    base = re.sub(r"\s+", " ", (user_text or "").strip())
    if not base:
        base = "cryptocurrency market momentum"
    # Avoid doubling the full trailer when already present
    lower = base.lower()
    if "neon-glow" in lower and "4k" in lower and "cinematic" in lower:
        return base
    return f"{base}, {_CRYPTO_STYLE_SUFFIX}"


# ---------------------------------------------------------------------------
# Paths / HTTP helpers
# ---------------------------------------------------------------------------


def _ensure_dirs(out_dir: Path) -> dict[str, Path]:
    images = out_dir / "images"
    audio = out_dir / "audio"
    videos = out_dir / "videos"
    for d in (images, audio, videos):
        d.mkdir(parents=True, exist_ok=True)
    return {"root": out_dir, "images": images, "audio": audio, "videos": videos}


def _stem(topic: str, prefix: str = "fm") -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", (topic or "topic").strip())[:40].strip("_").lower()
    slug = slug or "topic"
    return f"{prefix}_{slug}_{uuid.uuid4().hex[:8]}"


def _http_get_bytes(url: str, params: dict[str, Any], timeout: float) -> tuple[int, bytes, str]:
    """GET image bytes via httpx (preferred) or urllib — no API key."""
    try:
        import httpx

        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.get(url, params=params)
            ctype = (resp.headers.get("content-type") or "").lower()
            return resp.status_code, resp.content, ctype
    except ImportError:
        from urllib.parse import urlencode
        from urllib.request import Request, urlopen

        qs = urlencode({k: str(v) for k, v in params.items()})
        full = f"{url}?{qs}" if qs else url
        req = Request(full, headers={"User-Agent": "VERIDIQ-free-media/1.0"})
        with urlopen(req, timeout=timeout) as resp:  # noqa: S310 — fixed public CDN
            ctype = (resp.headers.get("Content-Type") or "").lower()
            return int(getattr(resp, "status", 200) or 200), resp.read(), ctype


def _try_pollinations_slot():
    """Reuse shared IP-queue lock when the heavier integration module is importable."""
    try:
        from veridiq.integrations.pollinations_image import pollinations_slot

        return pollinations_slot()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Image generation (Pollinations)
# ---------------------------------------------------------------------------


def generate_image(
    prompt: str,
    out_path: str | Path,
    width: int = 1280,
    height: int = 720,
    *,
    model: str = "flux",
    timeout: float = 60.0,
    max_attempts: int = 4,
) -> Path:
    """Download one HD still from Pollinations into ``out_path``.

    Uses ``https://image.pollinations.ai/prompt/...`` with ``nologo=true`` and
    model ``flux`` (falls back to ``turbo``). Free tier may rate-limit (HTTP 429)
    per IP — retries with exponential-ish backoff. No API key required.

    Raises:
        RuntimeError: if all attempts fail (including persistent 429).
    """
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    enhanced = enhance_crypto_prompt(prompt)
    w = max(512, min(1280, int(width or 1280)))
    h = max(512, min(1280, int(height or 720)))
    models = []
    for m in (model, "flux", "turbo"):
        if m and m not in models:
            models.append(m)
    seed = int(hashlib.md5(enhanced.encode("utf-8", errors="ignore")).hexdigest()[:8], 16) % 2_147_483_647
    seed = (seed + int(time.time()) % 10_000) % 2_147_483_647

    last_err = "unknown"
    slot = _try_pollinations_slot()
    ctx = slot if slot is not None else _NullCtx()

    with ctx:
        for attempt in range(max(1, int(max_attempts))):
            if attempt > 0:
                pause = _RETRY_BACKOFF_SEC[min(attempt - 1, len(_RETRY_BACKOFF_SEC) - 1)]
                time.sleep(pause)
            use_model = models[min(attempt, len(models) - 1)]
            use_base = _POLL_BASES[attempt % len(_POLL_BASES)]
            params = {
                "width": w,
                "height": h,
                "nologo": "true",
                "enhance": "true",
                "model": use_model,
                "seed": seed + attempt,
            }
            url = f"{use_base}/{quote(enhanced)}"
            try:
                status, body, ctype = _http_get_bytes(url, params, timeout=float(timeout))
            except Exception as exc:
                last_err = f"network: {exc}"
                logger.warning("Pollinations attempt %s failed: %s", attempt + 1, last_err)
                continue
            if status == 429:
                last_err = "HTTP 429 — Pollinations free-tier IP queue busy"
                logger.warning("%s (attempt %s)", last_err, attempt + 1)
                continue
            if status == 200 and ("image" in ctype or (body[:3] == b"\xff\xd8\xff") or body[:8] == b"\x89PNG\r\n\x1a\n"):
                if len(body) < 2000:
                    last_err = "downloaded image too small"
                    continue
                out.write_bytes(body)
                return out.resolve()
            last_err = f"HTTP {status} ctype={ctype[:40]!r}"

    raise RuntimeError(
        f"Pollinations image failed after {max_attempts} attempts ({last_err}). "
        "Free tier may be rate-limited — retry in a minute."
    )


class _NullCtx:
    def __enter__(self) -> "_NullCtx":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None


def generate_images(
    topic: str,
    count: int = 3,
    out_dir: str | Path | None = None,
    *,
    width: int = 1280,
    height: int = 720,
) -> list[Path]:
    """Generate ``count`` local stills for ``topic`` under ``out_dir/images``."""
    root = Path(out_dir) if out_dir else DEFAULT_OUT
    dirs = _ensure_dirs(root)
    n = max(1, min(8, int(count or 3)))
    paths: list[Path] = []
    base_prompt = enhance_crypto_prompt(topic)
    angles = (
        "wide establishing shot",
        "dynamic diagonal composition, close energy",
        "macro detail of glowing charts and coins",
        "epic skyline silhouette with neon sky",
        "abstract data vortex with soft bokeh",
    )
    for i in range(n):
        angle = angles[i % len(angles)]
        prompt = f"{base_prompt}, {angle}, variation {i + 1}"
        dest = dirs["images"] / f"{_stem(topic, f'img{i + 1}')}.jpg"
        try:
            paths.append(generate_image(prompt, dest, width=width, height=height))
        except RuntimeError as exc:
            logger.error("Image %s/%s failed: %s", i + 1, n, exc)
            # Continue so partial galleries still feed video when possible
            continue
        # Soft pacing between free-tier calls
        if i + 1 < n:
            time.sleep(1.5)
    return paths


# ---------------------------------------------------------------------------
# Voiceover (edge-tts)
# ---------------------------------------------------------------------------


def generate_voiceover(
    script: str,
    out_mp3_or_wav: str | Path,
    voice: str = _DEFAULT_VOICE,
) -> Path:
    """Synthesize neural VO with free edge-tts into ``out_mp3_or_wav``."""
    text = re.sub(r"\s+", " ", (script or "").strip())
    if not text:
        raise ValueError("script is required for voiceover")
    out = Path(out_mp3_or_wav)
    out.parent.mkdir(parents=True, exist_ok=True)
    voice_id = (voice or _DEFAULT_VOICE).strip() or _DEFAULT_VOICE

    try:
        import edge_tts
    except ImportError as exc:
        raise RuntimeError("edge-tts is not installed. Run: pip install edge-tts") from exc

    async def _run() -> None:
        communicate = edge_tts.Communicate(text, voice_id, rate="-2%", pitch="+0Hz")
        await communicate.save(str(out))

    try:
        asyncio.run(_run())
    except RuntimeError as exc:
        # Nested event loop (e.g. Jupyter / agent runtime) — use a fresh loop thread
        if "asyncio" in str(exc).lower() or "running event loop" in str(exc).lower():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                fut = pool.submit(lambda: asyncio.run(_run()))
                fut.result(timeout=180)
        else:
            raise

    if not out.is_file() or out.stat().st_size < 400:
        raise RuntimeError(f"edge-tts produced empty audio at {out}")
    return out.resolve()


# ---------------------------------------------------------------------------
# Video (MoviePy Ken Burns + fallback)
# ---------------------------------------------------------------------------


def _patch_pillow_for_moviepy() -> None:
    """MoviePy 1.0.3 expects PIL.Image.ANTIALIAS (removed in Pillow ≥10).

    Idempotent re-apply before moviepy import / resize (in case another
    import path cleared or shadowed attributes).
    """
    try:
        from PIL import Image

        _lanczos = getattr(getattr(Image, "Resampling", Image), "LANCZOS", None)
        _bicubic = getattr(getattr(Image, "Resampling", Image), "BICUBIC", None)
        _bilinear = getattr(getattr(Image, "Resampling", Image), "BILINEAR", None)
        if not hasattr(Image, "ANTIALIAS") and _lanczos is not None:
            Image.ANTIALIAS = _lanczos  # type: ignore[attr-defined]
        if not hasattr(Image, "BICUBIC") and _bicubic is not None:
            Image.BICUBIC = _bicubic  # type: ignore[attr-defined]
        if not hasattr(Image, "BILINEAR") and _bilinear is not None:
            Image.BILINEAR = _bilinear  # type: ignore[attr-defined]
    except Exception:
        pass


def _moviepy_api():
    """Return (mods dict, version_major) or None."""
    _patch_pillow_for_moviepy()
    try:
        # MoviePy 2.x
        from moviepy import AudioFileClip, ImageClip, concatenate_videoclips

        return {
            "ImageClip": ImageClip,
            "AudioFileClip": AudioFileClip,
            "concatenate_videoclips": concatenate_videoclips,
        }, 2
    except Exception:
        pass
    try:
        # MoviePy 1.x
        from moviepy.editor import AudioFileClip, ImageClip, concatenate_videoclips

        return {
            "ImageClip": ImageClip,
            "AudioFileClip": AudioFileClip,
            "concatenate_videoclips": concatenate_videoclips,
        }, 1
    except Exception:
        return None


def _ken_burns_clip(mods: dict, path: Path, duration: float, index: int, major: int, size=(1280, 720)):
    """Gentle zoom (Ken Burns) on a still — MoviePy resize over time.

    Pan via CompositeVideoClip is skipped for reliability on Windows + MoviePy 1.0.3;
    alternating zoom-in / zoom-out still reads as motion.
    """
    ImageClip = mods["ImageClip"]
    zoom_in = index % 2 == 0
    start_scale = 1.0 if zoom_in else 1.15
    end_scale = 1.15 if zoom_in else 1.0

    def _scale(t: float) -> float:
        if duration <= 0:
            return end_scale
        return start_scale + (end_scale - start_scale) * (t / duration)

    if major >= 2:
        clip = ImageClip(str(path)).with_duration(duration)
        try:
            return clip.resized(lambda t: _scale(t))
        except Exception:
            return clip.resized(end_scale if zoom_in else start_scale)

    clip = ImageClip(str(path)).set_duration(duration)
    try:
        return clip.resize(_scale)
    except Exception:
        return clip.resize(end_scale if zoom_in else start_scale)


def _build_video_moviepy(
    image_paths: Sequence[Path],
    audio_path: Path | None,
    out_mp4: Path,
    duration_per_image: float,
) -> Path:
    api = _moviepy_api()
    if api is None:
        raise ImportError("moviepy not installed")
    mods, major = api
    concatenate_videoclips = mods["concatenate_videoclips"]
    AudioFileClip = mods["AudioFileClip"]

    clips = []
    for i, p in enumerate(image_paths):
        clips.append(_ken_burns_clip(mods, Path(p), float(duration_per_image), i, major))
    if not clips:
        raise ValueError("no valid image clips")

    video = concatenate_videoclips(clips, method="compose")

    audio_clip = None
    if audio_path and Path(audio_path).is_file():
        audio_clip = AudioFileClip(str(audio_path))
        try:
            aud_dur = float(audio_clip.duration or 0)
        except Exception:
            aud_dur = 0.0
        if aud_dur > 0 and aud_dur > float(video.duration or 0) + 0.25:
            extra = aud_dur - float(video.duration)
            last = clips[-1]
            if major >= 2:
                hold = last.with_duration(float(last.duration) + extra)
            else:
                hold = last.set_duration(float(last.duration) + extra)
            clips = list(clips[:-1]) + [hold]
            try:
                video.close()
            except Exception:
                pass
            video = concatenate_videoclips(clips, method="compose")
        if major >= 2:
            video = video.with_audio(audio_clip)
        else:
            video = video.set_audio(audio_clip)

    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    write_kwargs: dict[str, Any] = {
        "fps": 24,
        "codec": "libx264",
        "audio_codec": "aac",
        "threads": 2,
        "logger": None,
    }
    try:
        video.write_videofile(str(out_mp4), **write_kwargs)
    except TypeError:
        write_kwargs.pop("logger", None)
        video.write_videofile(str(out_mp4), **write_kwargs)
    finally:
        try:
            video.close()
        except Exception:
            pass
        if audio_clip is not None:
            try:
                audio_clip.close()
            except Exception:
                pass
        for c in clips:
            try:
                c.close()
            except Exception:
                pass

    if not out_mp4.is_file() or out_mp4.stat().st_size < 1000:
        raise RuntimeError(f"MoviePy wrote empty/missing file: {out_mp4}")
    return out_mp4.resolve()


def _build_video_fallback(
    image_paths: Sequence[Path],
    audio_path: Path | None,
    out_mp4: Path,
    duration_per_image: float,
) -> Path:
    """Fallback: existing local_video Ken Burns assemble so agents don't crash."""
    from veridiq.integrations import local_video

    stills = [str(Path(p).resolve()) for p in image_paths if Path(p).is_file()]
    if not stills:
        raise RuntimeError("No local images for video fallback")
    n = len(stills)
    per = float(duration_per_image)
    total = max(per * n, 3.0)
    storyboard = {
        "storyboard_id": f"free_media_{uuid.uuid4().hex[:10]}",
        "duration_sec": total,
        "aspect": "16:9",
        "shot_list": [{"duration_sec": per} for _ in stills],
    }
    render = local_video.render_storyboard_from_stills(
        storyboard,
        stills,
        audio_path=str(audio_path) if audio_path else None,
        mira_cinematic=True,
    )
    if not render.get("ok"):
        raise RuntimeError(render.get("message") or "local_video assemble failed")
    src = Path(render.get("absolute_path") or render.get("video_path") or "")
    if not src.is_file():
        # Some returns use relative marketing path
        rel = render.get("video_path") or render.get("mp4_path")
        if rel:
            cand = _ROOT / str(rel).replace("\\", "/")
            if cand.is_file():
                src = cand
    if not src.is_file():
        raise RuntimeError(f"local_video ok but file missing: {render}")
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    if src.resolve() != out_mp4.resolve():
        out_mp4.write_bytes(src.read_bytes())
    return out_mp4.resolve()


def build_video(
    image_paths: Sequence[str | Path],
    audio_path: str | Path | None,
    out_mp4: str | Path,
    duration_per_image: float = 4.0,
) -> Path:
    """Assemble stills into an MP4 with Ken Burns zoom/pan and optional audio.

    Primary engine: MoviePy. If MoviePy is missing, falls back to
    ``veridiq.integrations.local_video`` so posting agents do not crash.
    """
    paths = [Path(p) for p in image_paths if p and Path(p).is_file()]
    if not paths:
        raise ValueError("image_paths must contain at least one existing image file")
    out = Path(out_mp4)
    audio = Path(audio_path) if audio_path else None
    dur = max(1.5, float(duration_per_image or 4.0))

    if _moviepy_api() is not None:
        try:
            return _build_video_moviepy(paths, audio, out, dur)
        except Exception as exc:
            logger.warning("MoviePy build failed (%s) — trying local_video fallback", exc)

    return _build_video_fallback(paths, audio, out, dur)


# ---------------------------------------------------------------------------
# Pipeline entry (for posting agents)
# ---------------------------------------------------------------------------


def _default_script(topic: str) -> str:
    t = re.sub(r"\s+", " ", (topic or "crypto markets").strip())
    return (
        f"Here's the pulse on {t}. "
        "Markets move fast — stay sharp, verify the narrative, and ride the momentum with clarity. "
        "This is VERIDIQ free media — cinematic crypto visuals, zero paid APIs."
    )


def run_pipeline(
    topic: str,
    script: str | None = None,
    out_dir: str | Path | None = None,
    *,
    count: int = 3,
    voice: str = _DEFAULT_VOICE,
    width: int = 1280,
    height: int = 720,
    duration_per_image: float = 4.0,
) -> dict[str, Any]:
    """End-to-end free media: images → voiceover → Ken Burns MP4.

    Returns a dict with ``image_paths``, ``image_urls`` (file:// / relative),
    ``audio_path``, ``video_path``, ``ok``, and status notes for agents.

    Designed for Mira / other posting agents to call locally with no API keys.
    """
    topic_clean = re.sub(r"\s+", " ", (topic or "").strip())
    if not topic_clean:
        return {
            "ok": False,
            "status": "invalid_args",
            "message": "topic is required",
            "image_paths": [],
            "image_urls": [],
            "audio_path": None,
            "video_path": None,
        }

    root = Path(out_dir) if out_dir else DEFAULT_OUT
    dirs = _ensure_dirs(root)
    vo_script = (script or "").strip() or _default_script(topic_clean)
    notes: list[str] = []

    image_paths = generate_images(
        topic_clean,
        count=count,
        out_dir=root,
        width=width,
        height=height,
    )
    if not image_paths:
        return {
            "ok": False,
            "status": "error",
            "message": (
                "No images generated — Pollinations free tier may be rate-limiting (429). "
                "Retry shortly; no API key can bypass the public IP queue."
            ),
            "image_paths": [],
            "image_urls": [],
            "audio_path": None,
            "video_path": None,
            "notes": notes,
            "out_dir": str(root),
        }

    audio_path: Optional[Path] = None
    try:
        audio_path = generate_voiceover(
            vo_script,
            dirs["audio"] / f"{_stem(topic_clean, 'vo')}.mp3",
            voice=voice,
        )
    except Exception as exc:
        notes.append(f"voiceover skipped: {exc}")
        logger.warning("edge-tts failed: %s", exc)

    video_path: Optional[Path] = None
    try:
        video_path = build_video(
            image_paths,
            audio_path,
            dirs["videos"] / f"{_stem(topic_clean, 'vid')}.mp4",
            duration_per_image=duration_per_image,
        )
    except Exception as exc:
        notes.append(f"video failed: {exc}")
        logger.error("build_video failed: %s", exc)

    def _rel(p: Path) -> str:
        try:
            return str(p.resolve().relative_to(_ROOT)).replace("\\", "/")
        except ValueError:
            return str(p.resolve())

    rel_images = [_rel(p) for p in image_paths]
    return {
        "ok": bool(video_path) or bool(image_paths),
        "status": "ok" if video_path else ("partial" if image_paths else "error"),
        "topic": topic_clean,
        "script": vo_script,
        "voice": voice,
        "image_paths": [str(p.resolve()) for p in image_paths],
        "image_urls": [f"file:///{p.resolve().as_posix()}" for p in image_paths],
        "image_paths_rel": rel_images,
        "audio_path": str(audio_path.resolve()) if audio_path else None,
        "audio_path_rel": _rel(audio_path) if audio_path else None,
        "video_path": str(video_path.resolve()) if video_path else None,
        "video_path_rel": _rel(video_path) if video_path else None,
        "out_dir": str(root.resolve()),
        "notes": notes,
        "message": (
            f"Free media ready: {len(image_paths)} image(s)"
            + (f", video={video_path.name}" if video_path else "")
            + (f", audio={audio_path.name}" if audio_path else "")
        ),
        "provider": {
            "images": "pollinations.ai (free, may 429)",
            "video": "moviepy Ken Burns (fallback: local_video)",
            "audio": "edge-tts (free neural)",
        },
    }


__all__ = [
    "enhance_crypto_prompt",
    "generate_image",
    "generate_images",
    "generate_voiceover",
    "build_video",
    "run_pipeline",
    "DEFAULT_OUT",
]
