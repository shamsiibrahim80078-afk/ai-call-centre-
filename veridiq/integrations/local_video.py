"""Local unlimited free video — storyboard → real media file, $0 forever.

Primary: MP4 via imageio-ffmpeg when installed (smoother, sharper).
Fallback: animated GIF via Pillow.

Assembles AI stills or title-card slides. Honors requested duration_sec
(hold / Ken Burns / cycle) so MP4 playback length matches the ask.
Optional soundtrack mux via system ffmpeg.

Default output: 1920×1080 @ 30fps (Gemini quality recipe).
Optional 4K via VERIDIQ_VIDEO_4K=1; optional 60fps via VERIDIQ_VIDEO_FPS=60.

True Veo-style generative motion and facial lip-sync phoneme keypoints are
NOT available on stills-slideshow — only Ken Burns / crossfade / mid-frame blend
motion. Mira Cinematic mode strengthens pan/zoom + interpolation (still not Veo).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import textwrap
from pathlib import Path
from typing import Any, Optional

from veridiq.integrations.base import status_shape

PLATFORM = "local_video"
DISPLAY = "Local Free Video (unlimited)"
CATEGORY = "video"
ENV_VARS: list[str] = ["VERIDIQ_VIDEO_LOCAL", "VERIDIQ_VIDEO_4K", "VERIDIQ_VIDEO_FPS"]
CAPABILITIES = ["render_storyboard_slideshow_gif_or_mp4", "mux_audio_soundtrack"]
DOCS = None

_ROOT = Path(__file__).resolve().parent.parent.parent
OUT_DIR = _ROOT / "marketing_out" / "videos"

# ~6 Mbps target for 1080p
VIDEO_BITRATE = "6M"
BG = (8, 14, 28)
ACCENT = (79, 140, 255)
TEXT = (232, 240, 255)
MUTED = (160, 180, 210)

# Duration clamps (playback length of final MP4)
MIN_DURATION_SEC = 10
MAX_DURATION_SEC = 300
DEFAULT_DURATION_SEC = 15


def _env_flag(name: str, default: str = "0") -> bool:
    return (os.getenv(name) or default).strip().lower() in ("1", "true", "yes", "on")


def _output_size(*, portrait: bool = False) -> tuple[int, int]:
    """Default 1080p landscape; optional 4K when VERIDIQ_VIDEO_4K=1; 9:16 when portrait."""
    if _env_flag("VERIDIQ_VIDEO_4K"):
        return (2160, 3840) if portrait else (3840, 2160)
    return (1080, 1920) if portrait else (1920, 1080)


def _target_fps() -> int:
    """Default 30fps; optional 60 via VERIDIQ_VIDEO_FPS=60."""
    raw = (os.getenv("VERIDIQ_VIDEO_FPS") or "30").strip()
    try:
        v = int(raw)
    except ValueError:
        v = 30
    if v >= 60:
        return 60
    return 30


def _sync_wh_fps(*, portrait: bool | None = None) -> tuple[int, int, int]:
    """Refresh module W/H/FPS from env for this encode pass.

    If portrait is omitted, keep the current orientation (H>W = portrait) so
    helper resize/encode calls don't snap back to 16:9 mid-render.
    """
    global W, H, FPS
    if portrait is None:
        portrait = H > W
    W, H = _output_size(portrait=bool(portrait))
    FPS = _target_fps()
    return W, H, FPS


# Module-level defaults (re-synced from env on each encode)
W, H = 1920, 1080
FPS = 30


def is_enabled() -> bool:
    flag = (os.getenv("VERIDIQ_VIDEO_LOCAL") or "1").strip().lower()
    return flag not in ("0", "false", "no", "off")


def status() -> dict[str, Any]:
    w, h, fps = _sync_wh_fps()
    if not is_enabled():
        return status_shape(
            PLATFORM,
            DISPLAY,
            CATEGORY,
            status="disabled",
            configured=False,
            message="Local free video disabled (VERIDIQ_VIDEO_LOCAL=0).",
            env_vars=ENV_VARS,
            capabilities=CAPABILITIES,
            docs_url=DOCS,
        )
    try:
        from PIL import Image  # noqa: F401

        has_mp4 = False
        try:
            import imageio_ffmpeg  # noqa: F401

            has_mp4 = True
        except Exception:
            has_mp4 = False
        has_mux = bool(_ffmpeg_exe())
        return status_shape(
            PLATFORM,
            DISPLAY,
            CATEGORY,
            status="configured",
            configured=True,
            message=(
                "Local unlimited free render ready (Pillow GIF"
                + (" + MP4" if has_mp4 else "")
                + (" + audio mux" if has_mux else "")
                + f") — {w}x{h} @{fps}fps, no paid API."
            ),
            env_vars=ENV_VARS,
            capabilities=CAPABILITIES,
            docs_url=DOCS,
            extra={
                "unlimited": True,
                "cost": 0,
                "mp4": has_mp4,
                "gif": True,
                "fps": fps,
                "width": w,
                "height": h,
                "bitrate": VIDEO_BITRATE,
                "ffmpeg_mux": has_mux,
                "veo_motion": False,
                "lip_sync": False,
            },
        )
    except Exception as exc:
        return status_shape(
            PLATFORM,
            DISPLAY,
            CATEGORY,
            status="configuration_required",
            configured=False,
            message=f"Pillow required for local free video: {str(exc)[:120]}",
            env_vars=ENV_VARS,
            capabilities=CAPABILITIES,
            docs_url=DOCS,
        )


def test_connection() -> dict[str, Any]:
    st = status()
    return {
        "platform": PLATFORM,
        "status": st.get("status"),
        "ok": bool(st.get("configured")),
        "message": st.get("message"),
    }


def clamp_duration_sec(sec: Any, *, default: int = DEFAULT_DURATION_SEC) -> int:
    try:
        v = int(round(float(sec)))
    except (TypeError, ValueError):
        v = int(default)
    return max(MIN_DURATION_SEC, min(MAX_DURATION_SEC, v))


def format_duration_label(sec: float | int) -> str:
    s = max(0, int(round(float(sec))))
    m, rem = divmod(s, 60)
    if m <= 0:
        return f"{rem}s"
    return f"{m}:{rem:02d}"


def _wrap(text: str, width: int = 42) -> list[str]:
    clean = re.sub(r"\s+", " ", (text or "").strip())
    if not clean:
        return []
    return textwrap.wrap(clean, width=width)[:8]


def _draw_slide(*, title: str, subtitle: str, body: str, scene_label: str = ""):
    from PIL import Image, ImageDraw, ImageFont

    w, h, _ = _sync_wh_fps()
    img = Image.new("RGB", (w, h), BG)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, 10, h], fill=ACCENT)
    draw.rectangle([0, h - 6, w, h], fill=ACCENT)

    try:
        font_lg = ImageFont.truetype("arial.ttf", 42)
        font_md = ImageFont.truetype("arial.ttf", 28)
        font_sm = ImageFont.truetype("arial.ttf", 22)
    except Exception:
        font_lg = ImageFont.load_default()
        font_md = font_lg
        font_sm = font_lg

    # Never burn "Scene 1/2/3" or raw prompt dumps — short brand mark only
    try:
        from veridiq.postings.local_stills import _clean_topic_title
    except Exception:
        _clean_topic_title = lambda t: "VERIDIQ"  # type: ignore[assignment]

    brand = "VERIDIQ"
    if scene_label and not re.search(r"\bscene\s*\d+\b", scene_label, re.I):
        brand = _clean_topic_title(scene_label) or brand
    draw.text((40, 36), brand, fill=ACCENT, font=font_sm)
    y = 90
    # Title: reject prompt dumps / scene indices / long user commands
    clean_title = _clean_topic_title(title or "") or "VERIDIQ"
    for line in _wrap(clean_title, 36)[:2]:
        draw.text((40, y), line, fill=TEXT, font=font_lg)
        y += 52
    y += 12
    # Subtitle: branded tagline only — never raw topic / Mira · prompt
    clean_sub = _clean_topic_title(subtitle or "") if subtitle else ""
    if not clean_sub or clean_sub.upper() == clean_title.upper() or len(str(subtitle or "")) > 40:
        clean_sub = "Truth. Verified."
    for line in _wrap(clean_sub, 48)[:2]:
        draw.text((40, y), line, fill=MUTED, font=font_md)
        y += 36
    # Do not dump voiceover / raw prompt onto frames
    draw.text((40, h - 48), "VERIDIQ · Truth. Verified.", fill=MUTED, font=font_sm)
    return img


def _unsharp_mild(img: Any) -> Any:
    """Mild unsharp mask after Lanczos upscale — crisper without halo noise."""
    from PIL import ImageFilter

    try:
        return img.filter(ImageFilter.UnsharpMask(radius=1.2, percent=120, threshold=2))
    except Exception:
        return img


def _smoothstep(t: float) -> float:
    """Ease-in-out for optical-flow-ish pan/zoom (no neural flow — math only)."""
    x = max(0.0, min(1.0, float(t)))
    return x * x * (3.0 - 2.0 * x)


def _resize_sharp(img: Any, *, unsharp: bool = False) -> Any:
    """Resize/upscale with high-quality filter (e.g. 1280×720 gen → 1920×1080)."""
    from PIL import Image

    w, h, _ = _sync_wh_fps()
    if img.size == (w, h):
        out = img.convert("RGB")
    else:
        resample = getattr(Image, "Resampling", Image).LANCZOS
        out = img.convert("RGB").resize((w, h), resample)
    return _unsharp_mild(out) if unsharp else out


def _crossfade(a: Any, b: Any, steps: int = 4) -> list[Any]:
    """Short blend between slides for smoother playback."""
    from PIL import Image

    if steps <= 0:
        return []
    out: list[Any] = []
    for i in range(1, steps + 1):
        alpha = _smoothstep(i / (steps + 1))
        out.append(Image.blend(a, b, alpha))
    return out


def _prepare_ken_source(img: Any, *, mira: bool = False) -> Any:
    """Upscale once per still for Ken Burns crops."""
    from PIL import Image

    w, h, _ = _sync_wh_fps()
    base = img.convert("RGB")
    src_w, src_h = base.size
    # Mira: larger overscan for stronger pan/zoom without edge stretch
    scale_up = 1.22 if mira else 1.12
    resample = getattr(Image, "Resampling", Image).LANCZOS
    return base.resize(
        (max(w + 8, int(src_w * scale_up)), max(h + 8, int(src_h * scale_up))),
        resample,
    )


def _ken_burns_frame_from_big(big: Any, *, t: float, variant: int = 0, mira: bool = False) -> Any:
    """Single Ken Burns frame from a pre-upscaled source at progress t in [0,1]."""
    w, h, _ = _sync_wh_fps()
    bw, bh = big.size
    # Mira patterns: wider zoom span + multi-axis drift (optical-flow-ish feel)
    if mira:
        patterns = (
            (1.0, 1.16, 0.0, 0.0, 0.08, 0.04),
            (1.14, 1.0, 0.08, 0.05, -0.07, -0.04),
            (1.02, 1.18, 0.1, 0.0, -0.09, 0.06),
            (1.12, 1.0, 0.0, 0.08, 0.06, -0.07),
            (1.04, 1.15, 0.06, 0.03, -0.05, 0.05),
            (1.15, 1.02, 0.03, 0.06, 0.05, -0.05),
        )
    else:
        patterns = (
            (1.0, 1.08, 0.0, 0.0, 0.02, 0.01),
            (1.08, 1.0, 0.04, 0.02, -0.02, -0.01),
            (1.02, 1.1, 0.05, 0.0, -0.04, 0.02),
            (1.06, 1.0, 0.0, 0.04, 0.03, -0.03),
        )
    z0, z1, x0, y0, dx, dy = patterns[variant % len(patterns)]
    te = _smoothstep(t) if mira else t
    zoom = z0 + (z1 - z0) * te
    cw = min(bw, max(w, int(bw / zoom)))
    ch = min(bh, max(h, int(bh / zoom)))
    max_x = max(0, bw - cw)
    max_y = max(0, bh - ch)
    left = int(max(0, min(max_x, (x0 + dx * te) * max_x)))
    top = int(max(0, min(max_y, (y0 + dy * te) * max_y)))
    crop = big.crop((left, top, left + cw, top + ch))
    return _resize_sharp(crop, unsharp=mira)


def _ken_burns_frame(img: Any, *, t: float, variant: int = 0, mira: bool = False) -> Any:
    return _ken_burns_frame_from_big(
        _prepare_ken_source(img, mira=mira), t=t, variant=variant, mira=mira
    )


def _ken_burns_frames(
    img: Any, *, duration_sec: float, variant: int = 0, mira: bool = False
) -> list[Any]:
    """Slow pan/zoom over a still (small clips only — prefer streaming writer for long)."""
    _, _, fps = _sync_wh_fps()
    n = max(1, int(round(float(duration_sec) * fps)))
    if n <= 1:
        return [_resize_sharp(img, unsharp=mira)]
    big = _prepare_ken_source(img, mira=mira)
    return [
        _ken_burns_frame_from_big(big, t=(i / max(1, n - 1)), variant=variant, mira=mira)
        for i in range(n)
    ]


def _effective_fps(duration_sec: float) -> int:
    """Use configured target FPS; drop to 15fps for ≥60s so long encodes stay fast."""
    base = _target_fps()
    d = float(duration_sec)
    if d >= 60:
        return 15
    return base


def _writer_kwargs(fps: int, *, light: bool = False) -> dict[str, Any]:
    """imageio writer options — ~5–8 Mbps for 1080p; light for fast reliability encodes."""
    if light:
        return {
            "fps": fps,
            "codec": "libx264",
            "quality": 7,
            "pixelformat": "yuv420p",
            "macro_block_size": 1,
            "ffmpeg_params": ["-b:v", "2.5M", "-maxrate", "3M", "-bufsize", "5M", "-preset", "ultrafast"],
        }
    return {
        "fps": fps,
        "codec": "libx264",
        "quality": 8,
        "pixelformat": "yuv420p",
        "macro_block_size": 1,
        "ffmpeg_params": ["-b:v", VIDEO_BITRATE, "-maxrate", "8M", "-bufsize", "16M"],
    }


def _write_mp4_streaming(
    segments: list[tuple[Any, float, int]],
    out_path: Path,
    *,
    target_sec: float,
    crossfade_sec: float = 0.4,
    mira: bool = False,
) -> tuple[bool, float]:
    """Stream Ken Burns frames to MP4 without holding the whole timeline in RAM.

    mira=True: stronger zoom/pan, longer eased crossfades, mid-frame blends between
    consecutive Ken Burns samples for smoother 30fps (still not generative Veo motion).
    """
    try:
        import imageio.v2 as imageio
        import numpy as np
        from PIL import Image
    except Exception:
        return False, 0.0

    fps = _effective_fps(target_sec)
    # Mira: longer crossfade; default path keeps ≥0.4s at 30fps
    if mira:
        crossfade_sec = max(float(crossfade_sec), 0.65)
    elif fps >= 30 and crossfade_sec < 0.4:
        crossfade_sec = 0.4
    need = max(1, int(round(float(target_sec) * fps)))
    written = 0
    try:
        writer = imageio.get_writer(out_path, **_writer_kwargs(fps))
    except Exception:
        try:
            writer = imageio.get_writer(out_path, fps=fps, codec="libx264", quality=8, pixelformat="yuv420p")
        except Exception:
            return False, 0.0

    try:
        last_arr = None
        last_pil = None
        for i, (img, dur, variant) in enumerate(segments):
            if written >= need:
                break
            big = _prepare_ken_source(img, mira=mira)
            fade_budget = crossfade_sec if i + 1 < len(segments) else 0.0
            hold_main = max(0.4, float(dur) - fade_budget)
            n_hold = max(1, int(round(hold_main * fps)))
            for fi in range(n_hold):
                if written >= need:
                    break
                t = fi / max(1, n_hold - 1)
                frame = _ken_burns_frame_from_big(big, t=t, variant=variant, mira=mira)
                # Mid-frame blend with previous for smoother 30fps (Option C)
                if mira and last_pil is not None and fi > 0:
                    mid = Image.blend(last_pil, frame, 0.35)
                    # Write eased mid then current — but only if budget allows
                    # Prefer denser motion: replace every other frame with blend
                    if fi % 2 == 1:
                        frame = mid
                arr = np.asarray(frame)
                writer.append_data(arr)
                last_arr = arr
                last_pil = frame
                written += 1
            if fade_budget > 0 and i + 1 < len(segments) and written < need and last_arr is not None:
                nxt_big = _prepare_ken_source(segments[i + 1][0], mira=mira)
                nxt = _ken_burns_frame_from_big(
                    nxt_big, t=0.0, variant=segments[i + 1][2], mira=mira
                )
                # More mid-frames between stills for Mira
                steps = max(4 if mira else 2, int(round(fade_budget * fps)))
                a_img = Image.fromarray(last_arr)
                for s in range(1, steps + 1):
                    if written >= need:
                        break
                    alpha = _smoothstep(s / (steps + 1)) if mira else (s / (steps + 1))
                    blended = Image.blend(a_img, nxt, alpha)
                    arr = np.asarray(blended)
                    writer.append_data(arr)
                    last_arr = arr
                    last_pil = blended
                    written += 1
        while written < need and last_arr is not None:
            writer.append_data(last_arr)
            written += 1
    finally:
        writer.close()

    actual = written / float(fps) if fps else 0.0
    ok = out_path.exists() and out_path.stat().st_size > 1000
    return ok, actual


def _write_mp4_holds(
    segments: list[tuple[Any, float, int]],
    out_path: Path,
    *,
    target_sec: float,
    crossfade_sec: float = 0.4,
    force_fps: int | None = None,
    max_wh: tuple[int, int] | None = None,
) -> tuple[bool, float]:
    """Fast assemble: hold resized stills with short crossfades — Pillow/imageio path."""
    try:
        import imageio.v2 as imageio
        import numpy as np
        from PIL import Image
    except Exception:
        return False, 0.0

    light = bool(force_fps and int(force_fps) > 0 and int(force_fps) <= 15)
    fps = int(force_fps) if force_fps and int(force_fps) > 0 else _effective_fps(target_sec)
    if fps >= 30 and crossfade_sec < 0.4:
        crossfade_sec = 0.4
    if light:
        crossfade_sec = min(float(crossfade_sec), 0.2)

    tw, th = max_wh if max_wh else ((1280, 720) if light else _sync_wh_fps()[:2])

    def _fit(img: Any) -> Any:
        base = img.convert("RGB")
        if base.size == (tw, th):
            return base
        resample = getattr(Image, "Resampling", Image).BILINEAR if light else getattr(Image, "Resampling", Image).LANCZOS
        return base.resize((tw, th), resample)

    need = max(1, int(round(float(target_sec) * fps)))
    written = 0
    try:
        writer = imageio.get_writer(out_path, **_writer_kwargs(fps, light=light))
    except Exception:
        try:
            writer = imageio.get_writer(out_path, fps=fps, codec="libx264", quality=7, pixelformat="yuv420p")
        except Exception:
            return False, 0.0

    try:
        last_arr = None
        for i, (img, dur, _variant) in enumerate(segments):
            if written >= need:
                break
            frame = _fit(img)
            arr = np.asarray(frame)
            fade_budget = crossfade_sec if i + 1 < len(segments) else 0.0
            hold_main = max(0.35, float(dur) - fade_budget)
            n_hold = max(1, int(round(hold_main * fps)))
            for _ in range(n_hold):
                if written >= need:
                    break
                writer.append_data(arr)
                last_arr = arr
                written += 1
            if fade_budget > 0 and i + 1 < len(segments) and written < need and last_arr is not None:
                nxt = _fit(segments[i + 1][0])
                steps = max(2, int(round(fade_budget * fps)))
                if light:
                    steps = min(steps, 3)
                a_img = Image.fromarray(last_arr)
                for s in range(1, steps + 1):
                    if written >= need:
                        break
                    blended = Image.blend(a_img, nxt, s / (steps + 1))
                    b_arr = np.asarray(blended)
                    writer.append_data(b_arr)
                    last_arr = b_arr
                    written += 1
        while written < need and last_arr is not None:
            writer.append_data(last_arr)
            written += 1
    finally:
        writer.close()

    actual = written / float(fps) if fps else 0.0
    ok = out_path.exists() and out_path.stat().st_size > 1000
    return ok, actual


def _target_duration(storyboard: dict[str, Any], slides_fallback: list[tuple[Any, float]] | None = None) -> int:
    raw = storyboard.get("duration_sec") or storyboard.get("target_duration_sec")
    if raw is not None:
        return clamp_duration_sec(raw)
    if slides_fallback:
        total = sum(float(d) for _, d in slides_fallback)
        if total >= MIN_DURATION_SEC:
            return clamp_duration_sec(total)
    shots = storyboard.get("shot_list") or []
    shot_sum = 0.0
    for s in shots:
        if isinstance(s, dict):
            try:
                shot_sum += float(s.get("duration_sec") or 0)
            except (TypeError, ValueError):
                pass
    if shot_sum >= MIN_DURATION_SEC:
        return clamp_duration_sec(shot_sum)
    return DEFAULT_DURATION_SEC


def _distribute_durations(n: int, target: float, preferred: list[float] | None = None) -> list[float]:
    """Split target seconds across n segments (prefer shot durations when they sum close)."""
    if n <= 0:
        return []
    target = float(max(MIN_DURATION_SEC, min(MAX_DURATION_SEC, target)))
    if preferred and len(preferred) >= n:
        prefs = [max(0.5, float(preferred[i])) for i in range(n)]
        s = sum(prefs)
        if s > 0:
            scale = target / s
            out = [p * scale for p in prefs]
            # Fix rounding drift on last
            out[-1] = max(0.5, target - sum(out[:-1]))
            return out
    each = target / n
    out = [each] * n
    out[-1] = max(0.5, target - sum(out[:-1]))
    return out


def _expand_stills_for_duration(
    still_imgs: list[Any],
    target_sec: float,
    *,
    max_unique_hold: float = 28.0,
) -> list[tuple[Any, float, int]]:
    """
    Build (image, duration, ken_burns_variant) list totaling ≈ target_sec.
    Cycles stills with variant bumps when a single hold would be too long.
    """
    if not still_imgs:
        return []
    target_sec = float(clamp_duration_sec(target_sec))
    n = len(still_imgs)
    # Ideal: one pass; if each would exceed max_unique_hold, cycle more cuts
    min_cuts = max(n, int(round(target_sec / max_unique_hold)))
    cuts = max(n, min_cuts)
    # Cap absurd cut counts (e.g. very long + 1 still)
    cuts = min(cuts, max(n * 4, n))
    durs = _distribute_durations(cuts, target_sec)
    out: list[tuple[Any, float, int]] = []
    for i, dur in enumerate(durs):
        img = still_imgs[i % n]
        variant = (i // n) + (i % n)
        out.append((img, float(dur), variant))
    return out


def _build_slides(storyboard: dict[str, Any]) -> list[tuple[Any, float]]:
    # Metadata title may contain user prompts — never draw it; use brand cards only
    _ = str(storyboard.get("title") or "VERIDIQ Demo")
    logline = str(storyboard.get("logline") or "")
    shots = storyboard.get("shot_list") or []
    target = _target_duration(storyboard)
    if not shots:
        shots = [
            {
                "scene": 1,
                "duration_sec": target,
                "on_screen_text": "VERIDIQ",
                "voiceover": logline or "VERIDIQ",
                "shot": logline or "VERIDIQ",
            }
        ]
    imgs: list[Any] = []
    prefs: list[float] = []
    for i, shot in enumerate(shots):
        if not isinstance(shot, dict):
            continue
        # Never burn "Scene N" or raw user prompts onto frames
        ost = str(shot.get("on_screen_text") or "").strip()
        head = ost or "VERIDIQ"
        if (
            re.search(r"\bscene\s*\d+\b", head, re.I)
            or len(head) > 40
            or re.search(
                r"\b(create|make|generate)\s+(a\s+)?(video|clip|image)\b",
                head,
                re.I,
            )
        ):
            head = "VERIDIQ"
        img = _draw_slide(title=head, subtitle="Truth. Verified.", body="", scene_label="VERIDIQ")
        imgs.append(img)
        try:
            prefs.append(float(shot.get("duration_sec") or 3))
        except (TypeError, ValueError):
            prefs.append(3.0)
    if not imgs:
        return []
    durs = _distribute_durations(len(imgs), target, prefs)
    return list(zip(imgs, durs))


def render_storyboard_from_stills(
    storyboard: dict[str, Any],
    still_paths: list[str],
    *,
    audio_path: Optional[str] = None,
    fast_hold: bool = False,
    mira_cinematic: bool = False,
    crossfade_sec: float | None = None,
    caption_lines: list[str] | None = None,
    force_fps: int | None = None,
    burn_captions: bool = False,
) -> dict[str, Any]:
    """Assemble AI still images into a real GIF/MP4 slideshow matching duration_sec.

    Default: gentle Ken Burns + crossfade between distinct stills.
    fast_hold=True: repeat resized frames (faster encode, less motion).
    mira_cinematic=True: stronger pan/zoom, longer eased crossfades, mid-frame
    blends, mild unsharp — Mira Cinematic Engine path (still not generative Veo).
    force_fps: override encode FPS (e.g. 12 for reliability / local-still path).
    burn_captions: OFF by default — never burn scene labels; only polished VO when True.
    """
    from PIL import Image

    st = status()
    if not st.get("configured"):
        return {
            "status": "configuration_required",
            "ok": False,
            "message": st.get("message") or "Local video renderer not available.",
        }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sid = re.sub(r"[^a-zA-Z0-9_-]+", "", str(storyboard.get("storyboard_id") or "local"))[:48] or "local"
    shots = storyboard.get("shot_list") or []
    target = _target_duration(storyboard)
    aspect = str(storyboard.get("aspect") or storyboard.get("aspect_ratio") or "16:9").strip()
    portrait = aspect in ("9:16", "9/16", "portrait", "vertical")
    w, h, fps = _sync_wh_fps(portrait=portrait)
    if force_fps and int(force_fps) > 0:
        fps = int(force_fps)
    use_fast = bool(fast_hold) and not mira_cinematic
    # Reliability / fast-hold: keep native ~720p — skip 1080p Lanczos upscale
    if use_fast and force_fps and int(force_fps) <= 15:
        w, h = (1080, 1280) if portrait else (1280, 720)

    still_imgs: list[Any] = []
    prefs: list[float] = []
    for i, path_str in enumerate(still_paths):
        p = Path(path_str)
        if not p.is_file():
            continue
        try:
            raw = Image.open(p)
            if use_fast:
                still_imgs.append(raw.convert("RGB"))
            else:
                still_imgs.append(_resize_sharp(raw, unsharp=mira_cinematic))
        except Exception:
            continue
        if i < len(shots) and isinstance(shots[i], dict):
            try:
                prefs.append(float(shots[i].get("duration_sec") or 3))
            except (TypeError, ValueError):
                prefs.append(3.0)
        else:
            prefs.append(3.0)

    caps = list(caption_lines or [])
    # Never pull shot voiceover/on_screen_text as burn-in (often raw prompt / scene N)
    # Only keep polished VO lines when explicitly requested via burn_captions
    if caps:
        caps = [
            re.sub(r"\b(?:this\s+is\s+)?scene\s*(?:one|two|three|\d+)\b", "", c, flags=re.I).strip()
            for c in caps
        ]
        caps = [c for c in caps if c and not re.match(r"^(scene|shot)\b", c, re.I)]

    if not still_imgs:
        return render_storyboard(storyboard, audio_path=audio_path)

    # Redistribute full target across available stills (never leave at 2×3s=6s)
    segments = _expand_stills_for_duration(still_imgs, target)
    if not segments:
        return render_storyboard(storyboard, audio_path=audio_path)

    mp4_path = OUT_DIR / f"{sid}.mp4"
    # Mira never uses static fast_hold — motion is the product differentiator vs soft slideshow
    xf = 0.7 if mira_cinematic else 0.35
    if crossfade_sec is not None:
        xf = float(crossfade_sec)
    if use_fast:
        ok_mp4, actual_sec = _write_mp4_holds(
            segments,
            mp4_path,
            target_sec=float(target),
            crossfade_sec=xf,
            force_fps=force_fps,
            max_wh=(w, h),
        )
        assemble_note = f"fast hold + crossfade @{fps}fps"
    else:
        ok_mp4, actual_sec = _write_mp4_streaming(
            segments,
            mp4_path,
            target_sec=float(target),
            crossfade_sec=xf,
            mira=mira_cinematic,
        )
        assemble_note = (
            "Mira cinematic (Ken Burns + mid-frame blends + unsharp)"
            if mira_cinematic
            else "Ken Burns + crossfade"
        )
    if ok_mp4:
        muxed = _maybe_mux_audio(mp4_path, audio_path, sid)
        path = muxed.get("path") or mp4_path
        # Caption burn OFF by default — ruins product look with scene labels / prompt dumps
        if burn_captions and caps:
            capped = _maybe_burn_captions(path, caps, float(actual_sec or target), sid)
            if capped.get("path"):
                path = capped["path"]
                if capped.get("message"):
                    assemble_note = f"{assemble_note}; {capped['message']}"
        payload = _ok_payload(storyboard, sid, path, kind="mp4", duration_sec=actual_sec or target)
        # Reflect actual encode size/fps (reliability may be 1280x720 @ 12fps)
        payload["width"] = w
        payload["height"] = h
        payload["fps"] = fps
        audio_note = muxed.get("message") or ""
        payload["message"] = (
            f"{format_duration_label(actual_sec or target)} video ready "
            f"({path.stat().st_size // 1024} KB) — {len(still_imgs)} unique still(s), "
            f"{len(segments)} holds @ {assemble_note} {w}x{h} @{fps}fps. {audio_note}"
        ).strip()
        if muxed.get("audio_url") and not muxed.get("muxed"):
            payload["audio_url"] = muxed["audio_url"]
            payload["audio_separate"] = True
        elif muxed.get("muxed"):
            payload["has_audio"] = True
        if mira_cinematic:
            payload["mira_engine"] = True
            payload["motion_mode"] = "mira_cinematic"
            payload["generative_motion"] = False
            payload["veo_motion"] = False
        return payload

    # GIF fallback — hold stills (no full Ken Burns to keep file smaller)
    gif_path = OUT_DIR / f"{sid}.gif"
    durs = _distribute_durations(len(still_imgs), target, prefs[: len(still_imgs)])
    frames = still_imgs
    durations_ms = [max(700, int(d * 1000)) for d in durs]
    frames[0].save(
        gif_path,
        save_all=True,
        append_images=frames[1:],
        duration=durations_ms,
        loop=0,
        optimize=False,
        quality=95,
    )
    if not gif_path.exists():
        return {"status": "error", "ok": False, "message": "Failed to write stills video."}
    payload = _ok_payload(storyboard, sid, gif_path, kind="gif", duration_sec=sum(durs))
    payload["message"] = (
        f"{format_duration_label(sum(durs))} GIF ready ({gif_path.stat().st_size // 1024} KB) — "
        f"{len(still_imgs)} still(s) held to match requested length."
    )
    return payload


def render_storyboard(
    storyboard: dict[str, Any],
    *,
    audio_path: Optional[str] = None,
) -> dict[str, Any]:
    """Write a real local media file from storyboard. Unlimited / $0."""
    st = status()
    if not st.get("configured"):
        return {
            "status": "configuration_required",
            "ok": False,
            "message": st.get("message") or "Local video renderer not available.",
        }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sid = re.sub(r"[^a-zA-Z0-9_-]+", "", str(storyboard.get("storyboard_id") or "local"))[:48] or "local"
    aspect = str(storyboard.get("aspect") or storyboard.get("aspect_ratio") or "16:9").strip()
    portrait = aspect in ("9:16", "9/16", "portrait", "vertical")
    _sync_wh_fps(portrait=portrait)
    slides = _build_slides(storyboard or {})
    if not slides:
        return {"status": "error", "ok": False, "message": "No slides generated from storyboard."}

    target = _target_duration(storyboard, slides)
    # Stream title-card segments too (avoids huge RAM on long demos)
    card_segments: list[tuple[Any, float, int]] = [
        (img, float(dur), i) for i, (img, dur) in enumerate(slides)
    ]
    mp4_path = OUT_DIR / f"{sid}.mp4"
    ok_mp4, actual_sec = _write_mp4_streaming(card_segments, mp4_path, target_sec=float(target))
    if ok_mp4:
        muxed = _maybe_mux_audio(mp4_path, audio_path, sid)
        path = muxed.get("path") or mp4_path
        payload = _ok_payload(storyboard, sid, path, kind="mp4", duration_sec=actual_sec or target)
        note = muxed.get("message") or ""
        payload["message"] = (
            f"Local free MP4 ready — {format_duration_label(actual_sec or target)} "
            f"({path.stat().st_size // 1024} KB), unlimited $0. {note}"
        ).strip()
        if muxed.get("audio_url") and not muxed.get("muxed"):
            payload["audio_url"] = muxed["audio_url"]
            payload["audio_separate"] = True
        elif muxed.get("muxed"):
            payload["has_audio"] = True
        return payload

    gif_path = OUT_DIR / f"{sid}.gif"
    frames = [s[0] for s in slides]
    durations_ms = [max(700, int(s[1] * 1000)) for s in slides]
    frames[0].save(
        gif_path,
        save_all=True,
        append_images=frames[1:],
        duration=durations_ms,
        loop=0,
        optimize=False,
    )
    if not gif_path.exists() or gif_path.stat().st_size < 500:
        return {"status": "error", "ok": False, "message": "Local GIF was not written."}
    return _ok_payload(storyboard, sid, gif_path, kind="gif", duration_sec=sum(s[1] for s in slides))


def _try_mp4_frames(frames: list[Any], out_path: Path) -> bool:
    try:
        import imageio.v2 as imageio
        import numpy as np
    except Exception:
        return False
    try:
        arrs = [np.asarray(f) for f in frames]
        if not arrs:
            return False
        imageio.mimsave(
            out_path,
            arrs,
            fps=FPS,
            codec="libx264",
            quality=8,
            pixelformat="yuv420p",
            macro_block_size=1,
        )
        return out_path.exists() and out_path.stat().st_size > 1000
    except Exception:
        try:
            import imageio.v2 as imageio
            import numpy as np

            arrs = [np.asarray(f) for f in frames]
            imageio.mimsave(out_path, arrs, fps=FPS, codec="libx264", quality=8, pixelformat="yuv420p")
            return out_path.exists() and out_path.stat().st_size > 1000
        except Exception:
            return False


def _try_mp4(slides: list[tuple[Any, float]], out_path: Path) -> bool:
    """Legacy helper: expand (img, dur) slides then write MP4."""
    frames: list[Any] = []
    for img, dur in slides:
        n = max(1, int(round(float(dur) * FPS)))
        frames.extend([img] * n)
    return _try_mp4_frames(frames, out_path)


def _resolve_audio_file(audio_path: Optional[str]) -> Optional[Path]:
    if not audio_path:
        return None
    p = Path(str(audio_path))
    if p.is_file():
        return p
    # Relative from repo root
    cand = _ROOT / str(audio_path).lstrip("/").replace("\\", "/")
    if cand.is_file():
        return cand
    # marketing API style path fragment
    name = Path(str(audio_path)).name
    for folder in (_ROOT / "marketing_out" / "audio", OUT_DIR):
        c2 = folder / name
        if c2.is_file():
            return c2
    return None


def _ffmpeg_exe() -> Optional[str]:
    """Prefer system ffmpeg; fall back to imageio-ffmpeg's Windows/Linux binary."""
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def _write_poster_still(video_path: Path, *, seek_sec: float = 0.1) -> Optional[Path]:
    """Extract a visible first-frame JPEG next to the MP4 for <video poster=>."""
    ffmpeg = _ffmpeg_exe()
    if not ffmpeg or not video_path.is_file():
        return None
    poster = video_path.with_name(f"{video_path.stem}_poster.jpg")
    try:
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-ss",
                str(seek_sec),
                "-i",
                str(video_path),
                "-frames:v",
                "1",
                "-q:v",
                "3",
                str(poster),
            ],
            check=True,
            capture_output=True,
            timeout=60,
        )
    except Exception:
        return None
    return poster if poster.is_file() and poster.stat().st_size > 200 else None


