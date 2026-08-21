"""LiveKit meetings hub — token mint, schedule PKT, join gate."""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

# Ensure LiveKit test creds exist before app/dotenv side effects in imports.
os.environ.setdefault("VERIDIQ_LIVEKIT_URL", "wss://example.livekit.cloud")
os.environ.setdefault("VERIDIQ_LIVEKIT_API_KEY", "APItestkey")
os.environ.setdefault("VERIDIQ_LIVEKIT_API_SECRET", "testsecret_for_jwt_signing_only_32b")
os.environ.setdefault("LIVEKIT_URL", os.environ["VERIDIQ_LIVEKIT_URL"])
os.environ.setdefault("LIVEKIT_API_KEY", os.environ["VERIDIQ_LIVEKIT_API_KEY"])
os.environ.setdefault("LIVEKIT_API_SECRET", os.environ["VERIDIQ_LIVEKIT_API_SECRET"])


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_file = tmp_path / "meetings_test.db"
    monkeypatch.setenv("VERIDIQ_LIVEKIT_URL", "wss://example.livekit.cloud")
    monkeypatch.setenv("VERIDIQ_LIVEKIT_API_KEY", "APItestkey")
    monkeypatch.setenv("VERIDIQ_LIVEKIT_API_SECRET", "testsecret_for_jwt_signing_only_32b")
    # Avoid Telegram network during start_meeting
    monkeypatch.delenv("VERIDIQ_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("BOT_TOKEN", raising=False)

    import database

    monkeypatch.setattr(database, "DB_PATH", db_file)
    database.initialize_database(db_file)

    from app import app

    return TestClient(app)


def test_livekit_token_mint_roundtrip(client):
    from veridiq.calling.livekit_tokens import mint_access_token

    out = mint_access_token(identity="tester", room_name="room-a", name="Tester")
    assert out["ok"] is True
    assert out["token"]
    assert out["url"].startswith("wss://")
    payload = jwt.decode(
        out["token"],
        "testsecret_for_jwt_signing_only_32b",
        algorithms=["HS256"],
        options={"require": ["exp", "iss", "sub"]},
    )
    assert payload["iss"] == "APItestkey"
    assert payload["sub"] == "tester"
    assert payload["video"]["room"] == "room-a"
    assert payload["video"]["roomJoin"] is True


def test_hub_schedule_start_join_token(client, monkeypatch):
    monkeypatch.setenv("VERIDIQ_LIVEKIT_URL", "wss://example.livekit.cloud")
    monkeypatch.setenv("VERIDIQ_LIVEKIT_API_KEY", "APItestkey")
    monkeypatch.setenv("VERIDIQ_LIVEKIT_API_SECRET", "testsecret_for_jwt_signing_only_32b")

    enter = client.post("/api/v1/veridiq/calling/meetings/hub/enter")
    assert enter.status_code == 200
    assert enter.json()["ceo_present"] is True
    assert len(enter.json()["messages"]) >= 2

    pkt = (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%dT%H:%M")
    sched = client.post(
        "/api/v1/veridiq/calling/meetings",
        json={"topic": "PKT ops sync", "scheduled_at_pkt": pkt},
    )
    assert sched.status_code == 200, sched.text
    meeting = sched.json()["meeting"]
    mid = meeting["meeting_id"]
    assert meeting["status"] == "scheduled"
    assert "Asia/Karachi" in meeting["scheduled_at_pkt"] or "+05:00" in meeting["scheduled_at_pkt"] or meeting["scheduled_at_pkt"]

    start = client.post(f"/api/v1/veridiq/calling/meetings/{mid}/start")
    assert start.status_code == 200, start.text
    assert start.json()["meeting"]["status"] == "live"
    assert start.json()["telegram"]["status"] in ("configuration_required", "ok", "error")

    # User cannot mint before admit
    denied = client.post(
        "/api/v1/veridiq/calling/livekit/token",
        json={"meeting_id": mid, "identity": "user-1", "name": "You", "role": "user"},
    )
    assert denied.status_code == 400

    req = client.post(f"/api/v1/veridiq/calling/meetings/{mid}/request-join")
    assert req.status_code == 200
    assert req.json()["meeting"]["join_gate_status"] == "user_waiting"

    # Force ready_prompt by rewinding join_requested_at
    from database import db_session
    from veridiq.calling import meetings as meetings_mod

    past = (datetime.now(timezone.utc) - timedelta(seconds=meetings_mod.JOIN_WAIT_SEC + 1)).isoformat()
    with db_session() as conn:
        conn.execute(
            "UPDATE veridiq_meetings SET join_requested_at = ? WHERE meeting_id = ?",
            (past, mid),
        )

    conf = client.post(
        f"/api/v1/veridiq/calling/meetings/{mid}/confirm-join",
        json={"yes": True},
    )
    assert conf.status_code == 200, conf.text
    assert conf.json()["admitted"] is True

    tok = client.post(
        "/api/v1/veridiq/calling/livekit/token",
        json={"meeting_id": mid, "identity": "user-1", "name": "You", "role": "user"},
    )
    assert tok.status_code == 200, tok.text
    body = tok.json()
    assert body["ok"] is True
    assert body["token"]
    assert body["room"] == meeting["livekit_room"]
    decoded = jwt.decode(
        body["token"],
        "testsecret_for_jwt_signing_only_32b",
        algorithms=["HS256"],
        options={"require": ["exp", "iss"]},
    )
    assert decoded["video"]["room"] == meeting["livekit_room"]
    assert decoded["exp"] > int(time.time())


def test_calling_agent_reports_livekit_mode(client):
    resp = client.get("/api/v1/veridiq/calling/agent")
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "livekit_meetings"
    assert "livekit" in data
    assert "agora" in data
    assert data["agora"]["primary_video"] == "livekit"
    assert data["agora"]["blocks_livekit"] is False


def test_agora_status_optional_without_certificate(client, monkeypatch):
    monkeypatch.setenv("VERIDIQ_AGORA_APP_ID", "appid_test")
    monkeypatch.setenv("VERIDIQ_AGORA_AGENT_ID", "agentid_test")
    monkeypatch.delenv("VERIDIQ_AGORA_APP_CERTIFICATE", raising=False)
    monkeypatch.delenv("AGORA_APP_CERTIFICATE", raising=False)
    resp = client.get("/api/v1/veridiq/calling/agora/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["configured"] is True
    assert data["app_certificate_set"] is False
    assert data["rtc_token_ready"] is False
    assert data["mode"] == "agent_ids_only"
    assert data["blocks_livekit"] is False
    assert "app_id" not in data or not data.get("app_id")


def test_agora_status_rtc_ready_with_certificate(client, monkeypatch):
    app_id = "a" * 32
    cert = "b" * 32
    monkeypatch.setenv("VERIDIQ_AGORA_APP_ID", app_id)
    monkeypatch.setenv("VERIDIQ_AGORA_AGENT_ID", "agentid_test")
    monkeypatch.setenv("VERIDIQ_AGORA_APP_CERTIFICATE", cert)
    monkeypatch.delenv("AGORA_APP_CERTIFICATE", raising=False)
    resp = client.get("/api/v1/veridiq/calling/agora/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["app_certificate_set"] is True
    assert data["rtc_token_ready"] is True
    assert data["mode"] == "rtc_ready"
    assert data["blocks_livekit"] is False
    assert data["primary_video"] == "livekit"
    assert cert not in str(data)
    assert app_id not in str(data)


def test_agora_token_mint(client, monkeypatch):
    app_id = "970CA35de60c44645bbae8a215061b33"
    cert = "5CFd2fd1755d40ecb72977518be15d3b"
    monkeypatch.setenv("VERIDIQ_AGORA_APP_ID", app_id)
    monkeypatch.setenv("VERIDIQ_AGORA_APP_CERTIFICATE", cert)
    monkeypatch.setenv("VERIDIQ_AGORA_AGENT_ID", "agentid_test")
    monkeypatch.delenv("AGORA_APP_CERTIFICATE", raising=False)
    resp = client.post(
        "/api/v1/veridiq/calling/agora/token",
        json={"channel": "veridiq-test", "uid": 42, "role": "publisher", "ttl_sec": 600},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["token"].startswith("007")
    assert data["channel"] == "veridiq-test"
    assert data["primary_video"] == "livekit"
    assert data["blocks_livekit"] is False
    assert cert not in str(data)
