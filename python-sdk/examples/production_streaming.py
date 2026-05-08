"""Production-ready streaming example with DatAPI price feeds and volume-based pricing.

Mirrors ``rust-sdk/examples/production_streaming.rs``:

* Uses integer arithmetic for precise financial calculations.
* Streams orderbooks for SOL/USDC and a custom MCT/USDC SPL token pair.
* Demonstrates swap streaming with transaction signing via solders.
"""

import asyncio
import base64
import logging
import os
import sys
from typing import List, Optional, Tuple

# Make ``rfq_sdk`` and ``protos`` importable when run directly from the repo
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "src"))
sys.path.insert(0, _HERE)

import base58  # noqa: E402  pylint: disable=wrong-import-position
from solders.keypair import Keypair  # type: ignore[import]  noqa: E402
from solders.transaction import VersionedTransaction  # type: ignore[import]  noqa: E402

from helpers.datapi import DatapiClient  # noqa: E402  pylint: disable=wrong-import-position
from rfq_sdk import (  # noqa: E402
    ClientConfig,
    MarketMakerClient,
    MarketMakerQuoteBuilder,
    MarketMakerSwap,
    StreamConfig,
    SwapMessageType,
    TokenHelper,
    TokenPair,
    swap_helpers,
)
from rfq_sdk.streaming import update_helpers  # noqa: E402


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("production_streaming")


# ---------------------------------------------------------------------------
# Constants — mirror the Rust example exactly
# ---------------------------------------------------------------------------

class SolanaTokens:
    """Mirrors the Rust ``SolanaTokens`` struct."""

    SOL = "So11111111111111111111111111111111111111112"
    USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    SPL_TOKEN = "A3QAoKnf3jFcCfTGvEpE7KVBMZqXQJwvwt6Uc4UExkDp"


PRICE_DECIMALS = 6
SOL_DECIMALS = 9
SPL_TOKEN_DECIMALS = 6
SPL_TOKEN_SCALE = 10 ** SPL_TOKEN_DECIMALS
PRICE_SCALE = 10 ** PRICE_DECIMALS
SOL_SCALE = 10 ** SOL_DECIMALS
BASIS_POINTS_SCALE = 10_000
PRICE_IMPROVEMENT_BP = 7

# (volume_in_lamports, spread_basis_points) — mirrors Rust ``VOLUME_TIERS``.
VOLUME_TIERS: List[Tuple[int, int]] = [
    (1 * SOL_SCALE, 0),
    (10 * SOL_SCALE, 0),
    (100 * SOL_SCALE, 0),
    (1000 * SOL_SCALE, 0),
    (5000 * SOL_SCALE, 0),
]


# ---------------------------------------------------------------------------
# Pricing helpers
# ---------------------------------------------------------------------------

def fetch_token_prices(datapi: DatapiClient) -> Tuple[int, Optional[int]]:
    """Fetch USD prices for SOL and the custom SPL token. Mirrors Rust helper."""
    response = datapi.fetch_prices([SolanaTokens.SOL, SolanaTokens.SPL_TOKEN])

    sol_data = response.get(SolanaTokens.SOL)
    if sol_data is None:
        raise RuntimeError("SOL price not found in DatAPI response")
    sol_price = round(sol_data.usd_price * PRICE_SCALE)

    spl_data = response.get(SolanaTokens.SPL_TOKEN)
    spl_price: Optional[int] = (
        round(spl_data.usd_price * PRICE_SCALE) if spl_data is not None else None
    )

    return sol_price, spl_price


def usdc_to_token_volume(usdc_amount: int, token_price: int, token_scale: int) -> int:
    if token_price == 0:
        return 0
    product = usdc_amount * token_scale
    return product // token_price


def usdc_to_sol_volume(usdc_amount: int, sol_price: int) -> int:
    return usdc_to_token_volume(usdc_amount, sol_price, SOL_SCALE)


def get_spread_bp(volume_lamports: int) -> int:
    """Get the spread in basis points based on volume tier."""
    for tier_volume, spread in reversed(VOLUME_TIERS):
        if volume_lamports >= tier_volume:
            return spread
    return 1


