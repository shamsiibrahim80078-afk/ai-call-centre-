"""Browser automation connector — Playwright via VERIDIQ runtime (opt-in)."""

from __future__ import annotations

import os
from typing import Any, Optional

from veridiq.integrations.base import status_shape

ENV_FLAG = "VERIDIQ_BROWSER_RUNTIME"
ENV_VARS = [ENV_FLAG]
CAPABILITIES = ["screenshot", "page_title"]
DOCS = "https://playwright.dev/python/"


def status() -> dict[str, Any]:
    enabled = os.getenv(ENV_FLAG, "").strip() in {"1", "true", "TRUE", "yes", "on"}
    if not enabled:
        return status_shape(
            "browser_playwright",
            "Browser Automation (Playwright)",
            "automation",
            status="configuration_required",
            configured=False,
            message=f"Set {ENV_FLAG}=1 to enable opt-in Playwright browser automation.",
            env_vars=ENV_VARS,
            capabilities=CAPABILITIES,
            docs_url=DOCS,
        )
    return status_shape(
        "browser_playwright",
        "Browser Automation (Playwright)",
        "automation",
        status="configured",
        configured=True,
        message="Playwright runtime enabled — screenshots run through the VERIDIQ browser service.",
        env_vars=ENV_VARS,
        capabilities=CAPABILITIES,
        docs_url=DOCS,
    )


def test_connection() -> dict[str, Any]:
    st = status()
    if not st["configured"]:
        return {"platform": "browser_playwright", "status": "configuration_required", "message": st["message"]}
    try:
        from playwright.sync_api import sync_playwright  # type: ignore

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
        return {
            "platform": "browser_playwright",
            "status": "ok",
            "message": "Playwright Chromium launch verified.",
        }
    except Exception as exc:
        return {
            "platform": "browser_playwright",
            "status": "error",
            "message": f"Playwright unavailable: {str(exc)[:200]}",
        }


def screenshot(*, url: Optional[str] = None, **_kwargs: Any) -> dict[str, Any]:
    st = status()
    if not st["configured"]:
        return {"platform": "browser_playwright", "status": "configuration_required", "ok": False, "message": st["message"]}
    target = (url or "").strip()
    if not target.startswith(("http://", "https://")):
        return {"platform": "browser_playwright", "status": "invalid_args", "ok": False, "message": "url must be http(s)."}
    try:
        from pathlib import Path
        import uuid

        from playwright.sync_api import sync_playwright  # type: ignore

        out = Path("reports_out") / f"browser_{uuid.uuid4().hex[:10]}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(target, wait_until="domcontentloaded", timeout=20000)
            page.screenshot(path=str(out))
            title = page.title()
            browser.close()
        return {
            "platform": "browser_playwright",
            "status": "ok",
            "ok": True,
            "url": target,
            "title": title,
            "screenshot_path": str(out),
            "message": "Screenshot captured via VERIDIQ Playwright connector.",
        }
    except Exception as exc:
        return {"platform": "browser_playwright", "status": "error", "ok": False, "message": str(exc)[:300]}
