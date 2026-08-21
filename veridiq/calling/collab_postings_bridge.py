"""Collaboration Hub → Postings (Mira) HTTP bridge.

Mirrors marketing handoff: call public ``POST /api/v1/veridiq/postings/agent``
without importing ``veridiq.postings`` engines. Results are shaped for hub UI.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib import error as urlerror
from urllib import request as urlrequest

logger = logging.getLogger("veridiq.calling.collab_postings_bridge")

_ROOT = Path(__file__).resolve().parent.parent.parent
HANDOFF_DIR = _ROOT / "marketing_out" / "handoff" / "collab"
DEFAULT_API_BASE = os.getenv("VERIDIQ_INTERNAL_API_BASE", "http://127.0.0.1:8002").rstrip("/")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _http_postings_agent(*, message: str, timeout_sec: float = 90.0) -> dict[str, Any]:
    url = f"{DEFAULT_API_BASE}/api/v1/veridiq/postings/agent"
    body = json.dumps({"message": message}).encode("utf-8")
    req = urlrequest.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urlrequest.urlopen(req, timeout=timeout_sec) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            data = json.loads(raw) if raw else {}
            return {
                "ok": bool(data.get("ok", True)),
                "status": "posted_via_http",
                "http_status": getattr(resp, "status", 200),
                "response": data,
            }
    except urlerror.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        return {
            "ok": False,
            "status": "http_error",
            "http_status": exc.code,
            "message": detail or str(exc),
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "status": "unreachable", "message": str(exc)[:300]}


def _extract_media_links(response: dict[str, Any]) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    seen: set[str] = set()

    def _add(label: str, href: Any) -> None:
        h = str(href or "").strip()
        if not h or h in seen:
            return
        seen.add(h)
        links.append({"label": label, "href": h})

    for key in ("image_url", "video_url", "audio_url", "url", "media_url"):
        if response.get(key):
            _add(key.replace("_", " ").title(), response[key])
    for item in response.get("media") or response.get("assets") or []:
        if isinstance(item, dict):
            _add(str(item.get("label") or item.get("kind") or "Media"), item.get("url") or item.get("href"))
        elif isinstance(item, str):
            _add("Media", item)
    result = response.get("result") if isinstance(response.get("result"), dict) else {}
    for key in ("image_url", "video_url", "url"):
        if result.get(key):
            _add(key.replace("_", " ").title(), result[key])
    draft = response.get("draft") if isinstance(response.get("draft"), dict) else {}
    if draft.get("image_url"):
        _add("Draft image", draft["image_url"])
    if draft.get("video_url"):
        _add("Draft video", draft["video_url"])
    return links


def _format_reply(http: dict[str, Any]) -> str:
    if not http.get("ok"):
        return (
            "Mira (Postings): Couldn’t reach the Postings agent just now "
            f"({http.get('status')}: {str(http.get('message') or '')[:120]}). "
            "Try again or open Postings Studio."
        )
    data = http.get("response") or {}
    reply = (
        data.get("reply")
        or data.get("message")
        or data.get("summary")
        or (data.get("draft") or {}).get("caption")
        or ""
    )
    reply = str(reply).strip()
    media = _extract_media_links(data if isinstance(data, dict) else {})
    parts = [f"Mira (Postings): {reply}"] if reply else ["Mira (Postings): Draft ready."]
    if data.get("job_id"):
        parts.append(f"Video job `{data['job_id']}` — poll Postings or wait for render.")
    for m in media[:4]:
        parts.append(f"{m['label']}: {m['href']}")
    if not reply and not media and not data.get("job_id"):
        parts.append("See Postings Studio for full artifacts.")
    return "\n".join(parts)


def handoff_collab_to_postings(
    *,
    message: str,
    thread_id: Optional[str] = None,
) -> dict[str, Any]:
    """Forward a collab-hub creative command to Mira Postings over HTTP."""
    text = (message or "").strip()
    if not text:
        return {"ok": False, "status": "invalid_args", "message": "message required", "reply_text": ""}

    HANDOFF_DIR.mkdir(parents=True, exist_ok=True)
    handoff_id = f"collab-{uuid.uuid4().hex[:12]}"
    artifact = {
        "handoff_id": handoff_id,
        "thread_id": thread_id,
        "message": text,
        "created_at": _utc_now(),
        "source": "collaboration_hub",
    }
    path = HANDOFF_DIR / f"{handoff_id}.json"
    path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")

    http = _http_postings_agent(message=text)
    reply_text = _format_reply(http)
    media = _extract_media_links((http.get("response") or {}) if http.get("ok") else {})

    out = {
        "ok": bool(http.get("ok")),
        "status": "handed_off" if http.get("ok") else http.get("status") or "failed",
        "message": reply_text,
        "reply_text": reply_text,
        "handoff_id": handoff_id,
        "artifact_path": str(path).replace("\\", "/"),
        "http": http,
        "media": media,
        "links": [
            {"label": "Open in Postings", "href": "/dashboard/postings"},
        ],
    }
    try:
        try:
            rel = str(path.relative_to(_ROOT)).replace("\\", "/")
        except ValueError:
            rel = str(path).replace("\\", "/")
        out["artifact_path"] = rel
        path.write_text(json.dumps({**artifact, "result": out}, indent=2), encoding="utf-8")
    except OSError:
        pass
    return out
