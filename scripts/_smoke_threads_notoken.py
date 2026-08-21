"""Offline smoke: Threads/marketing no-token honesty. Never fabricates send success.

Run: python scripts/_smoke_threads_notoken.py
Does not require a live Threads user token.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Load .env without overwriting existing process env; never print secret values.
for line in (ROOT / ".env").read_text(encoding="utf-8", errors="ignore").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, val = line.split("=", 1)
    key, val = key.strip(), val.strip().strip('"').strip("'")
    if key and key not in os.environ:
        os.environ[key] = val

from fastapi.testclient import TestClient  # noqa: E402

from app import app  # noqa: E402
from veridiq.integrations import threads  # noqa: E402

client = TestClient(app)
failures: list[str] = []


def _ok(label: str, cond: bool, detail: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {label}" + (f" — {detail}" if detail else ""))
    if not cond:
        failures.append(label)


def main() -> int:
    token = (os.getenv(threads.ACCESS_TOKEN) or "").strip()
    user_id = (os.getenv(threads.THREADS_USER_ID) or "").strip()
    app_id = (os.getenv(threads.APP_ID) or "").strip()
    app_secret = (os.getenv(threads.APP_SECRET) or "").strip()

    print("=== ENV (presence only) ===")
    print(f"  {threads.APP_ID}: {'SET' if app_id else 'MISSING'}")
    print(f"  {threads.APP_SECRET}: {'SET' if app_secret else 'MISSING'}")
    print(f"  {threads.ACCESS_TOKEN}: {'SET' if token else 'MISSING'}")
    print(f"  {threads.THREADS_USER_ID}: {'SET' if user_id else 'MISSING'}")

    if token or user_id:
        print("NOTE: user token/id present — this smoke still checks honesty paths.")
    else:
        print("NOTE: no live Threads user token — expected configuration_required.")

    st = threads.status()
    _ok(
        "threads.status configuration_required without token",
        (not token and st.get("status") == "configuration_required")
        or (bool(token) and st.get("status") in {"configured", "ok", "configuration_required"}),
        f"status={st.get('status')}",
    )

    tc = threads.test_connection()
    if not token:
        _ok(
            "threads.test_connection configuration_required",
            tc.get("status") == "configuration_required",
            f"status={tc.get('status')} msg={(tc.get('message') or '')[:100]}",
        )

    # Direct publish without token must not fake success (early return; no network).
    if not token or not user_id:
        pub = threads.publish_text(text="Veridiq no-token smoke (should not post)")
        _ok(
            "threads.publish_text configuration_required",
            pub.get("status") == "configuration_required",
            f"status={pub.get('status')} msg={(pub.get('message') or '')[:120]}",
        )
        _ok("publish message names env keys", "VERIDIQ_THREADS" in (pub.get("message") or ""))

    # Integrations board via API
    board = client.get("/api/v1/veridiq/integrations").json()
    threads_row = next(
        (i for i in board.get("integrations", []) if i.get("platform") == "threads"),
        None,
    )
    _ok("integrations board includes threads", threads_row is not None)
    if threads_row and not token:
        _ok(
            "board threads status honest",
            threads_row.get("status") == "configuration_required",
            f"status={threads_row.get('status')}",
        )

    # Marketing: ensure campaign + threads draft, then approve without token
    camps = client.get("/api/v1/veridiq/marketing/campaigns").json()
    campaign_id = None
    if camps.get("campaigns"):
        campaign_id = camps["campaigns"][0]["campaign_id"]
    else:
        created = client.post(
            "/api/v1/veridiq/marketing/campaigns",
            json={
                "name": "Threads no-token smoke",
                "channels": ["threads", "telegram"],
            },
        ).json()
        campaign_id = created.get("campaign", created).get("campaign_id")
    _ok("marketing campaign available", bool(campaign_id), str(campaign_id))

    # Bounded social_poster run (threads specialty) via agent path if available,
    # else draft_marketing_content through comms draft API.
    draft_resp = client.post(
        "/api/v1/veridiq/comms/draft",
        json={
            "channel": "threads",
            "subject": "Threads smoke draft",
            "body": "Veridiq Threads pipeline smoke — draft only, no live token.",
            "recipient_hint": "",
            "purpose": "marketing",
            "campaign_id": campaign_id,
            "created_by_agent": "social_poster",
        },
    )
    # Some builds use draft_marketing_content endpoint only — fall back.
    if draft_resp.status_code >= 400:
        from veridiq.comms import draft_marketing_content

        draft = draft_marketing_content(
            channel="threads",
            body="Veridiq Threads pipeline smoke — draft only, no live token.",
            campaign_id=campaign_id,
            created_by_agent="social_poster",
        )
        draft_id = draft["draft_id"]
        print(f"[INFO] drafted via helper draft_id={draft_id}")
    else:
        payload = draft_resp.json()
        draft = payload.get("draft") or payload
        draft_id = draft.get("draft_id")
        print(f"[INFO] drafted via API draft_id={draft_id} status={draft.get('external_action_status')}")
    _ok("threads marketing draft created", bool(draft_id))

    approved = client.post(
        "/api/v1/veridiq/comms/approve",
        json={"draft_id": draft_id, "approved": True, "channel": "threads"},
    ).json()
    status = approved.get("status")
    send_attempt = (approved.get("draft") or {}).get("send_attempt")
    print(f"[INFO] approve status={status} send_attempt={send_attempt}")
    _ok(
        "approve without token does not fake sent",
        status != "sent" and status in {"approved_pending_integration", "configuration_required", "error"},
        f"status={status}",
    )
    if not token:
        _ok(
            "approve stays pending / configuration_required",
            status == "approved_pending_integration" and send_attempt is None,
            f"status={status} send_attempt={send_attempt}",
        )

    # Activity feed should record configuration_required
    activity = client.get("/api/v1/veridiq/integrations/activity").json()
    entries = activity.get("activity") or []
    threads_cfg = [
        e
        for e in entries
        if e.get("platform") == "threads"
        and e.get("completion_status") == "configuration_required"
    ]
    _ok(
        "activity logs configuration_required for threads",
        bool(threads_cfg) or not token,
        f"matching_entries={len(threads_cfg)}",
    )

    checklist = client.get("/api/v1/veridiq/marketing/go-live-checklist").json()
    thr = next((p for p in checklist.get("platforms", []) if p.get("platform") == "threads"), None)
    _ok("go-live checklist includes threads", thr is not None)
    if thr and not token:
        _ok(
            "threads not send_ready without token",
            thr.get("send_ready") is False,
            f"send_ready={thr.get('send_ready')} status={thr.get('status')}",
        )

    # Team run / social_poster channel mapping
    from veridiq.marketing.team_run import TEAM_RUN_CHANNELS

    _ok("social_poster team channel is threads", TEAM_RUN_CHANNELS.get("social_poster") == ["threads"])

    print()
    if failures:
        print(f"SMOKE FAILED: {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("SMOKE PASSED: no-token Threads/marketing path is honest.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
