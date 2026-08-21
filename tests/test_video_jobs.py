"""Unit tests for async Mira create_video jobs."""

from __future__ import annotations

import time


def test_start_video_job_returns_id_and_completes(monkeypatch):
    from veridiq.postings import video_jobs

    video_jobs.clear_jobs_for_tests()

    def _fake_handle(message, *, history=None, _force_sync_video=False, _parsed_override=None, **_k):
        assert _force_sync_video is True
        return {
            "ok": True,
            "intent": "create_video",
            "reply": "15s video ready",
            "action": {
                "action": "create_video",
                "status": "ok",
                "ok": True,
                "message": "15s video ready",
                "render": {"ok": True, "video_url": "/api/v1/fake.mp4", "has_audio": True},
                "stills_count": 2,
            },
        }

    monkeypatch.setattr("veridiq.postings.studio.handle_command", _fake_handle)

    job_id = video_jobs.start_video_job(
        message="create a video for my verdiq explaining what veridiq is",
        history=[],
        parsed={"intent": "create_video", "topic": "veridiq", "duration_sec": 15},
    )
    assert job_id
    assert isinstance(job_id, str)

    snap = video_jobs.get_job(job_id)
    assert snap["job_id"] == job_id
    assert snap["status"] in ("queued", "running", "done")

    deadline = time.time() + 5
    while time.time() < deadline:
        snap = video_jobs.get_job(job_id)
        if snap["status"] in ("done", "error"):
            break
        time.sleep(0.05)

    assert snap["status"] == "done"
    assert snap["progress"] == 100
    assert snap["result"]["action"]["render"]["video_url"]


def test_get_job_unknown():
    from veridiq.postings import video_jobs

    miss = video_jobs.get_job("does-not-exist")
    assert miss["status"] == "not_found"
    assert miss["ok"] is False


def test_handle_command_async_video_returns_job_id(monkeypatch):
    from veridiq.postings import studio, video_jobs

    video_jobs.clear_jobs_for_tests()
    monkeypatch.setattr(video_jobs, "_run_video_job", lambda *_a, **_k: None)
    monkeypatch.setattr(
        studio,
        "parse_intent",
        lambda message: {
            "intent": "create_video",
            "topic": message,
            "duration_sec": 15,
            "reply": "Generating…",
            "parser": "keywords",
            "channel": "linkedin",
            "title": "",
            "feature_key": "truth_verification",
            "style": "cinematic",
        },
    )

    res = studio.handle_command(
        "create a video for my verdiq in that tell what veridiq is",
        async_video=True,
    )
    assert res["status"] == "started"
    assert res["job_id"]
    assert res["intent"] == "create_video"
    assert res["action"]["status"] == "started"
    assert res["action"]["job_id"] == res["job_id"]


def test_job_wall_raised_for_encode():
    from veridiq.postings import video_jobs

    assert float(video_jobs._JOB_WALL_SEC) == 150.0
