"""Wallet integration interfaces — env-backed, no hardcoded keys."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class WalletIdentity:
    address: Optional[str]
    has_private_key: bool
    provider: str = "env"


class WalletService:
    """Interface for signing / identity. Live RPC signing can be plugged in later."""

    def identity(self) -> WalletIdentity:
        return WalletIdentity(
            address=os.getenv("VERIDIQ_WALLET_ADDRESS"),
            has_private_key=bool(os.getenv("VERIDIQ_DEPLOYER_PRIVATE_KEY")),
            provider=os.getenv("VERIDIQ_WALLET_PROVIDER", "env"),
        )

    def ready_for_transactions(self) -> bool:
        ident = self.identity()
        return bool(ident.address and ident.has_private_key)


global_wallet = WalletService()
