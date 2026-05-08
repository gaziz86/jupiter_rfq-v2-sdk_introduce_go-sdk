"""Streaming functionality for real-time quote and swap updates.

Mirrors ``rust-sdk/src/streaming.rs``: provides bidirectional gRPC streaming
between the market maker client and the ingestion service. The client can send
quotes / swaps to the server and receive real-time updates.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import AsyncIterator, Optional

import grpc

from protos.market_maker_pb2 import (
    MarketMakerQuote,
    MarketMakerSwap,
    QuoteUpdate,
    SwapMessageType,
    SwapUpdate,
    UpdateType,
)

from .error import GrpcError, MarketMakerError, StreamingError, TimeoutError

logger = logging.getLogger(__name__)


# --- Stream configuration --------------------------------------------------

@dataclass
class StreamConfig:
    """Configuration for streaming behavior.

    Mirrors the Rust ``StreamConfig`` struct.
    """

    send_buffer_size: int = 1000
    operation_timeout: timedelta = field(default_factory=lambda: timedelta(seconds=30))
    auto_reconnect: bool = False
    max_reconnect_attempts: int = 3
    inactivity_timeout: timedelta = field(default_factory=lambda: timedelta(seconds=120))

    @classmethod
    def new(cls) -> "StreamConfig":
        """Create a new stream configuration with defaults."""
        return cls()

    def with_send_buffer_size(self, size: int) -> "StreamConfig":
        self.send_buffer_size = size
        return self

    def with_operation_timeout(self, timeout: timedelta) -> "StreamConfig":
        self.operation_timeout = timeout
        return self

    def with_auto_reconnect(self, max_attempts: int) -> "StreamConfig":
        self.auto_reconnect = True
        self.max_reconnect_attempts = max_attempts
        return self

    def with_inactivity_timeout(self, timeout: timedelta) -> "StreamConfig":
        self.inactivity_timeout = timeout
        return self


# --- Connection statistics -------------------------------------------------

@dataclass
class ConnectionStats:
    """Generic connection statistics for monitoring stream health.

    Mirrors the Rust ``ConnectionStats`` struct. ``connected_at`` and
    ``last_activity`` are :class:`datetime` instances (Rust uses
    ``std::time::Instant``).
    """

    messages_sent: int = 0
    updates_received: int = 0
    errors_encountered: int = 0
    reconnections: int = 0
    connected_at: datetime = field(default_factory=datetime.now)
    last_activity: Optional[datetime] = None

    def activity(self) -> None:
        self.last_activity = datetime.now()

    def message_sent(self) -> None:
        self.messages_sent += 1
        self.activity()

    def update_received(self) -> None:
        self.updates_received += 1
        self.activity()

    def error_encountered(self) -> None:
        self.errors_encountered += 1

    def reconnection(self) -> None:
        self.reconnections += 1

    def time_since_last_activity(self) -> Optional[timedelta]:
        if self.last_activity is None:
            return None
        return datetime.now() - self.last_activity

    def elapsed(self) -> timedelta:
        """Time elapsed since connection — mirrors ``connected_at.elapsed()``."""
        return datetime.now() - self.connected_at


# Type alias matching the Rust SDK
SwapStats = ConnectionStats


# --- Quote stream handle ---------------------------------------------------

class QuoteStreamHandle:
    """Handle for managing a bidirectional gRPC quote stream.

    Mirrors the Rust ``QuoteStreamHandle``.
    """

    def __init__(
        self,
        quote_queue: asyncio.Queue,
        update_stream: "grpc.aio.StreamStreamCall",
        config: Optional[StreamConfig] = None,
    ):
        self._quote_queue = quote_queue
        self._update_stream = update_stream
        self._config = config or StreamConfig()
        self._is_closed = False
        self._stats = ConnectionStats()
        self._stats_lock = asyncio.Lock()
        self._shutdown = asyncio.Event()
        # Public attribute mirroring Rust's `update_receiver`
        self.update_receiver = update_stream

    async def send_quote(self, quote: MarketMakerQuote) -> None:
        """Send a quote directly to the gRPC server.

        Raises :class:`StreamingError` if the stream is closed.
        """
        if self._is_closed:
            raise StreamingError("Stream has been closed")
        try:
            await self._quote_queue.put(quote)
        except Exception as exc:  # pragma: no cover - asyncio.Queue does not raise
            async with self._stats_lock:
                self._stats.error_encountered()
            raise StreamingError(f"Failed to send quote: {exc}") from exc

        async with self._stats_lock:
            self._stats.message_sent()

    async def receive_update(self) -> Optional[QuoteUpdate]:
        """Receive the next quote update from the gRPC server.

        Returns ``None`` when the stream ends.
        """
        if self._is_closed:
            return None
        try:
            update = await self._update_stream.read()
        except asyncio.CancelledError:
            self._is_closed = True
            return None
        except grpc.RpcError as rpc_err:
            async with self._stats_lock:
                self._stats.error_encountered()
            raise GrpcError(rpc_err) from rpc_err

        # gRPC aio uses an end-of-stream sentinel; both ``None`` and
        # ``grpc.aio.EOF`` indicate the stream is finished.
        if update is None or update is getattr(grpc.aio, "EOF", object()):
            self._is_closed = True
            return None

        async with self._stats_lock:
            self._stats.update_received()
        return update

    async def receive_update_timeout(self, timeout_secs: float) -> Optional[QuoteUpdate]:
        """Receive an update with a timeout (in seconds)."""
        try:
            return await asyncio.wait_for(self.receive_update(), timeout=timeout_secs)
        except asyncio.TimeoutError as exc:
            raise TimeoutError("Timed out waiting for update") from exc

    async def close(self) -> None:
        """Close the gRPC stream gracefully."""
        if self._is_closed:
            return
        logger.info("Initiating graceful stream shutdown")
        self._is_closed = True

        # Signal the outbound iterator to stop
        try:
            self._quote_queue.put_nowait(None)
        except asyncio.QueueFull:
            pass

        # Cancel the inbound stream
        try:
            self._update_stream.cancel()
        except Exception:  # noqa: BLE001 - best effort cancel
            pass

        self._shutdown.set()
        await asyncio.sleep(0.1)
        logger.info("Stream shutdown completed")

    async def close_with_timeout(self, timeout_secs: float) -> None:
        """Close the stream with a timeout, raising :class:`TimeoutError` on timeout."""
        try:
            await asyncio.wait_for(self.close(), timeout=timeout_secs)
        except asyncio.TimeoutError as exc:
            self._is_closed = True
            raise TimeoutError("Stream close operation timed out") from exc

    async def is_closed(self) -> bool:
        """Check if the stream is closed."""
        return self._is_closed

    async def get_stats(self) -> ConnectionStats:
        """Return a snapshot of the connection statistics."""
        async with self._stats_lock:
            return ConnectionStats(
                messages_sent=self._stats.messages_sent,
                updates_received=self._stats.updates_received,
                errors_encountered=self._stats.errors_encountered,
                reconnections=self._stats.reconnections,
                connected_at=self._stats.connected_at,
                last_activity=self._stats.last_activity,
            )

    async def reset_stats(self) -> None:
        """Reset connection statistics."""
        async with self._stats_lock:
            self._stats = ConnectionStats()

    async def is_healthy(self, config: Optional[StreamConfig] = None) -> bool:
        """Return ``True`` while the stream has had recent activity.

        Mirrors :meth:`SwapStreamHandle.is_healthy` from the Rust SDK and
        uses :attr:`StreamConfig.inactivity_timeout`.
        """
        cfg = config or self._config
        async with self._stats_lock:
            since = self._stats.time_since_last_activity()
            if since is not None:
                return since <= cfg.inactivity_timeout
            return self._stats.elapsed() < cfg.inactivity_timeout

    async def wait_for_shutdown(self) -> None:
        """Block until :meth:`close` is invoked."""
        await self._shutdown.wait()

    def updates(self) -> "QuoteUpdateStream":
        """Return an async iterator yielding :class:`QuoteUpdate` items."""
        return QuoteUpdateStream(self)


class QuoteUpdateStream:
    """Async iterator helper for :class:`QuoteStreamHandle.updates`."""

    def __init__(self, handle: QuoteStreamHandle):
        self._handle = handle

    def __aiter__(self) -> "QuoteUpdateStream":
        return self

    async def __anext__(self) -> QuoteUpdate:
        update = await self.next()
        if update is None:
            raise StopAsyncIteration
        return update

    async def next(self) -> Optional[QuoteUpdate]:
        """Get the next update with graceful shutdown support."""
        if await self._handle.is_closed():
            return None
        return await self._handle.receive_update()

    async def next_timeout(self, timeout_secs: float) -> Optional[QuoteUpdate]:
        """Get the next update with a timeout (in seconds)."""
        if await self._handle.is_closed():
            return None
        return await self._handle.receive_update_timeout(timeout_secs)


# --- Swap stream handle ----------------------------------------------------

class SwapStreamHandle:
    """Handle for managing a bidirectional gRPC swap stream.

    Mirrors the Rust ``SwapStreamHandle``.
    """

    def __init__(
        self,
        swap_queue: asyncio.Queue,
        update_stream: "grpc.aio.StreamStreamCall",
        config: Optional[StreamConfig] = None,
    ):
        self._swap_queue = swap_queue
        self._update_stream = update_stream
        self._config = config or StreamConfig()
        self._is_closed = False
        self._stats = ConnectionStats()
        self._stats_lock = asyncio.Lock()
        self._shutdown = asyncio.Event()
        self.update_receiver = update_stream

    async def send_swap(self, swap: MarketMakerSwap) -> None:
        """Send a swap directly to the gRPC server."""
        if self._is_closed:
            raise StreamingError("Stream has been closed")
        try:
            await self._swap_queue.put(swap)
        except Exception as exc:  # pragma: no cover
            async with self._stats_lock:
                self._stats.error_encountered()
            raise StreamingError(f"Failed to send swap: {exc}") from exc

        async with self._stats_lock:
            self._stats.message_sent()

    async def receive_update(self) -> Optional[SwapUpdate]:
        """Receive the next swap update from the gRPC server."""
        if self._is_closed:
            return None
        try:
            update = await self._update_stream.read()
        except asyncio.CancelledError:
            self._is_closed = True
            return None
        except grpc.RpcError as rpc_err:
            async with self._stats_lock:
                self._stats.error_encountered()
            raise GrpcError(rpc_err) from rpc_err

        if update is None or update is getattr(grpc.aio, "EOF", object()):
            self._is_closed = True
            return None

        async with self._stats_lock:
            self._stats.update_received()
        return update

    async def receive_update_timeout(self, timeout_secs: float) -> Optional[SwapUpdate]:
        """Receive an update with a timeout (in seconds)."""
        try:
            return await asyncio.wait_for(self.receive_update(), timeout=timeout_secs)
        except asyncio.TimeoutError as exc:
            raise TimeoutError("Timed out waiting for update") from exc

    async def close(self) -> None:
        """Close the gRPC swap stream gracefully."""
        if self._is_closed:
            return
        logger.info("Initiating graceful swap stream shutdown")
        self._is_closed = True

        try:
            self._swap_queue.put_nowait(None)
        except asyncio.QueueFull:
            pass

        try:
            self._update_stream.cancel()
        except Exception:  # noqa: BLE001
            pass

        self._shutdown.set()
        await asyncio.sleep(0.1)
        logger.info("Swap stream shutdown completed")

    async def close_with_timeout(self, timeout_secs: float) -> None:
        """Close the stream with a timeout."""
        try:
            await asyncio.wait_for(self.close(), timeout=timeout_secs)
        except asyncio.TimeoutError as exc:
            self._is_closed = True
            raise TimeoutError("Swap stream close operation timed out") from exc

    async def is_closed(self) -> bool:
        return self._is_closed

    async def get_stats(self) -> ConnectionStats:
        async with self._stats_lock:
            return ConnectionStats(
                messages_sent=self._stats.messages_sent,
                updates_received=self._stats.updates_received,
                errors_encountered=self._stats.errors_encountered,
                reconnections=self._stats.reconnections,
                connected_at=self._stats.connected_at,
                last_activity=self._stats.last_activity,
            )

    async def reset_stats(self) -> None:
        async with self._stats_lock:
            self._stats = ConnectionStats()

    async def is_healthy(self, config: Optional[StreamConfig] = None) -> bool:
        """Check connection health based on activity."""
        cfg = config or self._config
        async with self._stats_lock:
            since = self._stats.time_since_last_activity()
            if since is not None:
                return since <= cfg.inactivity_timeout
            return self._stats.elapsed() < cfg.inactivity_timeout

    async def wait_for_shutdown(self) -> None:
        await self._shutdown.wait()

    async def updates(self) -> AsyncIterator[SwapUpdate]:
        """Async generator yielding :class:`SwapUpdate` items."""
        while not self._is_closed:
            update = await self.receive_update()
            if update is None:
                break
            yield update


# --- Quote update helpers (mirrors `update_helpers` mod) -------------------

class update_helpers:  # noqa: N801 - mirrors Rust module name
    """Helpers for inspecting :class:`QuoteUpdate` messages.

    Implemented as a class with only static methods so callers can use it as
    ``streaming.update_helpers.is_new_quote(u)`` — mirroring Rust's
    ``streaming::update_helpers::is_new_quote(u)``.
    """

    @staticmethod
    def is_heartbeat(update: QuoteUpdate) -> bool:
        return update.update_type == UpdateType.UPDATE_TYPE_UNSPECIFIED

    @staticmethod
    def is_new_quote(update: QuoteUpdate) -> bool:
        return update.update_type == UpdateType.UPDATE_TYPE_NEW

    @staticmethod
    def is_updated_quote(update: QuoteUpdate) -> bool:
        return update.update_type == UpdateType.UPDATE_TYPE_UPDATED

    @staticmethod
    def is_expired_quote(update: QuoteUpdate) -> bool:
        return update.update_type == UpdateType.UPDATE_TYPE_EXPIRED

    @staticmethod
    def is_rejected_quote(update: QuoteUpdate) -> bool:
        return update.update_type == UpdateType.UPDATE_TYPE_REJECTED

    @staticmethod
    def get_status_message(update: QuoteUpdate) -> Optional[str]:
        msg = getattr(update, "status_message", "")
        return msg if msg else None

    @staticmethod
    def update_type_description(update: QuoteUpdate) -> str:
        if update.update_type == UpdateType.UPDATE_TYPE_NEW:
            return "New Quote"
        if update.update_type == UpdateType.UPDATE_TYPE_UPDATED:
            return "Updated Quote"
        if update.update_type == UpdateType.UPDATE_TYPE_EXPIRED:
            return "Expired Quote"
        if update.update_type == UpdateType.UPDATE_TYPE_REJECTED:
            return "Rejected Quote"
        return "System Message"


# --- Swap update helpers (mirrors `swap_update_helpers` mod) ---------------

class swap_update_helpers:  # noqa: N801 - mirrors Rust module name
    """Helpers for inspecting :class:`SwapUpdate` messages.

    Mirrors Rust's ``streaming::swap_update_helpers`` module.
    """

    @staticmethod
    def is_pong(update: SwapUpdate) -> bool:
        return update.message_type == SwapMessageType.SWAP_MESSAGE_TYPE_PONG

    @staticmethod
    def is_connection_ready(update: SwapUpdate) -> bool:
        return update.message_type == SwapMessageType.SWAP_MESSAGE_TYPE_CONNECTION_READY

    @staticmethod
    def is_swap_available(update: SwapUpdate) -> bool:
        return update.message_type == SwapMessageType.SWAP_MESSAGE_TYPE_SWAP_AVAILABLE

    @staticmethod
    def is_transaction_confirmed(update: SwapUpdate) -> bool:
        return update.message_type == SwapMessageType.SWAP_MESSAGE_TYPE_TRANSACTION_CONFIRMED

    @staticmethod
    def is_error(update: SwapUpdate) -> bool:
        return update.message_type == SwapMessageType.SWAP_MESSAGE_TYPE_ERROR

    @staticmethod
    def get_swap_uuid(update: SwapUpdate) -> Optional[str]:
        uuid = getattr(update, "swap_uuid", "")
        return uuid if uuid else None

    @staticmethod
    def get_unsigned_transaction(update: SwapUpdate) -> Optional[str]:
        tx = getattr(update, "unsigned_transaction", "")
        return tx if tx else None

    @staticmethod
    def get_transaction_signature(update: SwapUpdate) -> Optional[str]:
        sig = getattr(update, "transaction_signature", "")
        return sig if sig else None

    @staticmethod
    def get_status_message(update: SwapUpdate) -> Optional[str]:
        msg = getattr(update, "status_message", "")
        return msg if msg else None

    @staticmethod
    def update_type_description(update: SwapUpdate) -> str:
        mapping = {
            SwapMessageType.SWAP_MESSAGE_TYPE_PING: "Ping",
            SwapMessageType.SWAP_MESSAGE_TYPE_PONG: "Pong",
            SwapMessageType.SWAP_MESSAGE_TYPE_CONNECTION_READY: "Connection Ready",
            SwapMessageType.SWAP_MESSAGE_TYPE_SWAP_AVAILABLE: "Swap Available",
            SwapMessageType.SWAP_MESSAGE_TYPE_SWAP_SUBMIT: "Swap Submit",
            SwapMessageType.SWAP_MESSAGE_TYPE_TRANSACTION_CONFIRMED: "Transaction Confirmed",
            SwapMessageType.SWAP_MESSAGE_TYPE_ERROR: "Error",
        }
        return mapping.get(update.message_type, "Unknown Message Type")

    @staticmethod
    def extract_swap_details(update: SwapUpdate):  # -> Optional[Tuple[str, str]]
        """Return ``(swap_uuid, unsigned_transaction)`` for an available swap."""
        if not swap_update_helpers.is_swap_available(update):
            return None
        uuid = swap_update_helpers.get_swap_uuid(update)
        tx = swap_update_helpers.get_unsigned_transaction(update)
        if uuid and tx:
            return (uuid, tx)
        return None

    @staticmethod
    def extract_confirmation_details(update: SwapUpdate):  # -> Optional[Tuple[str, str]]
        """Return ``(swap_uuid, transaction_signature)`` for a confirmation."""
        if not swap_update_helpers.is_transaction_confirmed(update):
            return None
        uuid = swap_update_helpers.get_swap_uuid(update)
        sig = swap_update_helpers.get_transaction_signature(update)
        if uuid and sig:
            return (uuid, sig)
        return None


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
