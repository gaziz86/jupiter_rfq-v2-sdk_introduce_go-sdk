"""Backward compatibility shim — see :mod:`rfq_sdk.streaming` for the canonical
streaming module that mirrors ``rust-sdk/src/streaming.rs``.
"""

from .streaming import (
    ConnectionStats,
    QuoteStreamHandle,
    QuoteUpdateStream,
    StreamConfig,
    SwapStats,
    SwapStreamHandle,
    swap_update_helpers,
    update_helpers,
)

__all__ = [
    "ConnectionStats",
    "QuoteStreamHandle",
    "QuoteUpdateStream",
    "StreamConfig",
    "SwapStats",
    "SwapStreamHandle",
    "swap_update_helpers",
    "update_helpers",
]