def concat_video_segments(
    segment_paths: list[str],
    *,
    filename_stem: str | None = None,
    audio_path: Optional[str] = None,
) -> dict[str, Any]:
    """Concatenate Veo (or other) MP4 clips with ffmpeg concat demuxer.

    Used when a target duration needs 2–4 short Veo clips stitched into one
    1080p timeline. Optionally muxes narration afterward.
    """
    import uuid

    ffmpeg = _ffmpeg_exe()
    if not ffmpeg:
        return {
            "ok": False,
            "status": "error",
            "message": "ffmpeg required to concatenate Veo segments.",
        }
    paths: list[Path] = []
    for p in segment_paths or []:
        cand = Path(str(p))
        if cand.is_file() and cand.stat().st_size > 1000:
            paths.append(cand)
    if not paths:
        return {"ok": False, "status": "error", "message": "No valid Veo segments to concatenate."}
    if len(paths) == 1 and not audio_path:
        only = paths[0]
        try:
            rel = str(only.relative_to(_ROOT)).replace("\\", "/")
        except ValueError:
            rel = str(only).replace("\\", "/")
        return {
            "ok": True,
            "status": "ok",
            "provider": "google_ai_veo",
            "format": "mp4",
            "video_path": rel,
            "video_url": f"/api/v1/veridiq/marketing/video/file/{only.name}",
            "absolute_path": str(only),
            "bytes": only.stat().st_size,
            "segments": 1,
            "veo_motion": True,
            "message": f"Single Veo clip ready ({only.stat().st_size // 1024} KB).",
        }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^a-zA-Z0-9_-]+", "", (filename_stem or uuid.uuid4().hex)[:40]) or uuid.uuid4().hex[:12]
    list_path = OUT_DIR / f"{stem}_concat.txt"
    out_path = OUT_DIR / f"{stem}_veo_concat.mp4"
    try:
        # ffmpeg concat demuxer — escape single quotes in Windows paths
        lines = []
        for p in paths:
            escaped = str(p.resolve()).replace("\\", "/").replace("'", "'\\''")
            lines.append(f"file '{escaped}'")
        list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_path),
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(out_path),
            ],
            check=True,
            capture_output=True,
            timeout=180,
        )
        if not out_path.is_file() or out_path.stat().st_size < 1000:
            # Re-encode fallback when stream copy fails across mismatched clips
            subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    str(list_path),
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-b:v",
                    VIDEO_BITRATE,
                    "-c:a",
                    "aac",
                    "-b:a",
                    "160k",
                    "-movflags",
                    "+faststart",
                    str(out_path),
                ],
                check=True,
                capture_output=True,
                timeout=300,
            )
    except Exception as exc:
        return {
            "ok": False,
            "status": "error",
            "message": f"Veo concat failed: {str(exc)[:160]}",
        }
    finally:
        try:
            list_path.unlink(missing_ok=True)  # type: ignore[call-arg]
        except Exception:
            pass

    if not out_path.is_file() or out_path.stat().st_size < 1000:
        return {"ok": False, "status": "error", "message": "Veo concat produced empty file."}

    muxed = _maybe_mux_audio(out_path, audio_path, stem)
    path = muxed.get("path") or out_path
    dur = _probe_media_duration(ffmpeg, path) or float(len(paths) * 5)
    w, h, fps = _sync_wh_fps()
    try:
        rel = str(path.relative_to(_ROOT)).replace("\\", "/")
    except ValueError:
        rel = str(path).replace("\\", "/")
    payload: dict[str, Any] = {
        "ok": True,
        "status": "ok",
        "provider": "google_ai_veo",
        "format": "mp4",
        "video_path": rel,
        "video_url": f"/api/v1/veridiq/marketing/video/file/{path.name}",
        "absolute_path": str(path),
        "bytes": path.stat().st_size,
        "duration_sec": round(float(dur), 2),
        "duration_label": format_duration_label(dur),
        "width": w,
        "height": h,
        "fps": fps,
        "segments": len(paths),
        "veo_motion": True,
        "message": (
            f"Veo concat ready — {format_duration_label(dur)} from {len(paths)} clip(s) "
            f"({path.stat().st_size // 1024} KB). {muxed.get('message') or ''}"
        ).strip(),
    }
    if muxed.get("audio_url") and not muxed.get("muxed"):
        payload["audio_url"] = muxed["audio_url"]
        payload["audio_separate"] = True
    elif muxed.get("muxed"):
        payload["has_audio"] = True
    return payload


