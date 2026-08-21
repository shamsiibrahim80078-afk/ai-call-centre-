"""ABI registry — load contract ABIs from artifacts or abi/ folder."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent
ABI_DIR = Path(os.getenv("VERIDIQ_ABI_DIR", str(_ROOT / "blockchain" / "abi")))
ARTIFACTS_DIR = _ROOT / "artifacts" / "contracts"


def load_abi(contract_name: str) -> Optional[list[dict[str, Any]]]:
    abi_path = ABI_DIR / f"{contract_name}.json"
    if abi_path.exists():
        data = json.loads(abi_path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "abi" in data:
            return data["abi"]

    # Hardhat artifact fallback
    artifact = ARTIFACTS_DIR / f"{contract_name}.sol" / f"{contract_name}.json"
    if artifact.exists():
        data = json.loads(artifact.read_text(encoding="utf-8"))
        return data.get("abi")
    return None


def list_available_abis() -> dict[str, bool]:
    names = [
        "WorkforceToken",
        "WorkforceTreasury",
        "SubscriptionManager",
        "AgentMarketplace",
        "TruthAttestation",
    ]
    return {n: load_abi(n) is not None for n in names}
