"""Tests for :mod:`rfq_sdk.reflection`.

Mirrors the inline ``#[cfg(test)] mod tests`` block in
``rust-sdk/src/reflection.rs``: validates that the dataclasses render with the
expected human-readable formatting. Also includes an end-to-end check against
an in-process gRPC server with reflection enabled.
"""

import socket

import grpc
import pytest
from grpc_reflection.v1alpha import reflection

from protos.market_maker_pb2 import DESCRIPTOR
from protos.market_maker_pb2_grpc import (
    MarketMakerIngestionServiceServicer,
    add_MarketMakerIngestionServiceServicer_to_server,
)
from rfq_sdk import FieldInfo, MessageInfo, MethodInfo, ReflectionClient, ServiceInfo


def test_method_info_str_bidirectional():
    """Mirrors Rust ``test_method_info_display``."""
    method = MethodInfo(
        name="StreamQuotes",
        input_type=".market_maker.MarketMakerQuote",
        output_type=".market_maker.QuoteUpdate",
        client_streaming=True,
        server_streaming=True,
    )
    rendered = str(method)
    assert "StreamQuotes" in rendered
    assert "bidirectional streaming" in rendered


def test_method_info_str_unary():
    method = MethodInfo(
        name="GetLastSequenceNumber",
        input_type=".market_maker.SequenceNumberRequest",
        output_type=".market_maker.SequenceNumberResponse",
        client_streaming=False,
        server_streaming=False,
    )
    rendered = str(method)
    assert "GetLastSequenceNumber" in rendered
    assert "streaming" not in rendered


def test_service_info_str():
    """Mirrors Rust ``test_service_info_display``."""
    service = ServiceInfo(
        name="market_maker.MarketMakerIngestionService",
        methods=[
            MethodInfo(
                name="GetLastSequenceNumber",
                input_type=".market_maker.SequenceNumberRequest",
                output_type=".market_maker.SequenceNumberResponse",
                client_streaming=False,
                server_streaming=False,
            ),
            MethodInfo(
                name="StreamQuotes",
                input_type=".market_maker.MarketMakerQuote",
                output_type=".market_maker.QuoteUpdate",
                client_streaming=True,
                server_streaming=True,
            ),
        ],
    )
    rendered = str(service)
    assert "MarketMakerIngestionService" in rendered
    assert "GetLastSequenceNumber" in rendered
    assert "StreamQuotes" in rendered


def test_message_info_str():
    """Mirrors Rust ``test_message_info_display``."""
    msg = MessageInfo(
        name="Token",
        fields=[
            FieldInfo(
                name="address",
                number=1,
                type_name="string",
                is_repeated=False,
                is_required=True,
                is_optional=False,
            ),
            FieldInfo(
                name="decimals",
                number=2,
                type_name="uint32",
                is_repeated=False,
                is_required=True,
                is_optional=False,
            ),
        ],
    )
    rendered = str(msg)
    assert "message Token" in rendered
    assert "required string address = 1;" in rendered


# --- End-to-end reflection test against an in-process server -------------


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class _StubService(MarketMakerIngestionServiceServicer):
    """Minimal servicer used only so the gRPC server has something to advertise."""


@pytest.fixture
async def reflection_server():
    """Spin up a gRPC server with the reflection service enabled."""
    server = grpc.aio.server()
    add_MarketMakerIngestionServiceServicer_to_server(_StubService(), server)
    service_names = (
        DESCRIPTOR.services_by_name["MarketMakerIngestionService"].full_name,
        reflection.SERVICE_NAME,
    )
    reflection.enable_server_reflection(service_names, server)

    port = _free_port()
    server.add_insecure_port(f"127.0.0.1:{port}")
    await server.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        await server.stop(0)


@pytest.mark.asyncio
async def test_list_services_returns_market_maker(reflection_server):
    client = await ReflectionClient.connect(reflection_server)
    try:
        services = await client.list_services()
        assert any("MarketMakerIngestionService" in s for s in services)
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_verify_market_maker_service(reflection_server):
    client = await ReflectionClient.connect(reflection_server)
    try:
        info = await client.verify_market_maker_service()
        method_names = {m.name for m in info.methods}
        # All methods declared in the .proto file should be present
        assert {
            "GetLastSequenceNumber",
            "GetAllOrderbooks",
            "StreamQuotes",
            "StreamSwap",
            "GetQuotes",
        }.issubset(method_names)

        # StreamQuotes is bidirectional in the proto — verify reflection
        # surfaces that correctly.
        stream_quotes = next(m for m in info.methods if m.name == "StreamQuotes")
        assert stream_quotes.client_streaming is True
        assert stream_quotes.server_streaming is True
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_get_message_info_for_quote(reflection_server):
    client = await ReflectionClient.connect(reflection_server)
    try:
        info = await client.get_message_info("market_maker.MarketMakerQuote")
        names = {f.name for f in info.fields}
        assert {"timestamp", "sequence_number", "maker_id", "token_pair"}.issubset(
            names
        )
    finally:
        await client.close()
