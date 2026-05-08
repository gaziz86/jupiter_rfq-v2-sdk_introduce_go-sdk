"""Builder patterns for creating RFQv2 quotes and requests.

Mirrors ``rust-sdk/src/builders.rs``. The primary entry point is
:class:`MarketMakerQuoteBuilder` (also exported as :class:`QuoteBuilder`
for backward compatibility). The Rust SDK exposes ``MarketMakerQuote::builder()``
— in Python this is :func:`market_maker_quote_builder` or you can call
:meth:`MarketMakerQuoteBuilder.new` directly.
"""

from datetime import datetime, timezone
from typing import List, Optional

from protos.market_maker_pb2 import (
    Cluster,
    MarketMakerQuote,
    PriceLevel,
    TokenPair,
)

from .error import ValidationError
from .types import TokenPairHelper

# 30 seconds in microseconds — matches the Rust default
DEFAULT_QUOTE_EXPIRY_MICROS: int = 30_000_000


class MarketMakerQuoteBuilder:
    """Builder for creating :class:`MarketMakerQuote` instances.

    Mirrors the Rust ``MarketMakerQuoteBuilder``. All setter methods return
    ``self`` for fluent chaining, ending in :meth:`build` which validates the
    quote and returns the protobuf message.
    """

    def __init__(self) -> None:
        self._maker_id: Optional[str] = None
        self._cluster: int = Cluster.CLUSTER_MAINNET
        self._token_pair: Optional[TokenPair] = None
        self._bid_levels: List[PriceLevel] = []
        self._ask_levels: List[PriceLevel] = []
        self._quote_expiry_time: int = DEFAULT_QUOTE_EXPIRY_MICROS
        self._timestamp: Optional[int] = None
        self._sequence_number: Optional[int] = None
        self._maker_address: Optional[str] = None
        self._lot_size_base: Optional[int] = None

    # ------------------------------------------------------------------ #
    # Constructors
    # ------------------------------------------------------------------ #
    @classmethod
    def new(cls) -> "MarketMakerQuoteBuilder":
        """Create a new builder."""
        return cls()

    @classmethod
    def from_quote(cls, quote: MarketMakerQuote) -> "MarketMakerQuoteBuilder":
        """Create a builder seeded with values from an existing quote.

        Mirrors the Rust ``MarketMakerQuoteBuilderExt::to_builder`` method.
        """
        b = cls()
        b._maker_id = quote.maker_id
        b._cluster = quote.cluster
        b._token_pair = quote.token_pair
        b._bid_levels = list(quote.bid_levels)
        b._ask_levels = list(quote.ask_levels)
        b._quote_expiry_time = quote.quote_expiry_time
        b._timestamp = quote.timestamp
        b._sequence_number = quote.sequence_number
        b._maker_address = quote.maker_address
        b._lot_size_base = quote.lot_size_base
        return b

    # ------------------------------------------------------------------ #
    # Setters (mirror Rust method names)
    # ------------------------------------------------------------------ #
    def maker_id(self, maker_id: str) -> "MarketMakerQuoteBuilder":
        """Set the maker ID."""
        self._maker_id = maker_id
        return self

    def cluster(self, cluster: int) -> "MarketMakerQuoteBuilder":
        """Set the cluster (mainnet/devnet)."""
        self._cluster = cluster
        return self

    def token_pair(self, token_pair: TokenPair) -> "MarketMakerQuoteBuilder":
        """Set the token pair."""
        self._token_pair = token_pair
        return self

    def sol_usdc_pair(self) -> "MarketMakerQuoteBuilder":
        """Use the SOL/USDC token pair."""
        self._token_pair = TokenPairHelper.sol_usdc()
        return self

    def eth_usdc_pair(self) -> "MarketMakerQuoteBuilder":
        """Use the ETH/USDC token pair."""
        self._token_pair = TokenPairHelper.eth_usdc()
        return self

    def bid_level(self, volume: int, price: int) -> "MarketMakerQuoteBuilder":
        """Add a single bid level."""
        self._bid_levels.append(PriceLevel(volume=volume, price=price))
        return self

    def bid_levels(self, levels: List[PriceLevel]) -> "MarketMakerQuoteBuilder":
        """Append multiple bid levels."""
        self._bid_levels.extend(levels)
        return self

    def ask_level(self, volume: int, price: int) -> "MarketMakerQuoteBuilder":
        """Add a single ask level."""
        self._ask_levels.append(PriceLevel(volume=volume, price=price))
        return self

    def ask_levels(self, levels: List[PriceLevel]) -> "MarketMakerQuoteBuilder":
        """Append multiple ask levels."""
        self._ask_levels.extend(levels)
        return self

    def expiry_time_micros(self, micros: int) -> "MarketMakerQuoteBuilder":
        """Set quote expiry time in microseconds."""
        self._quote_expiry_time = micros
        return self

    def expiry_time_secs(self, secs: int) -> "MarketMakerQuoteBuilder":
        """Set quote expiry time in seconds.

        .. note::
           To match the Rust SDK's behaviour exactly, this setter writes the
           given value verbatim to the underlying field (which the proto
           documents as microseconds). Use :meth:`expiry_time_micros` if you
           want explicit unit conversion.
        """
        self._quote_expiry_time = secs
        return self

    def maker_address(self, address: str) -> "MarketMakerQuoteBuilder":
        """Set the maker's Solana address."""
        self._maker_address = address
        return self

    def timestamp(self, timestamp_micros: int) -> "MarketMakerQuoteBuilder":
        """Set a custom timestamp in microseconds."""
        self._timestamp = timestamp_micros
        return self

    def sequence_number(self, seq: int) -> "MarketMakerQuoteBuilder":
        """Set the sequence number."""
        self._sequence_number = seq
        return self

    def lot_size_base(self, lot_size: int) -> "MarketMakerQuoteBuilder":
        """Set the lot size for the base token."""
        self._lot_size_base = lot_size
        return self

    # ------------------------------------------------------------------ #
    # Build
    # ------------------------------------------------------------------ #
    def build(self) -> MarketMakerQuote:
        """Validate the configuration and produce a :class:`MarketMakerQuote`.

        Raises :class:`ValidationError` if required fields are missing or any
        bid/ask level has zero volume or price.
        """
        if self._maker_id is None:
            raise ValidationError("maker_id is required")
        if self._token_pair is None:
            raise ValidationError("token_pair is required")
        if not self._bid_levels and not self._ask_levels:
            raise ValidationError("at least one bid or ask level is required")

        for level in list(self._bid_levels) + list(self._ask_levels):
            if level.price == 0:
                raise ValidationError("price cannot be zero")
            if level.volume == 0:
                raise ValidationError("volume cannot be zero")

        if self._maker_address is None:
            raise ValidationError("maker_address is required")
        if self._lot_size_base is None:
            raise ValidationError("lot_size_base is required")

        timestamp = (
            self._timestamp
            if self._timestamp is not None
            else int(datetime.now(timezone.utc).timestamp() * 1_000_000)
        )
        sequence_number = self._sequence_number if self._sequence_number is not None else 1

        return MarketMakerQuote(
            timestamp=timestamp,
            sequence_number=sequence_number,
            quote_expiry_time=self._quote_expiry_time,
            maker_id=self._maker_id,
            maker_address=self._maker_address,
            lot_size_base=self._lot_size_base,
            cluster=self._cluster,
            token_pair=self._token_pair,
            bid_levels=self._bid_levels,
            ask_levels=self._ask_levels,
        )


# Backward compatible alias — older code uses ``QuoteBuilder``.
QuoteBuilder = MarketMakerQuoteBuilder


def market_maker_quote_builder() -> MarketMakerQuoteBuilder:
    """Convenience function mirroring Rust's ``MarketMakerQuote::builder()``."""
    return MarketMakerQuoteBuilder.new()


__all__ = [
    "DEFAULT_QUOTE_EXPIRY_MICROS",
    "MarketMakerQuoteBuilder",
    "QuoteBuilder",
    "market_maker_quote_builder",
]
