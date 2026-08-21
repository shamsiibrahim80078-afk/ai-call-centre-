"""Lightweight learned quality adapter — prompt suffixes from feedback, not NN weights.

``mira_learning_config.json`` holds preferred styles, negative lists from downvotes,
and top prompt suffixes from upvotes. ``apply_learned_quality`` injects anchors
from similar past successes + brand/reference guidance.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Optional

_CONFIG_PATH = Path(__file__).resolve().parent / "mira_learning_config.json"

_STOP = frozenset(
    {
        "a", "an", "the", "and", "or", "of", "to", "for", "in", "on", "with",
        "is", "are", "be", "as", "at", "by", "from", "this", "that", "it",
        "my", "your", "our", "make", "create", "generate", "image", "video",
        "please", "want", "need", "me", "a", "of",
    }
)

DEFAULT_CONFIG: dict[str, Any] = {
    "version": 1,
    "kind": "mira_learning_adapter",
    "disclaimer": (
        "Continuous improvement via user ratings + user-upload brand references. "
        "Free, local only — no Unsplash/Meta. Not foundation-model training. "
        "Not web scraping of copyrighted sites."
    ),
    "preferred_styles": [],
    "negative_from_downvotes": [],
    "prompt_suffixes_from_upvotes": [],
    "rated_examples": 0,
    "updated_at": None,
}


def config_path() -> Path:
    return _CONFIG_PATH


def load_learning_config() -> dict[str, Any]:
    path = _CONFIG_PATH
    if not path.is_file():
        return dict(DEFAULT_CONFIG)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return dict(DEFAULT_CONFIG)
        out = dict(DEFAULT_CONFIG)
        out.update(data)
        return out
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULT_CONFIG)


def save_learning_config(cfg: dict[str, Any]) -> Path:
    path = _CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    merged = dict(DEFAULT_CONFIG)
    merged.update(cfg)
    path.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def tokenize(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {w for w in words if len(w) > 2 and w not in _STOP}


def keyword_overlap_score(a: str, b: str) -> float:
    """Simple Jaccard-like overlap on content tokens (no external embeddings required)."""
    ta, tb = tokenize(a), tokenize(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    if union == 0:
        return 0.0
    return inter / union


def similar_successes(
    topic: str,
    *,
    limit: int = 3,
    min_score: float = 0.08,
) -> list[dict[str, Any]]:
    """Retrieve top-rated past prompts similar to ``topic``."""
    from veridiq.postings.learning.store import top_rated_feedback

    query = (topic or "").strip()
    if not query:
        return []
    scored: list[tuple[float, dict[str, Any]]] = []
    for row in top_rated_feedback(limit=80):
        blob = f"{row.get('topic') or ''} {row.get('prompt') or ''} {row.get('style') or ''}"
        score = keyword_overlap_score(query, blob)
        if score >= min_score:
            scored.append((score, row))
    scored.sort(key=lambda x: (-x[0], -int(x[1].get("rating") or 0)))
    return [r for _, r in scored[:limit]]


def rebuild_learning_config() -> dict[str, Any]:
    """Recompute adapter JSON from stored feedback."""
    from datetime import datetime, timezone

    from veridiq.postings.learning.store import (
        downvoted_feedback,
        feedback_count,
        top_rated_feedback,
    )

    ups = top_rated_feedback(limit=60)
    downs = downvoted_feedback(limit=40)
    style_counts: Counter[str] = Counter()
    suffixes: list[str] = []
    for row in ups:
        st = (row.get("style") or "").strip().lower()
        if st and st not in ("upload", "unknown", ""):
            style_counts[st] += 1
        prompt = (row.get("prompt") or "").strip()
        if prompt:
            # Keep a short distinctive tail as a quality suffix hint
            tail = prompt[-180:].strip() if len(prompt) > 180 else prompt
            if len(tail) > 24 and tail not in suffixes:
                suffixes.append(tail[:160])
        topic = (row.get("topic") or "").strip()
        if topic and len(topic) > 8 and topic not in suffixes:
            suffixes.append(f"quality look inspired by past success: {topic[:100]}")

    neg_bits: list[str] = []
    for row in downs:
        topic = (row.get("topic") or row.get("prompt") or "").strip().lower()
        toks = [t for t in tokenize(topic) if len(t) > 3][:6]
        for t in toks:
            phrase = f"avoid failed look: {t}"
            if phrase not in neg_bits:
                neg_bits.append(phrase)

    preferred = [s for s, _ in style_counts.most_common(5)]
    cfg = {
        "version": 1,
        "kind": "mira_learning_adapter",
        "disclaimer": DEFAULT_CONFIG["disclaimer"],
        "preferred_styles": preferred,
        "negative_from_downvotes": neg_bits[:12],
        "prompt_suffixes_from_upvotes": suffixes[:8],
        "rated_examples": feedback_count(),
        "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    save_learning_config(cfg)
    return cfg


def apply_learned_quality(prompt: str, topic: str = "") -> str:
    """Inject quality anchors from past successes + references into ``prompt``.

    Safe no-op when nothing has been rated yet. Never claims neural fine-tuning.
    """
    base = (prompt or "").strip()
    if not base:
        return base
    topic_s = (topic or base).strip()
    cfg = load_learning_config()
    parts: list[str] = [base]
    low = base.lower()

    # Similar high-rated prompts → short quality anchors
    hits = similar_successes(topic_s, limit=2)
    if hits:
        anchors: list[str] = []
        for h in hits:
            tip = (h.get("topic") or h.get("prompt") or "").strip()
            if not tip:
                continue
            short = tip[:110].rstrip(" .,;")
            if short.lower() in low:
                continue
            anchors.append(short)
        if anchors:
            block = "; ".join(anchors[:2])
            parts.append(
                f"Quality anchors from past successes (user-rated): {block}"
            )

    # Preferred styles from upvotes
    styles = [s for s in (cfg.get("preferred_styles") or []) if isinstance(s, str)]
    if styles:
        pick = styles[0]
        if pick and pick not in low:
            parts.append(f"lean toward preferred style: {pick}")

    # Suffixes learned from upvotes (cap length)
    for suf in (cfg.get("prompt_suffixes_from_upvotes") or [])[:1]:
        if isinstance(suf, str) and suf.strip() and suf.lower()[:40] not in low:
            parts.append(suf.strip()[:140])

    # Negatives from downvotes
    negs = [n for n in (cfg.get("negative_from_downvotes") or []) if isinstance(n, str)]
    if negs:
        # Extract bare keywords after "avoid failed look: "
        cleaned = []
        for n in negs[:5]:
            m = re.sub(r"^avoid failed look:\s*", "", n, flags=re.I).strip()
            if m and m not in cleaned:
                cleaned.append(m)
        if cleaned:
            parts.append(f"Avoid previously disliked cues: {', '.join(cleaned)}")

    # Legal brand reference guidance from user uploads only (text only; no Unsplash)
    try:
        from veridiq.postings.learning.references import reference_guidance_for_topic

        guide = reference_guidance_for_topic(topic_s)
        if guide and guide.lower() not in low:
            parts.append(guide)
    except Exception:
        pass

    out = ". ".join(p.rstrip(".") for p in parts if p)
    while ".." in out:
        out = out.replace("..", ".")
    return out[:2000]


def feedback_stats() -> dict[str, Any]:
    from veridiq.postings.learning.store import (
        downvoted_feedback,
        feedback_count,
        list_feedback,
        reference_count,
        top_rated_feedback,
    )

    n = feedback_count()
    ups = len(top_rated_feedback(limit=500))
    downs = len(downvoted_feedback(limit=500))
    recent = list_feedback(limit=8)
    cfg = load_learning_config()
    return {
        "ok": True,
        "rated_examples": n,
        "thumbs_up_ish": ups,
        "thumbs_down_ish": downs,
        "references": reference_count(),
        "preferred_styles": cfg.get("preferred_styles") or [],
        "learning_sources": ["ratings", "uploads"],
        "unsplash": False,
        "cost": "free",
        "learning_note": (
            "Learns from your ratings & uploads — free, no Unsplash/Meta. "
            "No mass web scraping; not foundation-model training."
        ),
        "recent": recent,
        "config_updated_at": cfg.get("updated_at"),
    }


def learning_status() -> dict[str, Any]:
    stats = feedback_stats()
    cfg = load_learning_config()
    return {
        "ok": True,
        "enabled": True,
        "rated_examples": stats["rated_examples"],
        "references": stats["references"],
        "adapter_kind": cfg.get("kind"),
        "disclaimer": cfg.get("disclaimer") or DEFAULT_CONFIG["disclaimer"],
        "unsplash": False,
        "unsplash_configured": False,
        "learning_sources": ["ratings", "uploads"],
        "cost": "free",
        "message": stats["learning_note"],
    }
