"""Mira Postings user image uploads — save under marketing_out/uploads/."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Optional

from veridiq.security_uploads import ALLOWED_EXT, safe_filename

_ROOT = Path(__file__).resolve().parent.parent.parent
UPLOAD_DIR = _ROOT / "marketing_out" / "uploads"
PUBLIC_URL_PREFIX = "/api/v1/veridiq/marketing/upload/file"
_IMAGE_EXT = ALLOWED_EXT["image"]


def ensure_upload_dir() -> Path:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    return UPLOAD_DIR


def upload_public_url(filename: str) -> str:
    return f"{PUBLIC_URL_PREFIX}/{safe_filename(filename)}"


def save_image_bytes(
    data: bytes,
    original_name: str,
    *,
    as_brand_reference: bool = True,
    topic: str = "",
) -> dict[str, Any]:
    """Persist validated image bytes; return path + public URL metadata.

    When ``as_brand_reference`` is True (default), also indexes a lasting copy
    under marketing_out/references/ for legal style guidance.
    """
    ensure_upload_dir()
    base = safe_filename(original_name)
    ext = Path(base).suffix.lower()
    if ext not in _IMAGE_EXT:
        ext = ".png"
        base = f"{Path(base).stem or 'upload'}{ext}"
    unique = f"up_{uuid.uuid4().hex[:12]}_{base}"
    unique = safe_filename(unique)
    dest = UPLOAD_DIR / unique
    dest.write_bytes(data)
    out: dict[str, Any] = {
        "ok": True,
        "filename": unique,
        "path": str(dest),
        "relative_path": f"marketing_out/uploads/{unique}",
        "url": upload_public_url(unique),
        "size": len(data),
    }
    if as_brand_reference:
        try:
            from veridiq.postings.learning.references import promote_upload_as_brand_reference

            ref = promote_upload_as_brand_reference(
                str(dest),
                topic=topic or Path(original_name).stem or "brand",
                tags=["brand", "user_upload"],
            )
            out["brand_reference"] = ref
        except Exception as exc:
            out["brand_reference"] = {"ok": False, "error": str(exc)[:120]}
    return out


def resolve_attachment_paths(attachments: Optional[list[Any]]) -> list[str]:
    """Map client attachment refs (url, filename, relative path) to local files.

    Only files inside marketing_out/uploads/ are accepted (no path traversal).
    """
    if not attachments:
        return []
    ensure_upload_dir()
    resolved: list[str] = []
    seen: set[str] = set()
    root = UPLOAD_DIR.resolve()
    for raw in attachments:
        if raw is None:
            continue
        if isinstance(raw, dict):
            ref = str(
                raw.get("filename")
                or raw.get("path")
                or raw.get("url")
                or raw.get("relative_path")
                or ""
            ).strip()
        else:
            ref = str(raw).strip()
        if not ref:
            continue
        name = _extract_upload_filename(ref)
        if not name:
            continue
        path = (UPLOAD_DIR / name).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            continue
        if not path.is_file():
            continue
        ext = path.suffix.lower()
        if ext not in _IMAGE_EXT:
            continue
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        resolved.append(key)
    return resolved


def _extract_upload_filename(ref: str) -> str:
    s = (ref or "").replace("\\", "/").strip()
    if not s:
        return ""
    # Strip query / fragment
    s = s.split("?", 1)[0].split("#", 1)[0]
    # Accept public URL or relative marketing_out/uploads/... or bare filename
    markers = (
        "/marketing/upload/file/",
        "marketing_out/uploads/",
        "/uploads/",
    )
    for marker in markers:
        if marker in s:
            s = s.split(marker, 1)[-1]
            break
    name = Path(s).name
    return safe_filename(name) if name else ""


def copy_upload_as_image(path: str, *, filename_stem: str = "up_img") -> dict[str, Any]:
    """Copy an upload into marketing_out/images and return create_image-shaped meta."""
    import shutil

    src = Path(path)
    if not src.is_file():
        return {"ok": False, "status": "error", "message": "Upload file missing."}
    img_dir = _ROOT / "marketing_out" / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    ext = src.suffix.lower() if src.suffix.lower() in _IMAGE_EXT else ".png"
    dest_name = safe_filename(f"{filename_stem}_{uuid.uuid4().hex[:10]}{ext}")
    dest = img_dir / dest_name
    shutil.copy2(src, dest)
    url = f"/api/v1/veridiq/marketing/image/file/{dest_name}"
    return {
        "ok": True,
        "status": "ok",
        "image_url": url,
        "absolute_path": str(dest),
        "filename": dest_name,
        "provider": "user_upload",
        "message": "Using your uploaded image.",
    }
