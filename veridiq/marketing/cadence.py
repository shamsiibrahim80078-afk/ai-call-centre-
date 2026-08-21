"""Human send cadence — optional jitter between batch approvals.

When multiple marketing drafts are approved at once, waiting 30–180 seconds
between sends avoids blasting platforms with instant identical traffic.
Uses official APIs only; this is pacing, not stealth or ban evasion.

Configure via environment:
  VERIDIQ_MARKETING_CADENCE_ENABLED=1   (default: on for batch approve)
  VERIDIQ_MARKETING_SEND_JITTER_MIN_SEC=30
  VERIDIQ_MARKETING_SEND_JITTER_MAX_SEC=180

Set jitter min/max to 0 to disable sleeps (useful in tests/CI).
"""

from __future__ import annotations

import hashlib
import os
import time
from typing import Any, Optional


def cadence_enabled() -> bool:
    raw = os.getenv("VERIDIQ_MARKETING_CADENCE_ENABLED", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def jitter_bounds() -> tuple[int, int]:
    lo = max(0, int(os.getenv("VERIDIQ_MARKETING_SEND_JITTER_MIN_SEC", "30")))
    hi = max(lo, int(os.getenv("VERIDIQ_MARKETING_SEND_JITTER_MAX_SEC", "180")))
    return lo, hi


def compute_delay_sec(draft_id: str, *, index: int = 0) -> int:
    """Deterministic jitter per draft — same draft always gets the same delay."""
    lo, hi = jitter_bounds()
    if lo == 0 and hi == 0:
        return 0
    if lo == hi:
        return lo
    blob = f"{draft_id}|{index}"
    digest = hashlib.sha256(blob.encode()).hexdigest()
    span = hi - lo + 1
    return lo + (int(digest, 16) % span)


def approve_batch_with_cadence(
    draft_specs: list[dict[str, Any]],
    *,
    approved: bool = True,
    cadence: Optional[bool] = None,
) -> dict[str, Any]:
    """Approve multiple comms drafts sequentially with optional jitter between sends.

    Each spec: {"draft_id": str, "channel": str}
    """
    from veridiq.comms import approve_external_action

    use_cadence = cadence_enabled() if cadence is None else cadence
    results: list[dict[str, Any]] = []
    total_wait = 0

    for i, spec in enumerate(draft_specs):
        draft_id = str(spec.get("draft_id") or "").strip()
        channel = str(spec.get("channel") or "email").strip()
        if not draft_id:
            results.append({"ok": False, "error": "missing draft_id"})
            continue
        delay_before = 0
        if use_cadence and approved and i > 0:
            prev = results[-1] if results else {}
            if prev.get("status") == "sent":
                delay_before = compute_delay_sec(draft_id, index=i)
                if delay_before > 0:
                    total_wait += delay_before
                    time.sleep(delay_before)
        outcome = approve_external_action(draft_id, approved=approved, channel=channel)
        outcome["delay_before_sec"] = delay_before
        results.append(outcome)

    sent = sum(1 for r in results if r.get("status") == "sent")
    pending = sum(1 for r in results if r.get("status") == "approved_pending_integration")
    return {
        "ok": True,
        "count": len(results),
        "sent": sent,
        "approved_pending_integration": pending,
        "cadence_enabled": use_cadence,
        "total_wait_sec": total_wait,
        "jitter_bounds_sec": list(jitter_bounds()),
        "results": results,
        "message": (
            f"Processed {len(results)} approval(s)"
            + (f" with {total_wait}s total cadence spacing" if total_wait else "")
            + "."
        ),
    }