def calculate_price_deviation_for_usdc(
    usdc_amount: int, sol_price: int
) -> Tuple[int, int, int]:
    """Calculate the price deviation for a given USDC input amount."""
    volume_lamports = usdc_to_sol_volume(usdc_amount, sol_price)
    spread_bp = get_spread_bp(volume_lamports)

    half_spread = sol_price * spread_bp // (BASIS_POINTS_SCALE * 2)
    improvement = sol_price * PRICE_IMPROVEMENT_BP // BASIS_POINTS_SCALE
    final_bid = max(0, sol_price - half_spread + improvement)
    final_ask = max(0, sol_price + half_spread - improvement)
    return final_bid, final_ask, volume_lamports


def price_to_display(price: int) -> str:
    whole = price // PRICE_SCALE
    fractional = price % PRICE_SCALE
    return f"{whole}.{fractional:0{PRICE_DECIMALS}d}"


def lamports_to_display(lamports: int) -> str:
    whole = lamports // SOL_SCALE
    fractional = lamports % SOL_SCALE
    return f"{whole}.{fractional:0{SOL_DECIMALS}d}"


def basis_points_to_percentage(bp: int) -> float:
    return (bp / BASIS_POINTS_SCALE) * 100.0


# ---------------------------------------------------------------------------
# Keypair management
# ---------------------------------------------------------------------------

def load_or_generate_keypair() -> Keypair:
    """Load a keypair from ``SOLANA_PRIVATE_KEY`` or generate a temporary one."""
    private_key_str = os.environ.get("SOLANA_PRIVATE_KEY")
    if private_key_str:
        logger.info("Loading keypair from SOLANA_PRIVATE_KEY environment variable")
        try:
            keypair = Keypair.from_bytes(base58.b58decode(private_key_str.strip()))
            logger.info("Loaded keypair with public key: %s", keypair.pubkey())
            return keypair
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to load keypair: %s", exc)
    logger.warning("No keypair provided - generating a temporary keypair")
    keypair = Keypair()
    logger.info("Generated temporary keypair: %s", keypair.pubkey())
    return keypair


# ---------------------------------------------------------------------------
# Transaction signing
# ---------------------------------------------------------------------------

def process_and_sign_transaction(
    swap_uuid: str, unsigned_tx_base64: str, keypair: Keypair
) -> str:
    """Decode, validate, sign and re-encode an unsigned transaction.

    Mirrors Rust ``process_and_sign_transaction``.
    """
    logger.info("Processing transaction for swap UUID: %s", swap_uuid)
    tx_bytes = base64.b64decode(unsigned_tx_base64)
    logger.info("Decoded transaction: %d bytes", len(tx_bytes))

    transaction = VersionedTransaction.from_bytes(tx_bytes)
    logger.info("Transaction deserialized successfully")
    validate_versioned_transaction(transaction)

    # solders signs at index 0 by default; the Rust example signs at index 1
    # (the maker's slot). Build a fresh transaction with the maker as the
    # second signer slot, then move the signature into the original layout.
    signed = VersionedTransaction(transaction.message, [keypair])
    sigs = list(transaction.signatures)
    sigs[1] = list(signed.signatures)[0]
    final_tx = VersionedTransaction.populate(transaction.message, sigs)
    encoded = base64.b64encode(bytes(final_tx)).decode("ascii")
    logger.info("Transaction signed and encoded successfully")
    return encoded


def validate_versioned_transaction(transaction: VersionedTransaction) -> None:
    """Mirror Rust ``validate_versioned_transaction`` — raise on malformed tx."""
    msg = transaction.message
    if not msg.instructions:
        raise RuntimeError("Transaction has no instructions")
    if not msg.account_keys:
        raise RuntimeError("Transaction has no account keys")
    logger.info("Transaction validation passed")
    logger.info("Instructions: %d", len(msg.instructions))
    logger.info("Account keys: %d", len(msg.account_keys))


# ---------------------------------------------------------------------------
# Swap stream handling
# ---------------------------------------------------------------------------