def _write_srt(lines: list[str], duration_sec: float, path: Path) -> bool:
    """Write a simple evenly-timed SRT from VO caption lines."""
    clean = [re.sub(r"\s+", " ", (x or "").strip())[:90] for x in lines if (x or "").strip()]
    if not clean:
        return False
    total = max(1.0, float(duration_sec or 1.0))
    slot = total / len(clean)

    def _ts(sec: float) -> str:
        ms = int(round(sec * 1000))
        h, rem = divmod(ms, 3_600_000)
        m, rem = divmod(rem, 60_000)
        s, milli = divmod(rem, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{milli:03d}"

    parts: list[str] = []
    for i, text in enumerate(clean):
        start = i * slot
        end = min(total, (i + 1) * slot - 0.05)
        if end <= start:
            end = start + 0.4
        parts.append(f"{i + 1}\n{_ts(start)} --> {_ts(end)}\n{text}\n")
    try:
        path.write_text("\n".join(parts), encoding="utf-8")
        return path.is_file()
    except Exception:
        return False


def _maybe_burn_captions(
    video_path: Path,
    lines: list[str],
    duration_sec: float,
    sid: str,
) -> dict[str, Any]:
    """Burn simple SRT captions onto MP4 when ffmpeg is available (best-effort)."""
    ffmpeg = _ffmpeg_exe()
    if not ffmpeg or not video_path.is_file() or not lines:
        return {"path": video_path, "burned": False}
    srt = OUT_DIR / f"{sid}_caps.srt"
    if not _write_srt(lines, duration_sec, srt):
        return {"path": video_path, "burned": False}
    out = OUT_DIR / f"{sid}_cap.mp4"
    # Escape path for ffmpeg subtitles filter (Windows-safe-ish)
    srt_esc = str(srt).replace("\\", "/").replace(":", "\\:")
    try:
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(video_path),
                "-vf",
                f"subtitles='{srt_esc}':force_style='FontSize=18,PrimaryColour=&H00FFFFFF&,Outline=1'",
                "-c:a",
                "copy",
                "-movflags",
                "+faststart",
                str(out),
            ],
            check=True,
            capture_output=True,
            timeout=180,
        )
        if out.exists() and out.stat().st_size > 1000:
            try:
                video_path.unlink(missing_ok=True)  # type: ignore[call-arg]
            except TypeError:
                if video_path.exists():
                    video_path.unlink()
            out.replace(video_path)
            return {"path": video_path, "burned": True, "message": "captions burned"}
    except Exception:
        return {"path": video_path, "burned": False}
    return {"path": video_path, "burned": False}


