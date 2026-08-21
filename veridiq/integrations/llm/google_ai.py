"""Google AI Studio / Gemini — official Generative Language API."""

from __future__ import annotations

from typing import Any

import requests

from veridiq.integrations.llm._common import configured_status, http_get_json, require_token

PLATFORM = "google_ai"
DISPLAY = "Google AI Studio / Gemini"
CATEGORY = "ai"
ENV_VARS = ("VERIDIQ_GOOGLE_AI_API_KEY", "GOOGLE_API_KEY")
CAPABILITIES = ["list_models", "generate_text", "generate_image", "generate_video"]
DOCS = "https://ai.google.dev/gemini-api/docs"
BASE = "https://generativelanguage.googleapis.com/v1beta"
IMAGE_MODELS = (
    # Working Flash image models only — do NOT list removed preview IDs
    # (gemini-2.0-flash-preview-image-generation → 404 on v1beta).
    "gemini-2.5-flash-image",
    "gemini-2.0-flash-exp-image-generation",
)


def status() -> dict[str, Any]:
    return configured_status(
        PLATFORM,
        DISPLAY,
        CATEGORY,
        env_names=ENV_VARS,
        capabilities=CAPABILITIES,
        docs_url=DOCS,
        missing_message=f"Set {ENV_VARS[0]} (or GOOGLE_API_KEY) for Gemini API access.",
        configured_message="Google AI key present — use /test to verify with models.list.",
    )


def test_connection() -> dict[str, Any]:
    token, err = require_token(PLATFORM, *ENV_VARS)
    if err:
        return err
    resp, data, exc = http_get_json(f"{BASE}/models", params={"key": token, "pageSize": 5})
    if exc:
        return {"platform": PLATFORM, "status": "error", "ok": False, "message": exc}
    assert resp is not None
    if resp.status_code == 200:
        models = (data or {}).get("models") or []
        names = [m.get("name") for m in models[:3] if isinstance(m, dict)]
        return {
            "platform": PLATFORM,
            "status": "ok",
            "ok": True,
            "api_response_status": resp.status_code,
            "message": f"Gemini API reachable; sample models: {', '.join(n for n in names if n) or 'listed'}.",
            "model_count": len(models),
        }
    return {
        "platform": PLATFORM,
        "status": "error",
        "ok": False,
        "api_response_status": resp.status_code,
        "message": f"Gemini API HTTP {resp.status_code}.",
    }


def generate_text(*, prompt: str, model: str = "gemini-2.0-flash", **_kwargs: Any) -> dict[str, Any]:
    token, err = require_token(PLATFORM, *ENV_VARS)
    if err:
        return err
    if not (prompt or "").strip():
        return {"platform": PLATFORM, "status": "invalid_args", "ok": False, "message": "prompt is required."}
    model_id = model if model.startswith("models/") else f"models/{model}"
    try:
        r = requests.post(
            f"{BASE}/{model_id}:generateContent",
            params={"key": token},
            json={"contents": [{"parts": [{"text": prompt[:12000]}]}]},
            timeout=45,
        )
        payload = r.json() if "json" in (r.headers.get("content-type") or "").lower() else {}
        if r.status_code == 200:
            candidates = payload.get("candidates") or []
            text = ""
            if candidates:
                parts = ((candidates[0].get("content") or {}).get("parts")) or []
                text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
            return {
                "platform": PLATFORM,
                "status": "ok",
                "ok": True,
                "api_response_status": r.status_code,
                "model": model,
                "text": text[:8000],
                "message": "Gemini generateContent succeeded.",
            }
        err_msg = (payload.get("error") or {}).get("message") if isinstance(payload.get("error"), dict) else None
        return {
            "platform": PLATFORM,
            "status": "error",
            "ok": False,
            "api_response_status": r.status_code,
            "message": err_msg or f"Gemini HTTP {r.status_code}.",
        }
    except Exception as exc:
        return {"platform": PLATFORM, "status": "error", "ok": False, "message": str(exc)[:200]}