async def run_swap_stream(swap_stream, keypair: Keypair, stream_config: StreamConfig) -> None:
    """Run the swap streaming loop. Mirrors Rust ``run_swap_stream``."""
    swap_count = 0
    health_check_counter = 0
    last_ping = asyncio.get_event_loop().time()
    ping_interval = 10.0

    logger.info("Swap stream started with keep-alive monitoring")

    while True:
        # Send periodic pings to keep the connection alive
        now = asyncio.get_event_loop().time()
        if now - last_ping >= ping_interval:
            ping = MarketMakerSwap(
                message_type=SwapMessageType.SWAP_MESSAGE_TYPE_PING,
                swap_uuid="",
                signed_transaction="",
            )
            try:
                await swap_stream.send_swap(ping)
                logger.info("Sent ping to server")
                last_ping = now
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to send ping: %s", exc)
                break

        # Receive updates with a short timeout
        try:
            update = await swap_stream.receive_update_timeout(0.1)
        except Exception:  # noqa: BLE001 - includes our TimeoutError
            update = None

        if update is None:
            await asyncio.sleep(0.05)
            continue

        health_check_counter += 1

        if swap_helpers.is_pong(update):
            logger.info("Received pong from server")
            continue

        if swap_helpers.is_connection_ready(update):
            status = swap_helpers.get_status_message(update) or "Ready"
            logger.info("Swap stream connection established: %s", status)
            continue

        if swap_helpers.is_error(update):
            err = swap_helpers.get_status_message(update) or "Unknown error"
            logger.error("Swap stream error: %s", err)
            continue

        if swap_helpers.is_transaction_confirmed(update):
            details = swap_helpers.extract_confirmation_details(update)
            if details is not None:
                uuid, signature = details
                logger.info("Transaction confirmed - UUID: %s, Signature: %s", uuid, signature)
            continue

        if swap_helpers.is_swap_available(update):
            details = swap_helpers.extract_swap_details(update)
            if details is None:
                logger.warning("Received swap available but missing details")
                continue
            swap_uuid, unsigned_tx = details
            swap_count += 1
            logger.info("Swap #%d: %s", swap_count, swap_uuid)
            try:
                signed_tx = process_and_sign_transaction(swap_uuid, unsigned_tx, keypair)
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to sign transaction: %s", exc)
                continue
            outbound = MarketMakerSwap(
                message_type=SwapMessageType.SWAP_MESSAGE_TYPE_SWAP_SUBMIT,
                swap_uuid=swap_uuid,
                signed_transaction=signed_tx,
            )
            try:
                await swap_stream.send_swap(outbound)
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to send signed tx: %s", exc)
                break
        else:
            logger.info(
                "Received other swap update type: %s",
                swap_helpers.update_type_description(update),
            )

        if health_check_counter >= 10:
            if not await swap_stream.is_healthy(stream_config):
                logger.warning("Swap stream health check failed - possible connection issue")
            health_check_counter = 0

    logger.info("Swap stream completed: %d swaps processed", swap_count)
    final_stats = await swap_stream.get_stats()
    logger.info(
        "Swap stats: %d sent, %d received, %d errors, uptime %s",
        final_stats.messages_sent,
        final_stats.updates_received,
        final_stats.errors_encountered,
        final_stats.elapsed(),
    )
    try:
        await swap_stream.close_with_timeout(5.0)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Swap stream close error: %s", exc)


# ---------------------------------------------------------------------------
# Quote stream helpers
# ---------------------------------------------------------------------------

def _build_volume_tiers(builder: MarketMakerQuoteBuilder, base_price: int) -> Tuple[
    MarketMakerQuoteBuilder, int, int
]:
    """Add volume-tier bid/ask levels to the builder. Mirrors Rust helper."""
    min_bid = None
    max_ask = 0
    for volume, spread_bp in VOLUME_TIERS:
        half_spread = base_price * spread_bp // (BASIS_POINTS_SCALE * 2)
        improvement = base_price * PRICE_IMPROVEMENT_BP // BASIS_POINTS_SCALE
        final_bid = max(0, base_price - half_spread + improvement)
        final_ask = max(0, base_price + half_spread - improvement)
        if final_bid > 0 and (min_bid is None or final_bid < min_bid):
            min_bid = final_bid
        if final_ask > max_ask:
            max_ask = final_ask
        builder = builder.bid_level(volume, final_bid).ask_level(volume, final_ask)
    return builder, min_bid or 0, max_ask


def spl_token_usdc_pair() -> TokenPair:
    """Mirrors the Rust ``spl_token_usdc_pair`` helper."""
    base = TokenHelper.new(
        SolanaTokens.SPL_TOKEN,
        SPL_TOKEN_DECIMALS,
        "MCT",
        "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
    )
    quote = TokenHelper.new(
        SolanaTokens.USDC,
        PRICE_DECIMALS,
        "USDC",
        "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
    )
    return TokenPair(base_token=base, quote_token=quote)


