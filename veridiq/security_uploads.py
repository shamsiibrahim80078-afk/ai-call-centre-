"""Upload validation helpers for VERIDIQ media pipelines."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, UploadFile

MAX_UPLOAD_MB = int(os.getenv("VERIDIQ_MAX_UPLOAD_MB", "25"))
MAX_BYTES = MAX_UPLOAD_MB * 1024 * 1024

ALLOWED_EXT = {
    "video": {".mp4", ".webm", ".mov", ".avi", ".mkv"},
    "audio": {".wav", ".mp3", ".m4a", ".ogg", ".flac"},
    "image": {".png", ".jpg", ".jpeg", ".webp", ".gif"},
}


def safe_filename(name: str) -> str:
    base = Path(name or "upload.bin").name
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", base)
    return cleaned[:180] or "upload.bin"


def validate_upload_bytes(data: bytes, filename: str, kind: str) -> tuple[bytes, str]:
    """Validate raw upload bytes (extension allow-list + size cap)."""
    safe = safe_filename(filename)
    ext = Path(safe).suffix.lower()
    allowed = ALLOWED_EXT.get(kind, set())
    if ext not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported {kind} type '{ext}'. allowed: {sorted(allowed)}",
        )
    if not data:
        raise HTTPException(status_code=400, detail=f"empty {kind} upload")
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail=f"{kind} exceeds {MAX_UPLOAD_MB}MB limit")
    return data, safe


async def read_validated_upload(upload: Optional[UploadFile], kind: str) -> tuple[Optional[bytes], Optional[str]]:
    if upload is None or not upload.filename:
        return None, None
    data = await upload.read()
    return validate_upload_bytes(data, upload.filename, kind)
