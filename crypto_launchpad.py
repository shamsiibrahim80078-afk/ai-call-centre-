"""
Crypto Smart Contract Launchpad
Programmatic ERC-20 generation, regex security audit, and simulated multi-network broadcast.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass, field
from typing import Any

from database import initialize_database, list_deployed_contracts, save_deployed_contract

SUPPORTED_NETWORKS = ("Base", "Solana", "Ethereum")


@dataclass
class AuditFinding:
    severity: str
    rule: str
    detail: str


@dataclass
class AuditReport:
    passed: bool
    findings: list[AuditFinding] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "findings": [
                {"severity": f.severity, "rule": f.rule, "detail": f.detail}
                for f in self.findings
            ],
        }


@dataclass
class BroadcastResult:
    network: str
    contract_address: str
    tx_hash: str
    db_record_id: int
    token_name: str
    token_symbol: str


def generate_erc20_solidity(
    token_name: str,
    token_symbol: str,
    initial_supply: int = 1_000_000,
    decimals: int = 18,
) -> str:
    """
    Generate raw Solidity ERC-20 token source from string inputs.
    Produces a self-contained contract with transfer, approve, and transferFrom.
    """
    if not token_name or not token_name.strip():
        raise ValueError("token_name is required.")
    if not token_symbol or not token_symbol.strip():
        raise ValueError("token_symbol is required.")
    if initial_supply <= 0:
        raise ValueError("initial_supply must be positive.")
    if decimals < 0 or decimals > 18:
        raise ValueError("decimals must be between 0 and 18.")

    safe_name = re.sub(r"[^A-Za-z0-9_]", "", token_name.strip().replace(" ", ""))
    if not safe_name or not safe_name[0].isalpha():
        safe_name = f"Token{safe_name}" if safe_name else "GeneratedToken"

    symbol = token_symbol.strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{2,10}", symbol):
        raise ValueError("token_symbol must be 2-10 alphanumeric characters.")

    display_name = token_name.strip().replace('"', "")
    total = initial_supply * (10**decimals)

    source = f"""// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @title {display_name} ({symbol})
