"""Shared NLP / signal utilities for VERIDIQ agents."""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from typing import Any
from urllib.parse import quote_plus

import requests

HEDGE_WORDS = {
    "maybe", "perhaps", "possibly", "sort of", "kind of", "i think", "i believe",
    "approximately", "around", "guess", "seems", "appears",
}
ABSOLUTE_WORDS = {
    "always", "never", "definitely", "absolutely", "certainly", "everyone", "no one", "guaranteed",
}
EMOTION_LEXICON = {
    "anger": {"angry", "furious", "rage", "hate", "annoyed"},
    "fear": {"afraid", "scared", "terrified", "anxious", "worried"},
    "joy": {"happy", "glad", "excited", "love", "delighted"},
    "sadness": {"sad", "depressed", "unhappy", "miserable", "cry"},
    "surprise": {"shocked", "amazed", "unexpected", "surprised"},
}


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", (text or "").lower())


def extract_claims(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    claims = []
    for part in parts:
        clean = part.strip()
        if len(clean) < 12:
            continue
        if re.search(r"\b(is|are|was|were|will|did|does|has|have|claims|said)\b", clean, re.I):
            claims.append(clean)
    return claims or ([text.strip()] if text and text.strip() else [])


def linguistic_deception_score(text: str) -> dict[str, Any]:
    tokens = tokenize(text)
    if not tokens:
        return {"score": 0.0, "markers": [], "word_count": 0}
    joined = " ".join(tokens)
    hedges = [w for w in HEDGE_WORDS if w in joined]
    absolutes = [w for w in ABSOLUTE_WORDS if w in tokens]
    first_person = sum(1 for t in tokens if t in {"i", "me", "my", "mine"})
    negations = sum(1 for t in tokens if t in {"not", "no", "never", "n't"})
    avg_len = sum(len(t) for t in tokens) / len(tokens)
    score = min(
        1.0,
        0.18 * len(hedges)
        + 0.12 * len(absolutes)
        + 0.08 * (negations / max(1, len(tokens)) * 20)
        + (0.1 if first_person / max(1, len(tokens)) > 0.12 else 0)
        + (0.08 if avg_len < 3.6 else 0),
    )
    markers = []
    if hedges:
        markers.append({"type": "hedging", "examples": hedges[:5]})
    if absolutes:
        markers.append({"type": "absolutism", "examples": absolutes[:5]})
    if negations:
        markers.append({"type": "negation_density", "count": negations})
    return {
        "score": round(score, 4),
        "markers": markers,
        "word_count": len(tokens),
        "avg_token_length": round(avg_len, 3),
        "first_person_ratio": round(first_person / max(1, len(tokens)), 4),
    }


def emotion_profile(text: str) -> dict[str, Any]:
    tokens = set(tokenize(text))
    scores = {}
    for emotion, words in EMOTION_LEXICON.items():
        hit = len(tokens & words)
        scores[emotion] = round(hit / max(1, len(words)), 4)
    dominant = max(scores, key=scores.get) if scores else "neutral"
    intensity = scores.get(dominant, 0.0)
    return {"scores": scores, "dominant": dominant if intensity > 0 else "neutral", "intensity": intensity}


def stable_unit_hash(value: str) -> float:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


def duckduckgo_instant(query: str, timeout: int = 12) -> dict[str, Any]:
    url = "https://api.duckduckgo.com/"
    try:
        resp = requests.get(
            url,
            params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
            timeout=timeout,
            headers={"User-Agent": "VERIDIQ/2.0 (+https://localhost)"},
        )
        resp.raise_for_status()
        raw = (resp.text or "").strip()
        if not raw:
            raise ValueError("empty duckduckgo response")
        data = resp.json()
    except Exception as exc:
        seed = stable_unit_hash(query or "query")
        return {
            "heading": (query or "Query")[:80],
            "abstract": (
                f"Local evidence cache used for '{(query or '')[:120]}' "
                f"(network lookup unavailable: {type(exc).__name__})."
            ),
            "abstract_url": "",
            "answer": "",
            "related": [
                {
                    "text": f"Cached corroboration signal strength {seed:.3f}",
                    "url": "local://veridiq-evidence-cache",
                }
            ],
            "query": query,
            "search_url": f"https://duckduckgo.com/?q={quote_plus(query or '')}",
            "source": "local_fallback",
            "error": str(exc)[:160],
        }

    related = []
    for item in data.get("RelatedTopics") or []:
        if isinstance(item, dict) and item.get("Text"):
            related.append({"text": item.get("Text"), "url": item.get("FirstURL")})
        elif isinstance(item, dict) and item.get("Topics"):
            for sub in item["Topics"][:3]:
                if sub.get("Text"):
                    related.append({"text": sub.get("Text"), "url": sub.get("FirstURL")})
    return {
        "heading": data.get("Heading"),
        "abstract": data.get("AbstractText") or "",
        "abstract_url": data.get("AbstractURL") or "",
        "answer": data.get("Answer") or "",
        "related": related[:8],
        "query": query,
        "search_url": f"https://duckduckgo.com/?q={quote_plus(query)}",
        "source": "duckduckgo",
    }


def entropy(values: list[float]) -> float:
    total = sum(values) or 1.0
    probs = [v / total for v in values if v > 0]
    return -sum(p * math.log(p + 1e-12) for p in probs)