def log_quote_update(update) -> None:
    """Log a QuoteUpdate. Mirrors Rust ``log_quote_update``."""
    if update_helpers.is_new_quote(update):
        logger.info("Server ACK: quote accepted (NEW)")
    elif update_helpers.is_updated_quote(update):
        logger.info("Server ACK: quote accepted (UPDATED)")
    elif update_helpers.is_expired_quote(update):
        logger.warning("Server: quote EXPIRED")
    elif update_helpers.is_rejected_quote(update):
        reason = update_helpers.get_status_message(update) or "no reason provided"
        logger.error("Server REJECTED quote — reason: %s", reason)
    elif update_helpers.is_heartbeat(update):
        logger.info("Server heartbeat received")
    else:
        logger.warning(
            "Unknown update_type=%s, status_message=%r",
            update.update_type,
            getattr(update, "status_message", ""),
        )


async def drain_quote_updates(stream) -> None:
    """Drain pending QuoteUpdate messages. Mirrors Rust ``drain_quote_updates``."""
    while True:
        try:
            update = await stream.receive_update_timeout(0.2)
        except Exception:  # noqa: BLE001 - includes TimeoutError
            return
        if update is None:
            logger.warning("Quote stream closed by server while draining updates")
            return
        log_quote_update(update)


async def run_quote_stream(
    stream,
    next_sequence: int,
    maker_id: str,
    maker_address: str,
    datapi: DatapiClient,
    sol_price: int,
    spl_token_price: int,
) -> None:
    """Run the quote streaming loop. Mirrors Rust ``run_quote_stream``."""
    quote_counter = 0
    price_refresh_counter = 0
    price_refresh_interval = 5
    spl_pair = spl_token_usdc_pair()

    while True:
        if price_refresh_counter >= price_refresh_interval:
            try:
                new_sol, new_spl = fetch_token_prices(datapi)
                if abs(new_sol - sol_price) > PRICE_SCALE // 100:
                    logger.info(
                        "Updated SOL price: $%s -> $%s",
                        price_to_display(sol_price),
                        price_to_display(new_sol),
                    )
                    sol_price = new_sol
                if new_spl is not None and abs(new_spl - spl_token_price) > PRICE_SCALE // 100:
                    logger.info(
                        "Updated MCT price: $%s -> $%s",
                        price_to_display(spl_token_price),
                        price_to_display(new_spl),
                    )
                    spl_token_price = new_spl
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to refresh prices from DatAPI: %s", exc)
            price_refresh_counter = 0

        # --- Quote 1: SOL/USDC ---
        builder = (
            MarketMakerQuoteBuilder.new()
            .maker_id(maker_id)
            .sol_usdc_pair()
            .sequence_number(next_sequence)
            .expiry_time_secs(60)
            .maker_address(maker_address)
            .lot_size_base(10 ** 3)
        )
        builder, sol_min_bid, sol_max_ask = _build_volume_tiers(builder, sol_price)

        try:
            sol_quote = builder.build()
            await stream.send_quote(sol_quote)
            logger.info(
                "SOL/USDC  Quote #%d sent (seq: %d) - %d levels, $%s-$%s",
                quote_counter + 1,
                next_sequence,
                len(VOLUME_TIERS),
                price_to_display(sol_min_bid),
                price_to_display(sol_max_ask),
            )
            next_sequence += 1
            quote_counter += 1
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to send SOL/USDC quote: %s", exc)
            break

        await drain_quote_updates(stream)
        await asyncio.sleep(0.1)

        # --- Quote 2: SPL Token / USDC ---
        builder = (
            MarketMakerQuoteBuilder.new()
            .maker_id(maker_id)
            .token_pair(spl_pair)
            .sequence_number(next_sequence)
            .expiry_time_secs(60)
            .maker_address(maker_address)
            .lot_size_base(10 ** max(0, SPL_TOKEN_DECIMALS - PRICE_DECIMALS))
        )
        builder, spl_min_bid, spl_max_ask = _build_volume_tiers(builder, spl_token_price)

        try:
            spl_quote = builder.build()
            await stream.send_quote(spl_quote)
            logger.info(
                "MCT/USDC  Quote #%d sent (seq: %d) - %d levels, $%s-$%s",
                quote_counter + 1,
                next_sequence,
                len(VOLUME_TIERS),
                price_to_display(spl_min_bid),
                price_to_display(spl_max_ask),
            )
            next_sequence += 1
            quote_counter += 1
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to send MCT/USDC quote: %s", exc)
            break

        await drain_quote_updates(stream)
        price_refresh_counter += 1
        await asyncio.sleep(10.0)
        await drain_quote_updates(stream)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> int:
    """Production streaming entrypoint."""
    logger.info("Production Streaming Example - RFQv2 SDK")
    keypair = load_or_generate_keypair()

    datapi_url = os.environ.get("DATAPI_URL", "https://datapi.jup.ag")
    if not os.environ.get("DATAPI_URL"):
        logger.warning("DATAPI_URL not set - using default %s", datapi_url)
    datapi = DatapiClient(datapi_url)

    try:
        sol_price, spl_optional = fetch_token_prices(datapi)
        logger.info("SOL price: $%s", price_to_display(sol_price))

        usdc_amount = 1_000_000 * PRICE_SCALE
        bid, ask, volume_lamports = calculate_price_deviation_for_usdc(usdc_amount, sol_price)
        price_safe = max(sol_price, 1)
        bid_dev = max(0, sol_price - bid) * BASIS_POINTS_SCALE // price_safe
        ask_dev = max(0, ask - sol_price) * BASIS_POINTS_SCALE // price_safe
        spread_bp = max(0, ask - bid) * BASIS_POINTS_SCALE // price_safe
        logger.info(
            "Example 1M USDC: %s SOL, bid $%s (-%.3f%%), ask $%s (+%.3f%%), spread %.3f%%",
            lamports_to_display(volume_lamports),
            price_to_display(bid),
            basis_points_to_percentage(bid_dev),
            price_to_display(ask),
            basis_points_to_percentage(ask_dev),
            basis_points_to_percentage(spread_bp),
        )

        if spl_optional is not None:
            logger.info("MCT price: $%s", price_to_display(spl_optional))
            spl_price = spl_optional
        else:
            logger.warning("MCT price not available from DatAPI — using fallback $0.20")
            spl_price = 200_000
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to fetch prices from DatAPI: %s. Using fallbacks", exc)
        sol_price, spl_price = 100 * PRICE_SCALE, 200_000

    auth_token = os.environ.get(
        "MM_AUTH_TOKEN",
        "production_jwt_token",
    )
    if not os.environ.get("MM_AUTH_TOKEN"):
        logger.warning(
            "MM_AUTH_TOKEN not set - using default 'production_jwt_token'. "
            "Set MM_AUTH_TOKEN environment variable for production use"
        )

    config = (
        ClientConfig(endpoint="https://rfq-mm-edge-grpc.raccoons.dev")
        .with_timeout(30)
        .with_max_retries(5)
        .with_auth_token(auth_token)
    )

    logger.info("Connecting to RFQv2 service...")
    try:
        client = await MarketMakerClient.connect_with_config(config)
    except Exception as exc:  # noqa: BLE001
        logger.error("Connection failed: %s", exc)
        return 1
    logger.info("Connected successfully")

    stream_config = StreamConfig().with_send_buffer_size(10000)

    maker_id = os.environ.get("MM_MAKER_ID", "production_maker")
    if not os.environ.get("MM_MAKER_ID"):
        logger.warning("MM_MAKER_ID not set - using default 'production_maker'")

    logger.info("Starting quote streaming for maker: %s...", maker_id)
    try:
        stream, next_sequence = await client.start_streaming_with_sync_and_config(
            maker_id, auth_token, stream_config
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to start streaming: %s", exc)
        await client.close()
        return 1
    logger.info("Quote streaming started (sequence: %d)", next_sequence)

    swap_task: Optional[asyncio.Task] = None
    try:
        swap_stream = await client.start_swap_streaming(stream_config)
        swap_task = asyncio.create_task(
            run_swap_stream(swap_stream, keypair, stream_config)
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Swap streaming failed: %s. Continuing with quotes only", exc)

    try:
        await run_quote_stream(
            stream,
            next_sequence,
            maker_id,
            str(keypair.pubkey()),
            datapi,
            sol_price,
            spl_price,
        )
    except KeyboardInterrupt:
        logger.info("Received shutdown signal")

    if swap_task is not None:
        try:
            await asyncio.wait_for(swap_task, timeout=10.0)
            logger.info("Swap handler completed successfully")
        except asyncio.TimeoutError:
            logger.warning("Swap handler timeout")
            swap_task.cancel()

    await client.close()
    logger.info("Shutdown complete")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(0)
