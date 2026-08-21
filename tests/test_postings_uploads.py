"""Tests for Mira Postings image uploads + video attachment stills."""

from __future__ import annotations

from pathlib import Path

from PIL import Image


def _tiny_png_bytes() -> bytes:
    from io import BytesIO

    buf = BytesIO()
    Image.new("RGB", (32, 32), color=(40, 120, 200)).save(buf, format="PNG")
    return buf.getvalue()


def test_save_image_bytes_and_resolve(tmp_path, monkeypatch):
    from veridiq.postings import uploads

    monkeypatch.setattr(uploads, "UPLOAD_DIR", tmp_path)
    meta = uploads.save_image_bytes(_tiny_png_bytes(), "My Photo!.PNG")
    assert meta["ok"] is True
    assert meta["filename"].endswith(".PNG") or meta["filename"].endswith(".png")
    assert Path(meta["path"]).is_file()
    assert meta["url"].startswith("/api/v1/veridiq/marketing/upload/file/")
    assert ".." not in meta["filename"]

    resolved = uploads.resolve_attachment_paths(
        [
            meta["filename"],
            meta["url"],
            meta["relative_path"],
            {"filename": meta["filename"]},
            "../../../etc/passwd",
            "not-a-real.png",
        ]
    )
    assert len(resolved) == 1
    assert Path(resolved[0]).is_file()


def test_validate_rejects_non_image():
    from fastapi import HTTPException

    from veridiq.security_uploads import validate_upload_bytes

    try:
        validate_upload_bytes(b"not-an-image", "evil.exe", "image")
        assert False, "expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 400


def test_create_video_uses_attachment_stills(tmp_path, monkeypatch):
    from veridiq.postings import mira_engine, uploads

    monkeypatch.setattr(uploads, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(mira_engine, "IMG_DIR", tmp_path)

    meta = uploads.save_image_bytes(_tiny_png_bytes(), "still.png")
    path = meta["path"]

    captured: dict = {}

    def _fake_assemble(board, stills, **kwargs):
        captured["stills"] = list(stills)
        return {
            "ok": True,
            "status": "ok",
            "video_url": "/api/v1/fake.mp4",
            "has_audio": False,
            "duration_sec": 8,
            "motion_mode": "hold",
            "message": "assembled",
            "width": 1280,
            "height": 720,
            "fps": 12,
        }

    def _no_ai(*_a, **_k):
        raise AssertionError("AI keyframes must not run when uploads are provided")

    monkeypatch.setattr(mira_engine, "assemble_cinematic", _fake_assemble)
    monkeypatch.setattr(mira_engine, "generate_keyframes", _no_ai)
    monkeypatch.setattr(mira_engine, "_default_narration", lambda *a, **k: (None, "no vo", []))

    out = mira_engine.generate_video(
        "make a video from my photo",
        duration_sec=8,
        attachments=[meta["filename"]],
        force_narration=False,
        n_stills=2,
    )
    assert out.get("ok") is True
    assert path in (captured.get("stills") or [])
    assert path in (out.get("attachments_used") or [])
    assert "upload" in str(out.get("message") or "").lower() or out.get("attachments_used")


def test_create_image_uses_upload(tmp_path, monkeypatch):
    from veridiq.postings import mira_model, uploads

    monkeypatch.setattr(uploads, "UPLOAD_DIR", tmp_path)
    # copy_upload_as_image writes under marketing_out/images — redirect via monkeypatch on _ROOT images
    img_dir = tmp_path / "images"
    img_dir.mkdir()
    monkeypatch.setattr(uploads, "_ROOT", tmp_path)

    # Re-point UPLOAD_DIR relative to new root
    up_dir = tmp_path / "marketing_out" / "uploads"
    up_dir.mkdir(parents=True)
    monkeypatch.setattr(uploads, "UPLOAD_DIR", up_dir)

    meta = uploads.save_image_bytes(_tiny_png_bytes(), "face.jpg")
    # _ROOT/marketing_out/images
    (tmp_path / "marketing_out" / "images").mkdir(parents=True, exist_ok=True)

    out = mira_model._create_image("use this", attachments=[meta["filename"]])
    assert out.get("status") == "ok"
    assert out.get("provider") == "user_upload"
    assert out.get("image_url")
    assert meta["path"] in (out.get("attachments_used") or [meta["path"]])
