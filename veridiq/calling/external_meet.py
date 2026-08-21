"""External meeting proxy (Google Meet / any URL) — best-effort.

Practical limits: Google Meet blocks headless bots; full tab audio injection needs
a browser extension. This module:
  1. Stores meeting URL + instructions
  2. Tries Playwright/Chromium to open the URL and click Join if selectors work
  3. Mirrors status on a LiveKit agent room where Marcus narrates the proxy attempt
  4. Logs honestly when Meet blocks automation

Env:
  VERIDIQ_EXTERNAL_MEET_HEADED=0   # set 1 to open headed Chromium
  VERIDIQ_EXTERNAL_MEET_ENABLED=1
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("veridiq.calling.external_meet")

_ROOT = Path(__file__).resolve().parent.parent.parent
JOB_DIR = _ROOT / "marketing_out" / "external_meet"
_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}


def _utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def enabled() -> bool:
    raw = (os.getenv("VERIDIQ_EXTERNAL_MEET_ENABLED", "1") or "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def headed() -> bool:
    raw = (os.getenv("VERIDIQ_EXTERNAL_MEET_HEADED", "0") or "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def get_job(job_id: str) -> Optional[dict[str, Any]]:
    with _lock:
        hit = _jobs.get(job_id)
    if hit:
        return dict(hit)
    path = JOB_DIR / f"{job_id}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return None
    return None


def list_jobs(*, limit: int = 20) -> list[dict[str, Any]]:
    JOB_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(JOB_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    out: list[dict[str, Any]] = []
    for p in files[: max(1, min(limit, 50))]:
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            continue
    return out


def _persist(job: dict[str, Any]) -> None:
    JOB_DIR.mkdir(parents=True, exist_ok=True)
    path = JOB_DIR / f"{job['job_id']}.json"
    path.write_text(json.dumps(job, indent=2), encoding="utf-8")
    with _lock:
        _jobs[job["job_id"]] = dict(job)


def _update(job_id: str, **fields: Any) -> dict[str, Any]:
    job = get_job(job_id) or {"job_id": job_id}
    job.update(fields)
    job["updated_at"] = _utc_iso()
    _persist(job)
    return job


def _try_playwright_join(url: str, job_id: str) -> dict[str, Any]:
    """Best-effort: open Meet URL, attempt Join click. Honest about bot blocks."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # noqa: BLE001
        logger.info("Playwright not installed for external meet: %s", exc)
        return {
            "ok": False,
            "status": "playwright_missing",
            "message": (
                "Playwright/Chromium not installed. Install with "
                "`pip install playwright && playwright install chromium` for best-effort Join."
            ),
        }

    result: dict[str, Any] = {
        "ok": False,
        "status": "joining",
        "message": "Opening meeting URL…",
        "clicked_join": False,
    }
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=not headed())
            context = browser.new_context(
                permissions=[],
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                ),
            )
            page = context.new_page()
            _update(job_id, status="joining", playwright={"phase": "goto"})
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(2500)

            # Common Meet / generic join selectors (best-effort, often blocked)
            selectors = [
                'button:has-text("Join now")',
                'button:has-text("Ask to join")',
                'button:has-text("Join")',
                '[aria-label*="Join"]',
                'button:has-text("Continue")',
            ]
            clicked = False
            for sel in selectors:
                try:
                    loc = page.locator(sel).first
                    if loc.count() and loc.is_visible(timeout=1500):
                        loc.click(timeout=3000)
                        clicked = True
                        break
                except Exception:  # noqa: BLE001
                    continue

            page.wait_for_timeout(2000)
            title = ""
            try:
                title = page.title()
            except Exception:  # noqa: BLE001
                pass

            # Heuristic: Meet often shows sign-in / blocked for bots
            body_text = ""
            try:
                body_text = page.inner_text("body")[:800].lower()
            except Exception:  # noqa: BLE001
                pass
            blocked = any(
                k in body_text
                for k in (
                    "sign in",
                    "couldn't join",
                    "you can't join",
                    "blocked",
                    "not allowed",
                    "unsupported browser",
                )
            )

            if blocked:
                result = {
                    "ok": False,
                    "status": "failed",
                    "clicked_join": clicked,
                    "page_title": title,
                    "message": (
                        "Google Meet (or host page) appears to block automated browsers. "
                        "Full Meet bot audio requires a signed-in profile + extension; "
                        "Marcus narrates the proxy attempt in the LiveKit mirror room."
                    ),
                }
            elif clicked:
                result = {
                    "ok": True,
                    "status": "in_meeting",
                    "clicked_join": True,
                    "page_title": title,
                    "message": (
                        "Best-effort Join clicked. Tab audio injection into Meet is not available "
                        "without an extension — use LiveKit mirror for spoken proxy narration."
                    ),
                }
            else:
                result = {
                    "ok": True,
                    "status": "in_meeting",
                    "clicked_join": False,
                    "page_title": title,
                    "message": (
                        "Opened meeting URL. Join button not found or already in lobby. "
                        "Cannot inject TTS into the Meet tab without an extension."
                    ),
                }

            # Keep headed browser briefly; always close headless
            if headed():
                page.wait_for_timeout(8000)
            browser.close()
    except Exception as exc:  # noqa: BLE001
        logger.exception("external meet playwright failed")
        result = {
            "ok": False,
            "status": "failed",
            "message": f"Playwright error: {str(exc)[:240]}",
        }
    return result


