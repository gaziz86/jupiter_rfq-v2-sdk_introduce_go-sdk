"""Main client implementation for the RFQv2 SDK.

Mirrors ``rust-sdk/src/client.rs``: provides :class:`MarketMakerClient`,
the entry point for unary RPCs and bidirectional streaming.
"""

import asyncio
import logging
from datetime import timedelta
from typing import List, Optional, Tuple

import grpc

from protos.market_maker_pb2 import (
    Cluster,
    GetAllOrderbooksRequest,
    GetAllOrderbooksResponse,
    GetQuotesRequest,
    GetQuotesResponse,
    SequenceNumberRequest,
    TokenPair,
)
from protos.market_maker_pb2_grpc import MarketMakerIngestionServiceStub

from .error import (
    ConfigurationError,
    ConnectionError as MMConnectionError,
    GrpcError,
    MarketMakerError,
    TimeoutError,
)
from .reflection import ReflectionClient, ReflectionHandle, ServiceInfo
from .streaming import (
    QuoteStreamHandle,
    StreamConfig,
    SwapStreamHandle,
)
from .types import ClientConfig

logger = logging.getLogger(__name__)


# Channel options that mirror the keepalive settings from the Rust SDK.
# (10s ping interval, 20s ping timeout, keepalive while idle, no message-size limit.)
_KEEPALIVE_OPTIONS = [
    ("grpc.keepalive_time_ms", 10_000),
    ("grpc.keepalive_timeout_ms", 20_000),
    ("grpc.keepalive_permit_without_calls", 1),
    ("grpc.http2.max_pings_without_data", 0),
    ("grpc.http2.min_time_between_pings_ms", 10_000),
    ("grpc.http2.min_ping_interval_without_data_ms", 5_000),
    ("grpc.max_send_message_length", -1),
    ("grpc.max_receive_message_length", -1),
]


