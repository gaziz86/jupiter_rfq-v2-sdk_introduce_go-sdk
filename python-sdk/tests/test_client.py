"""Tests for :class:`MarketMakerClient`.

Mirrors the inline ``#[cfg(test)] mod tests`` block in
``rust-sdk/src/client.rs``: a minimal in-process gRPC server implements only
``GetQuotes`` and we assert the client wires the request/response through
correctly.
"""

import asyncio
import socket

import grpc
import pytest

from protos.market_maker_pb2 import (
    Cluster,
    GetQuotesResponse,
    MarketMakerQuote,
    PriceLevel,
)
from protos.market_maker_pb2_grpc import (
    MarketMakerIngestionServiceServicer,
    add_MarketMakerIngestionServiceServicer_to_server,
)
from rfq_sdk import MarketMakerClient, TokenPairHelper


class MockMarketMakerService(MarketMakerIngestionServiceServicer):
    """Minimal mock that only implements ``GetQuotes`` — mirrors the Rust mock."""

    async def GetQuotes(self, request, context):  # noqa: N802 - gRPC method name
        # Echo back a single fake quote for the requested pair
        return GetQuotesResponse(
            quotes=[
                MarketMakerQuote(
                    timestamp=1_000_000,
                    sequence_number=1,
                    quote_expiry_time=30_000_000,
                    maker_id="test-maker",
                    maker_address="11111111111111111111111111111111",
                    lot_size_base=1000,
                    cluster=Cluster.CLUSTER_MAINNET,
                    token_pair=request.token_pair,
                    bid_levels=[PriceLevel(volume=1_000_000_000, price=150_000_000)],
                    ask_levels=[PriceLevel(volume=1_000_000_000, price=151_000_000)],
                )
            ]
        )


def _free_port() -> int:
    """Pick a free TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
async def mock_server():
    """Spin up an in-process gRPC server hosting :class:`MockMarketMakerService`."""
    server = grpc.aio.server()
    add_MarketMakerIngestionServiceServicer_to_server(
        MockMarketMakerService(), server
    )
    port = _free_port()
    server.add_insecure_port(f"127.0.0.1:{port}")
    await server.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        await server.stop(0)


@pytest.mark.asyncio
async def test_get_quotes_returns_quotes(mock_server):
    """Mirrors Rust ``test_get_quotes_returns_quotes``."""
    client = await MarketMakerClient.connect(mock_server)
    try:
        pair = TokenPairHelper.sol_usdc()
        resp = await client.get_quotes(pair, "test-token")

        assert len(resp.quotes) == 1
        quote = resp.quotes[0]
        assert quote.maker_id == "test-maker"
        assert len(quote.bid_levels) == 1
        assert len(quote.ask_levels) == 1
        assert quote.bid_levels[0].price == 150_000_000
        assert quote.ask_levels[0].price == 151_000_000
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_get_quotes_preserves_token_pair(mock_server):
    """Mirrors Rust ``test_get_quotes_preserves_token_pair``."""
    client = await MarketMakerClient.connect(mock_server)
    try:
        pair = TokenPairHelper.eth_usdc()
        resp = await client.get_quotes(pair, "test-token")

        # The mock echoes back the requested token pair
        returned_pair = resp.quotes[0].token_pair
        assert returned_pair.base_token.symbol == "ETH"
        assert returned_pair.quote_token.symbol == "USDC"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_client_context_manager(mock_server):
    """The client supports ``async with`` for automatic cleanup."""
    async with await MarketMakerClient.connect(mock_server) as client:
        resp = await client.get_quotes(TokenPairHelper.sol_usdc(), "test-token")
        assert len(resp.quotes) == 1
