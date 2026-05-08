"""Example: Deploy a new SPL Token on Solana.

Mirrors ``rust-sdk/examples/deploy_spl_token.rs``: creates a new SPL token
mint, an Associated Token Account, and mints an initial supply.
"""

import asyncio
import base64
import logging
import os
import sys
import time
from typing import Optional

import base58
import requests
from solders.hash import Hash  # type: ignore[import]
from solders.instruction import AccountMeta, Instruction  # type: ignore[import]
from solders.keypair import Keypair  # type: ignore[import]
from solders.pubkey import Pubkey  # type: ignore[import]
from solders.system_program import create_account, CreateAccountParams  # type: ignore[import]
from solders.transaction import Transaction  # type: ignore[import]


# ---------------------------------------------------------------------------
# Constants — mirrors the Rust example exactly
# ---------------------------------------------------------------------------

TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
ASSOCIATED_TOKEN_PROGRAM_ID = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
SYSTEM_PROGRAM_ID = Pubkey.from_string("11111111111111111111111111111111")

MINT_SIZE = 82
TOKEN_NAME = "My Custom Token"
TOKEN_SYMBOL = "MCT"
TOKEN_DECIMALS = 6
INITIAL_SUPPLY = 1_000_000_000_000  # 1,000,000 tokens with 6 decimals


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("deploy_spl_token")


# ---------------------------------------------------------------------------
# Instruction builders — mirror the Rust helpers byte-for-byte
# ---------------------------------------------------------------------------

def build_initialize_mint2_ix(
    mint: Pubkey,
    mint_authority: Pubkey,
    freeze_authority: Optional[Pubkey],
    decimals: int,
) -> Instruction:
    """SPL Token ``InitializeMint2`` (instruction index = 20)."""
    data = bytearray()
    data.append(20)
    data.append(decimals)
    data.extend(bytes(mint_authority))
    if freeze_authority is not None:
        data.append(1)
        data.extend(bytes(freeze_authority))
    else:
        data.append(0)
        data.extend(bytes(32))

    return Instruction(
        program_id=TOKEN_PROGRAM_ID,
        accounts=[AccountMeta(pubkey=mint, is_signer=False, is_writable=True)],
        data=bytes(data),
    )


def build_mint_to_ix(
    mint: Pubkey, destination: Pubkey, authority: Pubkey, amount: int
) -> Instruction:
    """SPL Token ``MintTo`` (instruction index = 7)."""
    data = bytearray()
    data.append(7)
    data.extend(amount.to_bytes(8, "little"))

    return Instruction(
        program_id=TOKEN_PROGRAM_ID,
        accounts=[
            AccountMeta(pubkey=mint, is_signer=False, is_writable=True),
            AccountMeta(pubkey=destination, is_signer=False, is_writable=True),
            AccountMeta(pubkey=authority, is_signer=True, is_writable=False),
        ],
        data=bytes(data),
    )


def get_associated_token_address(wallet: Pubkey, mint: Pubkey) -> Pubkey:
    """Derive the Associated Token Account address."""
    seeds = [bytes(wallet), bytes(TOKEN_PROGRAM_ID), bytes(mint)]
    pda, _ = Pubkey.find_program_address(seeds, ASSOCIATED_TOKEN_PROGRAM_ID)
    return pda


def build_create_ata_ix(payer: Pubkey, wallet: Pubkey, mint: Pubkey) -> Instruction:
    """SPL Associated Token Account ``Create`` instruction."""
    ata = get_associated_token_address(wallet, mint)
    return Instruction(
        program_id=ASSOCIATED_TOKEN_PROGRAM_ID,
        accounts=[
            AccountMeta(pubkey=payer, is_signer=True, is_writable=True),
            AccountMeta(pubkey=ata, is_signer=False, is_writable=True),
            AccountMeta(pubkey=wallet, is_signer=False, is_writable=False),
            AccountMeta(pubkey=mint, is_signer=False, is_writable=False),
            AccountMeta(pubkey=SYSTEM_PROGRAM_ID, is_signer=False, is_writable=False),
            AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
        ],
        data=b"",
    )


# ---------------------------------------------------------------------------
# RPC helpers
# ---------------------------------------------------------------------------

class SolanaRpcClient:
    """Minimal JSON-RPC client for Solana. Mirrors the Rust helper."""

    def __init__(self, url: str):
        self.url = url
        self.session = requests.Session()

    def _post(self, body: dict) -> dict:
        resp = self.session.post(self.url, json=body)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"RPC error: {data['error']}")
        return data

    def get_latest_blockhash(self) -> Hash:
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getLatestBlockhash",
            "params": [{"commitment": "finalized"}],
        }
        result = self._post(body)["result"]
        return Hash.from_string(result["value"]["blockhash"])

    def get_minimum_balance_for_rent_exemption(self, data_len: int) -> int:
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getMinimumBalanceForRentExemption",
            "params": [data_len],
        }
        return int(self._post(body)["result"])

    def send_transaction(self, tx: Transaction) -> str:
        encoded = base64.b64encode(bytes(tx)).decode("ascii")
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sendTransaction",
            "params": [
                encoded,
                {
                    "encoding": "base64",
                    "skipPreflight": False,
                    "preflightCommitment": "confirmed",
                },
            ],
        }
        return self._post(body)["result"]

    def confirm_transaction(self, signature: str, max_retries: int) -> bool:
        for attempt in range(1, max_retries + 1):
            time.sleep(2)
            body = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getSignatureStatuses",
                "params": [[signature]],
            }
            result = self._post(body)["result"]
            value = result["value"][0]
            if value is not None:
                if value.get("err") is not None:
                    logger.error("Transaction failed with error: %s", value["err"])
                    return False
                status = value.get("confirmationStatus") or ""
                if status in ("confirmed", "finalized"):
                    logger.info(
                        "Transaction confirmed (attempt %d/%d): status = %s",
                        attempt,
                        max_retries,
                        status,
                    )
                    return True
            logger.info("Waiting for confirmation (attempt %d/%d)...", attempt, max_retries)
        return False