class MarketMakerClient:
    """Main client for interacting with the RFQv2 service."""

    def __init__(self, config: ClientConfig):
        self.config = config
        self._channel: Optional[grpc.aio.Channel] = None
        self._stub: Optional[MarketMakerIngestionServiceStub] = None

    # ------------------------------------------------------------------ #
    # Async context manager
    # ------------------------------------------------------------------ #
    async def __aenter__(self) -> "MarketMakerClient":
        if self._channel is None:
            await self._establish_connection()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    # ------------------------------------------------------------------ #
    # Constructors
    # ------------------------------------------------------------------ #
    @classmethod
    async def connect(
        cls,
        endpoint: str,
        auth_token: Optional[str] = None,
    ) -> "MarketMakerClient":
        """Connect to the RFQv2 service with default configuration.

        Mirrors Rust's ``MarketMakerClient::connect``. ``auth_token`` is a
        Python-only convenience — pass it here or via :class:`ClientConfig`.
        """
        config = ClientConfig(endpoint=endpoint, auth_token=auth_token)
        return await cls.connect_with_config(config)

    @classmethod
    async def connect_with_config(
        cls, config: ClientConfig
    ) -> "MarketMakerClient":
        """Connect to the RFQv2 service with custom configuration."""
        logger.info("Connecting to RFQv2 service at %s", config.endpoint)
        client = cls(config)
        await client._establish_connection()
        return client

    async def _establish_connection(self) -> None:
        endpoint = self.config.endpoint
        if not endpoint:
            raise ConfigurationError("Invalid endpoint: empty")

        try:
            if endpoint.startswith("https://"):
                logger.debug("Configuring HTTPS connection with TLS")
                creds = grpc.ssl_channel_credentials()
                target = endpoint[len("https://") :]
                self._channel = grpc.aio.secure_channel(
                    target, creds, options=_KEEPALIVE_OPTIONS
                )
            else:
                logger.debug("Using HTTP/2 connection (plain text for development)")
                target = endpoint
                if target.startswith("http://"):
                    target = target[len("http://") :]
                self._channel = grpc.aio.insecure_channel(
                    target, options=_KEEPALIVE_OPTIONS
                )
        except Exception as exc:
            raise MMConnectionError(str(exc), source=exc) from exc

        self._stub = MarketMakerIngestionServiceStub(self._channel)
        logger.debug("Successfully connected to RFQv2 service")

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _metadata(self) -> List[Tuple[str, str]]:
        """Return metadata with the ``x-api-key`` auth header if configured."""
        meta: List[Tuple[str, str]] = []
        if self.config.auth_token:
            meta.append(("x-api-key", self.config.auth_token))
            logger.debug("Added authentication token to request metadata")
        return meta

    def _require_stub(self) -> MarketMakerIngestionServiceStub:
        if self._stub is None:
            raise MMConnectionError("Client is not connected")
        return self._stub

    # ------------------------------------------------------------------ #
    # Streaming
    # ------------------------------------------------------------------ #
    async def start_streaming(
        self, config: Optional[StreamConfig] = None
    ) -> QuoteStreamHandle:
        """Start a bidirectional gRPC stream for real-time quote updates."""
        return await self.start_streaming_with_config(config)

    async def start_streaming_with_config(
        self, config: Optional[StreamConfig] = None
    ) -> QuoteStreamHandle:
        """Start a quote stream with a custom :class:`StreamConfig`."""
        stream_config = config or StreamConfig()
        stub = self._require_stub()
        logger.info("Starting bidirectional gRPC streaming connection")

        quote_queue: asyncio.Queue = asyncio.Queue(maxsize=stream_config.send_buffer_size)

        async def request_iterator():
            while True:
                item = await quote_queue.get()
                if item is None:
                    break
                yield item

        try:
            update_stream = stub.StreamQuotes(
                request_iterator(),
                metadata=self._metadata(),
            )
        except grpc.RpcError as rpc_err:
            raise GrpcError(rpc_err) from rpc_err

        logger.debug("gRPC streaming connection established successfully")
        return QuoteStreamHandle(quote_queue, update_stream, stream_config)

    async def start_swap_streaming(
        self, config: Optional[StreamConfig] = None
    ) -> SwapStreamHandle:
        """Start a bidirectional gRPC stream for swap updates."""
        stream_config = config or StreamConfig()
        stub = self._require_stub()
        logger.info("Starting bidirectional gRPC swap streaming connection")

        swap_queue: asyncio.Queue = asyncio.Queue(maxsize=stream_config.send_buffer_size)

        async def request_iterator():
            while True:
                item = await swap_queue.get()
                if item is None:
                    break
                yield item

        try:
            update_stream = stub.StreamSwap(
                request_iterator(),
                metadata=self._metadata(),
            )
        except grpc.RpcError as rpc_err:
            raise GrpcError(rpc_err) from rpc_err

        logger.debug("gRPC swap streaming connection established successfully")
        return SwapStreamHandle(swap_queue, update_stream, stream_config)

    # ------------------------------------------------------------------ #
    # Unary RPCs
    # ------------------------------------------------------------------ #
    async def get_last_sequence_number(
        self, maker_id: str, auth_token: Optional[str] = None
    ) -> int:
        """Get the last sequence number for a maker (synchronization helper).

        ``auth_token`` defaults to the one configured on the client.
        """
        stub = self._require_stub()
        token = auth_token if auth_token is not None else (self.config.auth_token or "")
        logger.debug("Getting last sequence number for maker: %s", maker_id)

        request = SequenceNumberRequest(maker_id=maker_id, auth_token=token)

        try:
            response = await stub.GetLastSequenceNumber(
                request, metadata=self._metadata()
            )
        except grpc.RpcError as rpc_err:
            raise GrpcError(rpc_err) from rpc_err

        if response.success:
            logger.debug(
                "Retrieved last sequence number for maker %s: %d",
                maker_id,
                response.last_sequence_number,
            )
            return response.last_sequence_number

        logger.warning(
            "Failed to get sequence number for maker %s: %s",
            maker_id,
            response.message,
        )
        return 0

    async def get_quotes(
        self, token_pair: TokenPair, auth_token: Optional[str] = None
    ) -> GetQuotesResponse:
        """Fetch quotes for a specific token pair."""
        stub = self._require_stub()
        token = auth_token if auth_token is not None else (self.config.auth_token or "")
        logger.debug("Getting quotes for token pair")

        request = GetQuotesRequest(token_pair=token_pair, auth_token=token)

        try:
            response = await stub.GetQuotes(request, metadata=self._metadata())
        except grpc.RpcError as rpc_err:
            raise GrpcError(rpc_err) from rpc_err

        logger.info("Retrieved %d quotes", len(response.quotes))
        return response

    async def get_all_orderbooks(
        self, cluster: Optional[int] = None
    ) -> GetAllOrderbooksResponse:
        """Receive an update containing all orderbooks for the given cluster."""
        stub = self._require_stub()
        logger.debug("Receiving update for all orderbooks")

        request = GetAllOrderbooksRequest()
        if cluster is not None:
            request.cluster = cluster

        try:
            response = await stub.GetAllOrderbooks(
                request, metadata=self._metadata()
            )
        except grpc.RpcError as rpc_err:
            raise GrpcError(rpc_err) from rpc_err

        logger.info(
            "Retrieved %d orderbooks at timestamp %d",
            len(response.orderbooks),
            response.timestamp,
        )
        return response

    # Alias matching Rust's `receive_update` method
    async def receive_update(
        self, cluster: Optional[int] = None
    ) -> GetAllOrderbooksResponse:
        """Alias for :meth:`get_all_orderbooks` (mirrors Rust's ``receive_update``)."""
        return await self.get_all_orderbooks(cluster=cluster)

    # ------------------------------------------------------------------ #
    # Convenience: streaming + sync
    # ------------------------------------------------------------------ #
    async def start_streaming_with_sync(
        self,
        maker_id: str,
        auth_token: Optional[str] = None,
        stream_config: Optional[StreamConfig] = None,
    ) -> Tuple[QuoteStreamHandle, int]:
        """Start streaming with automatic sequence number synchronization."""
        return await self.start_streaming_with_sync_and_config(
            maker_id, auth_token, stream_config
        )

    async def start_streaming_with_sync_and_config(
        self,
        maker_id: str,
        auth_token: Optional[str] = None,
        stream_config: Optional[StreamConfig] = None,
    ) -> Tuple[QuoteStreamHandle, int]:
        """Start streaming with sequence sync and a custom :class:`StreamConfig`."""
        token = auth_token if auth_token is not None else (self.config.auth_token or "")
        logger.debug(
            "Starting streaming with sequence number synchronization for maker: %s",
            maker_id,
        )

        last_sequence = await self.get_last_sequence_number(maker_id, token)
        handle = await self.start_streaming_with_config(stream_config)
        next_sequence = last_sequence + 1

        logger.debug(
            "Sequence sync complete for maker %s: last=%d, next=%d",
            maker_id,
            last_sequence,
            next_sequence,
        )
        return handle, next_sequence

    # ------------------------------------------------------------------ #
    # Reflection
    # ------------------------------------------------------------------ #
    def reflection(self) -> ReflectionHandle:
        """Return a :class:`ReflectionHandle` bound to this client's endpoint."""
        return ReflectionHandle(self.config.endpoint)

    async def list_services(self) -> List[str]:
        """List all gRPC services advertised by the server via reflection."""
        logger.info("Querying server reflection for available services")
        client = await ReflectionClient.connect(self.config.endpoint)
        try:
            return await client.list_services()
        finally:
            await client.close()

    async def verify_service(self) -> ServiceInfo:
        """Verify the ``MarketMakerIngestionService`` is available on the server."""
        logger.info("Verifying MarketMakerIngestionService availability via reflection")
        client = await ReflectionClient.connect(self.config.endpoint)
        try:
            return await client.verify_market_maker_service()
        finally:
            await client.close()

    # ------------------------------------------------------------------ #
    # Cleanup
    # ------------------------------------------------------------------ #
    async def close(self) -> None:
        """Close the gRPC connection."""
        if self._channel is not None:
            logger.info("Closing gRPC connection")
            await self._channel.close()
            self._channel = None
            self._stub = None

    # ------------------------------------------------------------------ #
    # Static lifecycle helpers (mirror Rust's static methods)
    # ------------------------------------------------------------------ #
    @staticmethod
    async def shutdown_stream_with_timeout(
        stream: QuoteStreamHandle, timeout: float
    ) -> None:
        """Close a quote stream within ``timeout`` seconds."""
        logger.info("Shutting down streaming connection with timeout: %.1fs", timeout)
        try:
            await stream.close_with_timeout(timeout)
            logger.info("Stream shutdown completed successfully")
        except TimeoutError:
            logger.warning("Stream shutdown timed out after %.1fs", timeout)
            raise
        except MarketMakerError as exc:
            logger.warning("Stream shutdown encountered issues: %s", exc)
            raise

    @staticmethod
    async def shutdown_stream_with_stats(
        stream: QuoteStreamHandle, timeout: float
    ) -> None:
        """Print final stats then close a quote stream within ``timeout``."""
        logger.info("Collecting final statistics before shutdown")
        stats = await stream.get_stats()
        logger.info("Final Stream Statistics:")
        logger.info("Messages sent: %d", stats.messages_sent)
        logger.info("Updates received: %d", stats.updates_received)
        logger.info("Errors encountered: %d", stats.errors_encountered)
        logger.info("Connected for: %s", stats.elapsed())
        await MarketMakerClient.shutdown_stream_with_timeout(stream, timeout)


__all__ = ["MarketMakerClient"]
