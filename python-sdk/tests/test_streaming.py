"""Tests for :mod:`rfq_sdk.streaming` end-to-end via an in-process gRPC server.

Mirrors the streaming-related behaviour exercised by the Rust SDK examples:
the client sends a quote, the server echoes a NEW :class:`QuoteUpdate`, and
the client receives it with stats updated correctly.
"""

import asyncio
import socket

import grpc
import pytest

from protos.market_maker_pb2 import QuoteUpdate, SwapMessageType, SwapUpdate, UpdateType
from protos.market_maker_pb2_grpc import (
    MarketMakerIngestionServiceServicer,
    add_MarketMakerIngestionServiceServicer_to_server,
)
from rfq_sdk import MarketMakerClient, MarketMakerQuoteBuilder, MarketMakerSwap
from rfq_sdk.streaming import swap_update_helpers, update_helpers


class _EchoService(MarketMakerIngestionServiceServicer):
    """Mock service that echoes a NEW update for each quote and pongs each ping."""

    async def StreamQuotes(self, request_iterator, context):  # noqa: N802
        async for _quote in request_iterator:
            yield QuoteUpdate(update_type=UpdateType.UPDATE_TYPE_NEW)

    async def StreamSwap(self, request_iterator, context):  # noqa: N802
        async for swap in request_iterator:
            if swap.message_type == SwapMessageType.SWAP_MESSAGE_TYPE_PING:
                yield SwapUpdate(message_type=SwapMessageType.SWAP_MESSAGE_TYPE_PONG)
            elif swap.message_type == SwapMessageType.SWAP_MESSAGE_TYPE_SWAP_SUBMIT:
                yield SwapUpdate(
                    message_type=SwapMessageType.SWAP_MESSAGE_TYPE_TRANSACTION_CONFIRMED,
                    swap_uuid=swap.swap_uuid,
                    transaction_signature="signature_xyz",
                )


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
async def echo_endpoint():
    server = grpc.aio.server()
    add_MarketMakerIngestionServiceServicer_to_server(_EchoService(), server)
    port = _free_port()
    server.add_insecure_port(f"127.0.0.1:{port}")
    await server.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        await server.stop(0)


def _quote(seq: int = 1):
    return (
        MarketMakerQuoteBuilder.new()
        .maker_id("m")
        .sol_usdc_pair()
        .maker_address("a")
        .lot_size_base(1)
        .sequence_number(seq)
        .bid_level(1, 100)
        .build()
    )


@pytest.mark.asyncio
async def test_quote_stream_round_trip(echo_endpoint):
    client = await MarketMakerClient.connect(echo_endpoint)
    stream = await client.start_streaming()
    try:
        await stream.send_quote(_quote())
        update = await stream.receive_update_timeout(2.0)
        assert update is not None
        assert update_helpers.is_new_quote(update)

        stats = await stream.get_stats()
        assert stats.messages_sent == 1
        assert stats.updates_received == 1
    finally:
        await stream.close()
        await client.close()


@pytest.mark.asyncio
async def test_quote_stream_async_iterator(echo_endpoint):
    """The ``updates()`` helper exposes an async iterator (matches Rust API)."""
    client = await MarketMakerClient.connect(echo_endpoint)
    stream = await client.start_streaming()
    try:
        await stream.send_quote(_quote())
        await stream.send_quote(_quote(seq=2))

        seen = 0
        async for update in stream.updates():
            assert update_helpers.is_new_quote(update)
            seen += 1
            if seen >= 2:
                break
        assert seen == 2
    finally:
        await stream.close()
        await client.close()


@pytest.mark.asyncio
async def test_swap_stream_ping_pong(echo_endpoint):
    client = await MarketMakerClient.connect(echo_endpoint)
    stream = await client.start_swap_streaming()
    try:
        await stream.send_swap(
            MarketMakerSwap(
                message_type=SwapMessageType.SWAP_MESSAGE_TYPE_PING,
                swap_uuid="",
                signed_transaction="",
            )
        )
        update = await stream.receive_update_timeout(2.0)
        assert update is not None
        assert swap_update_helpers.is_pong(update)
    finally:
        await stream.close()
        await client.close()


@pytest.mark.asyncio
async def test_swap_stream_submit_returns_confirmation(echo_endpoint):
    client = await MarketMakerClient.connect(echo_endpoint)
    stream = await client.start_swap_streaming()
    try:
        await stream.send_swap(
            MarketMakerSwap(
                message_type=SwapMessageType.SWAP_MESSAGE_TYPE_SWAP_SUBMIT,
                swap_uuid="abc-123",
                signed_transaction="signed_tx_data",
            )
        )
        update = await stream.receive_update_timeout(2.0)
        assert swap_update_helpers.is_transaction_confirmed(update)
        details = swap_update_helpers.extract_confirmation_details(update)
        assert details == ("abc-123", "signature_xyz")
    finally:
        await stream.close()
        await client.close()


@pytest.mark.asyncio
async def test_send_after_close_raises(echo_endpoint):
    """Mirrors Rust behaviour: sending on a closed stream is an error."""
    from rfq_sdk import StreamingError

    client = await MarketMakerClient.connect(echo_endpoint)
    stream = await client.start_streaming()
    await stream.close()
    try:
        with pytest.raises(StreamingError):
            await stream.send_quote(_quote())
    finally:
        await client.close()
