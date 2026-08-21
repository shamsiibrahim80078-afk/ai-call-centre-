"""Mira Creative Model — single facade for Postings Studio create_* intents.

Branding: **Mira Creative Model (Free)** — VERIDIQ first-party pipeline.
We did NOT train a neural net; this routes free open backends (Flux stills,
cinematic assemble, edge-tts, song bed, LLM drafts). Premium (Veo/fal) can be
switched on later via ``VERIDIQ_MIRA_TIER=premium`` + backend flags without
rewriting the agent.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from veridiq.postings import tiers

MODEL_NAME = "Mira Creative Model"
MODEL_ID = "mira_creative_free_v1"
MODEL_TAGLINE = (
    "Mira Creative Model (Free) — first-party pipeline for posts, images, "
    "designs, videos, and songs. Not a trained foundation model; not Google Veo."
)
RENDER_MESSAGE = "Created with Mira Creative Model (free unlimited)"

_VALID = frozenset(
    {
        "create_post",
        "draft_post",
        "create_image",
        "create_design",
        "create_video",
        "create_song",
        "chat",
        "help",
    }
)


def model_identity() -> dict[str, Any]:
    t = tiers.status()
    return {
        "mira_model": MODEL_NAME,
        "mira_engine": True,
        "model_id": MODEL_ID,
        "tier": t["tier"],
        "free_unlimited": t["tier"] == "free" or not t["is_premium"],
        "premium_ready": t["premium_ready"],
        "is_premium": t["is_premium"],
        "paid_veo": False if not t["is_premium"] else tiers.veo_flag_on(),
        "free_features": t["free_features"],
        "premium_features": t["premium_features"],
        "is_trained_foundation_model": False,
        "is_google_veo": False,
        "kind": "first_party_pipeline",
        "tagline": MODEL_TAGLINE,
        "message": t["message"],
    }


def _normalize_intent(intent: str) -> str:
    raw = (intent or "chat").strip().lower()
    if raw == "draft_post":
        return "create_post"
    if raw in _VALID:
        return raw
    return "chat"


def generate(intent: str, topic: str = "", **opts: Any) -> dict[str, Any]:
    """Single entry — route to free backends (premium video only when unlocked)."""
    route = _normalize_intent(intent)
    topic = str(topic or opts.get("topic") or "").strip()
    brand = {
        "mira_model": MODEL_NAME,
        "model_id": MODEL_ID,
        "tier": tiers.current_tier(),
        "mira_engine": True,
        "free_unlimited": True,
        "paid_veo": False,
    }

    if route == "create_post":
        out = _create_post(topic, **opts)
    elif route == "create_image":
        out = _create_image(topic, **opts)
    elif route == "create_design":
        out = _create_design(topic, **opts)
    elif route == "create_video":
        out = _create_video(topic, **opts)
    elif route == "create_song":
        out = _create_song(topic, **opts)
    elif route == "help":
        out = {
            "action": "help",
            "status": "ok",
            "message": opts.get("message")
            or (
                f"{MODEL_NAME} generates posts, images, designs, free unlimited "
                "videos, and songs. Premium native video is optional later."
            ),
        }
    else:
        out = _chat(topic or str(opts.get("message") or ""), **opts)

    if isinstance(out, dict):
        for k, v in brand.items():
            out.setdefault(k, v)
        out.setdefault("identity", model_identity())
    return out


def _create_post(topic: str, **opts: Any) -> dict[str, Any]:
    """Draft a social post (never publishes live)."""
    from veridiq.comms import draft_marketing_content
    from veridiq.marketing import get_or_create_default_campaign

    composed = opts.get("composed")
    if not isinstance(composed, dict):
        # Thin fallback when studio did not pre-compose via LLM
        channel = str(opts.get("channel") or "linkedin")
        feature_key = str(opts.get("feature_key") or "truth_verification")
        subject = str(opts.get("subject") or f"VERIDIQ — {topic[:80] or 'update'}")
        body = str(opts.get("body") or topic or "VERIDIQ update")[:4000]
        composed = {
            "subject": subject,
            "body": body,
            "channel": channel,
            "feature_key": feature_key,
            "provider": opts.get("provider") or "mira_creative",
        }

    campaign = get_or_create_default_campaign()
    draft = draft_marketing_content(
        channel=str(composed.get("channel") or "linkedin"),
        subject=str(composed.get("subject") or "VERIDIQ"),
        body=str(composed.get("body") or topic),
        campaign_id=campaign.get("campaign_id"),
        created_by_agent=str(opts.get("created_by_agent") or "posting_studio"),
    )
    provider = composed.get("provider") or "llm"
    note = ""
    if composed.get("gemini_fallback_reason") and provider != "google_ai":
        note = " (Gemini quota/unavailable — used fallback LLM.)"
    return {
        "action": "draft_post",
        "status": "ok",
        "draft": draft,
        "channel": composed.get("channel"),
        "provider": provider,
        "model": composed.get("model") or MODEL_ID,
        "message": (
            f"Draft ready via {MODEL_NAME} ({provider}) for "
            f"{composed.get('channel')}{note} — "
            "approve in Comms / Marketing before any live send."
        ),
        "links": {"comms": "/dashboard/comms", "marketing": "/dashboard/marketing"},
    }


def _create_image(topic: str, **opts: Any) -> dict[str, Any]:
    from veridiq.integrations.pollinations_image import clean_user_prompt
    from veridiq.postings.creative import detect_style, generate_best_image, is_brand_topic
    from veridiq.postings.uploads import copy_upload_as_image, resolve_attachment_paths

    attach_paths = resolve_attachment_paths(opts.get("attachments") or opts.get("attachment_paths"))
    if attach_paths:
        copied = copy_upload_as_image(attach_paths[0], filename_stem="up_img")
        if copied.get("ok"):
            return {
                "action": "create_image",
                "status": "ok",
                "image": copied,
                "image_url": copied.get("image_url"),
                "provider": "user_upload",
                "style": str(opts.get("style") or "upload"),
                "retry": False,
                "attachments_used": attach_paths[:8],
                "message": (
                    "Using your uploaded image"
                    + (f" ({len(attach_paths)} attached)." if len(attach_paths) > 1 else ".")
                ),
                "links": {"postings": "/dashboard/postings"},
            }

    title = str(opts.get("title") or "").strip() or "VERIDIQ image"
    raw_topic = (topic or title).strip()

    # Preserve brand intent before meta-word stripping (avoids wiping "veridiq"
    # and falling through to a generic cinematic prompt → random AI animals).
    brand_request = is_brand_topic(raw_topic) or is_brand_topic(title)
    cleaned = clean_user_prompt(raw_topic) or raw_topic
    meta_only = re.sub(
        r"\b(create|generate|make|draw|an?|the|not|as|text|image|imae|imag|imge|pic|picture|photo|visual|va)\b",
        "",
        cleaned,
        flags=re.I,
    )
    meta_only = re.sub(r"\s+", " ", meta_only).strip(" .,!?:;")
    if brand_request:
        cleaned = meta_only if len(meta_only) >= 3 else "VERIDIQ product brand visual"
        if not is_brand_topic(cleaned):
            cleaned = f"VERIDIQ {cleaned}".strip()
    elif len(meta_only) < 3:
        cleaned = "striking cinematic scene, dramatic lighting, vivid detail"
    prompt = cleaned if len(cleaned) > 8 else f"{title}: {cleaned}"
    try:
        from veridiq.postings.learning import apply_learned_quality

        prompt = apply_learned_quality(prompt, topic=raw_topic or cleaned)
    except Exception:
        pass
    style = str(opts.get("style") or detect_style(prompt))
    result = generate_best_image(
        prompt=prompt,
        style=style,
        width=int(opts.get("width") or 1280),
        height=int(opts.get("height") or 1280),
        filename_stem=str(opts.get("filename_stem") or "img"),
        prefer_pollinations=not brand_request,
    )
    ok = bool(result.get("ok") or result.get("status") == "ok")
    msg = result.get("message") or (
        f"Image ready via {MODEL_NAME}." if ok else "Image busy — wait a few seconds and retry."
    )
    if not ok and len(str(msg)) > 160:
        msg = "Image busy — free queue full. Wait a few seconds and retry."
    return {
        "action": "create_image",
        "status": "ok" if ok else (result.get("status") or "error"),
        "image": result if ok else {"ok": False, "retry": True, "message": msg},
        "image_url": result.get("image_url") if ok else None,
        "provider": result.get("provider") or "mira_creative",
        "style": style,
        "retry": (not ok),
        "message": msg,
        "links": {"postings": "/dashboard/postings"},
    }


def _create_design(topic: str, **opts: Any) -> dict[str, Any]:
    from veridiq.integrations import canva
    from veridiq.postings.creative import generate_best_image

    title = str(opts.get("title") or "").strip() or "VERIDIQ social design"
    subject = topic or title
    prompt = f"{subject}. Square social poster titled '{title}' for VERIDIQ"
    result = generate_best_image(
        prompt=prompt,
        style=str(opts.get("style") or "cartoon"),
        width=int(opts.get("width") or 1280),
        height=int(opts.get("height") or 1280),
        filename_stem=str(opts.get("filename_stem") or "design"),
    )
    canva_result: dict[str, Any] = {"status": "skipped", "message": "Canva optional."}
    try:
        if canva.status().get("configured"):
            canva_result = canva.create_design(
                title=title[:255], design_type="custom", width=1080, height=1080
            )
    except Exception:
        pass

    ok = result.get("ok") or result.get("status") == "ok"
    return {
        "action": "create_design",
        "status": "ok" if ok else (result.get("status") or "error"),
        "image": result,
        "image_url": result.get("image_url"),
        "design_brief": f"Prompt:\n{(result.get('prompt') or prompt)[:500]}",
        "provider": result.get("provider") or "mira_creative",
        "canva": canva_result,
        "message": result.get("message")
        or (
            f"Design image ready via {MODEL_NAME}."
            if ok
            else "Design image failed."
        ),
        "links": {"postings": "/dashboard/postings"},
    }


def _create_song(topic: str, **opts: Any) -> dict[str, Any]:
    from veridiq.postings.creative import generate_song

    subject = topic or str(opts.get("title") or "VERIDIQ")
    result = generate_song(topic=subject)
    return {
        "action": "create_song",
        "status": result.get("status") or "ok",
        "song": result,
        "lyrics": result.get("lyrics"),
        "audio_url": result.get("audio_url"),
        "message": result.get("message") or f"Song ready via {MODEL_NAME}.",
        "links": {"postings": "/dashboard/postings"},
    }


def _create_video(topic: str, **opts: Any) -> dict[str, Any]:
    """Free path: Mira Cinematic Engine. Premium Veo only when tiers unlock it.

    Studio may pass pre-built ``storyboard``, ``prompts``, ``audio_path``, etc.
    Default never calls Veo — keep ``VERIDIQ_MIRA_TIER=free``.
    """
    from veridiq.postings import mira_engine

    duration_sec = int(opts.get("duration_sec") or 15)
    aspect = str(opts.get("aspect") or "16:9")
    style = str(opts.get("style") or "cinematic")
    prompts = opts.get("prompts")
    storyboard = opts.get("storyboard")
    audio_path: Optional[str] = opts.get("audio_path")
    force_narration = bool(opts.get("force_narration", True))
    n_stills = opts.get("n_stills")

    # Optional premium-first attempt (locked until tier=premium + Veo flag)
    if opts.get("try_premium_first") and tiers.premium_video_unlocked():
        veo = try_premium_veo_video(
            prompts=list(prompts or []),
            duration_sec=duration_sec,
            filename_stem=str(opts.get("filename_stem") or "mira_premium"),
            audio_path=audio_path,
        )
        if isinstance(veo, dict) and veo.get("ok"):
            return {
                "ok": True,
                "status": "ok",
                "action": "create_video",
                "render": veo,
                "mira_engine": False,
                "paid_veo": True,
                "tier": "premium",
                "free_unlimited": False,
                "engine": "Google Veo (premium)",
                "provider": veo.get("provider") or "google_ai_veo",
                "duration_sec": veo.get("duration_sec") or duration_sec,
                "has_audio": bool(veo.get("has_audio") or audio_path),
                "audio_url": veo.get("audio_url"),
                "message": veo.get("message") or "Premium Veo video ready.",
                "storyboard": storyboard or {},
            }

    mira = mira_engine.generate_video(
        topic=topic or "cinematic scene",
        duration_sec=duration_sec,
        aspect=aspect,
        prompts=list(prompts) if prompts else None,
        style=style,
        storyboard=storyboard if isinstance(storyboard, dict) else None,
        audio_path=audio_path,
        force_narration=force_narration,
        n_stills=int(n_stills) if n_stills is not None else None,
        attachments=opts.get("attachments") or opts.get("attachment_paths"),
    )
    if isinstance(mira, dict):
        mira.setdefault("action", "create_video")
        mira.setdefault("mira_model", MODEL_NAME)
        mira.setdefault("tier", tiers.current_tier())
        # Brand free path even when underlying engine is Mira Cinematic
        if mira.get("ok"):
            msg = str(mira.get("message") or "")
            if MODEL_NAME not in msg and "Mira" in msg:
                mira["message"] = msg
            mira.setdefault("engine_display", MODEL_NAME)
    return mira if isinstance(mira, dict) else {
        "ok": False,
        "status": "error",
        "action": "create_video",
        "message": "Mira Creative Model video path returned no result.",
    }


def try_premium_veo_video(
    *,
    prompts: list[str],
    duration_sec: int,
    filename_stem: str,
    audio_path: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Premium-only Veo helper. Returns None when premium/Veo is locked (default).

    Does not import studio (avoids circular imports). Studio may still call its
    multi-clip Veo path when ``tiers.premium_video_unlocked()`` is True.
    """
    if not tiers.premium_video_unlocked():
        return None
    try:
        from veridiq.integrations.llm import google_ai
        from veridiq.postings.creative import build_cinematic_prompt

        if not google_ai.veo_enabled():
            return None
        pr = (prompts[0] if prompts else "") or build_cinematic_prompt(
            "cinematic VERIDIQ scene", "smooth motion"
        )
        result = google_ai.generate_video(
            prompt=pr,
            duration_sec=min(8, max(4, int(duration_sec or 8))),
            filename_stem=filename_stem,
            max_wait_sec=240.0,
        )
        if isinstance(result, dict) and result.get("ok") and audio_path:
            # Mux VO when caller provided audio (best-effort)
            try:
                from veridiq.integrations import local_video

                concat = local_video.concat_video_segments(
                    [str(result["absolute_path"])],
                    filename_stem=f"{filename_stem}_mux",
                    audio_path=audio_path,
                )
                if concat.get("ok"):
                    concat["veo_motion"] = True
                    concat["paid_veo"] = True
                    return concat
            except Exception:
                pass
            result["paid_veo"] = True
        return result if isinstance(result, dict) else None
    except Exception as exc:
        return {
            "ok": False,
            "status": "error",
            "message": f"Premium Veo failed: {str(exc)[:160]}",
            "provider": "google_ai_veo",
            "paid_veo": True,
        }


