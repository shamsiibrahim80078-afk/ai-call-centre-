"""Smart-contract hooks for timed calling intents.

When WorkforceToken / SubscriptionManager / AgentMarketplace addresses are
configured, records an on-chain intent (or dry-run receipt). Never fabricates
a successful broadcast. Graceful on RPC / rate-limit failures.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger("veridiq.calling.chain_hooks")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _record_local_with_retry(listener: Any, intent: dict[str, Any], *, retries: int = 3) -> Optional[str]:
    """Best-effort local chain event write with backoff; returns error string or None."""
    attempts = max(1, min(5, int(retries)))
    last_err: Optional[str] = None
    for attempt in range(1, attempts + 1):
        try:
            listener.record_local(intent)
            return None
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)[:160]
            logger.warning(
                "chain event record failed (attempt %s/%s): %s",
                attempt,
                attempts,
                last_err,
            )
            if attempt < attempts:
                time.sleep(min(4.0, 0.25 * (2 ** (attempt - 1))))
    return last_err


def record_call_intent(
    *,
    session_id: str,
    agent_type: str = "ai_calling",
    user_key: str = "default",
    purpose: str = "",
    allowed_seconds: int = 120,
    metadata: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Prepare / stub an on-chain record that a timed call was scheduled.

    Graceful on RPC / rate-limit / import failures — never raises to callers.
    """
    try:
        from blockchain.config_loader import blockchain_status, get_contract_address
        from blockchain.event_listener import global_event_listener
        from blockchain.wallet import global_wallet
    except Exception as exc:  # noqa: BLE001
        logger.warning("blockchain modules unavailable for call intent: %s", exc)
        return {
            "ok": False,
            "status": "unavailable",
            "mode": "offline",
            "message": f"Blockchain modules unavailable: {exc}"[:200],
        }

    try:
        contracts = {
            "WorkforceToken": get_contract_address("WorkforceToken"),
            "SubscriptionManager": get_contract_address("SubscriptionManager"),
            "AgentMarketplace": get_contract_address("AgentMarketplace"),
        }
        chain = blockchain_status()
        wallet = global_wallet.identity()
    except Exception as exc:  # noqa: BLE001 — RPC / config blips
        logger.warning("chain status/wallet lookup failed: %s", exc)
        return {
            "ok": True,
            "status": "dry_run",
            "mode": "dry_run",
            "message": f"Chain lookup failed — local dry-run only: {exc}"[:200],
            "intent": {
                "type": "TimedCallIntent",
                "session_id": session_id,
                "agent_type": agent_type,
                "user_key": user_key,
                "purpose": (purpose or "")[:240],
                "allowed_seconds": int(allowed_seconds),
                "prepared_at": _utc_now(),
                "metadata": metadata or {},
                "mode": "dry_run",
            },
        }

    configured = {k: v for k, v in contracts.items() if v}
    intent = {
        "type": "TimedCallIntent",
        "session_id": session_id,
        "agent_type": agent_type,
        "user_key": user_key,
        "purpose": (purpose or "")[:240],
        "allowed_seconds": int(allowed_seconds),
        "contracts": contracts,
        "wallet": getattr(wallet, "address", None),
        "network": (chain or {}).get("network") or (chain or {}).get("active_network"),
        "prepared_at": _utc_now(),
        "metadata": metadata or {},
    }

    if not configured:
        intent["mode"] = "dry_run"
        intent["status"] = "awaiting_contract_address"
        intent["message"] = (
            "No WorkforceToken/SubscriptionManager/AgentMarketplace address configured — "
            "recorded local dry-run intent only."
        )
        err = _record_local_with_retry(global_event_listener, intent)
        if err:
            intent["event_error"] = err
        return {"ok": True, "status": "dry_run", "mode": "dry_run", "intent": intent}

    # Addresses present but we still avoid fabricating a broadcast without a live provider.
    intent["mode"] = "intent_recorded"
    intent["status"] = "intent_recorded"
    intent["message"] = (
        "On-chain call intent recorded locally against configured workforce contracts. "
        "Broadcast requires a live RPC + deployer key."
    )
    err = _record_local_with_retry(global_event_listener, intent)
    if err:
        intent["event_error"] = err

    return {
        "ok": True,
        "status": "intent_recorded",
        "mode": "intent_recorded",
        "configured_contracts": list(configured.keys()),
        "intent": intent,
    }


def intent_to_json(result: dict[str, Any]) -> str:
    return json.dumps(result, default=str)[:8000]