# ---------------------------------------------------------------------------
# Keypair loading
# ---------------------------------------------------------------------------

def load_keypair(value: str) -> Keypair:
    """Load a keypair from a JSON file path or a base58 string."""
    if os.path.isfile(value):
        with open(value, "r", encoding="utf-8") as fh:
            import json
            return Keypair.from_bytes(bytes(json.load(fh)))
    return Keypair.from_bytes(base58.b58decode(value))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> int:
    rpc_url = os.environ.get("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
    keypair_str = os.environ.get("SOLANA_KEYPAIR")
    if not keypair_str:
        logger.error(
            "SOLANA_KEYPAIR env var is required (base58 private key or path to JSON file)"
        )
        return 1
    payer = load_keypair(keypair_str)
    rpc = SolanaRpcClient(rpc_url)

    logger.info("=== SPL Token Deployment ===")
    logger.info("RPC endpoint : %s", rpc_url)
    logger.info("Payer wallet : %s", payer.pubkey())
    logger.info("Token name   : %s (%s)", TOKEN_NAME, TOKEN_SYMBOL)
    logger.info("Decimals     : %d", TOKEN_DECIMALS)
    logger.info(
        "Initial supply: %f (raw: %d smallest units)",
        INITIAL_SUPPLY / (10 ** TOKEN_DECIMALS),
        INITIAL_SUPPLY,
    )

    # ------------------------------------------------------------------
    # Step 1: create the mint account
    # ------------------------------------------------------------------
    logger.info("\n--- Step 1: Creating mint account ---")
    mint_kp = Keypair()
    mint_pubkey = mint_kp.pubkey()
    logger.info("New mint address: %s", mint_pubkey)

    rent_exemption = rpc.get_minimum_balance_for_rent_exemption(MINT_SIZE)
    logger.info(
        "Rent-exempt minimum: %d lamports (%.6f SOL)",
        rent_exemption,
        rent_exemption / 1e9,
    )

    create_mint_ix = create_account(
        CreateAccountParams(
            from_pubkey=payer.pubkey(),
            to_pubkey=mint_pubkey,
            lamports=rent_exemption,
            space=MINT_SIZE,
            owner=TOKEN_PROGRAM_ID,
        )
    )
    init_mint_ix = build_initialize_mint2_ix(
        mint_pubkey, payer.pubkey(), payer.pubkey(), TOKEN_DECIMALS
    )

    blockhash = rpc.get_latest_blockhash()
    tx = Transaction.new_signed_with_payer(
        [create_mint_ix, init_mint_ix], payer.pubkey(), [payer, mint_kp], blockhash
    )

    logger.info("Sending create-mint transaction...")
    sig = rpc.send_transaction(tx)
    logger.info("Transaction signature: %s", sig)
    if not rpc.confirm_transaction(sig, 15):
        logger.error("Failed to confirm mint creation transaction")
        return 1
    logger.info("Mint account created successfully!")

    # ------------------------------------------------------------------
    # Step 2: create an associated token account
    # ------------------------------------------------------------------
    logger.info("\n--- Step 2: Creating associated token account ---")
    ata = get_associated_token_address(payer.pubkey(), mint_pubkey)
    logger.info("Associated token account: %s", ata)

    create_ata_ix = build_create_ata_ix(payer.pubkey(), payer.pubkey(), mint_pubkey)
    blockhash = rpc.get_latest_blockhash()
    tx = Transaction.new_signed_with_payer(
        [create_ata_ix], payer.pubkey(), [payer], blockhash
    )

    logger.info("Sending create-ATA transaction...")
    sig = rpc.send_transaction(tx)
    logger.info("Transaction signature: %s", sig)
    if not rpc.confirm_transaction(sig, 15):
        logger.error("Failed to confirm ATA creation transaction")
        return 1
    logger.info("Associated token account created!")

    # ------------------------------------------------------------------
    # Step 3: mint initial supply
    # ------------------------------------------------------------------
    logger.info("\n--- Step 3: Minting initial supply ---")
    mint_to_ix = build_mint_to_ix(mint_pubkey, ata, payer.pubkey(), INITIAL_SUPPLY)
    blockhash = rpc.get_latest_blockhash()
    tx = Transaction.new_signed_with_payer(
        [mint_to_ix], payer.pubkey(), [payer], blockhash
    )

    logger.info("Sending mint-to transaction...")
    sig = rpc.send_transaction(tx)
    logger.info("Transaction signature: %s", sig)
    if not rpc.confirm_transaction(sig, 15):
        logger.error("Failed to confirm mint-to transaction")
        return 1
    logger.info("Initial supply minted!")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    logger.info("\n========================================")
    logger.info("  SPL Token Deployed Successfully!")
    logger.info("========================================")
    logger.info("  Mint address     : %s", mint_pubkey)
    logger.info("  Token account    : %s", ata)
    logger.info("  Mint authority   : %s", payer.pubkey())
    logger.info("  Freeze authority : %s", payer.pubkey())
    logger.info("  Decimals         : %d", TOKEN_DECIMALS)
    logger.info(
        "  Total supply     : %f", INITIAL_SUPPLY / (10 ** TOKEN_DECIMALS)
    )
    logger.info("========================================")
    logger.info(
        "  Explorer: https://explorer.solana.com/address/%s", mint_pubkey
    )
    logger.info("========================================")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(130)
