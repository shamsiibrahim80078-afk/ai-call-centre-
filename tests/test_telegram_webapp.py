"""Unit tests for Telegram Mini App initData HMAC validation."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from veridiq.integrations.telegram_webapp import (
    authenticate_webapp,
    build_data_check_string,
    compute_webapp_hash,
    parse_init_data,
    validate_init_data,
)


FAKE_TOKEN = "123456:ABC-DEF_fake_bot_token_for_tests"


def _sign_init_data(fields: dict[str, str], bot_token: str = FAKE_TOKEN) -> str:
    """Build a valid initData query string for unit tests."""
    data_check = build_data_check_string(fields)
    digest = compute_webapp_hash(data_check, bot_token)
    payload = {**fields, "hash": digest}
    return urlencode(payload)


def _isolate_db(monkeypatch, tmp_path, name: str = "miniapp.db"):
    db_path = tmp_path / name
    monkeypatch.setattr("database.DB_PATH", db_path)
    return db_path


def test_compute_webapp_hash_stable():
    # Fixed inputs → fixed HMAC (guards accidental algorithm drift).
    h = compute_webapp_hash("auth_date=1\nuser={}", FAKE_TOKEN)
    secret = hmac.new(b"WebAppData", FAKE_TOKEN.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, b"auth_date=1\nuser={}", hashlib.sha256).hexdigest()
    assert h == expected


def test_validate_init_data_ok():
    now = int(time.time())
    user = {"id": 42, "first_name": "Ada", "username": "ada"}
    fields = {
        "auth_date": str(now),
        "query_id": "AAEAAAE",
        "user": json.dumps(user, separators=(",", ":")),
    }
    init_data = _sign_init_data(fields)
    result = validate_init_data(init_data, bot_token=FAKE_TOKEN, now_ts=now)
    assert result["ok"] is True
    assert result["user"]["id"] == 42
    assert result["user"]["username"] == "ada"
    assert result["auth_date"] == now


def test_validate_init_data_rejects_tampered_hash():
    now = int(time.time())
    fields = {"auth_date": str(now), "user": json.dumps({"id": 1, "first_name": "X"})}
    init_data = _sign_init_data(fields)
    parts = parse_init_data(init_data)
    bad_hash = parts["hash"][:-1] + ("0" if parts["hash"][-1] != "0" else "1")
    tampered = urlencode({**{k: v for k, v in parts.items() if k != "hash"}, "hash": bad_hash})
    result = validate_init_data(tampered, bot_token=FAKE_TOKEN, now_ts=now)
    assert result["ok"] is False
    assert "mismatch" in (result.get("error") or "").lower()


def test_validate_init_data_rejects_wrong_bot_token():
    now = int(time.time())
    fields = {"auth_date": str(now), "user": json.dumps({"id": 9, "first_name": "Y"})}
    init_data = _sign_init_data(fields, bot_token=FAKE_TOKEN)
    result = validate_init_data(init_data, bot_token="999:WRONG_TOKEN", now_ts=now)
    assert result["ok"] is False


def test_validate_init_data_rejects_expired():
    old = int(time.time()) - 100_000
    fields = {"auth_date": str(old), "user": json.dumps({"id": 3, "first_name": "Old"})}
    init_data = _sign_init_data(fields)
    result = validate_init_data(
        init_data, bot_token=FAKE_TOKEN, max_age_sec=3600, now_ts=int(time.time())
    )
    assert result["ok"] is False
    assert "expired" in (result.get("error") or "").lower()


def test_validate_init_data_empty():
    result = validate_init_data("", bot_token=FAKE_TOKEN)
    assert result["ok"] is False


def test_authenticate_webapp_issues_session(monkeypatch, tmp_path):
    _isolate_db(monkeypatch, tmp_path, "session.db")
    monkeypatch.setenv("VERIDIQ_TELEGRAM_BOT_TOKEN", FAKE_TOKEN)
    monkeypatch.setenv("VERIDIQ_JWT_SECRET", "test-jwt-secret-miniapp")
    monkeypatch.setattr(
        "veridiq.integrations.telegram.bot_token",
        lambda: FAKE_TOKEN,
    )

    from database import initialize_database

    initialize_database()

    now = int(time.time())
    user = {"id": 1001, "first_name": "Mini", "username": "miniuser"}
    fields = {"auth_date": str(now), "user": json.dumps(user, separators=(",", ":"))}
    init_data = _sign_init_data(fields)

    result = authenticate_webapp(init_data, issue_session=True, max_age_sec=86400)
    assert result["ok"] is True
    assert result.get("access_token")
    assert result["session_user"]["email"] == "tg_1001@telegram.veridiq.local"
    assert result["user"]["id"] == 1001


@pytest.fixture()
def client(monkeypatch, tmp_path):
    _isolate_db(monkeypatch, tmp_path, "api_mini.db")
    monkeypatch.setenv("VERIDIQ_TELEGRAM_BOT_TOKEN", FAKE_TOKEN)
    monkeypatch.setenv("VERIDIQ_JWT_SECRET", "test-jwt-secret-miniapp-api")
    monkeypatch.setenv("VERIDIQ_TELEGRAM_AUTO_REPLY", "0")
    monkeypatch.setenv("VERIDIQ_TELEGRAM_LISTENER_IN_API", "0")
    monkeypatch.setattr(
        "veridiq.integrations.telegram.bot_token",
        lambda: FAKE_TOKEN,
    )
    from database import initialize_database

    initialize_database()
    from app import app

    return TestClient(app)


def test_webapp_auth_endpoint(client, monkeypatch):
    monkeypatch.setattr(
        "veridiq.integrations.telegram.bot_token",
        lambda: FAKE_TOKEN,
    )
    now = int(time.time())
    user = {"id": 77, "first_name": "Api", "username": "apiuser"}
    fields = {"auth_date": str(now), "user": json.dumps(user, separators=(",", ":"))}
    init_data = _sign_init_data(fields)

    resp = client.post(
        "/api/v1/veridiq/telegram/webapp/auth",
        json={"init_data": init_data, "issue_session": True},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["access_token"]
    assert body["user"]["id"] == 77


def test_webapp_auth_endpoint_rejects_bad_hash(client, monkeypatch):
    monkeypatch.setattr(
        "veridiq.integrations.telegram.bot_token",
        lambda: FAKE_TOKEN,
    )
    resp = client.post(
        "/api/v1/veridiq/telegram/webapp/auth",
        json={"init_data": "auth_date=1&user=%7B%7D&hash=deadbeef", "issue_session": False},
    )
    assert resp.status_code == 401


def test_miniapp_status_endpoint(client, monkeypatch):
    monkeypatch.setenv("VERIDIQ_TELEGRAM_MINIAPP_URL", "https://example.com/mini")
    resp = client.get("/api/v1/veridiq/telegram/miniapp")
    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"] is True
    assert body["miniapp_url"] == "https://example.com/mini"
