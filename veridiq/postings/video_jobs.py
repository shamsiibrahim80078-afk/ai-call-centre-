"""Async Mira create_video jobs — avoid browser/proxy timeouts on long stills.

POST /postings/agent returns ``job_id`` immediately for create_video; the client
polls GET /postings/video/jobs/{id} until done|error.

AI stills are capped (~35s) inside Mira; local Pillow stills guarantee an MP4.
Job wall is 150s for encode + VO — never leave the client with only a timeout
when the local fallback can finish.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Optional

_LOCK = threading.Lock()
_JOBS: dict[str, dict[str, Any]] = {}
_MAX_JOBS = 64
_JOB_WALL_SEC = 150.0


def _utc_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _prune_unlocked() -> None:
    """Drop oldest finished jobs when the store grows (caller holds _LOCK)."""
    if len(_JOBS) < _MAX_JOBS:
        return
    finished = [
        (jid, j.get("created_at") or "")
        for jid, j in _JOBS.items()
        if j.get("status") in ("done", "error")
    ]
    finished.sort(key=lambda x: x[1])
    for jid, _ in finished[: max(1, len(finished) // 2)]:
        _JOBS.pop(jid, None)


def _update(job_id: str, **fields: Any) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        job.update(fields)
        job["updated_at"] = _utc_iso()


def get_job(job_id: str) -> dict[str, Any]:
    """Return a public snapshot of the job (or not_found)."""
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return {
                "ok": False,
                "status": "not_found",
                "job_id": job_id,
                "message": f"Unknown video job {job_id}",
            }
        return dict(job)


def start_video_job(
    payload: dict[str, Any] | None = None,
    *,
    message: str = "",
    history: Optional[list[dict[str, Any]]] = None,
    parsed: Optional[dict[str, Any]] = None,
    attachments: Optional[list[str]] = None,
    chat_id: Optional[str] = None,
) -> str:
    """Queue create_video in a daemon thread; return job_id immediately."""
    if isinstance(payload, dict):
        message = str(payload.get("message") or message or "")
        history = payload.get("history") if history is None else history
        parsed = payload.get("parsed") if parsed is None else parsed
        if attachments is None and payload.get("attachments") is not None:
            attachments = payload.get("attachments")
        if chat_id is None and payload.get("chat_id"):
            chat_id = str(payload.get("chat_id") or "") or None

    attach_refs = [str(a).strip() for a in (attachments or []) if str(a).strip()]
    chat_ref = str(chat_id or "").strip() or None
    job_id = uuid.uuid4().hex[:16]
    now = _utc_iso()
    snap = {
        "id": job_id,
        "job_id": job_id,
        "ok": True,
        "status": "queued",
        "progress": 0,
        "message": "Video job queued — Mira Free Model starting…",
        "result": None,
        "created_at": now,
        "updated_at": now,
        "action": "create_video",
        "attachments": attach_refs,
        "chat_id": chat_ref,
    }
    with _LOCK:
        _prune_unlocked()
        _JOBS[job_id] = snap

    thread = threading.Thread(
        target=_run_video_job,
        args=(job_id, message, list(history or []), parsed, attach_refs, chat_ref),
        name=f"mira-video-{job_id}",
        daemon=True,
    )
    thread.start()
    return job_id


def _persist_chat_on_finish(chat_id: Optional[str], job: dict[str, Any]) -> None:
    """When a video job finishes, append the final assistant message to the chat."""
    cid = str(chat_id or job.get("chat_id") or "").strip()
    if not cid:
        return
    try:
        from veridiq.postings.chats import append_assistant_from_action, media_urls_from_action

        action = job.get("action") if isinstance(job.get("action"), dict) else {}
        result = job.get("result") if isinstance(job.get("result"), dict) else {}
        if not action and isinstance(result.get("action"), dict):
            action = result["action"]
        # Merge nested result.action media if top-level action is incomplete
        if isinstance(result.get("action"), dict):
            nested = result["action"]
            media = media_urls_from_action(action)
            if not media.get("video_url"):
                nested_media = media_urls_from_action(nested)
                if nested_media.get("video_url"):
                    action = {**nested, **action}
                    if not action.get("render") and nested.get("render"):
                        action["render"] = nested["render"]
                    if not action.get("video_url"):
                        action["video_url"] = nested_media["video_url"]
        reply = str(
            job.get("reply")
            or result.get("reply")
            or action.get("message")
            or job.get("message")
            or "Video ready."
        )
        if job.get("status") == "error":
            append_assistant_from_action(
                cid,
                reply=reply,
                action=action or {"action": "create_video", "status": "error", "message": reply},
            )
        else:
            saved = append_assistant_from_action(cid, reply=reply, action=action)
            media = media_urls_from_action(action)
            if not media.get("video_url"):
                print(
                    f"[video_jobs] WARN chat {cid}: persisted done job without video_url",
                    flush=True,
                )
            elif not (saved or {}).get("ok"):
                print(
                    f"[video_jobs] WARN chat {cid}: append failed: {saved}",
                    flush=True,
                )
    except Exception as exc:
        print(f"[video_jobs] persist chat failed: {exc}", flush=True)

def _run_video_job(
    job_id: str,
    message: str,
    history: list[dict[str, Any]],
    parsed: Optional[dict[str, Any]],
    attachments: Optional[list[str]] = None,
    chat_id: Optional[str] = None,
) -> None:
    _update(
        job_id,
        status="running",
        progress=8,
        message="Trying free AI scenes…",
    )
    try:
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

        from veridiq.postings import mira_engine, studio

        attach_refs = list(attachments or [])
        if attach_refs:
            _update(job_id, message=f"Using {len(attach_refs)} uploaded image(s)…", progress=12)

        def _on_progress(msg: str, progress: int | None = None) -> None:
            cur = get_job(job_id)
            if cur.get("status") not in ("queued", "running"):
                return
            fields: dict[str, Any] = {"message": str(msg or "")[:240]}
            if progress is not None:
                fields["progress"] = max(int(cur.get("progress") or 0), int(progress))
            _update(job_id, **fields)

        mira_engine.set_progress_hook(_on_progress)
        stop_hb = threading.Event()

        def _heartbeat() -> None:
            ticks = 0
            stages = (
                (20, "Trying free AI scenes…"),
                (42, "AI busy — using Mira local scenes…"),
                (68, "Assembling video…"),
                (85, "Almost done — finishing encode…"),
            )
            while not stop_hb.wait(14.0):
                ticks += 1
                idx = min(ticks - 1, len(stages) - 1)
                prog, msg = stages[idx]
                cur = get_job(job_id)
                if cur.get("status") not in ("queued", "running"):
                    return
                if int(cur.get("progress") or 0) >= 90:
                    return
                # Don't overwrite a more specific Mira progress message unless stale
                _update(job_id, progress=max(int(cur.get("progress") or 0), prog), message=msg)

        hb = threading.Thread(target=_heartbeat, name=f"mira-hb-{job_id}", daemon=True)
        hb.start()
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                fut = pool.submit(
                    studio.handle_command,
                    message,
                    history=history or None,
                    _force_sync_video=True,
                    _parsed_override=parsed,
                    attachments=attach_refs,
                )
                try:
                    result = fut.result(timeout=_JOB_WALL_SEC)
                except FuturesTimeout:
                    _update(
                        job_id,
                        status="error",
                        progress=100,
                        message=(
                            f"Video job timed out after {_JOB_WALL_SEC:.0f}s "
                            "(encode/VO). Local stills should usually finish sooner — retry."
                        ),
                        result=None,
                        reply=f"Video job timed out after {_JOB_WALL_SEC:.0f}s. Retry.",
                        intent="create_video",
                        action={
                            "action": "create_video",
                            "status": "error",
                            "message": f"Timed out after {_JOB_WALL_SEC:.0f}s",
                        },
                        ok=False,
                    )
                    _persist_chat_on_finish(chat_id, get_job(job_id))
                    return
        finally:
            stop_hb.set()
            mira_engine.clear_progress_hook()

        action = result.get("action") if isinstance(result, dict) else None
        action = action if isinstance(action, dict) else {}
        render = action.get("render") if isinstance(action.get("render"), dict) else {}
        has_video = bool(
            action.get("video_url")
            or render.get("video_url")
            or render.get("absolute_path")
        )
        status = str(action.get("status") or "")
        ok = bool(
            isinstance(result, dict)
            and status == "ok"
            and has_video
            and action.get("ok") is not False
        )

        if ok:
            _update(
                job_id,
                status="done",
                progress=100,
                message=str(action.get("message") or result.get("reply") or "Video ready."),
                result=result,
                reply=result.get("reply"),
                intent=result.get("intent") or "create_video",
                action=action,
            )
        else:
            msg = str(
                action.get("message")
                or result.get("reply")
                or "Video generation failed."
            )
            _update(
                job_id,
                status="error",
                progress=100,
                message=msg,
                result=result,
                reply=msg,
                intent=result.get("intent") or "create_video",
                action=action or {"action": "create_video", "status": "error", "message": msg},
                ok=False,
            )
        _persist_chat_on_finish(chat_id, get_job(job_id))
    except Exception as exc:
        try:
            from veridiq.postings import mira_engine as _me

            _me.clear_progress_hook()
        except Exception:
            pass
        msg = f"Video job failed: {str(exc)[:240]}"
        _update(
            job_id,
            status="error",
            progress=100,
            message=msg,
            result=None,
            reply=msg,
            intent="create_video",
            action={"action": "create_video", "status": "error", "message": msg},
            ok=False,
        )
        _persist_chat_on_finish(chat_id, get_job(job_id))


def clear_jobs_for_tests() -> None:
    """Test helper — wipe in-memory store."""
    with _LOCK:
        _JOBS.clear()
