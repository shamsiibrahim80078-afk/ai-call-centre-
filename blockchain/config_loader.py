"""Blockchain configuration — env-driven, no hardcoded addresses."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(os.getenv("VERIDIQ_CHAIN_CONFIG", str(_ROOT / "blockchain" / "config" / "networks.json")))
DEPLOYMENTS_PATH = Path(
    os.getenv("VERIDIQ_CHAIN_DEPLOYMENTS", str(_ROOT / "blockchain" / "config" / "deployments.json"))
)


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def get_networks() -> dict[str, Any]:
    data = _load_json(CONFIG_PATH, {"networks": {}})
    return data.get("networks") or {}


def get_active_network_name() -> str:
    return os.getenv("VERIDIQ_CHAIN_NETWORK", "hardhat")


def get_active_network() -> dict[str, Any]:
    networks = get_networks()
    name = get_active_network_name()
    cfg = dict(networks.get(name) or {})
    # Env overrides
    if os.getenv("VERIDIQ_RPC_URL"):
        cfg["rpc_url"] = os.getenv("VERIDIQ_RPC_URL")
    if os.getenv("VERIDIQ_CHAIN_ID"):
        cfg["chain_id"] = int(os.getenv("VERIDIQ_CHAIN_ID"))
    cfg["name"] = name
    return cfg


def get_deployments() -> dict[str, Any]:
    return _load_json(DEPLOYMENTS_PATH, {"networks": {}})


def get_contract_address(contract_name: str, network: Optional[str] = None) -> Optional[str]:
    network = network or get_active_network_name()
    env_key = f"VERIDIQ_CONTRACT_{contract_name.upper()}"
    if os.getenv(env_key):
        return os.getenv(env_key)
    deployments = get_deployments()
    net = (deployments.get("networks") or {}).get(network) or {}
    contracts = net.get("contracts") or {}
    addr = contracts.get(contract_name)
    return addr or None


def get_wallet_config() -> dict[str, Any]:
    return {
        "private_key_env": "VERIDIQ_DEPLOYER_PRIVATE_KEY",
        "address_env": "VERIDIQ_WALLET_ADDRESS",
        "configured": bool(os.getenv("VERIDIQ_DEPLOYER_PRIVATE_KEY") or os.getenv("VERIDIQ_WALLET_ADDRESS")),
        "wallet_address": os.getenv("VERIDIQ_WALLET_ADDRESS"),
    }


def blockchain_status() -> dict[str, Any]:
    net = get_active_network()
    deployments = get_deployments().get("networks", {}).get(get_active_network_name(), {})
    contracts = deployments.get("contracts") or {}
    return {
        "ready": True,
        "mode": "configured" if any(contracts.values()) or get_wallet_config()["configured"] else "stub",
        "network": net,
        "wallet": get_wallet_config(),
        "contracts": {
            name: {"address": get_contract_address(name), "configured": bool(get_contract_address(name))}
            for name in ("WorkforceToken", "WorkforceTreasury", "SubscriptionManager", "AgentMarketplace", "TruthAttestation")
        },
        "config_path": str(CONFIG_PATH),
        "deployments_path": str(DEPLOYMENTS_PATH),
    }
