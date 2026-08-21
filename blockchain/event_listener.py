"""Event listener service — polls/logs contract events when configured."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from blockchain.config_loader import get_active_network, get_contract_address


class EventListenerService:
    def __init__(self) -> None:
        self._buffer: list[dict[str, Any]] = []

    def poll(self, contract_name: str = "TruthAttestation", from_block: Optional[int] = None) -> dict[str, Any]:
        address = get_contract_address(contract_name)
        network = get_active_network()
        if not address:
            return {
                "listening": False,
                "reason": "contract address not configured",
                "network": network.get("name"),
                "events": [],
            }
        # Ready hook for web3 eth_getLogs once RPC + ABI are live
        return {
            "listening": True,
            "mode": "standby",
            "contract": contract_name,
            "address": address,
            "network": network.get("name"),
            "from_block": from_block,
            "events": self._buffer[-50:],
            "polled_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        }

    def record_local(self, event: dict[str, Any]) -> None:
        self._buffer.append(event)
        self._buffer = self._buffer[-200:]


global_event_listener = EventListenerService()
