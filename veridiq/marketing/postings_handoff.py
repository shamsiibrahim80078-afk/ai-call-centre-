"""Marketing → Postings handoff adapter.

Queues creative work for Mira Postings **without importing postings internals**.
Preferred path: HTTP POST to the existing public Postings agent API.
Fallback: write a draft artifact under ``marketing_out/handoff/`` and emit an
orchestration event so operators (or Postings UI) can pick it up.

Never sends live social posts — Postings / comms approval gates still apply.
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

logger = logging.getLogger("veridiq.marketing.postings_handoff")

_ROOT = Path(__file__).resolve().parent.parent.parent
HANDOFF_DIR = _ROOT / "marketing_out" / "handoff"

# Prefer internal loopback to the same API process. Override in multi-host deploys.
DEFAULT_API_BASE = os.getenv("VERIDIQ_INTERNAL_API_BASE", "http://127.0.0.1:8002").rstrip("/")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _enabled() -> bool:
    raw = (os.getenv("VERIDIQ_MARKETING_POSTINGS_HANDOFF", "1") or "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _write_local_artifact(
    *,
    caption: str,
    topic: str,
    channel: Optional[str],
    campaign_id: Optional[str],
    created_by_agent: Optional[str],
    draft_id: Optional[str],
) -> dict[str, Any]:
    HANDOFF_DIR.mkdir(parents=True, exist_ok=True)
    handoff_id = f"handoff-{uuid.uuid4().hex[:12]}"
    path = HANDOFF_DIR / f"{handoff_id}.json"
    payload = {
        "handoff_id": handoff_id,
        "status": "queued_local",
        "topic": topic,
        "caption": caption,
        "channel": channel,
        "campaign_id": campaign_id,
        "created_by_agent": created_by_agent,
        "source_draft_id": draft_id,
        "suggested_postings_message": (
            f"draft a post about {topic}: {caption[:500]}" if topic else f"draft a post: {caption[:600]}"
        ),
        "created_at": _utc_now(),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    try:
        rel = str(path.relative_to(_ROOT)).replace("\\", "/")
    except ValueError:
        rel = str(path).replace("\\", "/")
    return {**payload, "artifact_path": rel}


def _http_postings_draft(*, message: str, timeout_sec: float = 12.0, retries: int = 3) -> dict[str, Any]:
    """Call public Postings agent endpoint — no postings package import.

    Retries on transient network / 5xx / rate-limit failures; never raises.
    """
    import time

    url = f"{DEFAULT_API_BASE}/api/v1/veridiq/postings/agent"
    body = json.dumps({"message": message}).encode("utf-8")
    attempts = max(1, min(5, int(retries)))
    last: dict[str, Any] = {"ok": False, "status": "unreachable", "message": "no attempts"}
    for attempt in range(1, attempts + 1):
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
                    "attempts": attempt,
                }
        except urlerror.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:400]
            last = {
                "ok": False,
                "status": "http_error",
                "http_status": exc.code,
                "message": detail or str(exc),
                "attempts": attempt,
            }
            # Retry rate limits and upstream 5xx only
            if exc.code not in {408, 429, 500, 502, 503, 504} or attempt >= attempts:
                logger.warning(
                    "postings handoff HTTP %s (attempt %s/%s): %s",
                    exc.code,
                    attempt,
                    attempts,
                    (detail or str(exc))[:120],
                )
                return last
            backoff = min(8.0, 0.4 * (2 ** (attempt - 1)))
            logger.info("postings handoff retrying in %.1fs after HTTP %s", backoff, exc.code)
            time.sleep(backoff)
        except Exception as exc:  # noqa: BLE001 — honest adapter failure
            last = {
                "ok": False,
                "status": "unreachable",
                "message": str(exc)[:300],
                "attempts": attempt,
            }
            if attempt >= attempts:
                logger.warning("postings handoff unreachable after %s attempts: %s", attempts, exc)
                return last
            backoff = min(8.0, 0.4 * (2 ** (attempt - 1)))
            logger.info("postings handoff retrying in %.1fs after %s", backoff, type(exc).__name__)
            time.sleep(backoff)
    return last


def _emit_event(payload: dict[str, Any]) -> None:
    try:
        from scheduler.event_bus import global_event_bus

        global_event_bus.emit(
            "marketing.postings_handoff",
            payload,
            source=payload.get("created_by_agent") or "marketing",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("postings handoff event emit failed: %s", exc)


def handoff_draft_to_postings(
    *,
    body: str,
    subject: str = "",
    channel: Optional[str] = None,
    campaign_id: Optional[str] = None,
    created_by_agent: Optional[str] = None,
    draft_id: Optional[str] = None,
    use_http: bool = True,
) -> dict[str, Any]:
    """Hand a marketing draft caption to the Postings queue/API.

    Returns an honest status dict. Never fabricates a live published post.
    """
    if not _enabled():
        return {
            "ok": False,
            "status": "disabled",
            "message": "Set VERIDIQ_MARKETING_POSTINGS_HANDOFF=1 to enable marketing→postings handoff.",
        }

    caption = (body or "").strip()
    if not caption:
        return {"ok": False, "status": "invalid_args", "message": "body/caption is required for handoff."}

    topic = (subject or "").strip() or (channel or "VeriDiQ")
    local = _write_local_artifact(
        caption=caption,
        topic=topic,
        channel=channel,
        campaign_id=campaign_id,
        created_by_agent=created_by_agent,
        draft_id=draft_id,
    )
    _emit_event(
        {
            "handoff_id": local["handoff_id"],
            "campaign_id": campaign_id,
            "created_by_agent": created_by_agent,
            "channel": channel,
            "artifact_path": local.get("artifact_path"),
        }
    )

    http_result: Optional[dict[str, Any]] = None
    if use_http:
        http_result = _http_postings_draft(message=local["suggested_postings_message"])

    ok = True  # local artifact always counts as a successful offline handoff
    status = "queued_local"
    message = f"Wrote handoff artifact {local['handoff_id']} under marketing_out/handoff/."
    if http_result and http_result.get("ok"):
        status = "handed_off"
        message = (
            f"Handed off to Postings API ({local['handoff_id']}). "
            "Mira will draft media/caption — nothing posts live until approved."
        )
    elif http_result and not http_result.get("ok"):
        status = "queued_local_http_pending"
        message = (
            f"{message} HTTP Postings call unavailable ({http_result.get('status')}: "
            f"{http_result.get('message', '')[:120]}). Artifact remains for retry."
        )

    return {
        "ok": ok,
        "status": status,
        "message": message,
        "handoff": local,
        "http": http_result,
        "links": [
            {"label": "Postings Studio", "href": "/dashboard/postings"},
            {"label": "Marketing Agency", "href": "/dashboard/marketing"},
        ],
    }


def handoff_pack_drafts(
    drafts: list[dict[str, Any]],
    *,
    created_by_agent: Optional[str] = None,
    max_items: int = 3,
    use_http: bool = True,
) -> dict[str, Any]:
    """Hand off up to ``max_items`` marketing draft rows to Postings."""
    results = []
    for draft in (drafts or [])[: max(0, int(max_items))]:
        results.append(
            handoff_draft_to_postings(
                body=str(draft.get("body") or draft.get("text") or ""),
                subject=str(draft.get("subject") or ""),
                channel=str(draft.get("channel") or draft.get("kind") or "").replace("marketing_", "") or None,
                campaign_id=draft.get("campaign_id"),
                created_by_agent=created_by_agent or draft.get("created_by_agent"),
                draft_id=draft.get("draft_id"),
                use_http=use_http,
            )
        )
    handed = sum(1 for r in results if r.get("ok"))
    return {
        "ok": handed > 0 or not drafts,
        "count": handed,
        "results": results,
        "message": f"Handed off {handed}/{len(results)} draft(s) toward Postings.",
    }