/// @notice Auto-generated ERC-20 by Sovereign Swarm Crypto Launchpad
contract {safe_name} {{
    string public name = "{display_name}";
    string public symbol = "{symbol}";
    uint8 public decimals = {decimals};
    uint256 public totalSupply = {total};

    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed owner, address indexed spender, uint256 value);

    constructor() {{
        balanceOf[msg.sender] = totalSupply;
        emit Transfer(address(0), msg.sender, totalSupply);
    }}

    function transfer(address to, uint256 value) public returns (bool) {{
        require(to != address(0), "ERC20: transfer to zero address");
        require(balanceOf[msg.sender] >= value, "ERC20: insufficient balance");
        unchecked {{
            balanceOf[msg.sender] -= value;
            balanceOf[to] += value;
        }}
        emit Transfer(msg.sender, to, value);
        return true;
    }}

    function approve(address spender, uint256 value) public returns (bool) {{
        require(spender != address(0), "ERC20: approve to zero address");
        allowance[msg.sender][spender] = value;
        emit Approval(msg.sender, spender, value);
        return true;
    }}

    function transferFrom(address from, address to, uint256 value) public returns (bool) {{
        require(to != address(0), "ERC20: transfer to zero address");
        require(balanceOf[from] >= value, "ERC20: insufficient balance");
        require(allowance[from][msg.sender] >= value, "ERC20: insufficient allowance");
        unchecked {{
            allowance[from][msg.sender] -= value;
            balanceOf[from] -= value;
            balanceOf[to] += value;
        }}
        emit Transfer(from, to, value);
        return true;
    }}
}}
"""
    return source


# Structural security audit rules (regex-based static scan)
_AUDIT_RULES: list[tuple[str, str, str, bool]] = [
    # (rule_id, severity, pattern, fail_if_missing)
    ("SPDX_LICENSE", "critical", r"SPDX-License-Identifier\s*:", True),
    ("PRAGMA_SOLIDITY", "critical", r"pragma\s+solidity\s+\^?0\.8\.", True),
    ("CONTRACT_DECL", "critical", r"\bcontract\s+[A-Za-z_][A-Za-z0-9_]*\s*\{", True),
    ("TOTAL_SUPPLY", "high", r"\btotalSupply\b", True),
    ("BALANCE_MAPPING", "high", r"mapping\s*\(\s*address\s*=>\s*uint256\s*\)\s+public\s+balanceOf", True),
    ("TRANSFER_FN", "high", r"function\s+transfer\s*\(", True),
    ("APPROVE_FN", "high", r"function\s+approve\s*\(", True),
    ("TRANSFER_FROM_FN", "high", r"function\s+transferFrom\s*\(", True),
    ("TRANSFER_EVENT", "medium", r"event\s+Transfer\s*\(", True),
    ("APPROVAL_EVENT", "medium", r"event\s+Approval\s*\(", True),
    ("ZERO_ADDR_GUARD", "high", r"require\s*\(\s*\w+\s*!=\s*address\s*\(\s*0\s*\)", True),
    ("SELFDESTRUCT", "critical", r"\bselfdestruct\s*\(", False),
    ("DELEGATECALL", "critical", r"\bdelegatecall\s*\(", False),
    ("TX_ORIGIN", "high", r"\btx\.origin\b", False),
    ("INLINE_ASSEMBLY", "high", r"\bassembly\s*\{", False),
    ("SUICIDE_OPCODE", "critical", r"\bsuicide\s*\(", False),
]


def audit_solidity_source(source: str) -> AuditReport:
    """
    Regex security audit scanning for structural flaws and dangerous constructs.
    Fail-if-missing rules enforce ERC-20 skeleton integrity.
    Fail-if-present rules flag known-dangerous patterns.
    """
    if not source or not source.strip():
        return AuditReport(
            passed=False,
            findings=[
                AuditFinding("critical", "EMPTY_SOURCE", "Solidity source is empty."),
            ],
        )

    findings: list[AuditFinding] = []

    for rule_id, severity, pattern, fail_if_missing in _AUDIT_RULES:
        matched = re.search(pattern, source, flags=re.MULTILINE)
        if fail_if_missing and not matched:
            findings.append(
                AuditFinding(
                    severity=severity,
                    rule=rule_id,
                    detail=f"Required structural element missing: /{pattern}/",
                )
            )
        elif not fail_if_missing and matched:
            findings.append(
                AuditFinding(
                    severity=severity,
                    rule=rule_id,
                    detail=f"Dangerous construct detected at index {matched.start()}: /{pattern}/",
                )
            )

    # Unbalanced braces structural check
    if source.count("{") != source.count("}"):
        findings.append(
            AuditFinding(
                severity="critical",
                rule="BRACE_BALANCE",
                detail="Unbalanced curly braces detected in source.",
            )
        )

    # Floating pragma without caret or exact pin is flagged medium
    if re.search(r"pragma\s+solidity\s+>=", source):
        findings.append(
            AuditFinding(
                severity="medium",
                rule="LOOSE_PRAGMA",
                detail="Loose >= pragma range widens compiler surface; prefer ^0.8.x.",
            )
        )

    blocking = {"critical", "high"}
    passed = not any(f.severity in blocking for f in findings)
    return AuditReport(passed=passed, findings=findings)


def _simulate_evm_address(seed: str) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return "0x" + digest[:40]


def _simulate_solana_address(seed: str) -> str:
    # Base58-ish simulated address (alphanumeric, fixed length)
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    chars = [alphabet[b % len(alphabet)] for b in digest]
    return "".join(chars)[:44]


def _simulate_tx_hash(seed: str) -> str:
    nonce = secrets.token_hex(8)
    digest = hashlib.sha256(f"{seed}:{nonce}".encode("utf-8")).hexdigest()
    return "0x" + digest


def simulate_broadcast(
    token_name: str,
    token_symbol: str,
    network: str,
    solidity_source: str,
    audit: AuditReport | None = None,
) -> BroadcastResult:
    """
    Simulate broadcasting a transaction onto Base, Solana, or Ethereum and
    commit the resulting address logs into deployed_contracts via database.py.
    """
    normalized = network.strip()
    # Accept case-insensitive network names, store canonical casing
    network_map = {n.lower(): n for n in SUPPORTED_NETWORKS}
    if normalized.lower() not in network_map:
        raise ValueError(
            f"Unsupported network '{network}'. Supported: {', '.join(SUPPORTED_NETWORKS)}"
        )
    canonical_network = network_map[normalized.lower()]

    report = audit if audit is not None else audit_solidity_source(solidity_source)
    if not report.passed:
        blocked = ", ".join(f.rule for f in report.findings if f.severity in {"critical", "high"})
        raise RuntimeError(f"Broadcast blocked by security audit failures: {blocked}")

    seed = f"{token_name}|{token_symbol}|{canonical_network}|{len(solidity_source)}"
    if canonical_network == "Solana":
        contract_address = _simulate_solana_address(seed)
    else:
        contract_address = _simulate_evm_address(seed)

    tx_hash = _simulate_tx_hash(seed)

    record_id = save_deployed_contract(
        token_name=token_name,
        token_symbol=token_symbol,
        contract_address=contract_address,
        network=canonical_network,
        tx_hash=tx_hash,
    )

    return BroadcastResult(
        network=canonical_network,
        contract_address=contract_address,
        tx_hash=tx_hash,
        db_record_id=record_id,
        token_name=token_name,
        token_symbol=token_symbol.strip().upper(),
    )


def compile_audit_and_deploy(
    token_name: str,
    token_symbol: str,
    network: str = "Base",
    initial_supply: int = 1_000_000,
    decimals: int = 18,
) -> dict[str, Any]:
    """End-to-end pipeline: generate → audit → simulate broadcast → DB commit."""
    initialize_database()
    source = generate_erc20_solidity(
        token_name=token_name,
        token_symbol=token_symbol,
        initial_supply=initial_supply,
        decimals=decimals,
    )
    audit = audit_solidity_source(source)
    if not audit.passed:
        return {
            "success": False,
            "source_length": len(source),
            "audit": audit.to_dict(),
            "broadcast": None,
        }

    broadcast = simulate_broadcast(
        token_name=token_name,
        token_symbol=token_symbol,
        network=network,
        solidity_source=source,
        audit=audit,
    )
    return {
        "success": True,
        "source_length": len(source),
        "source_preview": source[:240] + ("..." if len(source) > 240 else ""),
        "audit": audit.to_dict(),
        "broadcast": {
            "network": broadcast.network,
            "contract_address": broadcast.contract_address,
            "tx_hash": broadcast.tx_hash,
            "db_record_id": broadcast.db_record_id,
            "token_name": broadcast.token_name,
            "token_symbol": broadcast.token_symbol,
        },
    }


def _self_test() -> None:
    print("=" * 60)
    print("CRYPTO LAUNCHPAD — SELF-TEST")
    print("=" * 60)

    initialize_database()
    print("[OK] Database initialized for launchpad test")

    source = generate_erc20_solidity("Sovereign Swarm Token", "SST", initial_supply=5_000_000)
    print(f"[OK] Generated Solidity source ({len(source)} bytes)")
    assert "contract SovereignSwarmToken" in source
    assert "function transfer(" in source

    audit = audit_solidity_source(source)
    print(f"[OK] Audit passed={audit.passed} findings={len(audit.findings)}")
    assert audit.passed, f"Unexpected audit failure: {audit.to_dict()}"

    # Negative audit: missing transfer should fail
    broken = re.sub(r"function\s+transfer\s*\([^)]*\)[^{]*\{[^}]*\}", "", source, count=1)
    broken_audit = audit_solidity_source(broken)
    assert not broken_audit.passed
    print("[OK] Negative audit correctly rejected surgically broken source")

    # Dangerous construct detection
    dangerous = source.replace(
        "function approve(address spender, uint256 value) public returns (bool) {",
        "function approve(address spender, uint256 value) public returns (bool) {\n"
        "        selfdestruct(payable(msg.sender));",
    )
    danger_audit = audit_solidity_source(dangerous)
    assert not danger_audit.passed
    assert any(f.rule == "SELFDESTRUCT" for f in danger_audit.findings)
    print("[OK] Dangerous selfdestruct pattern flagged")

    results = []
    for network in SUPPORTED_NETWORKS:
        payload = compile_audit_and_deploy(
            token_name="Sovereign Swarm Token",
            token_symbol="SST",
            network=network,
            initial_supply=5_000_000,
        )
        assert payload["success"] is True
        bc = payload["broadcast"]
        assert bc is not None
        results.append(bc)
        print(
            f"[OK] Simulated deploy on {bc['network']}: "
            f"addr={bc['contract_address'][:18]}... db_id={bc['db_record_id']}"
        )

    contracts = list_deployed_contracts()
    assert len(contracts) >= len(SUPPORTED_NETWORKS)
    print(f"[OK] deployed_contracts table contains {len(contracts)} record(s)")

    print("=" * 60)
    print("CRYPTO LAUNCHPAD SELF-TEST: PASSED")
    print("=" * 60)


if __name__ == "__main__":
    _self_test()