def _chat(message: str, **opts: Any) -> dict[str, Any]:
    """Light chat via gateway — media requests should use create_* intents."""
    history = opts.get("history") or []
    system = opts.get("system") or (
        f"You are Mira, powered by {MODEL_NAME}. You generate real media via "
        "create_image / create_video / create_song / create_post. Be brief."
    )
    hist_bits = ""
    for turn in list(history)[-6:]:
        if not isinstance(turn, dict):
            continue
        role = turn.get("role") or "user"
        text = (turn.get("text") or "")[:400]
        hist_bits += f"{role}: {text}\n"
    prompt = f"{system}\n\nRecent turns:\n{hist_bits}\nUser: {(message or '')[:1500]}\n\nAssistant:"
    try:
        from veridiq.integrations import ai_gateway

        gen = ai_gateway.generate(prompt=prompt, task_type="reason")
        if gen.get("ok") and (gen.get("text") or "").strip():
            return {
                "action": "chat",
                "status": "ok",
                "message": str(gen["text"]).strip()[:4000],
                "provider": gen.get("provider") or "mira_creative",
            }
    except Exception:
        pass
    # Allow studio to supply a ready reply
    if opts.get("fallback_message"):
        return {
            "action": "chat",
            "status": "ok",
            "message": str(opts["fallback_message"]),
            "provider": "mira_creative",
        }
    return {
        "action": "chat",
        "status": "ok",
        "message": (
            f"Hi — I'm Mira ({MODEL_NAME}). Ask me to create a post, image, "
            "design, free unlimited video, or song."
        ),
        "provider": "mira_creative",
    }


def status() -> dict[str, Any]:
    """Facade status for studio_status / UI."""
    ident = model_identity()
    t = tiers.status()
    return {
        **ident,
        "engine": MODEL_NAME,
        "engine_id": MODEL_ID,
        "tier": t["tier"],
        "premium_ready": True,
        "free_features": list(tiers.FREE_FEATURES),
        "premium_features": list(tiers.PREMIUM_FEATURES),
        "video_backend": (
            "veo_native"
            if tiers.premium_video_unlocked()
            else "mira_cinematic_free"
        ),
        "message": (
            f"{MODEL_TAGLINE} Tier={t['tier']}. "
            "Premium Veo locked until VERIDIQ_MIRA_TIER=premium and "
            "VERIDIQ_GEMINI_VIDEO=1."
        ),
    }
