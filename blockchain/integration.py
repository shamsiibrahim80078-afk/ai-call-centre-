"""
VERIDIQ blockchain integration façade — modular EVM-ready services.
"""

from __future__ import annotations

from typing import Any, Optional

from blockchain.abi_registry import list_available_abis, load_abi
from blockchain.config_loader import blockchain_status, get_active_network, get_contract_address
from blockchain.event_listener import global_event_listener
from blockchain.transaction_service import global_tx_service
from blockchain.wallet import global_wallet


class BlockchainIntegration:
    def status(self) -> dict[str, Any]:
        base = blockchain_status()
        base["abis"] = list_available_abis()
        base["transactions"] = global_tx_service.status()
        base["events"] = global_event_listener.poll()
        return base

    def attest_job_report(self, *, job_id: str, report_path: str) -> dict[str, Any]:
        result = global_tx_service.attest_report_hash(report_path=report_path, job_id=job_id)
        global_event_listener.record_local(
            {
                "type": "AttestationPrepared",
                "job_id": job_id,
                "report_hash": result.get("report_hash") or (result.get("receipt") or {}).get("report_hash"),
                "mode": result.get("mode"),
            }
        )
        return result

    def contract_info(self, name: str) -> dict[str, Any]:
        return {
            "name": name,
            "address": get_contract_address(name),
            "abi_loaded": load_abi(name) is not None,
            "network": get_active_network().get("name"),
            "wallet": global_wallet.identity().__dict__,
        }


global_blockchain = BlockchainIntegration()
