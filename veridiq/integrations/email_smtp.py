"""Email integration — real SMTP send/test. No third-party inbox scraping."""

from __future__ import annotations

import os
from typing import Any

from veridiq.integrations.base import status_shape

HOST = "VERIDIQ_SMTP_HOST"
PORT = "VERIDIQ_SMTP_PORT"
USER = "VERIDIQ_SMTP_USER"
PASSWORD = "VERIDIQ_SMTP_PASSWORD"
FROM = "VERIDIQ_SMTP_FROM"

ENV_VARS = [HOST, PORT, USER, PASSWORD, FROM]
CAPABILITIES = ["send_mail (after comms draft approval)"]


def status() -> dict[str, Any]:
    host = os.getenv(HOST)
    user = os.getenv(USER)
    password = os.getenv(PASSWORD)
    configured = bool(host and user and password)
    return status_shape(
        "email",
        "Email (SMTP)",
        "email",
        status="configured" if configured else "configuration_required",
        configured=configured,
        message=(
            "SMTP credentials configured. Use /test to verify login, or approve a comms draft to send."
            if configured
            else f"Set {HOST}, {USER}, {PASSWORD} (and optional {FROM}, {PORT}) to enable outbound email via SMTP."
        ),
        env_vars=ENV_VARS,
        capabilities=CAPABILITIES,
        docs_url=None,
    )


def test_connection() -> dict[str, Any]:
    host = os.getenv(HOST)
    if not host:
        return {
            "platform": "email",
            "status": "configuration_required",
            "message": f"Set {HOST}/{USER}/{PASSWORD} to run a live SMTP login test.",
        }
    port = int(os.getenv(PORT, "587"))
    user = os.getenv(USER)
    password = os.getenv(PASSWORD)
    try:
        import smtplib

        with smtplib.SMTP(host, port, timeout=6) as server:
            server.ehlo()
            try:
                server.starttls()
                server.ehlo()
            except Exception:
                pass
            if user and password:
                server.login(user, password)
        return {"platform": "email", "status": "ok", "message": f"SMTP login verified at {host}:{port}."}
    except Exception as exc:
        return {"platform": "email", "status": "error", "message": f"SMTP test failed: {str(exc)[:200]}"}


def send_email(*, to: str, subject: str, body: str) -> dict[str, Any]:
    """Real SMTP send — only ever invoked after explicit user approval of a comms draft."""
    host = os.getenv(HOST)
    if not host:
        return {"status": "configuration_required", "message": f"Set {HOST} to enable sending."}
    port = int(os.getenv(PORT, "587"))
    user = os.getenv(USER)
    password = os.getenv(PASSWORD)
    from_addr = os.getenv(FROM) or user or "veridiq@local"
    try:
        import smtplib
        from email.mime.text import MIMEText

        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = to
        with smtplib.SMTP(host, port, timeout=8) as server:
            server.ehlo()
            try:
                server.starttls()
                server.ehlo()
            except Exception:
                pass
            if user and password:
                server.login(user, password)
            server.sendmail(from_addr, [to], msg.as_string())
        return {"status": "ok", "message": f"Email sent to {to} via {host}."}
    except Exception as exc:
        return {"status": "error", "message": f"SMTP send failed: {str(exc)[:200]}"}