def generate_image(
    *,
    prompt: str,
    model: str = "gemini-2.5-flash-image",
    filename_stem: str | None = None,
    timeout: float = 90.0,
) -> dict[str, Any]:
    """Native Gemini image generation — opt-in paid/preview path.

    Free Mira path should NOT call this (use Pollinations). Broken/removed
    preview model IDs are skipped immediately.
    """
    import base64
    import os
    import re
    import uuid
    from pathlib import Path

    # Hard skip known-dead model IDs (404 on v1beta)
    _DEAD = frozenset(
        {
            "gemini-2.0-flash-preview-image-generation",
            "models/gemini-2.0-flash-preview-image-generation",
        }
    )

    token, err = require_token(PLATFORM, *ENV_VARS)
    if err:
        return err
    q = (prompt or "").strip()
    if not q:
        return {"platform": PLATFORM, "status": "invalid_args", "ok": False, "message": "prompt is required."}

    # Free tier default: skip Gemini image unless explicitly enabled
    flag = (os.getenv("VERIDIQ_USE_GEMINI_IMAGE") or "").strip().lower()
    if flag not in ("1", "true", "yes", "on"):
        return {
            "platform": PLATFORM,
            "status": "skipped",
            "ok": False,
            "message": "Gemini image skipped (free path). Set VERIDIQ_USE_GEMINI_IMAGE=1 to enable.",
            "provider": "google_ai",
        }

    out_dir = Path(__file__).resolve().parent.parent.parent.parent / "marketing_out" / "images"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^a-zA-Z0-9_-]+", "", (filename_stem or uuid.uuid4().hex)[:40]) or uuid.uuid4().hex[:12]
    stem = f"gem_{stem}_{uuid.uuid4().hex[:6]}"

    req_timeout = max(8.0, float(timeout or 90.0))
    models = [model] + [m for m in IMAGE_MODELS if m != model]
    models = [m for m in models if m and m not in _DEAD and f"models/{m}" not in _DEAD]
    last_err = "no model tried"
    for mid in models:
        if mid in _DEAD or mid.startswith("models/") and mid[7:] in {
            x.replace("models/", "") for x in _DEAD
        }:
            continue
        model_id = mid if mid.startswith("models/") else f"models/{mid}"
        try:
            r = requests.post(
                f"{BASE}/{model_id}:generateContent",
                params={"key": token},
                json={
                    "contents": [{"parts": [{"text": q[:2500]}]}],
                    "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
                },
                timeout=req_timeout,
            )
            payload = r.json() if "json" in (r.headers.get("content-type") or "").lower() else {}
            if r.status_code != 200:
                last_err = ((payload.get("error") or {}).get("message") if isinstance(payload.get("error"), dict) else None) or f"HTTP {r.status_code}"
                # Shorten; never return giant API dumps
                if "not found" in last_err.lower() or r.status_code == 404:
                    last_err = f"Gemini image model not found ({mid})"
                    continue
                if r.status_code == 429:
                    last_err = "Gemini image quota busy"
                    continue
                return {
                    "platform": PLATFORM,
                    "status": "error",
                    "ok": False,
                    "api_response_status": r.status_code,
                    "message": last_err[:120],
                    "provider": "google_ai",
                }
            parts = (((payload.get("candidates") or [{}])[0].get("content") or {}).get("parts")) or []
            text_bits: list[str] = []
            for part in parts:
                if not isinstance(part, dict):
                    continue
                if part.get("text"):
                    text_bits.append(str(part["text"]))
                inline = part.get("inlineData") or part.get("inline_data") or {}
                data_b64 = inline.get("data")
                mime = (inline.get("mimeType") or inline.get("mime_type") or "image/png").lower()
                if data_b64:
                    raw = base64.b64decode(data_b64)
                    ext = "png" if "png" in mime else "jpg"
                    path = out_dir / f"{stem}.{ext}"
                    path.write_bytes(raw)
                    rel = str(path.relative_to(Path(__file__).resolve().parent.parent.parent.parent)).replace("\\", "/")
                    return {
                        "platform": PLATFORM,
                        "status": "ok",
                        "ok": True,
                        "provider": "google_ai",
                        "model": mid,
                        "prompt": q[:500],
                        "caption": " ".join(text_bits)[:800],
                        "image_path": rel,
                        "image_url": f"/api/v1/veridiq/marketing/image/file/{path.name}",
                        "absolute_path": str(path),
                        "bytes": path.stat().st_size,
                        "message": f"Gemini image ready ({path.stat().st_size // 1024} KB, {mid}).",
                    }
            last_err = "Gemini returned no image bytes."
        except Exception as exc:
            last_err = str(exc)[:120]
            continue
    return {
        "platform": PLATFORM,
        "status": "error",
        "ok": False,
        "message": (last_err or "Gemini image failed")[:120],
        "provider": "google_ai",
    }


