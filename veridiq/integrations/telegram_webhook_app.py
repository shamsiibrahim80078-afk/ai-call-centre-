"""Minimal FastAPI app that receives Telegram webhook POSTs (Render Web Service).

Use this instead of long-poll when you prefer push delivery (e.g. free-tier web with
cold starts). Long-poll Background Worker is still recommended for always-on Starter+.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from veridiq.integrations import telegram
from veridiq.integrations.base import ensure_dotenv_loaded
from veridiq.integrations.telegram_listener import process_update

logger = logging.getLogger(__name__)

_bot_id: Optional[int] = None
_bot_username = ""


def _load_env() -> None:
    ensure_dotenv_loaded()
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass


def _ensure_bot_identity() -> bool:
    global _bot_id, _bot_username
    if _bot_id is not None:
        return True
    me = telegram.get_me(listener_fast=True)
    if me.get("status") != "ok":
        logger.error("Telegram getMe failed: %s", me.get("message"))
        return False
    bot = me.get("result") or {}
    _bot_id = bot.get("id")
    _bot_username = (bot.get("username") or "").strip()
    logger.info("Webhook bot identity: @%s id=%s", _bot_username, _bot_id)
    return _bot_id is not None


def _register_webhook() -> None:
    url = telegram.resolve_webhook_url()
    if not url:
        logger.warning(
            "No webhook URL — set VERIDIQ_TELEGRAM_WEBHOOK_URL or rely on RENDER_EXTERNAL_URL."
        )
        return
    result = telegram.set_webhook(url=url, drop_pending_updates=False)
    if result.get("status") == "ok":
        logger.info("Telegram webhook registered: %s", result.get("url"))
    else:
        logger.error("setWebhook failed: %s", result.get("message"))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _load_env()
    if not telegram.bot_token():
        logger.error("VERIDIQ_TELEGRAM_BOT_TOKEN missing — webhook service idle.")
    else:
        _ensure_bot_identity()
        _register_webhook()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="VERIDIQ Telegram Webhook", version="1.0.0", lifespan=lifespan)
    path = telegram.webhook_path()

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        return {
            "ok": True,
            "service": "telegram-webhook",
            "token_configured": bool(telegram.bot_token()),
            "webhook_url": telegram.resolve_webhook_url() or None,
            "bot_username": _bot_username or None,
        }

    @app.get("/")
    def root() -> PlainTextResponse:
        return PlainTextResponse("VERIDIQ Telegram webhook service")

    @app.post(path)
    async def telegram_webhook(
        request: Request,
        x_telegram_bot_api_secret_token: Optional[str] = Header(default=None),
    ) -> JSONResponse:
        expected = (os.getenv(telegram.WEBHOOK_SECRET) or "").strip()
        if expected:
            if (x_telegram_bot_api_secret_token or "") != expected:
                raise HTTPException(status_code=403, detail="Invalid webhook secret")
        try:
            update = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc
        if not isinstance(update, dict):
            raise HTTPException(status_code=400, detail="Update must be a JSON object")

        if not _ensure_bot_identity():
            return JSONResponse({"ok": False, "error": "bot_identity_unavailable"}, status_code=503)

        try:
            from veridiq.integrations.activity import global_platform_activity

            process_update(
                update,
                bot_id=_bot_id,
                bot_username=_bot_username,
                reply_only_mentions=telegram.reply_only_mentions_enabled(),
                log_fn=global_platform_activity.record,
            )
        except Exception:
            logger.exception("Webhook update handler failed")
            # Still 200 so Telegram does not hammer retries forever on app bugs.
            return JSONResponse({"ok": False})
        return JSONResponse({"ok": True})

    return app


app = create_app()