def _maybe_mux_audio(video_path: Path, audio_path: Optional[str], sid: str) -> dict[str, Any]:
    """Mux soundtrack into MP4 when ffmpeg is available; else return separate audio_url.

    Aligns audio duration to video (trim/pad). Applies light mastering (loudnorm,
    soft highpass) at 48kHz stereo AAC. Does NOT do facial lip-sync — true phoneme
    mouth shapes need a talking-head model, not stills slideshow.
    """
    audio_file = _resolve_audio_file(audio_path)
    if not audio_file:
        return {"path": video_path, "muxed": False}

    audio_url = f"/api/v1/veridiq/marketing/audio/file/{audio_file.name}"
    ffmpeg = _ffmpeg_exe()
    if not ffmpeg:
        return {
            "path": video_path,
            "muxed": False,
            "audio_url": audio_url,
            "message": "Soundtrack ready separately (install ffmpeg to mux into MP4).",
        }

    # Probe video duration for VO fit
    video_dur = _probe_media_duration(ffmpeg, video_path) or float(DEFAULT_DURATION_SEC)
    fitted = audio_file
    try:
        from veridiq.voice.tts import master_and_fit_audio

        fitted_path = master_and_fit_audio(audio_file, target_duration_sec=video_dur)
        if fitted_path and fitted_path.is_file():
            fitted = fitted_path
    except Exception:
        fitted = audio_file

    out = OUT_DIR / f"{sid}_audio.mp4"
    try:
        # Master + mux: 48kHz stereo AAC ~160kbps; video duration wins (pad/trim via fitted VO)
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(video_path),
                "-i",
                str(fitted),
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "160k",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-shortest",
                "-movflags",
                "+faststart",
                str(out),
            ],
            check=True,
            capture_output=True,
            timeout=180,
        )
        if out.exists() and out.stat().st_size > 1000:
            try:
                video_path.unlink(missing_ok=True)  # type: ignore[call-arg]
            except TypeError:
                if video_path.exists():
                    video_path.unlink()
            out.replace(video_path)
            return {
                "path": video_path,
                "muxed": True,
                "message": (
                    "Soundtrack muxed (48kHz stereo AAC, duration-aligned). "
                    "Facial lip-sync not applied (stills cannot drive phonemes)."
                ),
            }
    except Exception as exc:
        return {
            "path": video_path,
            "muxed": False,
            "audio_url": audio_url,
            "message": f"Audio mux failed ({str(exc)[:80]}); play video + audio separately.",
        }
    return {
        "path": video_path,
        "muxed": False,
        "audio_url": audio_url,
        "message": "Soundtrack available separately (mux failed).",
    }


