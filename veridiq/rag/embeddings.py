"""Local embedding helpers — deterministic, no external model required."""

from __future__ import annotations

import hashlib
import math
import re
from typing import Iterable


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def embed_text(text: str, dims: int = 64) -> list[float]:
    """Hashing trick embedding — stable across runs for the same text."""
    vec = [0.0] * dims
    toks = _tokens(text)
    if not toks:
        return vec
    for tok in toks:
        digest = hashlib.sha256(tok.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:4], "little") % dims
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        weight = 1.0 + (digest[5] / 255.0)
        vec[idx] += sign * weight
    # L2 normalize
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def cosine(a: Iterable[float], b: Iterable[float]) -> float:
    aa = list(a)
    bb = list(b)
    if len(aa) != len(bb) or not aa:
        return 0.0
    return sum(x * y for x, y in zip(aa, bb))