# Veo 3.1 models currently listed by Gemini API (paid preview).
VEO_MODELS = (
    "veo-3.1-generate-preview",
    "veo-3.1-fast-generate-preview",
    "veo-3.1-lite-generate-preview",
)


def _is_hard_veo_error(msg: str) -> bool:
    low = (msg or "").lower()
    return any(
        x in low
        for x in (
            "403",
            "429",
            "permission",
            "billing",
            "quota",
            "resource_exhausted",
            "resource exhausted",
            "not enabled",
            "payment",
        )
    )


def veo_enabled() -> bool:
    """Paid Veo is OFF by default — free unlimited path is the default.

    Only enable when VERIDIQ_GEMINI_VIDEO is explicitly 1/true/yes/on.
    Having a Google AI key alone does NOT turn Veo on.
    """
    import os

    flag = (os.getenv("VERIDIQ_GEMINI_VIDEO") or "").strip().lower()
    return flag in ("1", "true", "yes", "on")


def generate_video(
    *,
    prompt: str,
    duration_sec: int = 5,
    model: str = "veo-3.1-generate-preview",
    filename_stem: str | None = None,
    max_wait_sec: float = 240.0,
    aspect_ratio: str = "16:9",
    resolution: str = "1080p",
) -> dict[str, Any]:
    """Veo 3 / 3.1 text-to-video via google-genai SDK (paid/preview, opt-in).

    Disabled unless VERIDIQ_GEMINI_VIDEO=1. Default create_video uses free
    Pollinations stills + local assemble. Returns honest errors (403/billing/
    quota) — never fabricates a file. Clips are typically 4–8 seconds.
    """
    import os
    import re
    import time
    import uuid
    from pathlib import Path

    if not veo_enabled():
        return {
            "platform": PLATFORM,
            "status": "configuration_required",
            "ok": False,
            "message": "Veo off by default. Set VERIDIQ_GEMINI_VIDEO=1 only for paid Veo.",
            "provider": "google_ai_veo",
        }

    token, err = require_token(PLATFORM, *ENV_VARS)
    if err:
        return err
    q = (prompt or "").strip()
    if not q:
        return {"platform": PLATFORM, "status": "invalid_args", "ok": False, "message": "prompt is required."}

    try:
        from google import genai  # type: ignore
        from google.genai import types  # type: ignore
    except Exception:
        return {
            "platform": PLATFORM,
            "status": "configuration_required",
            "ok": False,
            "message": "Install google-genai to use Veo (pip install google-genai).",
            "provider": "google_ai_veo",
        }

    out_dir = Path(__file__).resolve().parent.parent.parent.parent / "marketing_out" / "videos"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^a-zA-Z0-9_-]+", "", (filename_stem or uuid.uuid4().hex)[:40]) or uuid.uuid4().hex[:12]
    stem = f"veo_{stem}_{uuid.uuid4().hex[:6]}"
    dur = max(4, min(8, int(duration_sec or 5)))
    env_model = (os.getenv("VERIDIQ_VEO_MODEL") or "").strip()
    models = [env_model] if env_model else []
    models += [model] + [m for m in VEO_MODELS if m != model and m != env_model]
    # de-dupe preserve order
    seen: set[str] = set()
    model_list = []
    for m in models:
        if m and m not in seen:
            seen.add(m)
            model_list.append(m)

    last_err = "no Veo model tried"
    last_status = 0
    try:
        client = genai.Client(api_key=token)
    except Exception as exc:
        return {
            "platform": PLATFORM,
            "status": "error",
            "ok": False,
            "message": f"Veo client init failed: {str(exc)[:160]}",
            "provider": "google_ai_veo",
        }

    for mid in model_list:
        try:
            # Prefer rich config; fall back if SDK rejects unknown fields.
            # Note: enhance_prompt is NOT supported on current Veo 3.1 preview models.
            config_kwargs: dict[str, Any] = {
                "number_of_videos": 1,
                "duration_seconds": dur,
            }
            # Optional cinematic knobs (supported on newer SDK / Veo 3.1)
            for key, val in (
                ("aspect_ratio", aspect_ratio or "16:9"),
                ("resolution", resolution or "1080p"),
            ):
                if val:
                    config_kwargs[key] = val

            try:
                cfg = types.GenerateVideosConfig(**config_kwargs)
            except TypeError:
                cfg = types.GenerateVideosConfig(
                    number_of_videos=1,
                    duration_seconds=dur,
                )

            # Prefer modern source= API; fall back to prompt= for older SDKs
            try:
                source = types.GenerateVideosSource(prompt=q[:2000])
                operation = client.models.generate_videos(model=mid, source=source, config=cfg)
            except (TypeError, AttributeError):
                operation = client.models.generate_videos(
                    model=mid,
                    prompt=q[:2000],
                    config=cfg,
                )
            deadline = time.monotonic() + max(45.0, float(max_wait_sec or 240.0))
            while not getattr(operation, "done", False):
                if time.monotonic() >= deadline:
                    last_err = f"Veo timed out on {mid}"
                    break
                time.sleep(8)
                operation = client.operations.get(operation)
            else:
                # Check operation error
                op_err = getattr(operation, "error", None)
                if op_err:
                    last_err = str(op_err)[:240]
                    if _is_hard_veo_error(last_err):
                        return {
                            "platform": PLATFORM,
                            "status": "error",
                            "ok": False,
                            "message": last_err[:240],
                            "provider": "google_ai_veo",
                            "api_response_status": 429 if "429" in last_err or "quota" in last_err.lower() else None,
                        }
                    continue

                # Prefer .response then .result (SDK versions differ)
                result_obj = getattr(operation, "response", None) or getattr(operation, "result", None)
                videos = getattr(result_obj, "generated_videos", None) or []
                if not videos:
                    last_err = f"Veo {mid} returned no video — key may lack Veo access (paid preview)."
                    continue

                video_obj = videos[0].video
                path = out_dir / f"{stem}.mp4"
                raw = getattr(video_obj, "video_bytes", None) or getattr(video_obj, "data", None)
                saved = False
                if raw:
                    path.write_bytes(raw if isinstance(raw, (bytes, bytearray)) else bytes(raw))
                    saved = path.is_file() and path.stat().st_size >= 1000
                if not saved:
                    uri = getattr(video_obj, "uri", None)
                    if uri and str(uri).startswith("http"):
                        r = requests.get(str(uri), timeout=120)
                        if r.status_code == 200 and len(r.content) >= 1000:
                            path.write_bytes(r.content)
                            saved = True
                        else:
                            last_err = f"Veo download HTTP {r.status_code}"
                            last_status = r.status_code
                    else:
                        try:
                            client.files.download(file=video_obj)
                            if hasattr(video_obj, "save"):
                                video_obj.save(str(path))
                                saved = path.is_file() and path.stat().st_size >= 1000
                            else:
                                last_err = "Veo download unsupported in this SDK build."
                        except Exception as exc:
                            last_err = f"Veo download failed: {str(exc)[:160]}"

                if not saved or not path.is_file() or path.stat().st_size < 1000:
                    last_err = last_err if "download" in last_err.lower() or "HTTP" in last_err else "Veo file missing or too small."
                    continue

                rel = str(path.relative_to(Path(__file__).resolve().parent.parent.parent.parent)).replace("\\", "/")
                return {
                    "platform": PLATFORM,
                    "status": "ok",
                    "ok": True,
                    "provider": "google_ai_veo",
                    "model": mid,
                    "format": "mp4",
                    "duration_sec": dur,
                    "aspect_ratio": aspect_ratio or "16:9",
                    "resolution": resolution or "1080p",
                    "video_path": rel,
                    "video_url": f"/api/v1/veridiq/marketing/video/file/{path.name}",
                    "absolute_path": str(path),
                    "bytes": path.stat().st_size,
                    "veo_motion": True,
                    "message": f"Veo video ready ({path.stat().st_size // 1024} KB, {mid}, {dur}s).",
                }
            # timed out on this model — try next
            continue
        except Exception as exc:
            msg = str(exc)[:240]
            last_err = msg
            # Hard auth/billing/quota — stop trying more models (do not mask with later 404s)
            if _is_hard_veo_error(msg):
                low = msg.lower()
                return {
                    "platform": PLATFORM,
                    "status": "error",
                    "ok": False,
                    "message": msg,
                    "provider": "google_ai_veo",
                    "api_response_status": last_status
                    or (403 if "403" in low else (429 if ("429" in low or "quota" in low or "resource_exhausted" in low) else 0)),
                }
            continue

    return {
        "platform": PLATFORM,
        "status": "error",
        "ok": False,
        "message": last_err[:240],
        "provider": "google_ai_veo",
        "api_response_status": last_status or None,
    }
