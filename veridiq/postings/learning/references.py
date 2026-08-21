"""Legal brand / style references — user uploads only.

NEVER scrapes Google, Pinterest, or arbitrary websites for images.
Unsplash is **not used** — ``UNSPLASH_ACCESS_KEY`` is ignored even if set.
Learning references come only from user uploads promoted as brand refs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from veridiq.postings.learning.store import (
    list_references,
    register_brand_reference,
)


def unsplash_configured() -> bool:
    """Always False — Unsplash is disabled / not used for learning."""
    return False


def fetch_unsplash_references(
    topic: str,
    *,
    per_page: int = 3,
    save: bool = True,
) -> dict[str, Any]:
    """Unsplash is not used. Returns a skipped response; never calls the network.

    ``UNSPLASH_ACCESS_KEY`` is ignored. Brand references come from user uploads only.
    """
    _ = (topic, per_page, save)
    return {
        "ok": False,
        "status": "disabled",
        "message": (
            "Unsplash is not used — learning uses ratings + user uploads only "
            "(free, no Unsplash/Meta). UNSPLASH_ACCESS_KEY is ignored."
        ),
        "references": [],
        "unsplash": False,
        "cost": "free",
    }


def promote_upload_as_brand_reference(
    upload_path: str,
    *,
    topic: str = "",
    tags: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Copy a user upload into the lasting brand reference library."""
    src = Path(upload_path)
    if not src.is_file():
        return {"ok": False, "message": "upload file not found"}
    return register_brand_reference(
        path=str(src),
        topic=topic or src.stem,
        tags=list(tags or ["brand", "user_upload"]),
        source="upload",
        license="user_upload",
        description=f"Brand reference from user upload: {src.name}",
        copy_into_references=True,
    )


def reference_guidance_for_topic(topic: str, *, limit: int = 3) -> str:
    """Build a short text block from local user-upload brand references only.

    Never calls Unsplash or any external API.
    """
    q = (topic or "").strip()
    if not q:
        return ""
    refs = list_references(topic=q, limit=limit)
    if not refs:
        refs = list_references(limit=limit)
    if not refs:
        return ""

    bits: list[str] = []
    for r in refs[:limit]:
        desc = (r.get("description") or r.get("topic") or "").strip()
        src = r.get("source") or "reference"
        lic = r.get("license") or ""
        attr = r.get("attribution") or ""
        piece = desc[:120] if desc else (r.get("topic") or "brand reference")[:80]
        note = f"{piece} ({src}"
        if lic:
            note += f", {lic}"
        note += ")"
        if attr:
            note += f" — {attr[:60]}"
        bits.append(note)

    if not bits:
        return ""
    return (
        "Style guidance from legal brand/reference library (prompt only, not model training): "
        + "; ".join(bits)
    )
