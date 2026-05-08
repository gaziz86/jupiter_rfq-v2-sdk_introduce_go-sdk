"""Shared configuration and helpers for the integration test suite.

Mirrors ``rust-sdk/tests/common/mod.rs``: provides :class:`TestConfig` (built
from environment variables) and :func:`sign_transaction` for the Ultra API
end-to-end tests.
"""

import base64
import os
from dataclasses import dataclass
from typing import Optional

import base58
from solders.keypair import Keypair  # type: ignore[import]
from solders.transaction import VersionedTransaction  # type: ignore[import]


USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
SPL_TOKEN_MINT = "A3QAoKnf3jFcCfTGvEpE7KVBMZqXQJwvwt6Uc4UExkDp"

DEFAULT_ULTRA_API_BASE = "https://preprod.ultra-api.jup.ag"


# Tell pytest not to try collecting this dataclass as a test class.
__test__ = False


@dataclass
class TestConfig:
    """End-to-end test configuration sourced from environment variables.

    Mirrors the Rust ``TestConfig`` struct in ``tests/common/mod.rs``.
    """

    __test__ = False  # silence PytestCollectionWarning

    ultra_api_base: str
    input_mint: str
    output_mint: str
    taker: str
    keypair: Optional["Keypair"] = None

    @classmethod
    def from_env(cls) -> "TestConfig":
        """Build configuration from environment variables.

        Recognised variables:

        * ``SOLANA_PRIVATE_KEY`` – base58 private key (required for signing)
        * ``ULTRA_API_BASE``    – Ultra API base URL
        * ``INPUT_MINT``        – input mint (default: USDC)
        * ``OUTPUT_MINT``       – output mint (default: SPL_TOKEN_MINT)
        * ``TAKER``             – taker pubkey (defaults to keypair.pubkey())
        """
        keypair: Optional[Keypair] = None
        sk = os.environ.get("SOLANA_PRIVATE_KEY")
        if sk:
            try:
                bytes_ = base58.b58decode(sk.strip())
            except Exception as exc:
                raise AssertionError("SOLANA_PRIVATE_KEY is not valid base58") from exc
            try:
                keypair = Keypair.from_bytes(bytes_)
            except Exception as exc:
                raise AssertionError("SOLANA_PRIVATE_KEY is not a valid keypair") from exc

        taker = os.environ.get("TAKER")
        if not taker:
            if keypair is None:
                raise AssertionError(
                    "Either TAKER or SOLANA_PRIVATE_KEY must be set"
                )
            taker = str(keypair.pubkey())

        return cls(
            ultra_api_base=os.environ.get("ULTRA_API_BASE", DEFAULT_ULTRA_API_BASE),
            input_mint=os.environ.get("INPUT_MINT", USDC_MINT),
            output_mint=os.environ.get("OUTPUT_MINT", SPL_TOKEN_MINT),
            taker=taker,
            keypair=keypair,
        )

    def require_keypair(self) -> "Keypair":
        """Return the keypair, asserting it was provided."""
        if self.keypair is None:
            raise AssertionError("SOLANA_PRIVATE_KEY is required for this test")
        return self.keypair


def sign_transaction(unsigned_tx_base64: str, keypair: "Keypair") -> str:
    """Decode a base64 unsigned transaction, sign it, and re-encode.

    Mirrors the Rust ``common::sign_transaction`` helper. Looks up the slot in
    the transaction's static account keys that matches the keypair's pubkey,
    signs the serialized message, and writes the signature back to that slot.
    """
    tx_bytes = base64.b64decode(unsigned_tx_base64)
    transaction = VersionedTransaction.from_bytes(tx_bytes)

    account_keys = transaction.message.account_keys
    pubkey = keypair.pubkey()
    signer_index = next(
        (i for i, k in enumerate(account_keys) if k == pubkey),
        None,
    )
    if signer_index is None:
        raise AssertionError(
            f"Taker pubkey {pubkey} not found in transaction account keys"
        )

    # solders requires constructing a fresh VersionedTransaction with all
    # signers; replicate the Rust behaviour by signing the serialized message
    # and inlining the signature at the appropriate slot.
    signed = VersionedTransaction(transaction.message, [keypair])
    sigs = list(signed.signatures)
    # Replace the relevant signature in the original signature vector
    original_signatures = list(transaction.signatures)
    original_signatures[signer_index] = sigs[0]

    signed_full = VersionedTransaction.populate(transaction.message, original_signatures)
    return base64.b64encode(bytes(signed_full)).decode("ascii")


__all__ = [
    "DEFAULT_ULTRA_API_BASE",
    "SPL_TOKEN_MINT",
    "TestConfig",
    "USDC_MINT",
    "sign_transaction",
]
