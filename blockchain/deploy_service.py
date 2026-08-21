"""
Blockchain deployment service — Hardhat bridge + DB persistence.
Supports dry-run (hardhat) and live networks via env-configured RPC keys.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from database import (  # noqa: E402
    initialize_database,
    list_deployed_contracts,
    save_deployed_contract,
)

SUPPORTED_DEPLOY_NETWORKS = ("Hardhat", "Sepolia", "Base", "Ethereum")
CONTRACT_CATALOG = (
    "WorkforceToken",
    "WorkforceTreasury",
    "SubscriptionManager",
    "AgentMarketplace",
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _npx_cmd() -> str:
    candidates = [
        shutil.which("npx.cmd"),
        shutil.which("npx"),
        str(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "nodejs" / "npx.cmd"),
        str(Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "nodejs" / "npx.cmd"),
        str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "nodejs" / "npx.cmd"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    raise RuntimeError(
        "npx not found. Install Node.js LTS and ensure npx is on PATH."
    )


def _subprocess_env() -> dict[str, str]:
    env = dict(os.environ)
    node_dirs = [
        str(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "nodejs"),
        str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "nodejs"),
    ]
    path_parts = [p for p in node_dirs if Path(p).exists()] + [env.get("PATH", "")]
    env["PATH"] = os.pathsep.join(path_parts)
    return env


def contract_sources_present() -> dict[str, bool]:
    contracts_dir = _ROOT / "contracts"
    return {name: (contracts_dir / f"{name}.sol").exists() for name in CONTRACT_CATALOG}


def list_contracts_from_db(limit: int = 200) -> list[dict[str, Any]]:
    initialize_database()
    return list_deployed_contracts()[:limit]


def contracts_status() -> dict[str, Any]:
    initialize_database()
    sources = contract_sources_present()
    deployed = list_contracts_from_db()
    by_network: dict[str, int] = {}
    for row in deployed:
        net = str(row.get("network") or "unknown")
        by_network[net] = by_network.get(net, 0) + 1

    artifacts_dir = _ROOT / "artifacts" / "contracts"
    return {
        "sources": sources,
        "all_sources_present": all(sources.values()),
        "compiled_artifacts_present": artifacts_dir.exists(),
        "deployed_count": len(deployed),
        "by_network": by_network,
        "supported_networks": list(SUPPORTED_DEPLOY_NETWORKS),
        "hardhat_config": (_ROOT / "hardhat.config.ts").exists(),
        "timestamp": _utc_now_iso(),
    }


def _hardhat_network_name(network: str) -> str:
    mapping = {
        "hardhat": "hardhat",
        "localhost": "hardhat",
        "sepolia": "sepolia",
        "base": "base",
        "ethereum": "ethereum",
        "mainnet": "ethereum",
    }
    key = network.strip().lower()
    if key not in mapping:
        raise ValueError(
            f"Unsupported network '{network}'. Use one of: {', '.join(SUPPORTED_DEPLOY_NETWORKS)}"
        )
    return mapping[key]


def _persist_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    saved: list[dict[str, Any]] = []
    for record in records:
        row_id = save_deployed_contract(
            token_name=record.get("token_name") or record.get("contract_name") or "Contract",
            token_symbol=str(record.get("token_symbol") or "CTR")[:10],
            contract_address=record["contract_address"],
            network=record["network"],
            tx_hash=record["tx_hash"],
            deployed_at=record.get("deployed_at") or _utc_now_iso(),
        )
        saved.append({**record, "db_id": row_id})
    return saved


def _load_deployment_file(network_label: str) -> Optional[dict[str, Any]]:
    deployments = _ROOT / "deployments"
    if not deployments.exists():
        return None
    candidates = [
        deployments / f"{network_label}-latest.json",
        deployments / f"{network_label.lower()}-latest.json",
        deployments / "Hardhat-latest.json",
        deployments / "hardhat-latest.json",
    ]
    for path in candidates:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    files = sorted(deployments.glob("*-latest.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if files:
        return json.loads(files[0].read_text(encoding="utf-8"))
    return None


def deploy_contracts(
    network: str = "Hardhat",
    *,
    dry_run: bool = True,
    timeout_seconds: int = 300,
) -> dict[str, Any]:
    initialize_database()
    if not all(contract_sources_present().values()):
        missing = [k for k, v in contract_sources_present().items() if not v]
        raise FileNotFoundError(f"Missing contract sources: {missing}")

    target = "hardhat" if dry_run else _hardhat_network_name(network)
    if not dry_run and target != "hardhat":
        rpc_map = {
            "sepolia": "SEPOLIA_RPC_URL",
            "base": "BASE_RPC_URL",
            "ethereum": "ETHEREUM_RPC_URL",
        }
        rpc_key = rpc_map[target]
        if not os.getenv(rpc_key) and not (target == "ethereum" and os.getenv("MAINNET_RPC_URL")):
            raise RuntimeError(f"Missing RPC env var {rpc_key} for live deploy.")
        if not (os.getenv("DEPLOYER_PRIVATE_KEY") or os.getenv("PRIVATE_KEY")):
            raise RuntimeError("Missing DEPLOYER_PRIVATE_KEY/PRIVATE_KEY for live deploy.")

    cmd = [_npx_cmd(), "hardhat", "run", "scripts/deploy_all.ts", "--network", target]
    completed = subprocess.run(
        cmd,
        cwd=str(_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        shell=False,
        env=_subprocess_env(),
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "Hardhat deploy failed:\n"
            f"STDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )

    payload = _load_deployment_file("Hardhat" if target == "hardhat" else network.title())
    if payload is None:
        raise RuntimeError("Deploy finished but deployment JSON was not found.")

    records = payload.get("contracts") or []
    for record in records:
        if dry_run:
            record["network"] = "Hardhat"
        record.setdefault("deployed_at", _utc_now_iso())

    saved = _persist_records(records)
    return {
        "success": True,
        "dry_run": dry_run,
        "network": "Hardhat" if dry_run else network,
        "hardhat_network": target,
        "deployed": saved,
        "stdout_tail": "\n".join(completed.stdout.strip().splitlines()[-20:]),
        "timestamp": _utc_now_iso(),
    }


def verify_contracts(network: str = "Hardhat", *, dry_run: bool = True) -> dict[str, Any]:
    initialize_database()
    target = "hardhat" if dry_run else _hardhat_network_name(network)
    cmd = [_npx_cmd(), "hardhat", "run", "scripts/verify.ts", "--network", target]
    completed = subprocess.run(
        cmd,
        cwd=str(_ROOT),
        capture_output=True,
        text=True,
        timeout=300,
        shell=False,
        env=_subprocess_env(),
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "Hardhat verify failed:\n"
            f"STDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )
    return {
        "success": True,
        "dry_run": dry_run or target == "hardhat",
        "network": "Hardhat" if target == "hardhat" else network,
        "message": (
            "Verification completed"
            if target != "hardhat"
            else "Dry-run verification skipped explorer"
        ),
        "stdout_tail": "\n".join(completed.stdout.strip().splitlines()[-30:]),
        "timestamp": _utc_now_iso(),
    }


def _self_test() -> None:
    print("=" * 60)
    print("BLOCKCHAIN SERVICE — SELF-TEST")
    print("=" * 60)
    initialize_database()
    status = contracts_status()
    assert status["all_sources_present"] is True
    print(f"[OK] sources present={status['sources']}")
    print(f"[OK] hardhat_config={status['hardhat_config']}")
    print("=" * 60)
    print("BLOCKCHAIN SERVICE SELF-TEST: PASSED")
    print("=" * 60)


if __name__ == "__main__":
    _self_test()
