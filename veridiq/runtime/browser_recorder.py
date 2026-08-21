"""Optional Playwright-based browser session recorder.

Disabled by default. Only activates when VERIDIQ_BROWSER_RUNTIME=1 AND the
`playwright` package (with a Chromium browser) is installed. It navigates to a
single, caller-provided public URL and takes a screenshot — it never scrapes
structured data, logs in to third-party accounts, or automates interactions
beyond a single page load. When disabled, the Live Agent Runtime page falls
back to the existing activity stream + deep links, exactly as required.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

SESSIONS_DIR = Path(__file__).resolve().parent.parent.parent / "reports_out" / "browser_sessions"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def is_enabled() -> bool:
    return os.getenv("VERIDIQ_BROWSER_RUNTIME") == "1"


def runtime_status() -> dict[str, Any]:
    if not is_enabled():
        return {
            "enabled": False,
            "status": "disabled",
            "message": (
                "Browser session recording is disabled. Set VERIDIQ_BROWSER_RUNTIME=1 to enable it "
                "(requires the playwright package). The live activity stream and deep links below "
                "work without it."
            ),
        }
    try:
        import playwright  # noqa: F401

        return {
            "enabled": True,
            "status": "ready",
            "message": "Playwright detected — optional session recording is available.",
        }
    except Exception:
        return {
            "enabled": True,
            "status": "not_installed",
            "message": (
                "VERIDIQ_BROWSER_RUNTIME=1 but the playwright package is not installed. "
                "Run: pip install playwright && playwright install chromium"
            ),
        }


def capture_session(*, url: str, job_id: Optional[str] = None, agent_type: Optional[str] = None) -> dict[str, Any]:
    status = runtime_status()
    if not status["enabled"]:
        return {"status": "disabled", "message": status["message"]}
    if status["status"] != "ready":
        return {"status": "unavailable", "message": status["message"]}
    if not (url.startswith("http://") or url.startswith("https://")):
        return {"status": "error", "message": "Provide a full http(s) URL of a public page you're allowed to view."}

    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    session_id = str(uuid.uuid4())
    screenshot_path = SESSIONS_DIR / f"{session_id}.png"
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=15000, wait_until="domcontentloaded")
            title = page.title()
            page.screenshot(path=str(screenshot_path))
            browser.close()
        result: dict[str, Any] = {
            "status": "ok",
            "session_id": session_id,
            "url": url,
            "page_title": title,
            "screenshot_url": f"/api/v1/veridiq/runtime/browser-session/{session_id}",
            "captured_at": _utc_now(),
        }
    except Exception as exc:
        result = {"status": "error", "message": f"Browser session failed: {str(exc)[:200]}"}

    try:
        from veridiq.integrations.activity import global_platform_activity

        global_platform_activity.record(
            platform="browser_runtime",
            task=f"Capture browser session for {url}",
            agent_type=agent_type,
            job_id=job_id,
            workflow_stage="browser_session",
            completion_status="completed" if result.get("status") == "ok" else "failed",
            api_response_status=result.get("status"),
            recent_activity=result.get("page_title") or result.get("message"),
            errors=result.get("message") if result.get("status") == "error" else None,
        )
    except Exception:
        pass
    return result


def screenshot_path(session_id: str) -> Path:
    return SESSIONS_DIR / f"{session_id}.png"


def list_recent_sessions(limit: int = 12) -> list[dict[str, Any]]:
    """Return metadata for recent Playwright captures (if any). Empty when none."""
    if not SESSIONS_DIR.exists():
        return []
    files = sorted(SESSIONS_DIR.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    out: list[dict[str, Any]] = []
    for path in files[: max(1, min(limit, 40))]:
        session_id = path.stem
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).replace(microsecond=0).isoformat()
        out.append(
            {
                "session_id": session_id,
                "screenshot_url": f"/api/v1/veridiq/runtime/browser-session/{session_id}",
                "captured_at": mtime,
                "bytes": path.stat().st_size,
            }
        )
    return out
