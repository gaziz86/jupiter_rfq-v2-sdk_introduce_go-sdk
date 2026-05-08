"""Type definitions and helpers for the RFQv2 SDK.

Mirrors ``rust-sdk/src/types.rs``: re-exports the generated protobuf types
under stable names, defines :class:`ClientConfig` and helper APIs around
:class:`TokenPair` / :class:`MarketMakerQuote`.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from protos.market_maker_pb2 import (  # re-exported for convenience
    Cluster,
    GetAllOrderbooksRequest,
    GetAllOrderbooksResponse,
    GetQuotesRequest,
    GetQuotesResponse,
    MarketMakerQuote,
    MarketMakerSwap,
    Orderbook,
    PriceLevel,
    QuoteResponse,
    QuoteUpdate,
    SequenceNumberRequest,
    SequenceNumberResponse,
    SwapMessageType,
    SwapUpdate,
    Token,
    TokenPair,
    UpdateType,
)


# --- Default constants (mirrors `lib.rs`) ----------------------------------

DEFAULT_TIMEOUT_SECS: int = 30
"""Default connection timeout in seconds."""

DEFAULT_CHANNEL_BUFFER_SIZE: int = 1000
"""Default channel buffer size for streaming."""

DEFAULT_ENDPOINT: str = "http://localhost:2408"


# --- Client configuration --------------------------------------------------

@dataclass
class ClientConfig:
    """Configuration for connecting to the RFQv2 service.

    Mirrors the Rust ``ClientConfig`` struct.
    """

    endpoint: str = DEFAULT_ENDPOINT
    timeout_secs: int = DEFAULT_TIMEOUT_SECS
    max_retries: int = 3
    stream_buffer_size: int = DEFAULT_CHANNEL_BUFFER_SIZE
    auth_token: Optional[str] = None

    @classmethod
    def new(cls, endpoint: str) -> "ClientConfig":
        """Create a new configuration with the specified endpoint."""
        return cls(endpoint=endpoint)

    @classmethod
    def default(cls) -> "ClientConfig":
        """Create a default configuration."""
        return cls()

    def with_timeout(self, timeout_secs: int) -> "ClientConfig":
        """Set the connection timeout (returns ``self`` for chaining)."""
        self.timeout_secs = timeout_secs
        return self

    def with_max_retries(self, max_retries: int) -> "ClientConfig":
        """Set the maximum retry attempts (returns ``self`` for chaining)."""
        self.max_retries = max_retries
        return self

    def with_auth_token(self, auth_token: str) -> "ClientConfig":
        """Set the authentication token for API access (returns ``self``)."""
        self.auth_token = auth_token
        return self


# --- TokenPair / Token / PriceLevel helpers --------------------------------

class TokenPairHelper:
    """Static helpers for common :class:`TokenPair` instances and operations.

    Mirrors the ``impl TokenPair`` block from the Rust SDK.
    """

    @staticmethod
    def sol_usdc() -> TokenPair:
        """SOL/USDC token pair on mainnet."""
        return TokenPair(
            base_token=Token(
                address="So11111111111111111111111111111111111111112",
                decimals=9,
                symbol="SOL",
                owner="TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
            ),
            quote_token=Token(
                address="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                decimals=6,
                symbol="USDC",
                owner="TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
            ),
        )

    @staticmethod
    def eth_usdc() -> TokenPair:
        """ETH/USDC token pair on mainnet."""
        return TokenPair(
            base_token=Token(
                address="7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs",
                decimals=8,
                symbol="ETH",
                owner="TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
            ),
            quote_token=Token(
                address="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                decimals=6,
                symbol="USDC",
                owner="TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
            ),
        )

    @staticmethod
    def new(base_token: Token, quote_token: Token) -> TokenPair:
        """Create a custom token pair."""
        return TokenPair(base_token=base_token, quote_token=quote_token)

    @staticmethod
    def pair_name(token_pair: TokenPair) -> str:
        """Get a string representation of the token pair (e.g., ``SOL/USDC``)."""
        return f"{token_pair.base_token.symbol}/{token_pair.quote_token.symbol}"


class TokenHelper:
    """Static helpers for :class:`Token`. Mirrors ``impl Token``."""

    @staticmethod
    def new(address: str, decimals: int, symbol: str, owner: str) -> Token:
        """Create a new token."""
        return Token(address=address, decimals=decimals, symbol=symbol, owner=owner)


class PriceLevelHelper:
    """Static helpers for :class:`PriceLevel`. Mirrors ``impl PriceLevel``."""

    @staticmethod
    def new(volume: int, price: int) -> PriceLevel:
        """Create a new price level."""
        return PriceLevel(volume=volume, price=price)

    @staticmethod
    def volume(level: PriceLevel) -> int:
        """Get volume as an int."""
        return level.volume

    @staticmethod
    def price(level: PriceLevel) -> int:
        """Get price as an int."""
        return level.price


# --- MarketMakerQuote helpers (mirrors `MarketMakerQuoteExt` trait) --------

class QuoteHelper:
    """Helper methods for working with :class:`MarketMakerQuote`.

    Mirrors the Rust ``MarketMakerQuoteExt`` trait.
    """

    @staticmethod
    def is_expired(quote: MarketMakerQuote) -> bool:
        """Check if the quote has expired (current time vs. timestamp + expiry)."""
        now_micros = int(datetime.now(timezone.utc).timestamp() * 1_000_000)
        return now_micros > quote.timestamp + quote.quote_expiry_time

    @staticmethod
    def best_bid(quote: MarketMakerQuote) -> Optional[PriceLevel]:
        """Get the best bid price level (highest price)."""
        if not quote.bid_levels:
            return None
        return max(quote.bid_levels, key=lambda lvl: lvl.price)

    @staticmethod
    def best_ask(quote: MarketMakerQuote) -> Optional[PriceLevel]:
        """Get the best ask price level (lowest price)."""
        if not quote.ask_levels:
            return None
        return min(quote.ask_levels, key=lambda lvl: lvl.price)

    @staticmethod
    def spread(quote: MarketMakerQuote) -> Optional[int]:
        """Calculate the spread in raw price units (ask - bid).

        Returns ``None`` if either side is missing, or if the spread would be
        negative (matching the Rust ``checked_sub`` behavior).
        """
        best_bid = QuoteHelper.best_bid(quote)
        best_ask = QuoteHelper.best_ask(quote)
        if best_bid is None or best_ask is None:
            return None
        diff = best_ask.price - best_bid.price
        if diff < 0:
            return None
        return diff


__all__ = [
    # Constants
    "DEFAULT_TIMEOUT_SECS",
    "DEFAULT_CHANNEL_BUFFER_SIZE",
    "DEFAULT_ENDPOINT",
    # Configuration
    "ClientConfig",
    # Helpers
    "TokenHelper",
    "TokenPairHelper",
    "PriceLevelHelper",
    "QuoteHelper",
    # Re-exported protobuf types
    "Cluster",
    "GetAllOrderbooksRequest",
    "GetAllOrderbooksResponse",
    "GetQuotesRequest",
    "GetQuotesResponse",
    "MarketMakerQuote",
    "MarketMakerSwap",
    "Orderbook",
    "PriceLevel",
    "QuoteResponse",
    "QuoteUpdate",
    "SequenceNumberRequest",
    "SequenceNumberResponse",
    "SwapMessageType",
    "SwapUpdate",
    "Token",
    "TokenPair",
    "UpdateType",
]