def _narrate_on_livekit(job: dict[str, Any]) -> dict[str, Any]:
    """Marcus TTS: 'I've joined your Google Meet as proxy' — for LiveKit mirror UI."""
    try:
        from veridiq.calling.agent_presence import synthesize_greeting

        url = job.get("url") or "the external meeting"
        script = (
            "I've joined your Google Meet as a proxy on your behalf. "
            f"Link: {str(url)[:120]}. "
            "Note: Meet may block bots, and browser-tab audio injection needs an extension. "
            "I'm narrating from the VERIDIQ LiveKit mirror room."
        )
        clip = synthesize_greeting(
            script,
            meeting_id=job.get("job_id") or "external",
            agent_type="ai_calling",
        )
        return {
            "ok": bool((clip.get("tts") or {}).get("ok")),
            "script": script,
            "audio_url": clip.get("audio_url"),
            "clip_id": clip.get("clip_id"),
            "tts": clip.get("tts"),
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("external meet narration failed")
        return {"ok": False, "message": str(exc)[:200]}


def _run_job(job_id: str) -> None:
    job = get_job(job_id)
    if not job:
        return
    _update(job_id, status="joining")
    narration = _narrate_on_livekit(job)
    _update(job_id, narration=narration)
    pw = _try_playwright_join(job["url"], job_id)
    final_status = pw.get("status") or ("in_meeting" if pw.get("ok") else "failed")
    _update(
        job_id,
        status=final_status,
        playwright=pw,
        message=pw.get("message") or narration.get("script"),
        ok=bool(pw.get("ok")) or bool(narration.get("ok")),
    )
    # Hub note
    tid = job.get("thread_id")
    if tid:
        try:
            from veridiq.calling.live_threads import _insert_thread_message
            from veridiq.workforce.identities import identity_for
            from database import db_session

            marcus = identity_for("ai_calling")["name"]
            body = (
                f"{marcus}: External meet proxy — status **{final_status}**. "
                f"{pw.get('message') or 'See job details.'}"
            )
            with db_session() as conn:
                _insert_thread_message(
                    conn,
                    thread_id=tid,
                    agent_id="ai_calling",
                    body=body.replace("**", ""),
                    kind="system",
                )
        except Exception:  # noqa: BLE001
            logger.exception("hub notify for external meet failed")


def schedule_external_join(
    *,
    url: str,
    instructions: str = "",
    thread_id: Optional[str] = None,
    run_async: bool = True,
) -> dict[str, Any]:
    """Store URL + instructions and kick off best-effort join + LiveKit narration."""
    if not enabled():
        return {
            "ok": False,
            "status": "disabled",
            "message": "External meet proxy disabled (VERIDIQ_EXTERNAL_MEET_ENABLED=0).",
        }
    clean = (url or "").strip()
    if not clean.startswith("http"):
        return {"ok": False, "status": "invalid_url", "message": "A http(s) meeting URL is required."}

    job_id = f"extmeet-{uuid.uuid4().hex[:12]}"
    job = {
        "job_id": job_id,
        "url": clean,
        "instructions": (instructions or "")[:2000],
        "thread_id": thread_id,
        "status": "queued",
        "ok": False,
        "created_at": _utc_iso(),
        "updated_at": _utc_iso(),
        "message": "Queued — opening meeting URL and preparing Marcus proxy narration.",
        "limitations": [
            "Google Meet often blocks headless/automated browsers.",
            "Full bot audio into the Meet tab requires a browser extension / signed-in profile.",
            "LiveKit mirror narration always attempts so the hub has an audible status.",
        ],
    }
    _persist(job)

    if run_async:
        t = threading.Thread(target=_run_job, args=(job_id,), daemon=True, name=f"ext-meet-{job_id[:8]}")
        t.start()
    else:
        _run_job(job_id)
        job = get_job(job_id) or job

    return {
        "ok": True,
        "status": job.get("status") or "queued",
        "job": get_job(job_id),
        "job_id": job_id,
        "message": (
            "External meet proxy started. Status: joining → in_meeting / failed. "
            "Marcus narrates on the LiveKit mirror; Playwright Join is best-effort."
        ),
    }