def _probe_media_duration(ffmpeg: str, path: Path) -> Optional[float]:
    """Return media duration in seconds via ffprobe-like ffmpeg -i parse."""
    try:
        proc = subprocess.run(
            [ffmpeg, "-i", str(path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        blob = (proc.stderr or "") + (proc.stdout or "")
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", blob)
        if m:
            h, mi, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
            return h * 3600 + mi * 60 + s
    except Exception:
        return None
    return None


def _ok_payload(
    storyboard: dict[str, Any],
    sid: str,
    path: Path,
    *,
    kind: str,
    duration_sec: float | None = None,
) -> dict[str, Any]:
    w, h, fps = _sync_wh_fps()
    try:
        rel = str(path.relative_to(_ROOT)).replace("\\", "/")
    except ValueError:
        rel = str(path).replace("\\", "/")
    media = "video/mp4" if kind == "mp4" else "image/gif"
    dur = float(duration_sec) if duration_sec is not None else float(
        storyboard.get("duration_sec") or DEFAULT_DURATION_SEC
    )
    poster_url = None
    if kind == "mp4":
        poster = _write_poster_still(path)
        if poster is not None:
            poster_url = f"/api/v1/veridiq/marketing/video/file/{poster.name}"
    payload = {
        "status": "ok",
        "ok": True,
        "provider": "local_video",
        "unlimited": True,
        "cost": 0,
        "format": kind,
        "media_type": media,
        "video_path": rel,
        "video_url": f"/api/v1/veridiq/marketing/video/file/{path.name}",
        "absolute_path": str(path),
        "bytes": path.stat().st_size,
        "fps": fps,
        "width": w,
        "height": h,
        "duration_sec": round(dur, 2),
        "duration_label": format_duration_label(dur),
        "veo_motion": False,
        "lip_sync": False,
        "message": (
            f"Local free {kind.upper()} ready — {format_duration_label(dur)} "
            f"({path.stat().st_size // 1024} KB), unlimited, $0, {w}x{h} @{fps}fps."
        ),
        "storyboard_id": storyboard.get("storyboard_id"),
    }
    if poster_url:
        payload["poster_url"] = poster_url
    return payload
