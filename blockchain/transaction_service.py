"""Transaction service — prepares and (optionally) submits chain writes."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Optional

from blockchain.abi_registry import load_abi
from blockchain.config_loader import get_active_network, get_contract_address
from blockchain.wallet import global_wallet


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class TransactionService:
    def prepare_attestation(self, *, report_hash: str, job_id: str, metadata: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        network = get_active_network()
        address = get_contract_address("TruthAttestation")
        abi = load_abi("TruthAttestation")
        wallet = global_wallet.identity()
        payload = {
            "job_id": job_id,
            "report_hash": report_hash,
            "metadata": metadata or {},
            "network": network.get("name"),
            "chain_id": network.get("chain_id"),
            "contract": address,
            "abi_loaded": abi is not None,
            "from": wallet.address,
            "prepared_at": _utc_now(),
            "status": "ready" if address else "awaiting_contract_address",
        }
        return payload

    def attest_report_hash(self, *, report_path: str, job_id: str) -> dict[str, Any]:
        data = open(report_path, "rb").read() if report_path else b""
        report_hash = hashlib.sha256(data).hexdigest()
        prepared = self.prepare_attestation(report_hash=report_hash, job_id=job_id, metadata={"report_path": report_path})
        prepared["report_hash"] = report_hash
        # Without a configured contract + key, return a deterministic dry-run receipt
        if prepared["status"] != "ready" or not global_wallet.ready_for_transactions():
            prepared["tx"] = None
            prepared["mode"] = "dry_run"
            prepared["receipt"] = {
                "simulated": True,
                "report_hash": report_hash,
                "note": "Configure VERIDIQ_CONTRACT_TRUTHATTESTATION and wallet env to submit on-chain.",
            }
            return prepared

        # Placeholder live submit hook — integrate web3 when addresses are live
        prepared["mode"] = "live_pending_provider"
        prepared["tx"] = {
            "to": prepared["contract"],
            "data_preview": f"attest({report_hash[:16]}…)",
            "status": "not_broadcast",
        }
        return prepared

    def status(self) -> dict[str, Any]:
        return {
            "service": "TransactionService",
            "wallet_ready": global_wallet.ready_for_transactions(),
            "attestation_contract": get_contract_address("TruthAttestation"),
            "network": get_active_network().get("name"),
        }


global_tx_service = TransactionService()
